"""departments table, human_assets.department_id and journey identifiers

Establishes the relational foundation behind the Employee Intelligence Hub:

* ``departments`` — a canonical, org-scoped department list.  Existing free-text
  ``human_assets.department`` values are backfilled into it and linked through
  the new ``human_assets.department_id`` column.
* ``campaigns.journey_id`` — one stable identifier per campaign journey.
* ``tracking_events.journey_id`` — denormalised copy, so the whole journey can
  be read without joining ``campaigns``.

The backfill is written in portable SQL/Python (no PostgreSQL-only constructs)
so the same migration runs on SQLite and PostgreSQL.

Revision ID: 0020_departments_journey
Revises: 0019_user_permissions
Create Date: 2026-11-27
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0020_departments_journey"
down_revision: str | None = "0019_user_permissions"
branch_labels = None
depends_on = None


def _create_departments_table() -> None:
    """Create the canonical department table."""
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=150), nullable=False, index=True),
        sa.Column("manager_name", sa.String(length=150), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_department_org_name"),
    )


def _backfill_departments() -> None:
    """Derive a department row for every distinct free-text value.

    Uses parameterised SQL through the migration connection so it behaves
    identically on SQLite and PostgreSQL.  A UUID is generated in Python, which
    keeps the value valid for both the native ``uuid`` and ``CHAR(32)`` shapes.
    """
    connection = op.get_bind()
    # The portable ``Uuid`` type stores a 32-character hex string on SQLite but
    # a native UUID on PostgreSQL.  Raw SQL bypasses SQLAlchemy's bind
    # processor, so the generated value must match the dialect's storage form.
    is_sqlite = connection.dialect.name == "sqlite"
    pairs = connection.execute(
        sa.text(
            "SELECT DISTINCT organization_id, department FROM human_assets "
            "WHERE department IS NOT NULL AND department != ''"
        )
    ).fetchall()
    for organization_id, name in pairs:
        existing_id = connection.execute(
            sa.text(
                "SELECT id FROM departments "
                "WHERE organization_id = :org_id AND name = :name LIMIT 1"
            ),
            {"org_id": organization_id, "name": name},
        ).scalar()
        if existing_id is None:
            generated = uuid.uuid4()
            existing_id = generated.hex if is_sqlite else generated
            connection.execute(
                sa.text(
                    "INSERT INTO departments (id, organization_id, name) "
                    "VALUES (:id, :org_id, :name)"
                ),
                {"id": existing_id, "org_id": organization_id, "name": name},
            )
        connection.execute(
            sa.text(
                "UPDATE human_assets SET department_id = :dept_id "
                "WHERE organization_id = :org_id AND department = :name"
            ),
            {"dept_id": existing_id, "org_id": organization_id, "name": name},
        )


def upgrade() -> None:
    """Add departments, department links and journey identifiers."""
    _create_departments_table()

    with op.batch_alter_table("human_assets") as batch:
        batch.add_column(sa.Column("department_id", sa.Uuid(as_uuid=True), nullable=True))
        batch.create_index("ix_human_assets_department_id", ["department_id"])
        batch.create_foreign_key(
            "fk_human_assets_department_id",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("campaigns", sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_index("ix_campaigns_journey_id", "campaigns", ["journey_id"])
    op.add_column(
        "tracking_events", sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.create_index("ix_tracking_events_journey_id", "tracking_events", ["journey_id"])

    _backfill_departments()

    # Every existing campaign becomes the journey it always implicitly was; the
    # column is then made NOT NULL, matching the model definition.
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE campaigns SET journey_id = id WHERE journey_id IS NULL")
    )
    connection.execute(
        sa.text(
            "UPDATE tracking_events SET journey_id = ("
            "SELECT campaigns.journey_id FROM campaigns "
            "WHERE campaigns.id = tracking_events.campaign_id) "
            "WHERE journey_id IS NULL"
        )
    )
    with op.batch_alter_table("campaigns") as batch:
        batch.alter_column("journey_id", existing_type=sa.Uuid(as_uuid=True), nullable=False)


def downgrade() -> None:
    """Remove the journey identifiers and the department relation."""
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_index("ix_campaigns_journey_id")
        batch.drop_column("journey_id")
    with op.batch_alter_table("tracking_events") as batch:
        batch.drop_index("ix_tracking_events_journey_id")
        batch.drop_column("journey_id")
    with op.batch_alter_table("human_assets") as batch:
        batch.drop_constraint("fk_human_assets_department_id", type_="foreignkey")
        batch.drop_index("ix_human_assets_department_id")
        batch.drop_column("department_id")
    op.drop_table("departments")
