"""interaction ledger: full submission capture and per-event audit trail

Revision ID: 0004_interaction_ledger
Revises: 0003_training_interactions
Create Date: 2026-01-01 00:00:03

Two changes turn the tracking row into a complete, second-by-second record:

1. ``email_tracking`` gains encrypted storage for the values a recipient typed
   (``submitted_password_encrypted``, ``submitted_payload_encrypted``) plus the
   non-secret ``client_context`` used as behavioural evidence.
2. ``training_interactions`` is an append-only ledger: one row per open, click,
   form render, submission, report and completion, each with microsecond
   timestamps, IP address, User-Agent and an optional encrypted payload.

Secrets are encrypted by the application with AES-256-GCM before they reach
the database, so the columns hold ``enc:v1:`` tokens, never plaintext.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_interaction_ledger"
down_revision: str | None = "0003_training_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type():
    """Return the JSON column type appropriate for the active dialect."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _uuid_type():
    """Return a UUID column type that works on PostgreSQL and SQLite."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.CHAR(32)


def _ip_type():
    """Return an INET column type with a portable fallback."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.INET()
    return sa.String(45)


def upgrade() -> None:
    """Add the encrypted capture columns and the interaction ledger."""
    op.add_column(
        "email_tracking",
        sa.Column("submitted_password_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "email_tracking",
        sa.Column("submitted_payload_encrypted", sa.Text(), nullable=True),
    )
    op.add_column("email_tracking", sa.Column("client_context", _json_type(), nullable=True))

    op.create_table(
        "training_interactions",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "tracking_id",
            _uuid_type(),
            sa.ForeignKey("email_tracking.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            _uuid_type(),
            sa.ForeignKey("email_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            _uuid_type(),
            sa.ForeignKey("human_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", _ip_type(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", _json_type(), nullable=True),
        sa.Column("payload_encrypted", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_training_interactions_tracking_id", "training_interactions", ["tracking_id"]
    )
    op.create_index(
        "ix_training_interactions_campaign_id", "training_interactions", ["campaign_id"]
    )
    op.create_index(
        "ix_training_interactions_employee_id", "training_interactions", ["employee_id"]
    )
    op.create_index(
        "ix_training_interactions_event_type", "training_interactions", ["event_type"]
    )
    op.create_index(
        "ix_training_interactions_occurred_at", "training_interactions", ["occurred_at"]
    )
    op.create_index(
        "ix_training_interactions_campaign_time",
        "training_interactions",
        ["campaign_id", "occurred_at"],
    )
    op.create_index(
        "ix_training_interactions_employee_time",
        "training_interactions",
        ["employee_id", "occurred_at"],
    )


def downgrade() -> None:
    """Remove the ledger and the encrypted capture columns."""
    op.drop_index("ix_training_interactions_employee_time", table_name="training_interactions")
    op.drop_index("ix_training_interactions_campaign_time", table_name="training_interactions")
    op.drop_index("ix_training_interactions_occurred_at", table_name="training_interactions")
    op.drop_index("ix_training_interactions_event_type", table_name="training_interactions")
    op.drop_index("ix_training_interactions_employee_id", table_name="training_interactions")
    op.drop_index("ix_training_interactions_campaign_id", table_name="training_interactions")
    op.drop_index("ix_training_interactions_tracking_id", table_name="training_interactions")
    op.drop_table("training_interactions")
    op.drop_column("email_tracking", "client_context")
    op.drop_column("email_tracking", "submitted_payload_encrypted")
    op.drop_column("email_tracking", "submitted_password_encrypted")
