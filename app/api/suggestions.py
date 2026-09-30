import html
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query
from fastapi.responses import HTMLResponse

from app.api.deps import MAX_OFFSET, DB, CurrentTenant
from app.errors import NotFound
from app.models import Suggestion
from app.repositories.suggestions import SuggestionRepository
from app.schemas.api import (
    CheckOut,
    ImageOut,
    PostOut,
    ReviewIn,
    ReviewOut,
    ReviewResult,
    SuggestionDetail,
    SuggestionOut,
)
from app.services.review import ReviewService

router = APIRouter(tags=["review"])

SuggestionId = Annotated[int, Path(ge=1)]
ReviewStatus = Literal["pending", "approved", "rejected"]


def suggestion_out(s: Suggestion) -> SuggestionOut:
    return SuggestionOut(
        id=s.id, post_id=s.post_id, post_title=s.post.title, image_id=s.image_id, filename=s.image.filename,
        rank=s.rank, similarity=s.similarity, decision=s.decision, explanation=s.explanation,
        review_status=s.review_status,
    )


def suggestion_detail(db: DB, s: Suggestion) -> SuggestionDetail:
    return SuggestionDetail(
        **suggestion_out(s).model_dump(),
        reasons=s.reasons,
        checks=[CheckOut(**c) for c in s.checks],
        guard_version=s.guard_version,
        post=PostOut.model_validate(s.post),
        image=ImageOut.model_validate(s.image),
        reviews=[ReviewOut.model_validate(r) for r in ReviewService(db).history(s.id)],
    )


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(
    db: DB,
    tenant: CurrentTenant,
    post_id: Annotated[int | None, Query(ge=1)] = None,
    review_status: ReviewStatus | None = None,
    decision: Literal["accepted", "rejected"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> list[SuggestionOut]:
    rows = SuggestionRepository(db).list(
        tenant.id, post_id=post_id, review_status=review_status, decision=decision, limit=limit, offset=offset
    )
    return [suggestion_out(s) for s in rows]


@router.get("/suggestions/{suggestion_id}", response_model=SuggestionDetail)
def inspect_suggestion(db: DB, tenant: CurrentTenant, suggestion_id: SuggestionId) -> SuggestionDetail:
    """Inspect why an image was suggested or refused: every guard check, the tags, the reviews."""
    s = SuggestionRepository(db).get(tenant.id, suggestion_id)
    if s is None:
        raise NotFound(f"suggestion {suggestion_id} not found")
    return suggestion_detail(db, s)


def _decide(db: DB, tenant_id: int, suggestion_id: int, action: str, body: ReviewIn | None) -> ReviewResult:
    body = body or ReviewIn()
    outcome = ReviewService(db).decide(tenant_id, suggestion_id, action, body.reviewer, body.note)
    status = outcome.suggestion.review_status
    message = f"suggestion {status}" if outcome.changed else f"already {status}; nothing changed (idempotent)"
    return ReviewResult(changed=outcome.changed, message=message, suggestion=suggestion_detail(db, outcome.suggestion))


@router.post("/suggestions/{suggestion_id}/approve", response_model=ReviewResult)
def approve(db: DB, tenant: CurrentTenant, suggestion_id: SuggestionId, body: ReviewIn | None = None) -> ReviewResult:
    return _decide(db, tenant.id, suggestion_id, "approve", body)


@router.post("/suggestions/{suggestion_id}/reject", response_model=ReviewResult)
def reject(db: DB, tenant: CurrentTenant, suggestion_id: SuggestionId, body: ReviewIn | None = None) -> ReviewResult:
    return _decide(db, tenant.id, suggestion_id, "reject", body)


@router.get("/review", response_class=HTMLResponse)
def review_table(
    db: DB,
    tenant: CurrentTenant,
    review_status: ReviewStatus | None = None,
    decision: Literal["accepted", "rejected"] | None = None,
) -> HTMLResponse:
    """A plain HTML table of suggestions for reviewers (no frontend build)."""
    rows = SuggestionRepository(db).list(tenant.id, review_status=review_status, decision=decision, limit=200)
    e = html.escape
    body = "".join(
        f"<tr><td>{s.id}</td><td>{e(s.post.title)}</td><td>{e(s.image.filename)}</td>"
        f"<td>{s.rank or ''}</td><td>{s.similarity:.2f}</td><td class='{s.decision}'>{s.decision}</td>"
        f"<td>{e(s.explanation)}</td><td>{s.review_status}</td></tr>"
        for s in rows
    )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Review queue</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left}}
.accepted{{color:#0a6b2d;font-weight:600}}.rejected{{color:#a4161a;font-weight:600}}</style></head>
<body><h1>Review queue ({len(rows)} suggestions)</h1>
<p>Approve or reject with <code>POST /suggestions/{{id}}/approve</code> or <code>/reject</code>;
inspect with <code>GET /suggestions/{{id}}</code>.</p>
<table><tr><th>id</th><th>post</th><th>image</th><th>rank</th><th>similarity</th><th>guard</th>
<th>explanation</th><th>review</th></tr>{body}</table></body></html>"""
    return HTMLResponse(page)
