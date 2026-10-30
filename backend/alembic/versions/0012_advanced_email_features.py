"""Advanced email features: OTP tracking, URL shortener, and automated retest.

Revision ID: 0012_advanced_email_features
Revises: 0011_qr_identity_resolution
Create Date: 2026-10-30 18:00:00

Adds:
* ``campaigns.auto_retest_failed``: auto-drip retest toggle for campaigns.
* ``tracking_events.short_code``: unique short URL code.
* ``tracking_events.otp_submitted``: flag indicating OTP / MFA code submission.
* ``tracking_events.otp_submitted_at``: timestamp of OTP submission.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_advanced_email_features"
down_revision: str | None = "0011_qr_identity_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAMPAIGNS = "campaigns"
TRACKING = "tracking_events"


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


def _add_column(table: str, column: sa.Column) -> None:
    """Add a column only when it is not already present."""
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(table: str, name: str, columns: list[str], unique: bool = False) -> None:
    """Create an index unless the same name already exists."""
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    """Add columns for OTP simulation, link shortener, and drip retesting."""
    _add_column(
        CAMPAIGNS,
        sa.Column(
            "auto_retest_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    _add_column(TRACKING, sa.Column("short_code", sa.String(16), nullable=True))
    _add_column(
        TRACKING,
        sa.Column(
            "otp_submitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column(TRACKING, sa.Column("otp_submitted_at", sa.DateTime(timezone=True), nullable=True))

    _create_index(TRACKING, "ix_tracking_events_short_code", ["short_code"], unique=True)


def downgrade() -> None:
    """Remove advanced email columns and indexes."""
    tracking_indexes = _indexes(TRACKING)
    if "ix_tracking_events_short_code" in tracking_indexes:
        op.drop_index("ix_tracking_events_short_code", table_name=TRACKING)

    tracking_columns = _columns(TRACKING)
    for col in ("short_code", "otp_submitted", "otp_submitted_at"):
        if col in tracking_columns:
            with op.batch_alter_table(TRACKING) as batch:
                batch.drop_column(col)

    campaign_columns = _columns(CAMPAIGNS)
    if "auto_retest_failed" in campaign_columns:
        with op.batch_alter_table(CAMPAIGNS) as batch:
            batch.drop_column("auto_retest_failed")
