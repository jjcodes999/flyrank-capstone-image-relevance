"""pipeline tables: tenants, images, metadata, tags, posts, jobs, cost records

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "images",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("photographer", sa.String(200)),
        sa.Column("license", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "filename", name="uq_images_tenant_filename"),
        sa.CheckConstraint(
            "status IN ('pending', 'tagged', 'needs_review', 'failed')", name="ck_images_status"
        ),
    )
    op.create_index("ix_images_tenant_status", "images", ["tenant_id", "status"])
    op.create_index("ix_images_sha256", "images", ["sha256"])

    op.create_table(
        "image_metadata",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "image_id", sa.Integer, sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("attributes", JSONB, nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("needs_review", sa.Boolean, nullable=False),
        sa.Column("review_reasons", JSONB, nullable=False),
        sa.Column("sharpness", sa.Float, nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("raw_response", sa.Text, nullable=False),
        sa.Column("validation_attempts", sa.Integer, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_image_metadata_confidence"),
    )
    op.create_index("ix_image_metadata_category", "image_metadata", ["category"])

    op.create_table(
        "image_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("image_id", sa.Integer, sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.UniqueConstraint("image_id", "tag", "kind", name="uq_image_tags_image_tag_kind"),
    )
    op.create_index("ix_image_tags_tag", "image_tags", ["tag"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("subject", sa.String(100)),
        sa.Column("category", sa.String(20)),
        sa.Column("concepts", JSONB),
        sa.Column("summary", sa.Text),
        sa.Column("analysis_confidence", sa.Float),
        sa.Column("analysis_model", sa.String(100)),
        sa.Column("analysis_prompt_version", sa.String(20)),
        sa.Column("error", sa.Text),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_posts_tenant_slug"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_posts_status"),
    )
    op.create_index("ix_posts_tenant_status", "posts", ["tenant_id", "status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column("force", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency_key"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"),
    )
    op.create_index("ix_jobs_status_id", "jobs", ["status", "id"])

    op.create_table(
        "job_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(10), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id", "target_type", "target_id", name="uq_job_items_job_target"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'skipped', 'failed')", name="ck_job_items_status"
        ),
        sa.CheckConstraint("target_type IN ('image', 'post')", name="ck_job_items_target_type"),
    )
    op.create_index("ix_job_items_job_status", "job_items", ["job_id", "status"])

    op.create_table(
        "cost_records",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("target_type", sa.String(10)),
        sa.Column("target_id", sa.Integer),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("notional_cost_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("actual_cost_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_records_tenant_created", "cost_records", ["tenant_id", "created_at"])
    op.create_index("ix_cost_records_job", "cost_records", ["job_id"])
    op.create_index("ix_cost_records_operation", "cost_records", ["operation"])


def downgrade() -> None:
    for table in ("cost_records", "job_items", "jobs", "posts", "image_tags", "image_metadata", "images", "tenants"):
        op.drop_table(table)
