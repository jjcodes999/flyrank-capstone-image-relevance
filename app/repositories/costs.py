from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CostRecord


class CostRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, record: CostRecord) -> CostRecord:
        self.s.add(record)
        self.s.flush()
        return record

    def total_notional(self, tenant_id: int) -> Decimal:
        total = self.s.scalar(
            select(func.coalesce(func.sum(CostRecord.notional_cost_usd), 0)).where(
                CostRecord.tenant_id == tenant_id
            )
        )
        return Decimal(total)

    def calls_for_job(self, job_id: int) -> int:
        return self.s.scalar(select(func.count()).where(CostRecord.job_id == job_id)) or 0

    def summary(self, tenant_id: int) -> list[dict]:
        rows = self.s.execute(
            select(
                CostRecord.operation,
                CostRecord.model,
                func.count().label("calls"),
                func.count().filter(CostRecord.success.is_(False)).label("failed_calls"),
                func.sum(CostRecord.input_tokens).label("input_tokens"),
                func.sum(CostRecord.output_tokens).label("output_tokens"),
                func.sum(CostRecord.duration_ms).label("duration_ms"),
                func.sum(CostRecord.notional_cost_usd).label("notional_cost_usd"),
                func.sum(CostRecord.actual_cost_usd).label("actual_cost_usd"),
            )
            .where(CostRecord.tenant_id == tenant_id)
            .group_by(CostRecord.operation, CostRecord.model)
            .order_by(CostRecord.operation)
        )
        return [dict(r._mapping) for r in rows]

    def list(
        self,
        tenant_id: int,
        *,
        operation: str | None = None,
        job_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CostRecord]:
        q = select(CostRecord).where(CostRecord.tenant_id == tenant_id)
        if operation:
            q = q.where(CostRecord.operation == operation)
        if job_id is not None:
            q = q.where(CostRecord.job_id == job_id)
        if target_type:
            q = q.where(CostRecord.target_type == target_type)
        if target_id is not None:
            q = q.where(CostRecord.target_id == target_id)
        return list(self.s.scalars(q.order_by(CostRecord.id.desc()).limit(limit).offset(offset)))

    def count(self, tenant_id: int) -> int:
        return self.s.scalar(select(func.count()).where(CostRecord.tenant_id == tenant_id)) or 0
