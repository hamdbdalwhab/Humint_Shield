"""Regression tests for tenant isolation, session revocation and proxy trust.

Each test pins a defect that was found during the system audit:

* QR radar scans were readable anonymously,
* containment logs were readable across organizations,
* JWTs could not be revoked (logout and password change were no-ops),
* production accepted generated signing keys and the shipped admin password,
* the client IP (and therefore the rate-limit bucket) trusted a spoofable
  ``X-Forwarded-For`` prefix.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.deps import _client_ip
from app.models import EmailCampaign, Organization, User
from app.security import hash_password


async def _make_campaign(db, org_id, name: str = "Audit Campaign") -> EmailCampaign:
    """Create a minimal campaign row for the given organization."""
    campaign = EmailCampaign(organization_id=org_id, name=name, channel="qr")
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@pytest.mark.asyncio
async def test_campaign_scans_requires_authentication(client, db, organization) -> None:
    """The QR radar leaks assignee names and fingerprints, so it needs a token."""
    campaign = await _make_campaign(db, organization.id)
    response = await client.get(f"/api/v1/campaigns/{campaign.id}/scans")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_campaign_scans_scoped_to_organization(
    client, db, organization, admin_user, auth_headers
) -> None:
    """A campaign from another tenant is indistinguishable from a missing one."""
    other_org = Organization(name="Other Corp", domain="other.example")
    db.add(other_org)
    await db.commit()
    await db.refresh(other_org)
    foreign = await _make_campaign(db, other_org.id, "Foreign Campaign")

    response = await client.get(
        f"/api/v1/campaigns/{foreign.id}/scans", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_containment_log_is_tenant_scoped(
    client, db, organization, admin_user, auth_headers
) -> None:
    """Containment history of a foreign campaign must not be readable."""
    other_org = Organization(name="Other Corp", domain="other2.example")
    db.add(other_org)
    await db.commit()
    await db.refresh(other_org)
    foreign = await _make_campaign(db, other_org.id, "Foreign Containment")
    own = await _make_campaign(db, organization.id, "Own Containment")

    foreign_response = await client.get(
        f"/api/v1/containment/campaign-log/{foreign.id}", headers=auth_headers
    )
    own_response = await client.get(
        f"/api/v1/containment/campaign-log/{own.id}", headers=auth_headers
    )
    assert foreign_response.status_code == 404
    assert own_response.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rotates_sessions(client, db, admin_user) -> None:
    """Changing the password revokes old tokens and returns a working pair."""
    login = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    assert login.status_code == 200
    old_access = login.json()["access"]
    old_headers = {"Authorization": f"Bearer {old_access}"}

    wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": "not-the-password", "new_password": "StrongerPass123!"},
    )
    assert wrong.status_code == 401

    weak = await client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": "Secret123!", "new_password": "short"},
    )
    assert weak.status_code == 422

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": "Secret123!", "new_password": "StrongerPass123!"},
    )
    assert changed.status_code == 200
    new_access = changed.json()["access"]
    assert new_access != old_access

    # The pre-change token is revoked immediately.
    stale = await client.get("/api/v1/auth/me", headers=old_headers)
    assert stale.status_code == 401

    fresh = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert fresh.status_code == 200

    # The new password is the one that authenticates now.
    relogin = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "StrongerPass123!"}
    )
    assert relogin.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_access_token(client, db, admin_user, auth_headers) -> None:
    """Logout invalidates the presented token server-side instead of only locally."""
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 200

    logout = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert logout.status_code == 200

    after = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_revoked_after_logout(
    client, db, admin_user, auth_headers
) -> None:
    """A refresh token issued before logout cannot mint a new access token."""
    login = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "Secret123!"}
    )
    refresh_token = login.json()["refresh"]

    assert (await client.post("/api/v1/auth/logout", headers=auth_headers)).status_code == 200

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_login_does_not_reveal_unknown_usernames(client) -> None:
    """Unknown accounts and wrong passwords return the same status."""
    unknown = await client.post(
        "/api/v1/auth/login", json={"username": "no-such-user", "password": "whatever"}
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "wrong"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_environment_tokens_are_ignored_without_trust() -> None:
    """The rightmost forwarded hop is used, never a client-supplied prefix."""
    request = SimpleNamespace(
        headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8", "x-real-ip": "9.9.9.9"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_ip(request) == "9.9.9.9"

    only_xff = SimpleNamespace(
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert _client_ip(only_xff) == "203.0.113.7"


def test_production_rejects_unsafe_defaults() -> None:
    """Generated keys / the shipped admin password abort a production start."""
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            secret_key="too-short",
            encryption_key="too-short",
            bootstrap_admin_password="ChangeMe123!",
        )


@pytest.mark.asyncio
async def test_password_hash_roundtrip_after_rotation(db, admin_user) -> None:
    """The stored hash after rotation verifies the new password only."""
    from app.security import verify_password

    admin_user.password_hash = hash_password("BrandNewPass123")
    await db.commit()
    assert verify_password("BrandNewPass123", admin_user.password_hash)
    assert not verify_password("Secret123!", admin_user.password_hash)
    assert isinstance(admin_user, User)
