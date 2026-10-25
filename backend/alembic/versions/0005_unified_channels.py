"""unified channel schema: templates, campaigns and tracking_events

Revision ID: 0005_unified_channels
Revises: 0004_interaction_ledger
Create Date: 2026-10-23 00:00:00

This migration promotes the email-only physical schema to the channel-neutral
tables used by the production Email Channel and the upcoming Vonage SMS /
WhatsApp channels:

* ``email_templates``  -> ``templates``
* ``email_campaigns``  -> ``campaigns``
* ``email_tracking``   -> ``tracking_events``

It also renames email-specific columns to channel-neutral ones, keeps every
existing row (no copy/drop), and adds:

* ``channel`` on all three tables (default ``email``),
* ``quiz_score`` / ``quiz_total`` on tracking events,
* ``is_reported_safe`` for the out-of-band "report safe" admin action,
* generic ``provider`` / ``provider_message_id`` delivery fields.

The upgrade is deliberately written with plain ``ALTER TABLE ... RENAME``
statements so it behaves identically on PostgreSQL and SQLite.  On SQLite this
also rewrites foreign keys that point at the renamed tables.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_unified_channels"
down_revision: str | None = "0004_interaction_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_RENAMES = (
    ("email_templates", "templates"),
    ("email_campaigns", "campaigns"),
    ("email_tracking", "tracking_events"),
)

COLUMN_RENAMES = (
    ("tracking_events", "email_template_id", "template_id"),
    ("tracking_events", "brevo_message_id", "provider_message_id"),
    ("tracking_events", "form_viewed_at", "viewed_at"),
    ("tracking_events", "form_submitted_at", "submitted_at"),
    ("tracking_events", "completed_training_at", "completed_at"),
)


def _table_exists(table: str) -> bool:
    """Return ``True`` when ``table`` exists in the current database."""
    return sa.inspect(op.get_bind()).has_table(table)


def _column_exists(table: str, column: str) -> bool:
    """Return ``True`` when ``table.column`` exists."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def _rename_table(old: str, new: str) -> None:
    """Rename a table when the old name is present and the new one is not."""
    if _table_exists(old) and not _table_exists(new):
        op.rename_table(old, new)


def _rename_column(table: str, old: str, new: str) -> None:
    """Rename a column in place (PostgreSQL and SQLite 3.25+)."""
    if _column_exists(table, old) and not _column_exists(table, new):
        op.execute(
            sa.text(
                f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'
            )
        )


def upgrade() -> None:
    """Promote the email-only schema to the unified channel schema."""
    for old, new in TABLE_RENAMES:
        _rename_table(old, new)

    for table, old, new in COLUMN_RENAMES:
        _rename_column(table, old, new)

    if not _column_exists("templates", "channel"):
        op.add_column(
            "templates",
            sa.Column(
                "channel",
                sa.String(20),
                nullable=False,
                server_default="email",
            ),
        )
        op.create_index("ix_templates_channel", "templates", ["channel"])

    if not _column_exists("campaigns", "channel"):
        op.add_column(
            "campaigns",
            sa.Column(
                "channel",
                sa.String(20),
                nullable=False,
                server_default="email",
            ),
        )
        op.create_index("ix_campaigns_channel", "campaigns", ["channel"])

    if not _column_exists("tracking_events", "channel"):
        op.add_column(
            "tracking_events",
            sa.Column(
                "channel",
                sa.String(20),
                nullable=False,
                server_default="email",
            ),
        )
        op.create_index(
            "ix_tracking_events_channel", "tracking_events", ["channel"]
        )

    if not _column_exists("tracking_events", "provider"):
        op.add_column(
            "tracking_events",
            sa.Column("provider", sa.String(30), nullable=True, server_default="brevo"),
        )

    if not _column_exists("tracking_events", "quiz_score"):
        op.add_column(
            "tracking_events", sa.Column("quiz_score", sa.Integer(), nullable=True)
        )

    if not _column_exists("tracking_events", "quiz_total"):
        op.add_column(
            "tracking_events",
            sa.Column(
                "quiz_total", sa.Integer(), nullable=True, server_default="5"
            ),
        )

    if not _column_exists("tracking_events", "is_reported_safe"):
        op.add_column(
            "tracking_events",
            sa.Column(
                "is_reported_safe",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Keep all existing data meaningful in the new model.
    op.execute(
        sa.text(
            "UPDATE tracking_events "
            "SET is_reported_safe = true, quiz_score = COALESCE(quiz_score, 5) "
            "WHERE reported_at IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tracking_events SET quiz_total = 5 "
            "WHERE completed_at IS NOT NULL AND quiz_total IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tracking_events SET provider = 'brevo' "
            "WHERE provider IS NULL AND provider_message_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    """Restore the original email-only table and column names."""
    for index_name, table in (
        ("ix_tracking_events_channel", "tracking_events"),
        ("ix_campaigns_channel", "campaigns"),
        ("ix_templates_channel", "templates"),
    ):
        if _table_exists(table):
            indexes = {
                item["name"]
                for item in sa.inspect(op.get_bind()).get_indexes(table)
            }
            if index_name in indexes:
                op.drop_index(index_name, table_name=table)

    for column in (
        "is_reported_safe",
        "quiz_total",
        "quiz_score",
        "provider",
        "channel",
    ):
        if _column_exists("tracking_events", column):
            op.drop_column("tracking_events", column)

    for table, column in (
        ("campaigns", "channel"),
        ("templates", "channel"),
    ):
        if _column_exists(table, column):
            op.drop_column(table, column)

    for table, old, new in reversed(COLUMN_RENAMES):
        _rename_column(table, new, old)

    for old, new in reversed(TABLE_RENAMES):
        _rename_table(new, old)
