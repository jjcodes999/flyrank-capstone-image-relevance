"""Request and response bodies for the HTTP API."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- images -----------------------------------------------------------------------
class ImageMetaOut(ORM):
    subject: str
    category: str
    attributes: list[str]
    caption: str
    confidence: float
    needs_review: bool
    review_reasons: list[str]
    sharpness: float
    model: str
    prompt_version: str
    validation_attempts: int


class ImageOut(ORM):
    id: int
    filename: str
    status: str
    error: str | None
    width: int
    height: int
    source_url: str | None
    photographer: str | None
    license: str | None
    meta: ImageMetaOut | None


class ImageList(BaseModel):
    count: int
    status_counts: dict[str, int]
    items: list[ImageOut]


# --- jobs -------------------------------------------------------------------------
class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["images"] = "images"
    force: bool = Field(default=False, description="Re-process items even if their results are current")


class JobItemOut(ORM):
    id: int
    target_type: str
    target_id: int
    status: str
    attempts: int
    last_error: str | None


class JobOut(ORM):
    id: int
    kind: str
    status: str
    idempotency_key: str | None
    force: bool
    total: int
    processed: int
    succeeded: int
    skipped: int
    failed: int
    progress: float
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failed_items: list[JobItemOut] = []


# --- costs ------------------------------------------------------------------------
class CostLine(BaseModel):
    operation: str
    model: str
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    duration_ms: int
    notional_cost_usd: Decimal
    actual_cost_usd: Decimal


class CostSummary(BaseModel):
    total_calls: int
    notional_cost_usd: Decimal
    actual_cost_usd: Decimal
    budget_usd: Decimal
    budget_remaining_usd: Decimal
    note: str
    by_operation: list[CostLine]


class CostRecordOut(ORM):
    id: int
    job_id: int | None
    target_type: str | None
    target_id: int | None
    operation: str
    provider: str
    model: str
    attempt: int
    input_tokens: int
    output_tokens: int
    duration_ms: int
    success: bool
    error: str | None
    notional_cost_usd: Decimal
    actual_cost_usd: Decimal
    created_at: datetime
