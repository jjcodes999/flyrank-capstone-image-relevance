from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentTenant
from app.config import get_settings
from app.repositories.costs import CostRepository
from app.schemas.api import CostLine, CostRecordOut, CostSummary

router = APIRouter(prefix="/costs", tags=["costs"])

Operation = Literal["vision_tag", "post_analysis", "embed"]


@router.get("", response_model=CostSummary)
def cost_summary(db: DB, tenant: CurrentTenant) -> CostSummary:
    repo = CostRepository(db)
    lines = [CostLine(**row) for row in repo.summary(tenant.id)]
    notional = sum((line.notional_cost_usd for line in lines), Decimal("0"))
    actual = sum((line.actual_cost_usd for line in lines), Decimal("0"))
    budget = Decimal(str(get_settings().ai_budget_usd))
    return CostSummary(
        total_calls=sum(line.calls for line in lines),
        notional_cost_usd=notional,
        actual_cost_usd=actual,
        budget_usd=budget,
        budget_remaining_usd=max(budget - notional, Decimal("0")),
        note="Local Ollama: actual cost is $0. Notional cost prices the same tokens at the "
        "reference rates in .env and is what the budget guard enforces.",
        by_operation=lines,
    )


@router.get("/records", response_model=list[CostRecordOut])
def cost_records(
    db: DB,
    tenant: CurrentTenant,
    operation: Operation | None = None,
    job_id: Annotated[int | None, Query(ge=1)] = None,
    target_type: Literal["image", "post"] | None = None,
    target_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CostRecordOut]:
    rows = CostRepository(db).list(
        tenant.id,
        operation=operation,
        job_id=job_id,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )
    return [CostRecordOut.model_validate(r) for r in rows]
