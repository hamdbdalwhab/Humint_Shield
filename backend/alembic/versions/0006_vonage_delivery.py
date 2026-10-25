"""Vonage delivery and read receipts

Revision ID: 0006_vonage_delivery
Revises: 0005_unified_channels
Create Date: 2026-10-23 00:10:00

Adds the provider-neutral delivery receipt fields used by the SMS DLR and
WhatsApp status webhooks, plus an index for the webhook lookup by
``provider_message_id``.

The migration is idempotent so deployments that already created the columns
from ORM metadata (``AUTO_CREATE_SCHEMA=true``) can still upgrade cleanly.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_vonage_delivery"
down_revision: str | None = "0005_unified_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "tracking_events"
INDEX = "ix_tracking_events_provider_message_id"


def _inspector():
    """Return a SQLAlchemy inspector for the current bind."""
    return sa.inspect(op.get_bind())


def _column_exists(column: str) -> bool:
    """Return ``True`` when ``tracking_events.column`` exists."""
    inspector = _inspector()
    if not inspector.has_table(TABLE):
        return False
    return column in {item["name"] for item in inspector.get_columns(TABLE)}


def _index_exists(name: str) -> bool:
    """Return ``True`` when the named index exists on the tracking table."""
    inspector = _inspector()
    if not inspector.has_table(TABLE):
        return False
    return name in {item["name"] for item in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    """Add delivery status, error and WhatsApp read timestamp fields."""
    if not _column_exists("delivery_status"):
        op.add_column(
            TABLE,
            sa.Column("delivery_status", sa.String(20), nullable=True),
        )
    if not _column_exists("delivery_error"):
        op.add_column(
            TABLE,
            sa.Column("delivery_error", sa.String(500), nullable=True),
        )
    if not _column_exists("read_at"):
        op.add_column(
            TABLE,
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Preserve meaningful history for rows sent before this migration.
    op.execute(
        sa.text(
            "UPDATE tracking_events SET delivery_status = 'delivered' "
            "WHERE delivery_status IS NULL AND delivered_at IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tracking_events SET delivery_status = 'submitted' "
            "WHERE delivery_status IS NULL AND sent_at IS NOT NULL "
            "AND channel IN ('sms', 'whatsapp')"
        )
    )

    if not _index_exists(INDEX):
        op.create_index(INDEX, TABLE, ["provider_message_id"])


def downgrade() -> None:
    """Remove the Vonage delivery receipt fields."""
    if _index_exists(INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    for column in ("read_at", "delivery_error", "delivery_status"):
        if _column_exists(column):
            op.drop_column(TABLE, column)
