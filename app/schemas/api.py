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

    kind: Literal["ingest", "images", "posts"] = "ingest"
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


# --- posts & matching -------------------------------------------------------------
class PostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$", examples=["red-fox-behavior"])
    title: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=20, max_length=20000)


class PostOut(ORM):
    id: int
    slug: str
    title: str
    body: str
    status: str
    subject: str | None
    category: str | None
    concepts: list[str] | None
    summary: str | None
    analysis_confidence: float | None
    error: str | None


class PostCreated(BaseModel):
    post: PostOut
    job_id: int


class CheckOut(BaseModel):
    name: str
    passed: bool
    detail: str
    value: float | None = None
    threshold: float | None = None


class CandidateOut(BaseModel):
    rank: int | None
    suggestion_id: int
    image_id: int
    filename: str
    subject: str | None
    category: str | None
    caption: str | None
    confidence: float | None
    needs_review: bool | None
    similarity: float
    subject_similarity: float | None
    decision: Literal["accepted", "rejected"]
    reasons: list[str]
    explanation: str
    checks: list[CheckOut]
    review_status: str


class MatchOut(BaseModel):
    post_id: int
    title: str
    post_subject: str | None
    post_category: str | None
    status: Literal["match", "no_confident_match"]
    suggestion: CandidateOut | None
    reasons: list[str]
    similarity_threshold: float
    candidates: list[CandidateOut]


class ForceCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: int = Field(ge=1)


# --- review -----------------------------------------------------------------------
class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reviewer: str = Field(default="editor", min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=2000)


class ReviewOut(ORM):
    id: int
    action: str
    reviewer: str
    note: str | None
    guard_decision: str
    created_at: datetime


class SuggestionOut(BaseModel):
    id: int
    post_id: int
    post_title: str
    image_id: int
    filename: str
    rank: int | None
    similarity: float
    decision: str
    explanation: str
    review_status: str


class SuggestionDetail(SuggestionOut):
    """Everything needed to see *why* an image was suggested or refused."""

    reasons: list[str]
    checks: list[CheckOut]
    guard_version: str
    post: PostOut
    image: ImageOut
    reviews: list[ReviewOut]


class ReviewResult(BaseModel):
    changed: bool
    message: str
    suggestion: SuggestionDetail
