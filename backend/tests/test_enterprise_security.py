"""Regression tests for the enterprise security hardening modules.

Covered here: audit trail, field encryption, account lockout, password policy,
input sanitisation, per-token revocation and environment separation.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import env_files
from app.models import AuditLog, HumanAsset, TokenRevocation
from app.schemas import ChangePasswordRequest, EmployeeCreate
from app.security import TokenError, create_access_token, decode_token
from app.services.encryption_service import decrypt_text, encrypt_text


# --------------------------------------------------------------------------- #
# Module 10 - environment separation
# --------------------------------------------------------------------------- #
def test_env_files_follow_app_env(monkeypatch) -> None:
    """``APP_ENV`` selects an overlay loaded after the base ``.env``."""
    monkeypatch.setenv("APP_ENV", "production")
    assert env_files() == (".env", ".env.production")

    monkeypatch.setenv("APP_ENV", "development")
    assert env_files() == (".env", ".env.development")

    monkeypatch.delenv("APP_ENV")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert env_files() == (".env",)


# --------------------------------------------------------------------------- #
# Module 3 - encryption at rest
# --------------------------------------------------------------------------- #
def test_encryption_service_roundtrip_and_tamper_detection() -> None:
    """AES-256-GCM seals values and rejects a modified ciphertext."""
    sealed = encrypt_text("jane.doe@example.com")
    assert isinstance(sealed, bytes)
    assert b"jane.doe" not in sealed
    assert decrypt_text(sealed) == "jane.doe@example.com"
    assert encrypt_text(None) is None
    assert decrypt_text(None) is None

    tampered = bytearray(sealed or b"")
    tampered[-1] ^= 0x01
    with pytest.raises(Exception):
        decrypt_text(bytes(tampered))


@pytest.mark.asyncio
async def test_employee_pii_is_encrypted_and_only_admin_can_decrypt(
    client, db, organization, admin_user, auth_headers, viewer_headers, session_factory
) -> None:
    """The BYTEA columns are populated; decryption is an admin-only route."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        headers=auth_headers,
        json={
            "email": "encrypted.user@acmetest.example",
            "first_name": "Encrypted",
            "last_name": "User",
            "phone": "+15550199000",
        },
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    async with session_factory() as probe:
        row = await probe.get(HumanAsset, uuid.UUID(employee_id))
        assert row is not None
        assert row.email_encrypted
        assert row.phone_encrypted
        assert b"encrypted.user" not in row.email_encrypted
        assert decrypt_text(row.email_encrypted) == "encrypted.user@acmetest.example"
        assert decrypt_text(row.phone_encrypted) == "+15550199000"

    forbidden = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee_id}/sensitive",
        headers=viewer_headers,
    )
    assert forbidden.status_code == 403

    allowed = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee_id}/sensitive",
        headers=auth_headers,
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["email"] == "encrypted.user@acmetest.example"
    assert body["phone"] == "+15550199000"
    assert body["encrypted_at_rest"] is True


