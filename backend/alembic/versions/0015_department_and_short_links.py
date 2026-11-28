"""Department-aware templates and SMS short links.

Revision ID: 0015_department_and_short_links
Revises: 0014_monthly_archives_guardrails
Create Date: 2026-11-12 18:00:00

Adds:
* ``templates.target_department`` (IT, Finance, HR, Executive, All).
* ``short_links`` table (code, tracking_uuid, target_path, clicks).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_department_and_short_links"
down_revision: str | None = "0014_monthly_archives_guardrails"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Match ``app.database.UUIDType``: native UUID on PostgreSQL, CHAR(32) on SQLite.
UUID_TYPE = sa.Uuid(as_uuid=True)
SHORT_LINKS = "short_links"


def _columns(table: str) -> set[str]:
    """Return the current column names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    """Apply the department and short-link schema additions."""
    if sa.inspect(op.get_bind()).has_table("templates"):
        if "target_department" not in _columns("templates"):
            op.add_column(
                "templates",
                sa.Column("target_department", sa.String(50), nullable=True),
            )

    if not sa.inspect(op.get_bind()).has_table(SHORT_LINKS):
        op.create_table(
            SHORT_LINKS,
            sa.Column("id", UUID_TYPE, primary_key=True, nullable=False),
            sa.Column("code", sa.String(16), nullable=False),
            sa.Column("tracking_uuid", UUID_TYPE, nullable=False),
            sa.Column("target_path", sa.String(500), nullable=False),
            sa.Column("display_url", sa.String(500), nullable=True),
            sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("last_clicked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("code", name="uq_short_links_code"),
        )
        op.create_index("ix_short_links_code", SHORT_LINKS, ["code"])
        op.create_index("ix_short_links_tracking_uuid", SHORT_LINKS, ["tracking_uuid"])


def downgrade() -> None:
    """Revert the department and short-link schema additions."""
    if sa.inspect(op.get_bind()).has_table(SHORT_LINKS):
        op.drop_index("ix_short_links_tracking_uuid", table_name=SHORT_LINKS)
        op.drop_index("ix_short_links_code", table_name=SHORT_LINKS)
        op.drop_table(SHORT_LINKS)
    if sa.inspect(op.get_bind()).has_table("templates"):
        if "target_department" in _columns("templates"):
            op.drop_column("templates", "target_department")
