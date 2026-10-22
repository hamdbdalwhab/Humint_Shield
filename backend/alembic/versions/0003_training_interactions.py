"""training interaction: simulated credential-form capture

Revision ID: 0003_training_interactions
Revises: 0002_email_campaigns
Create Date: 2026-01-01 00:00:02

Adds the engagement columns that record what a recipient did on the
server-rendered training page:

* ``form_viewed_at``       - the simulated credential form was rendered
* ``form_submitted_at``    - the form was submitted (first time)
* ``submission_count``     - how many times it was submitted
* ``submitted_identifier`` - the identifier the recipient typed
* ``submitted_fields``     - non-secret fields exactly as entered
* ``password_length``      - length of the typed password (never the value)

The password itself is deliberately never transmitted to the server: the page
sends only its length.  This migration therefore has no column able to hold a
plaintext secret.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_training_interactions"
down_revision: str | None = "0002_email_campaigns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type():
    """Return the JSON column type appropriate for the active dialect."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    """Add the training-interaction columns to ``email_tracking``."""
    op.add_column(
        "email_tracking", sa.Column("form_viewed_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "email_tracking", sa.Column("form_submitted_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "email_tracking",
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "email_tracking", sa.Column("submitted_identifier", sa.String(255))
    )
    op.add_column("email_tracking", sa.Column("submitted_fields", _json_type()))
    op.add_column("email_tracking", sa.Column("password_length", sa.Integer()))
    op.add_column(
        "email_tracking", sa.Column("reported_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    """Remove the training-interaction columns."""
    op.drop_column("email_tracking", "reported_at")
    op.drop_column("email_tracking", "password_length")
    op.drop_column("email_tracking", "submitted_fields")
    op.drop_column("email_tracking", "submitted_identifier")
    op.drop_column("email_tracking", "submission_count")
    op.drop_column("email_tracking", "form_submitted_at")
    op.drop_column("email_tracking", "form_viewed_at")
