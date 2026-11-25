"""make analytics stream processing idempotent

Revision ID: 20261125_0002
Revises: 20260812_0001
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20261125_0002"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("click_analytics", sa.Column("stream_id", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_click_analytics_stream_id",
        "click_analytics",
        ["stream_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_click_analytics_stream_id", table_name="click_analytics")
    op.drop_column("click_analytics", "stream_id")
