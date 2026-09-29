from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Suggestion


class SuggestionRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, tenant_id: int, suggestion_id: int) -> Suggestion | None:
        return self.s.scalar(
            select(Suggestion)
            .where(Suggestion.tenant_id == tenant_id, Suggestion.id == suggestion_id)
            .options(selectinload(Suggestion.post), selectinload(Suggestion.image))
        )

    def get_for_update(self, tenant_id: int, suggestion_id: int) -> Suggestion | None:
        """Row lock so two concurrent approve/reject calls are serialised."""
        return self.s.scalar(
            select(Suggestion)
            .where(Suggestion.tenant_id == tenant_id, Suggestion.id == suggestion_id)
            .with_for_update()
        )

    def list(
        self,
        tenant_id: int,
        *,
        post_id: int | None = None,
        review_status: str | None = None,
        decision: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Suggestion]:
        q = (
            select(Suggestion)
            .where(Suggestion.tenant_id == tenant_id)
            .options(selectinload(Suggestion.post), selectinload(Suggestion.image))
        )
        if post_id is not None:
            q = q.where(Suggestion.post_id == post_id)
        if review_status:
            q = q.where(Suggestion.review_status == review_status)
        if decision:
            q = q.where(Suggestion.decision == decision)
        q = q.order_by(Suggestion.post_id, Suggestion.rank.asc().nulls_last(), Suggestion.id)
        return list(self.s.scalars(q.limit(limit).offset(offset)))

    def clear_ranks(self, post_id: int) -> None:
        """Before re-ranking a post, forget old ranks (verdicts and reviews are kept)."""
        self.s.execute(update(Suggestion).where(Suggestion.post_id == post_id).values(rank=None))

    def get_pair(self, post_id: int, image_id: int) -> Suggestion | None:
        return self.s.scalar(
            select(Suggestion).where(Suggestion.post_id == post_id, Suggestion.image_id == image_id)
        )

    def upsert(self, tenant_id: int, post_id: int, image_id: int, **fields) -> Suggestion:
        """Insert or refresh the verdict for a pair. The human review status is kept."""
        row = self.get_pair(post_id, image_id)
        if row is None:
            row = Suggestion(tenant_id=tenant_id, post_id=post_id, image_id=image_id)
            self.s.add(row)
        for k, v in fields.items():
            setattr(row, k, v)
        self.s.flush()
        return row
