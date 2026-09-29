"""Human review of suggestions: approve / reject, idempotently.

- Repeating the same decision is a no-op (no second review row) -> safe to retry.
- Flipping a decision (approved -> rejected) is refused with 409; a reviewer must look
  at it on purpose, not by a replayed request.
- The suggestion row is locked while deciding, so two concurrent clicks cannot both write.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.models import Review, Suggestion
from app.repositories.suggestions import SuggestionRepository

STATUS_FOR = {"approve": "approved", "reject": "rejected"}


@dataclass
class ReviewOutcome:
    suggestion: Suggestion
    changed: bool  # False when this was a repeat of the current decision


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.suggestions = SuggestionRepository(session)

    def decide(self, tenant_id: int, suggestion_id: int, action: str, reviewer: str, note: str | None) -> ReviewOutcome:
        suggestion = self.suggestions.get_for_update(tenant_id, suggestion_id)
        if suggestion is None:
            raise NotFound(f"suggestion {suggestion_id} not found")
        target = STATUS_FOR[action]
        if suggestion.review_status == target:
            self.s.rollback()  # release the lock; nothing to do
            return ReviewOutcome(self.suggestions.get(tenant_id, suggestion_id), changed=False)  # type: ignore[arg-type]
        if suggestion.review_status != "pending":
            self.s.rollback()
            raise Conflict(
                f"suggestion {suggestion_id} is already {suggestion.review_status}; "
                f"refusing to {action} it again with a different decision"
            )
        suggestion.review_status = target
        self.s.add(
            Review(
                tenant_id=tenant_id,
                suggestion_id=suggestion.id,
                action=action,
                reviewer=reviewer,
                note=note,
                guard_decision=suggestion.decision,
            )
        )
        self.s.commit()
        return ReviewOutcome(self.suggestions.get(tenant_id, suggestion_id), changed=True)  # type: ignore[arg-type]

    def history(self, suggestion_id: int) -> list[Review]:
        return list(
            self.s.scalars(select(Review).where(Review.suggestion_id == suggestion_id).order_by(Review.id))
        )
