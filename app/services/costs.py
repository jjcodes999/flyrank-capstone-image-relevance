"""Per-call cost tracking and the budget guard.

Every AI call (vision, post analysis, embedding) gets one cost_records row, including
failed and invalid calls. The row is written *before* the call (begin) and completed
after it (finish), each in its own short transaction: a rollback of the surrounding work
can't erase it, and a worker killed mid-call still leaves an attributed row behind.

Local Ollama costs $0, so actual_cost_usd is always 0. notional_cost_usd prices the same
tokens at configurable reference rates; the budget guard enforces AI_BUDGET_USD on that
notional total, plus a hard cap on calls per job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import BudgetExceeded
from app.models import CostRecord
from app.repositories.costs import CostRepository

log = logging.getLogger(__name__)

PROVIDER = "ollama"
IN_PROGRESS = "no reply recorded: call in progress, or the worker stopped mid-call"


@dataclass(frozen=True)
class CallContext:
    """Who an AI call is for: used to attribute every cost row."""

    tenant_id: int
    job_id: int | None = None
    target_type: str | None = None
    target_id: int | None = None


class CostTracker:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._sessions = session_factory
        self._settings = settings

    def notional_cost(self, operation: str, input_tokens: int, output_tokens: int) -> Decimal:
        s = self._settings
        if operation == "embed":
            usd = input_tokens * s.notional_usd_per_1m_embed_tokens / 1_000_000
        else:
            usd = (
                input_tokens * s.notional_usd_per_1m_input_tokens
                + output_tokens * s.notional_usd_per_1m_output_tokens
            ) / 1_000_000
        return Decimal(str(round(usd, 8)))

    def check_budget(self, ctx: CallContext) -> None:
        """Raise BudgetExceeded *before* a call if the tenant or job is over its limit."""
        with self._sessions() as session:
            repo = CostRepository(session)
            spent = repo.total_notional(ctx.tenant_id)
            if spent >= Decimal(str(self._settings.ai_budget_usd)):
                raise BudgetExceeded(
                    f"AI budget exhausted: notional spend ${spent:.6f} >= budget "
                    f"${self._settings.ai_budget_usd:.2f}"
                )
            if ctx.job_id is not None:
                calls = repo.calls_for_job(ctx.job_id)
                if calls >= self._settings.ai_max_calls_per_job:
                    raise BudgetExceeded(
                        f"job {ctx.job_id} reached the cap of {self._settings.ai_max_calls_per_job} AI calls"
                    )

    def begin(self, ctx: CallContext, *, operation: str, model: str, attempt: int = 1) -> int:
        """Write the cost row before the call; returns its id for finish()."""
        row = CostRecord(
            tenant_id=ctx.tenant_id,
            job_id=ctx.job_id,
            target_type=ctx.target_type,
            target_id=ctx.target_id,
            operation=operation,
            provider=PROVIDER,
            model=model,
            attempt=attempt,
            success=False,
            error=IN_PROGRESS,
            notional_cost_usd=Decimal("0"),
            actual_cost_usd=Decimal("0"),
        )
        with self._sessions() as session:
            CostRepository(session).add(row)
            session.commit()
            return row.id

    def finish(
        self,
        row_id: int,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
        success: bool,
        error: str | None = None,
    ) -> None:
        with self._sessions() as session:
            row = session.get(CostRecord, row_id)
            assert row is not None
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            row.duration_ms = duration_ms
            row.success = success
            row.error = error[:1000] if error else None
            row.notional_cost_usd = self.notional_cost(row.operation, input_tokens, output_tokens)
            session.commit()
            log.info(
                "cost op=%s model=%s target=%s:%s in=%d out=%d ms=%d ok=%s",
                row.operation, row.model, row.target_type, row.target_id,
                input_tokens, output_tokens, duration_ms, success,
            )
