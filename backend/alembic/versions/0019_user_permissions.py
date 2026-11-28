"""users.permissions / users.last_login_at

Adds the storage for delegated, least-privilege permissions:

* ``users.permissions`` (JSON) — explicit grants layered on top of the role
  preset.  ``NULL``/``[]`` keeps the role's default set.
* ``users.last_login_at`` (timestamp) — shown in operator administration.

Revision ID: 0019_user_permissions
Revises: 0018_enterprise_security_hardening
Create Date: 2026-11-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019_user_permissions"
down_revision: str | None = "0018_enterprise_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the JSON grants column and the last-sign-in timestamp."""
    op.add_column("users", sa.Column("permissions", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    # Existing accounts keep their role preset; an empty list makes the intent
    # explicit ("no extra grants") instead of relying on NULL semantics.
    op.execute(sa.text("UPDATE users SET permissions = '[]' WHERE permissions IS NULL"))


def downgrade() -> None:
    """Drop both columns."""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("permissions")
