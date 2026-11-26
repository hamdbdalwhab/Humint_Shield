"""Monthly archives, campaign cooldown and repeated-failure blacklist.

Revision ID: 0014_monthly_archives_guardrails
Revises: 0013_qr_tracking_enhancements
Create Date: 2026-11-10 12:00:00

Adds:
* ``organizations.campaign_cooldown_days`` (default 14).
* ``campaigns.is_mandatory_training``.
* ``human_assets.is_blacklisted`` / ``blacklist_reason`` / ``blacklisted_at``.
* ``monthly_archives`` table.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_monthly_archives_guardrails"
down_revision: str | None = "0013_qr_tracking_enhancements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Match ``app.database.UUIDType``: native UUID on PostgreSQL, CHAR(32) on SQLite.
UUID_TYPE = sa.Uuid(as_uuid=True)
MONTHLY_ARCHIVES = "monthly_archives"


def _columns(table: str) -> set[str]:
    """Return the current column names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    """Return the current index names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    """Apply the module 2/3/4 schema additions."""
    if sa.inspect(op.get_bind()).has_table("organizations"):
        if "campaign_cooldown_days" not in _columns("organizations"):
            op.add_column(
                "organizations",
                sa.Column(
                    "campaign_cooldown_days",
                    sa.Integer(),
                    nullable=False,
                    server_default="14",
                ),
            )

    if sa.inspect(op.get_bind()).has_table("campaigns"):
        if "is_mandatory_training" not in _columns("campaigns"):
            op.add_column(
                "campaigns",
                sa.Column(
                    "is_mandatory_training",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )

    if sa.inspect(op.get_bind()).has_table("human_assets"):
        asset_columns = _columns("human_assets")
        if "is_blacklisted" not in asset_columns:
            op.add_column(
                "human_assets",
                sa.Column(
                    "is_blacklisted",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "blacklist_reason" not in asset_columns:
            op.add_column(
                "human_assets",
                sa.Column("blacklist_reason", sa.String(100), nullable=True),
            )
        if "blacklisted_at" not in asset_columns:
            op.add_column(
                "human_assets",
                sa.Column("blacklisted_at", sa.DateTime(timezone=True), nullable=True),
            )

    if not sa.inspect(op.get_bind()).has_table(MONTHLY_ARCHIVES):
        op.create_table(
            MONTHLY_ARCHIVES,
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column(
                "employee_id",
                UUID_TYPE,
                sa.ForeignKey("human_assets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("month_year", sa.String(7), nullable=False),
            sa.Column("final_elo_score", sa.Integer(), nullable=False),
            sa.Column(
                "total_reports", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "total_clicks", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "total_submissions", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "employee_id", "month_year", name="uq_monthly_archive_employee_month"
            ),
        )
        op.create_index(
            "ix_monthly_archives_employee_id",
            MONTHLY_ARCHIVES,
            ["employee_id"],
        )
        op.create_index(
            "ix_monthly_archives_month_year",
            MONTHLY_ARCHIVES,
            ["month_year"],
        )


def downgrade() -> None:
    """Revert the module 2/3/4 schema additions."""
    if sa.inspect(op.get_bind()).has_table(MONTHLY_ARCHIVES):
        op.drop_table(MONTHLY_ARCHIVES)

    if sa.inspect(op.get_bind()).has_table("human_assets"):
        asset_columns = _columns("human_assets")
        with op.batch_alter_table("human_assets") as batch:
            if "blacklisted_at" in asset_columns:
                batch.drop_column("blacklisted_at")
            if "blacklist_reason" in asset_columns:
                batch.drop_column("blacklist_reason")
            if "is_blacklisted" in asset_columns:
                batch.drop_column("is_blacklisted")

    if sa.inspect(op.get_bind()).has_table("campaigns"):
        if "is_mandatory_training" in _columns("campaigns"):
            with op.batch_alter_table("campaigns") as batch:
                batch.drop_column("is_mandatory_training")

    if sa.inspect(op.get_bind()).has_table("organizations"):
        if "campaign_cooldown_days" in _columns("organizations"):
            with op.batch_alter_table("organizations") as batch:
                batch.drop_column("campaign_cooldown_days")
