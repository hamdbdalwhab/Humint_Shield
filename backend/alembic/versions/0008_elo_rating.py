"""Add the Elo adaptive-difficulty rating to human assets.

Revision ID: 0008_elo_rating
Revises: 0007_delivery_failed_at
Create Date: 2026-10-24 21:00:00

Every employee starts at 1000.  Existing rows are backfilled with the same
starting value; the tracking service applies -32 on the first click and +32 on
the first report from that point onward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_elo_rating"
down_revision: str | None = "0007_delivery_failed_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "human_assets"
COLUMN = "elo_score"


def _column_exists() -> bool:
    """Return ``True`` when the employee table already has ``elo_score``."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return False
    return COLUMN in {item["name"] for item in inspector.get_columns(TABLE)}


def upgrade() -> None:
    """Add the non-null Elo column and backfill existing employees with 1000."""
    if _column_exists():
        return
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1000"),
        ),
    )


def downgrade() -> None:
    """Remove the Elo column."""
    if not _column_exists():
        return
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_column(COLUMN)
