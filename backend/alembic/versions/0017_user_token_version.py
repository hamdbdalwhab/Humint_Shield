"""Add ``users.token_version`` for server-side session revocation.

Revision ID: 0017_user_token_version
Revises: 0016_usb_ledger_nullable_employee
Create Date: 2026-11-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017_user_token_version"
down_revision: str | None = "0016_usb_ledger_nullable_employee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the session-generation counter (existing accounts start at 0)."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Drop the session-generation counter."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("token_version")
