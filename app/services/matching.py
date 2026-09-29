"""Rank images for a post, run the guard on each, and record the verdicts as suggestions."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import NotFound, NotReady
from app.models import Image, Post, Suggestion
from app.repositories.embeddings import EmbeddingRepository, RankedRow
from app.repositories.images import ImageRepository
from app.repositories.posts import PostRepository
from app.repositories.suggestions import SuggestionRepository
from app.services.guard import (
    GUARD_VERSION,
    GuardConfig,
    ImageFacts,
    PostFacts,
    Scores,
    Verdict,
    evaluate,
    no_match_reasons,
)


@dataclass
class Candidate:
    rank: int | None
    image: Image
    scores: Scores
    verdict: Verdict
    suggestion: Suggestion


@dataclass
class MatchResult:
    post: Post
    status: str  # "match" | "no_confident_match"
    suggestion: Candidate | None
    reasons: list[str]
    candidates: list[Candidate] = field(default_factory=list)


def guard_config(settings: Settings) -> GuardConfig:
    return GuardConfig(
        similarity_threshold=settings.similarity_threshold,
        min_confidence=settings.min_confidence,
        subject_sim_threshold=settings.subject_sim_threshold,
    )


def image_facts(image: Image, has_embedding: bool = True) -> ImageFacts:
    m = image.meta
    if m is None or not has_embedding:
        return ImageFacts(image_id=image.id, ready=False)
    return ImageFacts(
        image_id=image.id,
        ready=True,
        subject=m.subject,
        category=m.category,
        caption=m.caption,
        attributes=tuple(m.attributes),
        confidence=m.confidence,
        needs_review=m.needs_review,
        review_reasons=tuple(m.review_reasons),
    )


class MatchingService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.s = session
        self.posts = PostRepository(session)
        self.images = ImageRepository(session)
        self.embeddings = EmbeddingRepository(session)
        self.suggestions = SuggestionRepository(session)
        self.cfg = guard_config(settings)

    def _ready_post(self, tenant_id: int, post_id: int):  # noqa: ANN202
        post = self.posts.get(tenant_id, post_id)
        if post is None:
            raise NotFound(f"post {post_id} not found")
        emb = self.embeddings.get_post(post.id)
        if post.status != "ready" or emb is None:
            raise NotReady(
                f"post {post_id} has not been analysed yet (status '{post.status}'); "
                "run a job (POST /jobs) and wait for the worker"
            )
        return post, emb

    def _judge(self, tenant_id: int, post: Post, row: RankedRow, rank: int | None) -> Candidate:
        facts = image_facts(row.image)
        scores = Scores(similarity=row.similarity, subject_similarity=row.subject_similarity)
        verdict = evaluate(PostFacts(post.subject, post.category), facts, scores, self.cfg)
        suggestion = self.suggestions.upsert(
            tenant_id, post.id, row.image.id,
            rank=rank,
            similarity=round(row.similarity, 4),
            decision=verdict.decision,
            reasons=verdict.reasons,
            checks=verdict.checks_as_dicts(),
            explanation=verdict.explanation,
            guard_version=GUARD_VERSION,
        )
        return Candidate(rank, row.image, scores, verdict, suggestion)

    def suggest(self, tenant_id: int, post_id: int, limit: int = 10) -> MatchResult:
        post, emb = self._ready_post(tenant_id, post_id)
        rows = self.embeddings.rank_images(tenant_id, list(emb.embedding), list(emb.subject_embedding), limit)
        self.suggestions.clear_ranks(post.id)
        candidates = [self._judge(tenant_id, post, row, rank) for rank, row in enumerate(rows, start=1)]
        self.s.commit()

        best = next((c for c in candidates if c.verdict.accepted), None)
        if best is not None:
            return MatchResult(post, "match", best, [best.verdict.explanation], candidates)
        reasons = no_match_reasons(
            PostFacts(post.subject, post.category),
            [(image_facts(c.image), c.scores, c.verdict) for c in candidates],
            self.cfg,
        )
        return MatchResult(post, "no_confident_match", None, reasons, candidates)

    def force_check(self, tenant_id: int, post_id: int, image_id: int) -> Candidate:
        """Run the guard on one specific pair, whatever its rank (acceptance probe 3)."""
        post, emb = self._ready_post(tenant_id, post_id)
        image = self.images.get(tenant_id, image_id)
        if image is None:
            raise NotFound(f"image {image_id} not found")
        rows = self.embeddings.rank_images(
            tenant_id, list(emb.embedding), list(emb.subject_embedding), limit=1, image_id=image_id
        )
        if not rows:
            raise NotReady(f"image {image_id} has not been analysed yet (status '{image.status}')")
        existing = self.suggestions.get_pair(post_id, image_id)
        candidate = self._judge(tenant_id, post, rows[0], existing.rank if existing else None)
        self.s.commit()
        return candidate
