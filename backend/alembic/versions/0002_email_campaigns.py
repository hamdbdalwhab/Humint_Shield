"""email campaign subsystem: templates, campaigns, tracking

Revision ID: 0002_email_campaigns
Revises: 0001_initial_lms
Create Date: 2026-01-01 00:00:01

Creates the three campaign tables required by HUMINT Shield:

* ``email_templates``  - reusable, personalised simulation emails
* ``email_campaigns``  - an authorized simulation run and its counters
* ``email_tracking``   - per-recipient delivery + engagement record

Every statement is written so the migration also runs against SQLite (used by
the development/test environment); on PostgreSQL the native ``JSONB``,
``INET`` and ``UUID`` types are used.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_email_campaigns"
down_revision: str | None = "0001_initial_lms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    """Return ``True`` when migrating a PostgreSQL database."""
    return op.get_bind().dialect.name == "postgresql"


def _json_type():
    """Return the JSON column type appropriate for the active dialect."""
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _inet_type():
    """Return an ``INET`` column type (``VARCHAR(45)`` off PostgreSQL)."""
    if _is_postgres():
        return postgresql.INET()
    return sa.String(45)


def _uuid_default() -> sa.TextClause | None:
    """Return a server-side UUID default on PostgreSQL (built into PG 13+)."""
    if _is_postgres():
        return sa.text("gen_random_uuid()")
    return None


def upgrade() -> None:
    """Create the campaign tables."""
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("difficulty_level", sa.Integer(), server_default="5"),
        sa.Column(
            "available_variables",
            _json_type(),
            server_default=sa.text(
                "'[\"first_name\",\"last_name\",\"email\",\"department\","
                "\"company_name\",\"manager_name\"]'"
            ),
        ),
        sa.Column("is_built_in", sa.Boolean(), server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "difficulty_level >= 1 AND difficulty_level <= 10",
            name="ck_email_templates_difficulty",
        ),
    )
    op.create_index("idx_templates_org", "email_templates", ["organization_id"])

    op.create_table(
        "email_campaigns",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("email_templates.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("target_employee_ids", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_targets", sa.Integer(), server_default="0"),
        sa.Column("sent_count", sa.Integer(), server_default="0"),
        sa.Column("failed_count", sa.Integer(), server_default="0"),
        sa.Column("opened_count", sa.Integer(), server_default="0"),
        sa.Column("clicked_count", sa.Integer(), server_default="0"),
        sa.Column("completed_count", sa.Integer(), server_default="0"),
        sa.Column("launched_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft','active','completed','aborted')",
            name="ck_campaign_status",
        ),
    )
    op.create_index("idx_campaigns_status", "email_campaigns", ["status"])
    op.create_index("idx_campaigns_org", "email_campaigns", ["organization_id"])

    op.create_table(
        "email_tracking",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "campaign_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("email_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("human_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tracking_uuid", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "email_template_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("email_templates.id", ondelete="SET NULL"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("clicked_at", sa.DateTime(timezone=True)),
        sa.Column("completed_training_at", sa.DateTime(timezone=True)),
        sa.Column("brevo_message_id", sa.String(255)),
        sa.Column("open_count", sa.Integer(), server_default="0"),
        sa.Column("click_count", sa.Integer(), server_default="0"),
        sa.Column("last_ip_address", _inet_type()),
        sa.Column("last_user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tracking_uuid", name="uq_tracking_uuid"),
        sa.UniqueConstraint(
            "campaign_id", "employee_id", name="uq_tracking_campaign_employee"
        ),
    )
    op.create_index("idx_tracking_uuid", "email_tracking", ["tracking_uuid"], unique=True)
    op.create_index("idx_tracking_campaign", "email_tracking", ["campaign_id"])
    op.create_index("idx_tracking_employee", "email_tracking", ["employee_id"])


def downgrade() -> None:
    """Drop the campaign tables."""
    op.drop_index("idx_tracking_employee", table_name="email_tracking")
    op.drop_index("idx_tracking_campaign", table_name="email_tracking")
    op.drop_index("idx_tracking_uuid", table_name="email_tracking")
    op.drop_table("email_tracking")

    op.drop_index("idx_campaigns_org", table_name="email_campaigns")
    op.drop_index("idx_campaigns_status", table_name="email_campaigns")
    op.drop_table("email_campaigns")

    op.drop_index("idx_templates_org", table_name="email_templates")
    op.drop_table("email_templates")