# --------------------------------------------------------------------------- #
# Module 2 - audit logging
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_employee_create_and_delete_are_audited(
    client, db, organization, admin_user, auth_headers, session_factory
) -> None:
    """Both the create and the delete leave a before/after audit record."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        headers=auth_headers,
        json={"email": "audited@acmetest.example", "first_name": "Audited"},
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    async with session_factory() as probe:
        create_row = await probe.scalar(
            select(AuditLog).where(
                AuditLog.target_table == "human_assets",
                AuditLog.target_id == employee_id,
                AuditLog.action == "CREATE",
            )
        )
        assert create_row is not None
        assert create_row.organization_id == organization.id
        assert create_row.user_id == admin_user.id
        assert create_row.new_value["email"] == "audited@acmetest.example"
        assert create_row.ip_address

    deleted = await client.delete(
        f"/api/v1/organizations/{organization.id}/employees/{employee_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    async with session_factory() as probe:
        delete_row = await probe.scalar(
            select(AuditLog).where(
                AuditLog.target_table == "human_assets",
                AuditLog.target_id == employee_id,
                AuditLog.action == "DELETE",
            )
        )
        assert delete_row is not None
        assert delete_row.old_value["email"] == "audited@acmetest.example"
        assert delete_row.new_value is None


@pytest.mark.asyncio
async def test_invite_user_records_audit_and_is_admin_only(
    client, db, organization, admin_user, auth_headers, viewer_headers, session_factory
) -> None:
    """A viewer cannot create operators; an admin can, and it is audited."""
    payload = {
        "username": "invited_operator",
        "email": "invited@acmetest.example",
        "password": "InvitedPass123!",
        "role": "viewer",
    }
    denied = await client.post("/api/v1/users/invite", headers=viewer_headers, json=payload)
    assert denied.status_code == 403

    created = await client.post("/api/v1/users/invite", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["role"] == "viewer"
    assert body["organization_id"] == str(organization.id)
    assert "password" not in body

    async with session_factory() as probe:
        row = await probe.scalar(
            select(AuditLog).where(
                AuditLog.target_table == "users",
                AuditLog.target_id == body["id"],
                AuditLog.action == "CREATE",
            )
        )
        assert row is not None
        assert row.new_value["username"] == "invited_operator"
        assert "password" not in row.new_value


# --------------------------------------------------------------------------- #
# Module 4 - lockout and password policy
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_account_locks_after_five_failed_attempts(client, admin_user) -> None:
    """Five bad passwords lock the account for 15 minutes (HTTP 423)."""
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "tester", "password": "wrong-password"},
        )
        assert response.status_code == 401

    locked = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    assert locked.status_code == 423
    assert "locked" in locked.json()["detail"].lower()
    assert "Retry-After" in locked.headers


def test_password_policy_requires_every_character_class() -> None:
    """The Pydantic schema rejects weak or incomplete passwords."""
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Secret123!", new_password="Short1!")

    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Secret123!", new_password="NoSpecial123")

    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Secret123!", new_password="nouppercase1!")

    valid = ChangePasswordRequest(
        current_password="Secret123!", new_password="StrongerPass123!"
    )
    assert valid.new_password == "StrongerPass123!"


# --------------------------------------------------------------------------- #
# Module 7 - input sanitisation
# --------------------------------------------------------------------------- #
def test_employee_schema_rejects_active_content_and_strips_tags() -> None:
    """Script payloads are rejected; harmless markup is stripped."""
    with pytest.raises(ValidationError):
        EmployeeCreate(
            email="x@acmetest.example",
            first_name="<script>alert(1)</script>",
        )

    with pytest.raises(ValidationError):
        EmployeeCreate(
            email="x@acmetest.example",
            first_name="Ali",
            job_title="<img src=x onerror=alert(1)>",
        )

    cleaned = EmployeeCreate(
        email="x@acmetest.example",
        first_name="<b>Ali</b>",
        job_title="<i>Analyst</i>",
    )
    assert cleaned.first_name == "Ali"
    assert cleaned.job_title == "Analyst"


# --------------------------------------------------------------------------- #
# Module 8 - token revocation log
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_logout_writes_revocation_record(
    client, db, admin_user, auth_headers, session_factory
) -> None:
    """Logout persists the presented token's ``jti`` with a reason."""
    claims = decode_token(auth_headers["Authorization"].split(" ", 1)[1])
    assert claims.get("jti")

    logout = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert logout.status_code == 200

    async with session_factory() as probe:
        row = await probe.scalar(
            select(TokenRevocation).where(
                TokenRevocation.token_jti == claims["jti"]
            )
        )
        assert row is not None
        assert row.reason == "LOGOUT"
        assert row.user_id == admin_user.id


@pytest.mark.asyncio
async def test_revoked_jti_is_rejected_even_with_valid_signature(
    client, db, admin_user
) -> None:
    """The revocation table invalidates a token whose signature is still valid."""
    token = create_access_token(str(admin_user.id), {"role": "admin"})
    try:
        claims = decode_token(token)
    except TokenError:  # pragma: no cover - defensive
        pytest.fail("freshly created token must decode")

    db.add(
        TokenRevocation(
            user_id=admin_user.id, token_jti=str(claims["jti"]), reason="ADMIN_ACTION"
        )
    )
    await db.commit()

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
