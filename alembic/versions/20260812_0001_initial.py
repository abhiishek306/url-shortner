"""initial schema

Revision ID: 20260812_0001
Revises: 
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "urls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("short_id", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("click_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_urls_short_id_unique", "urls", ["short_id"], unique=True)
    op.create_index("ix_urls_user_created", "urls", ["user_id", "created_at"], unique=False)
    op.create_index("ix_urls_user_id", "urls", ["user_id"], unique=False)

    op.create_table(
        "click_analytics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("url_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("browser", sa.String(length=128), nullable=False),
        sa.Column("referrer", sa.String(length=255), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["url_id"], ["urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_click_analytics_clicked_at", "click_analytics", ["clicked_at"], unique=False)
    op.create_index("ix_click_analytics_url_id", "click_analytics", ["url_id"], unique=False)
    op.create_index("ix_click_analytics_user_id", "click_analytics", ["user_id"], unique=False)
    op.create_index("ix_click_analytics_url_time", "click_analytics", ["url_id", "clicked_at"], unique=False)
    op.create_index("ix_click_analytics_user_time", "click_analytics", ["user_id", "clicked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_click_analytics_user_time", table_name="click_analytics")
    op.drop_index("ix_click_analytics_url_time", table_name="click_analytics")
    op.drop_index("ix_click_analytics_user_id", table_name="click_analytics")
    op.drop_index("ix_click_analytics_url_id", table_name="click_analytics")
    op.drop_index("ix_click_analytics_clicked_at", table_name="click_analytics")
    op.drop_table("click_analytics")

    op.drop_index("ix_urls_user_id", table_name="urls")
    op.drop_index("ix_urls_user_created", table_name="urls")
    op.drop_index("ix_urls_short_id_unique", table_name="urls")
    op.drop_table("urls")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
