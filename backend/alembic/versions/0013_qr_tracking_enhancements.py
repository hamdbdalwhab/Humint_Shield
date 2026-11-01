"""QR tracking enhancements: nullable tracking employee_id and scan event_type.

Revision ID: 0013_qr_tracking_enhancements
Revises: 0012_advanced_email_features
Create Date: 2026-11-01 12:00:00

Adds:
* ``tracking_events.employee_id``: allows NULL for unauthenticated QR scans before identity resolution.
* ``qr_scans.event_type``: distinguishes initial scan (qr_scanned) from form submission (qr_credential_submitted).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_qr_tracking_enhancements"
down_revision: str | None = "0012_advanced_email_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRACKING = "tracking_events"
QR_SCANS = "qr_scans"
UUID_TYPE = postgresql.UUID(as_uuid=True).with_variant(sa.CHAR(36), "sqlite")


def _columns(table: str) -> set[str]:
    """Return the current column names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    """Return the current index names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    """Make tracking_events.employee_id nullable and add qr_scans.event_type."""
    if sa.inspect(op.get_bind()).has_table(TRACKING):
        with op.batch_alter_table(TRACKING) as batch:
            batch.alter_column(
                "employee_id",
                existing_type=UUID_TYPE,
                nullable=True,
            )

    if sa.inspect(op.get_bind()).has_table(QR_SCANS):
        if "event_type" not in _columns(QR_SCANS):
            op.add_column(
                QR_SCANS,
                sa.Column(
                    "event_type",
                    sa.String(40),
                    nullable=False,
                    server_default="qr_scanned",
                ),
            )


def downgrade() -> None:
    """Revert qr_scans.event_type and employee_id nullability."""
    if sa.inspect(op.get_bind()).has_table(QR_SCANS):
        if "event_type" in _columns(QR_SCANS):
            with op.batch_alter_table(QR_SCANS) as batch:
                batch.drop_column("event_type")

    if sa.inspect(op.get_bind()).has_table(TRACKING):
        with op.batch_alter_table(TRACKING) as batch:
            batch.alter_column(
                "employee_id",
                existing_type=UUID_TYPE,
                nullable=False,
            )
