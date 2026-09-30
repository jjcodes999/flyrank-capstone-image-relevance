"""Per-call cost tracking and the budget guard.

Every AI call (vision, post analysis, embedding) gets one cost_records row, including
failed and invalid calls. The row is written *before* the call (begin) and completed
after it (finish), each in its own short transaction: a rollback of the surrounding work
can't erase it, and a worker killed mid-call still leaves an attributed row behind.

Local Ollama costs $0, so actual_cost_usd is always 0. notional_cost_usd prices the same
tokens at configurable reference rates, and the budget guard enforces AI_BUDGET_USD on
that notional total as a hard cap:

- begin() reserves the call's worst-case cost (a call can't use more than OLLAMA_NUM_CTX
  tokens) and refuses the call if spend + reservation would exceed the budget;
- the check and the reservation happen in one transaction under a per-tenant lock, so
  concurrent workers can't both squeeze past the limit;
- finish() replaces the reservation with the real cost. If the real usage is unknown
  (timeout, crash) the reservation stays: an upper bound, never an under-count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import BudgetExceeded
from app.models import CostRecord
from app.repositories.costs import CostRepository
from app.repositories.jobs import JobRepository

log = logging.getLogger(__name__)

PROVIDER = "ollama"
IN_PROGRESS = "no reply recorded: call in progress, or the worker stopped mid-call"
USAGE_UNKNOWN = "usage unknown; notional cost is the reserved upper bound"


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

    def reservation(self, operation: str) -> Decimal:
        """Worst case for one call: every token of the context window at the dearest rate."""
        s = self._settings
        n = s.ollama_num_ctx
        if operation == "embed":
            return self.notional_cost("embed", n, 0)
        dearest = max(s.notional_usd_per_1m_input_tokens, s.notional_usd_per_1m_output_tokens)
        return Decimal(str(round(n * dearest / 1_000_000, 8)))

    def begin(self, ctx: CallContext, *, operation: str, model: str, attempt: int = 1) -> int:
        """Check the budget, reserve the call's worst-case cost and write its row.

        Raises BudgetExceeded *before* the call if it could take the tenant over budget,
        or if the job has used its call cap. Returns the row id for finish().
        """
        reserve = self.reservation(operation)
        budget = Decimal(str(self._settings.ai_budget_usd))
        with self._sessions() as session:
            # one budget decision at a time per tenant (released at commit/rollback)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx.tenant_id})
            repo = CostRepository(session)
            spent = repo.total_notional(ctx.tenant_id)  # includes other calls' reservations
            if spent + reserve > budget:
                raise BudgetExceeded(
                    f"AI budget exhausted: notional spend ${spent:.6f} + this call's reserve "
                    f"${reserve:.6f} would exceed the budget ${budget:.6f}"
                )
            if ctx.job_id is not None:
                if repo.calls_for_job(ctx.job_id) >= self._settings.ai_max_calls_per_job:
                    raise BudgetExceeded(
                        f"job {ctx.job_id} reached the cap of {self._settings.ai_max_calls_per_job} AI calls"
                    )
                # every model call is also a sign of life for the job that made it
                JobRepository(session).touch(ctx.job_id)
            row = repo.add(
                CostRecord(
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
                    notional_cost_usd=reserve,
                    actual_cost_usd=Decimal("0"),
                )
            )
            session.commit()
            return row.id

    def finish(
        self,
        row_id: int,
        *,
        input_tokens: int | None = 0,
        output_tokens: int | None = 0,
        duration_ms: int = 0,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Complete a row. Pass input_tokens=None when the call's usage is unknown."""
        with self._sessions() as session:
            row = session.get(CostRecord, row_id)
            assert row is not None
            row.duration_ms = duration_ms
            row.success = success
            if input_tokens is None:  # e.g. a timeout: keep the reservation as the cost
                error = f"{error} ({USAGE_UNKNOWN})" if error else USAGE_UNKNOWN
            else:
                row.input_tokens = input_tokens
                row.output_tokens = output_tokens or 0
                row.notional_cost_usd = self.notional_cost(row.operation, input_tokens, output_tokens or 0)
            row.error = error[:1000] if error else None
            session.commit()
            log.info(
                "cost op=%s model=%s target=%s:%s in=%s out=%s ms=%d ok=%s",
                row.operation, row.model, row.target_type, row.target_id,
                row.input_tokens, row.output_tokens, duration_ms, success,
            )
