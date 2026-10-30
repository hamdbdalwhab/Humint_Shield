"""QR identity resolution and the QR Live Scans ledger.

Revision ID: 0011_qr_identity_resolution
Revises: 0010_advanced_channels
Create Date: 2026-10-29 12:00:00

The new quishing landing portals ask for a username/employee number, a
corporate e-mail and a visual-only password.  This migration adds:

* ``human_assets.username`` and ``human_assets.employee_id_external`` so an
  entered identity can be matched by e-mail first and then by username/ID;
* non-secret identity fields and the once-only QR penalty marker on
  ``tracking_events``;
* the ``qr_scans`` ledger used by the admin "Live scans" table.  It supports
  unknown/campaign-level scans that have no pre-created recipient row, and can
  be assigned to an employee manually.

No password value or password length is added to ``qr_scans``.  Only the
boolean ``password_submitted`` is stored.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_qr_identity_resolution"
down_revision: str | None = "0010_advanced_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HUMAN_ASSETS = "human_assets"
TRACKING = "tracking_events"
QR_SCANS = "qr_scans"
JSON_TYPE = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


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


def _add_column(table: str, column: sa.Column) -> None:
    """Add a column only when it is not already present (idempotent migration)."""
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(table: str, name: str, columns: list[str]) -> None:
    """Create an index unless the same name already exists."""
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    """Add identity columns and create the QR scans ledger."""
    _add_column(HUMAN_ASSETS, sa.Column("username", sa.String(150), nullable=True))
    _add_column(
        HUMAN_ASSETS, sa.Column("employee_id_external", sa.String(100), nullable=True)
    )
    _create_index(HUMAN_ASSETS, "ix_human_assets_username", ["username"])
    _create_index(
        HUMAN_ASSETS, "ix_human_assets_employee_id_external", ["employee_id_external"]
    )

    _add_column(TRACKING, sa.Column("submitted_username", sa.String(150), nullable=True))
    _add_column(TRACKING, sa.Column("submitted_email", sa.String(255), nullable=True))
    _add_column(
        TRACKING,
        sa.Column(
            "password_submitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column(
        TRACKING, sa.Column("identity_resolution", sa.String(30), nullable=True)
    )
    _add_column(
        TRACKING,
        sa.Column("identity_resolved_employee_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    _add_column(
        TRACKING,
        sa.Column(
            "qr_penalty_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _create_index(
        TRACKING,
        "ix_tracking_events_identity_resolved_employee_id",
        ["identity_resolved_employee_id"],
    )

    # Preserve the historical evidence we already have: an older QR row with a
    # password length saw a password, even though the value was discarded.
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TRACKING):
        tracking = sa.table(
            TRACKING,
            sa.column("password_length", sa.Integer()),
            sa.column("password_submitted", sa.Boolean()),
        )
        bind.execute(
            tracking.update()
            .where(sa.or_(tracking.c.password_length.is_not(None), tracking.c.password_length > 0))
            .values(password_submitted=True)
        )

    if not sa.inspect(bind).has_table(QR_SCANS):
        op.create_table(
            QR_SCANS,
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "campaign_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tracking_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey("tracking_events.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "employee_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey("human_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("username", sa.String(150), nullable=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column(
                "password_submitted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "identity_resolution",
                sa.String(30),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("fingerprint_data", JSON_TYPE, nullable=True),
            sa.Column("elo_delta", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "penalty_applied",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("ip_address", postgresql.INET().with_variant(sa.String(45), "sqlite")),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        _create_index(QR_SCANS, "ix_qr_scans_organization_id", ["organization_id"])
        _create_index(QR_SCANS, "ix_qr_scans_campaign_id", ["campaign_id"])
        _create_index(QR_SCANS, "ix_qr_scans_tracking_id", ["tracking_id"])
        _create_index(QR_SCANS, "ix_qr_scans_employee_id", ["employee_id"])
        _create_index(QR_SCANS, "ix_qr_scans_campaign_time", ["campaign_id", "occurred_at"])
        _create_index(QR_SCANS, "ix_qr_scans_employee_time", ["employee_id", "occurred_at"])


def downgrade() -> None:
    """Drop the QR scans ledger and the identity columns."""
    if sa.inspect(op.get_bind()).has_table(QR_SCANS):
        op.drop_table(QR_SCANS)

    tracking_indexes = _indexes(TRACKING)
    if "ix_tracking_events_identity_resolved_employee_id" in tracking_indexes:
        op.drop_index("ix_tracking_events_identity_resolved_employee_id", table_name=TRACKING)
    tracking_columns = _columns(TRACKING)
    for column in (
        "qr_penalty_applied",
        "identity_resolved_employee_id",
        "identity_resolution",
        "password_submitted",
        "submitted_email",
        "submitted_username",
    ):
        if column in tracking_columns:
            with op.batch_alter_table(TRACKING) as batch:
                batch.drop_column(column)

    human_indexes = _indexes(HUMAN_ASSETS)
    for index in ("ix_human_assets_employee_id_external", "ix_human_assets_username"):
        if index in human_indexes:
            op.drop_index(index, table_name=HUMAN_ASSETS)
    human_columns = _columns(HUMAN_ASSETS)
    for column in ("employee_id_external", "username"):
        if column in human_columns:
            with op.batch_alter_table(HUMAN_ASSETS) as batch:
                batch.drop_column(column)
