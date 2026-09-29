"""SQLAlchemy ORM models. The schema itself is owned by Alembic migrations (alembic/versions)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

IMAGE_STATUSES = ("pending", "tagged", "needs_review", "failed")
POST_STATUSES = ("pending", "ready", "failed")
JOB_STATUSES = ("queued", "running", "succeeded", "failed")
ITEM_STATUSES = ("queued", "running", "done", "skipped", "failed")
REVIEW_STATUSES = ("pending", "approved", "rejected")
EMBED_DIM = 384  # all-minilm; must match migration 0002


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Image(TimestampMixin, Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("tenant_id", "filename", name="uq_images_tenant_filename"),
        Index("ix_images_tenant_status", "tenant_id", "status"),
        Index("ix_images_sha256", "sha256"),
        CheckConstraint(_in("status", IMAGE_STATUSES), name="ck_images_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    photographer: Mapped[str | None] = mapped_column(String(200))
    license: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)

    meta: Mapped["ImageMetadata | None"] = relationship(back_populates="image", uselist=False)
    embedding: Mapped["ImageEmbedding | None"] = relationship(uselist=False, viewonly=True)
    tags: Mapped[list["ImageTag"]] = relationship(back_populates="image", cascade="all, delete-orphan")


class ImageMetadata(TimestampMixin, Base):
    """Validated vision output for one image (one current row per image)."""

    __tablename__ = "image_metadata"
    __table_args__ = (Index("ix_image_metadata_category", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), unique=True)
    subject: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))
    attributes: Mapped[list[str]] = mapped_column(JSONB)
    caption: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean)
    review_reasons: Mapped[list[str]] = mapped_column(JSONB)
    sharpness: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    source_sha256: Mapped[str] = mapped_column(String(64))
    raw_response: Mapped[str] = mapped_column(Text)
    validation_attempts: Mapped[int] = mapped_column(Integer)

    image: Mapped[Image] = relationship(back_populates="meta")


class ImageTag(Base):
    __tablename__ = "image_tags"
    __table_args__ = (
        UniqueConstraint("image_id", "tag", "kind", name="uq_image_tags_image_tag_kind"),
        Index("ix_image_tags_tag", "tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    tag: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # subject | attribute | category

    image: Mapped[Image] = relationship(back_populates="tags")


class Post(TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_posts_tenant_slug"),
        Index("ix_posts_tenant_status", "tenant_id", "status"),
        CheckConstraint(_in("status", POST_STATUSES), name="ck_posts_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    # filled by post analysis (common-name subject, so "Vulpes vulpes" -> "red fox")
    subject: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(20))
    concepts: Mapped[list[str] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    analysis_confidence: Mapped[float | None] = mapped_column(Float)
    analysis_model: Mapped[str | None] = mapped_column(String(100))
    analysis_prompt_version: Mapped[str | None] = mapped_column(String(20))
    analysis_source_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)

    embedding: Mapped["PostEmbedding | None"] = relationship(uselist=False, viewonly=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency_key"),
        Index("ix_jobs_status_id", "status", "id"),
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_jobs_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    force: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    succeeded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["JobItem"]] = relationship(back_populates="job", order_by="JobItem.id")


class JobItem(Base):
    __tablename__ = "job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "target_type", "target_id", name="uq_job_items_job_target"),
        Index("ix_job_items_job_status", "job_id", "status"),
        CheckConstraint(_in("status", ITEM_STATUSES), name="ck_job_items_status"),
        CheckConstraint(_in("target_type", ("image", "post")), name="ck_job_items_target_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[Job] = relationship(back_populates="items")


class CostRecord(Base):
    """One row per AI call (vision, post analysis, embedding), successful or not."""

    __tablename__ = "cost_records"
    __table_args__ = (
        Index("ix_cost_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_cost_records_job", "job_id"),
        Index("ix_cost_records_operation", "operation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    target_type: Mapped[str | None] = mapped_column(String(10))
    target_id: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    notional_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    actual_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImageEmbedding(Base):
    __tablename__ = "image_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    subject_embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostEmbedding(Base):
    __tablename__ = "post_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True)
    model: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    subject_embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Suggestion(TimestampMixin, Base):
    """A guard verdict for one (post, image) pair, plus its human review status."""

    __tablename__ = "suggestions"
    __table_args__ = (
        UniqueConstraint("post_id", "image_id", name="uq_suggestions_post_image"),
        Index("ix_suggestions_post_rank", "post_id", "rank"),
        Index("ix_suggestions_tenant_review", "tenant_id", "review_status"),
        CheckConstraint(_in("decision", ("accepted", "rejected")), name="ck_suggestions_decision"),
        CheckConstraint(_in("review_status", REVIEW_STATUSES), name="ck_suggestions_review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    rank: Mapped[int | None] = mapped_column(Integer)
    similarity: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    checks: Mapped[list[dict]] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    guard_version: Mapped[str] = mapped_column(String(20))
    review_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")

    post: Mapped[Post] = relationship()
    image: Mapped[Image] = relationship()
