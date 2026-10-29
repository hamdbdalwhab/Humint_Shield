"""Advanced simulation channels: QR, vishing and pretexting.

Revision ID: 0010_advanced_channels
Revises: 0009_visual_templates_branding
Create Date: 2026-10-27 12:00:00

The advanced channels deliberately reuse the existing ``campaigns`` and
``tracking_events`` tables.  Only one JSON column is required: it stores the
channel-specific scenario (QR pretext, credential-page provider, or the copy
used by the vishing/pretexting experiences).

Existing rows receive an empty object so the column is safe to query before an
operator configures a scenario.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_advanced_channels"
down_revision: str | None = "0009_visual_templates_branding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "campaigns"
COLUMN = "channel_config"
JSON_TYPE = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def _column_exists() -> bool:
    """Return ``True`` when the campaign table already has ``channel_config``."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return False
    return COLUMN in {item["name"] for item in inspector.get_columns(TABLE)}


def upgrade() -> None:
    """Add the channel scenario JSON column and backfill existing campaigns."""
    if _column_exists():
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, JSON_TYPE, nullable=True, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    """Remove the channel scenario column."""
    if not _column_exists():
        return
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_column(COLUMN)
