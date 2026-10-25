"""Delivery failure timestamp

Revision ID: 0007_delivery_failed_at
Revises: 0006_vonage_delivery
Create Date: 2026-10-23 18:45:00

Records when Vonage reported a failed or rejected delivery.  Keeping the
timestamp separate from ``updated_at`` makes the provider event time available
for audits and campaign exports.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_delivery_failed_at"
down_revision: str | None = "0006_vonage_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "tracking_events"
COLUMN = "failed_at"


def _column_exists() -> bool:
    """Return ``True`` when the tracking table already has ``failed_at``."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return False
    return COLUMN in {item["name"] for item in inspector.get_columns(TABLE)}


def upgrade() -> None:
    """Add the provider failure timestamp column."""
    if not _column_exists():
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove the provider failure timestamp column."""
    if _column_exists():
        op.drop_column(TABLE, COLUMN)
