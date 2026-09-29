from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, status

from app.api.deps import DB, CurrentTenant
from app.config import get_settings
from app.errors import Conflict, NotFound
from app.models import POST_STATUSES, Post
from app.repositories.posts import PostRepository
from app.schemas.api import CandidateOut, CheckOut, ForceCheckIn, MatchOut, PostCreate, PostCreated, PostOut
from app.services.jobs import JobService
from app.services.matching import Candidate, MatchingService

router = APIRouter(prefix="/posts", tags=["posts"])

PostId = Annotated[int, Path(ge=1)]
PostStatus = Literal[POST_STATUSES]  # type: ignore[valid-type]


def candidate_out(c: Candidate) -> CandidateOut:
    m = c.image.meta
    return CandidateOut(
        rank=c.rank,
        suggestion_id=c.suggestion.id,
        image_id=c.image.id,
        filename=c.image.filename,
        subject=m.subject if m else None,
        category=m.category if m else None,
        caption=m.caption if m else None,
        confidence=m.confidence if m else None,
        needs_review=m.needs_review if m else None,
        similarity=round(c.scores.similarity, 4),
        subject_similarity=None if c.scores.subject_similarity is None else round(c.scores.subject_similarity, 4),
        decision=c.verdict.decision,
        reasons=c.verdict.reasons,
        explanation=c.verdict.explanation,
        checks=[CheckOut(**d) for d in c.verdict.checks_as_dicts()],
        review_status=c.suggestion.review_status,
    )


@router.post("", response_model=PostCreated, status_code=status.HTTP_201_CREATED)
def create_post(db: DB, tenant: CurrentTenant, body: PostCreate) -> PostCreated:
    """Create a post and queue a background job to analyse and embed it."""
    repo = PostRepository(db)
    if repo.get_by_slug(tenant.id, body.slug) is not None:
        raise Conflict(f"a post with slug '{body.slug}' already exists")
    post = repo.add(Post(tenant_id=tenant.id, slug=body.slug, title=body.title, body=body.body))
    db.commit()
    job, _ = JobService(db).create(
        tenant.id, "posts", idempotency_key=f"post-{post.id}-created", targets=[("post", post.id)]
    )
    return PostCreated(post=PostOut.model_validate(post), job_id=job.id)


@router.get("", response_model=list[PostOut])
def list_posts(
    db: DB,
    tenant: CurrentTenant,
    status: PostStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PostOut]:
    return [PostOut.model_validate(p) for p in PostRepository(db).list(tenant.id, status, limit, offset)]


@router.get("/{post_id}", response_model=PostOut)
def get_post(db: DB, tenant: CurrentTenant, post_id: PostId) -> PostOut:
    post = PostRepository(db).get(tenant.id, post_id)
    if post is None:
        raise NotFound(f"post {post_id} not found")
    return PostOut.model_validate(post)


@router.get("/{post_id}/images", response_model=MatchOut)
def suggest_images(
    db: DB,
    tenant: CurrentTenant,
    post_id: PostId,
    limit: Annotated[int, Query(ge=1, le=50, description="How many ranked candidates to judge")] = 10,
) -> MatchOut:
    """Ranked, explained image suggestions for a post, or "no_confident_match" with reasons.

    Each judged candidate is stored as a suggestion so it can be reviewed later.
    """
    result = MatchingService(db, get_settings()).suggest(tenant.id, post_id, limit)
    return MatchOut(
        post_id=result.post.id,
        title=result.post.title,
        post_subject=result.post.subject,
        post_category=result.post.category,
        status=result.status,
        suggestion=candidate_out(result.suggestion) if result.suggestion else None,
        reasons=result.reasons,
        similarity_threshold=get_settings().similarity_threshold,
        candidates=[candidate_out(c) for c in result.candidates],
    )


@router.post("/{post_id}/check", response_model=CandidateOut)
def force_check(db: DB, tenant: CurrentTenant, post_id: PostId, body: ForceCheckIn) -> CandidateOut:
    """Force one image as the candidate for a post and return the guard's verdict."""
    return candidate_out(MatchingService(db, get_settings()).force_check(tenant.id, post_id, body.image_id))
