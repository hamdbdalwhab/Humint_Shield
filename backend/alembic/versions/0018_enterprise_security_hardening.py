"""Enterprise security hardening: audit trail, encrypted PII, lockout, revocation.

Adds:

* ``audit_logs``                — immutable before/after trail of privileged changes.
* ``token_revocations``         — per-JWT revocation records (``jti``).
* ``users.failed_login_attempts`` / ``users.locked_until`` — account lockout.
* ``human_assets.email_encrypted`` / ``phone_encrypted`` (``BYTEA``) — AES-256-GCM
  copies of the PII columns, backfilled from the existing rows.

Revision ID: 0018_enterprise_security_hardening
Revises: 0017_user_token_version
Create Date: 2026-11-26

The backfill is idempotent (it re-seals every row with a fresh nonce) and is
safe to re-run.  The legacy plaintext ``email`` column is retained because the
unique index and case-insensitive search depend on it.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018_enterprise_security_hardening"
down_revision: str | None = "0017_user_token_version"
branch_labels = None
depends_on = None


def _backfill_encrypted_columns() -> None:
    """Encrypt every existing employee e-mail/phone into the new columns."""
    from app.security import decrypt_value
    from app.services.encryption_service import encrypt_text

    bind = op.get_bind()
    rows = (
        bind.execute(sa.text("SELECT id, email, phone FROM human_assets"))
        .mappings()
        .all()
    )
    for row in rows:
        email = row["email"]
        email_blob = encrypt_text(str(email)) if email else None

        phone_blob = None
        raw_phone = row["phone"]
        if raw_phone:
            try:
                # ``phone`` is stored by the legacy TEncryptedString type and
                # therefore holds an ``enc:v1:`` token; decrypt before re-sealing.
                plain_phone = decrypt_value(str(raw_phone))
                phone_blob = encrypt_text(plain_phone) if plain_phone else None
            except Exception:  # noqa: BLE001 - skip an unreadable legacy value
                phone_blob = None

        bind.execute(
            sa.text(
                "UPDATE human_assets "
                "SET email_encrypted = :email_blob, phone_encrypted = :phone_blob "
                "WHERE id = :row_id"
            ),
            {"email_blob": email_blob, "phone_blob": phone_blob, "row_id": row["id"]},
        )


def upgrade() -> None:
    """Create the compliance tables and the new security columns."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "failed_login_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index(
        "ix_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"]
    )
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_table", "target_id"])

    op.create_table(
        "token_revocations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_jti", sa.String(length=64), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_token_revocations_user_id", "token_revocations", ["user_id"])
    op.create_index(
        "ix_token_revocations_token_jti", "token_revocations", ["token_jti"]
    )

    with op.batch_alter_table("human_assets") as batch_op:
        batch_op.add_column(sa.Column("email_encrypted", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("phone_encrypted", sa.LargeBinary(), nullable=True))

    _backfill_encrypted_columns()


def downgrade() -> None:
    """Remove the hardening tables and columns."""
    with op.batch_alter_table("human_assets") as batch_op:
        batch_op.drop_column("phone_encrypted")
        batch_op.drop_column("email_encrypted")

    op.drop_index("ix_token_revocations_token_jti", table_name="token_revocations")
    op.drop_index("ix_token_revocations_user_id", table_name="token_revocations")
    op.drop_table("token_revocations")

    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_organization_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("locked_until")
        batch_op.drop_column("failed_login_attempts")
