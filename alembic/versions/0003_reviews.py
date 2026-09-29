"""reviews: the approve/reject log for suggestions

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "suggestion_id", sa.Integer, sa.ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("guard_decision", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action IN ('approve', 'reject')", name="ck_reviews_action"),
    )
    op.create_index("ix_reviews_suggestion", "reviews", ["suggestion_id"])
    op.create_index("ix_reviews_tenant_created", "reviews", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("reviews")
