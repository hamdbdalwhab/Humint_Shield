"""Allow campaign-level interaction events without an employee.

A physical USB-drop campaign can be a *generic* drop: the tracking row has no
``employee_id`` because whoever picks up the drive is the target.  The
interaction ledger declared ``employee_id`` NOT NULL, so every such open raised
``IntegrityError`` and the whole tracking transaction was rolled back — the
document was opened, the redirect still worked, but nothing reached the
monitoring board.  This migration makes the column nullable so an open is
always persisted and attributed to the endpoint instead of an employee.

Revision ID: 0016_usb_ledger_nullable_employee
Revises: 0015_department_and_short_links
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_usb_ledger_nullable_employee"
down_revision: str | None = "0015_department_and_short_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Make ``training_interactions.employee_id`` nullable."""
    with op.batch_alter_table("training_interactions") as batch_op:
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.CHAR(length=32),
            nullable=True,
        )


def downgrade() -> None:
    """Restore the NOT NULL constraint.

    Rows recorded for an unattributed endpoint have no employee; they cannot
    satisfy the restored constraint, so they are removed first.
    """
    op.execute(sa.text("DELETE FROM training_interactions WHERE employee_id IS NULL"))
    with op.batch_alter_table("training_interactions") as batch_op:
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.CHAR(length=32),
            nullable=False,
        )
