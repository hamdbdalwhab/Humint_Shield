"""initial LMS schema: organizations, users, human_assets, training library

Revision ID: 0001_initial_lms
Revises:
Create Date: 2026-01-01 00:00:00

Creates the pre-existing LMS tables.  These were part of the platform before
the campaign subsystem was added and are only referenced (never recreated) by
the campaign migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_lms"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type():
    """Return the JSON column type appropriate for the active dialect."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    """Create the original LMS tables."""
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100)),
        sa.Column("domain", sa.String(255), nullable=False, unique=True),
        sa.Column("allowed_test_hours", _json_type()),
        sa.Column("allow_personal_devices", sa.Boolean(), server_default=sa.false()),
        sa.Column("adaptive_mode", sa.Boolean(), server_default=sa.true()),
        sa.Column("max_tests_per_day", sa.Integer(), server_default="10"),
        sa.Column("data_retention_days", sa.Integer(), server_default="365"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="admin"),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "human_assets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        # Encrypted at rest with AES-256-GCM; stored as ciphertext TEXT.
        sa.Column("phone", sa.Text()),
        sa.Column("first_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("department", sa.String(100)),
        sa.Column("job_title", sa.String(100)),
        sa.Column("access_level", sa.Integer(), server_default="1"),
        sa.Column("immunity_score", sa.Numeric(6, 2), server_default="50.00"),
        sa.Column("behavioral_category", sa.String(20), server_default="hesitant"),
        sa.Column("total_tests_received", sa.Integer(), server_default="0"),
        sa.Column("total_clicks", sa.Integer(), server_default="0"),
        sa.Column("total_reports", sa.Integer(), server_default="0"),
        sa.Column("total_credential_submissions", sa.Integer(), server_default="0"),
        sa.Column("total_ignores", sa.Integer(), server_default="0"),
        sa.Column("last_test_date", sa.DateTime(timezone=True)),
        sa.Column("next_test_date", sa.Date()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        sa.Column("is_on_leave", sa.Boolean(), server_default=sa.false()),
        sa.Column("requires_mandatory_training", sa.Boolean(), server_default=sa.false()),
        sa.Column("under_enhanced_monitoring", sa.Boolean(), server_default=sa.false()),
        sa.Column("device_profile", _json_type()),
        sa.Column("risk_profile", _json_type()),
        sa.Column("behavioral_baseline", _json_type()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_human_assets_organization_id", "human_assets", ["organization_id"])
    op.create_index("ix_human_assets_email", "human_assets", ["email"])
    op.create_index("ix_human_assets_department", "human_assets", ["department"])

    op.create_table(
        "training_modules",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("content_html", sa.Text(), server_default=""),
        sa.Column("category", sa.String(100)),
        sa.Column("duration_minutes", sa.Integer(), server_default="10"),
        sa.Column("difficulty_level", sa.Integer(), server_default="3"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_training_modules_organization_id", "training_modules", ["organization_id"])

    op.create_table(
        "training_assignments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("training_modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("human_assets.id", ondelete="CASCADE"),
        ),
        sa.Column("status", sa.String(20), server_default="assigned"),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_training_assignments_organization_id", "training_assignments", ["organization_id"]
    )
    op.create_index("ix_training_assignments_employee_id", "training_assignments", ["employee_id"])

    op.create_table(
        "phishing_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("human_assets.id", ondelete="SET NULL"),
        ),
        sa.Column("reported_email_subject", sa.String(500)),
        sa.Column("reported_sender", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), server_default="new"),
        sa.Column("is_training_simulation", sa.Boolean(), server_default=sa.false()),
        sa.Column("triage_notes", sa.Text()),
        sa.Column("details", _json_type()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_phishing_reports_organization_id", "phishing_reports", ["organization_id"])
    op.create_index("ix_phishing_reports_employee_id", "phishing_reports", ["employee_id"])


def downgrade() -> None:
    """Drop the original LMS tables."""
    op.drop_table("phishing_reports")
    op.drop_table("training_assignments")
    op.drop_table("training_modules")
    op.drop_table("human_assets")
    op.drop_table("users")
    op.drop_table("organizations")
