"""matching tables: pgvector embeddings for images and posts, suggestions

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

DIM = 384  # all-minilm


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("posts", sa.Column("analysis_source_sha256", sa.String(64)))

    op.create_table(
        "image_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "image_id", sa.Integer, sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("subject_embedding", Vector(DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_image_embeddings_tenant", "image_embeddings", ["tenant_id"])
    # approximate nearest-neighbour index for cosine distance (the ranking query's ORDER BY)
    op.execute(
        "CREATE INDEX ix_image_embeddings_hnsw ON image_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "post_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "post_id", sa.Integer, sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("subject_embedding", Vector(DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_id", sa.Integer, sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer),  # null when the pair was force-checked, not ranked
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reasons", JSONB, nullable=False),
        sa.Column("checks", JSONB, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("guard_version", sa.String(20), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("post_id", "image_id", name="uq_suggestions_post_image"),
        sa.CheckConstraint("decision IN ('accepted', 'rejected')", name="ck_suggestions_decision"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')", name="ck_suggestions_review_status"
        ),
    )
    op.create_index("ix_suggestions_post_rank", "suggestions", ["post_id", "rank"])
    op.create_index("ix_suggestions_tenant_review", "suggestions", ["tenant_id", "review_status"])


def downgrade() -> None:
    op.drop_table("suggestions")
    op.drop_table("post_embeddings")
    op.drop_table("image_embeddings")
    op.drop_column("posts", "analysis_source_sha256")
