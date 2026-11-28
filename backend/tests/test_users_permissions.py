"""Operator administration: least-privilege grants and revocation semantics."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import AuditLog, User


async def _login(client, username: str, password: str) -> str:
    """Sign in and return the access token."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access"]


def _payload(**overrides) -> dict:
    """Return a valid account-creation payload with overrides."""
    base = {
        "username": f"operator_{uuid.uuid4().hex[:8]}",
        "email": f"operator_{uuid.uuid4().hex[:8]}@acmetest.example",
        "password": "StrongPass123!",
        "role": "custom",
        "permissions": ["employees.view"],
    }
    base.update(overrides)
    return base


async def test_permission_catalog_exposes_groups_and_presets(client, auth_headers) -> None:
    """The UI builds its matrix from the catalog, never from hard-coded keys."""
    response = await client.get("/api/v1/users/permissions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_permissions"] >= 20
    keys = {item["key"] for group in body["groups"] for item in group["permissions"]}
    assert {"users.manage", "settings.branding", "campaigns.launch"} <= keys
    presets = {role["key"]: role["default_permissions"] for role in body["roles"]}
    assert "settings.branding" in presets["manager"]
    assert presets["viewer"] == [
        permission for permission in presets["admin"] if permission.endswith(".view")
    ] or "employees.view" in presets["viewer"]
    assert presets["custom"] == []


async def test_viewer_cannot_read_or_mutate_operator_accounts(client, viewer_headers) -> None:
    """Operator administration is invisible to a read-only viewer."""
    listing = await client.get("/api/v1/users", headers=viewer_headers)
    assert listing.status_code == 403

    denied = await client.post("/api/v1/users", headers=viewer_headers, json=_payload())
    assert denied.status_code == 403


async def test_create_custom_user_grants_exact_permissions(
    client, auth_headers, db
) -> None:
    """A custom account holds exactly the granted keys."""
    payload = _payload(permissions=["employees.view", "reports.export", "employees.view"])
    response = await client.post("/api/v1/users", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "custom"
    assert set(body["permissions"]) == {"employees.view", "reports.export"}
    assert set(body["effective_permissions"]) == {"employees.view", "reports.export"}

    token = await _login(client, payload["username"], payload["password"])
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert set(me.json()["effective_permissions"]) == {"employees.view", "reports.export"}

    # Out-of-scope endpoints are refused by the permission layer.
    users = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert users.status_code == 403
    guardrails = await client.put(
        f"/api/v1/organizations/{body['organization_id']}/email-campaigns/guardrails",
        headers={"Authorization": f"Bearer {token}"},
        json={"campaign_cooldown_days": 3},
    )
    assert guardrails.status_code == 403

    stored = await db.scalar(select(User).where(User.username == payload["username"]))
    assert stored is not None and stored.permissions == ["employees.view", "reports.export"]


async def test_unknown_permission_is_rejected(client, auth_headers) -> None:
    """Unknown keys fail validation instead of being silently dropped."""
    response = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json=_payload(permissions=["employees.view", "root.everything"]),
    )
    assert response.status_code == 422


async def test_manager_permission_grants_cannot_exceed_authority(client, auth_headers) -> None:
    """A non-admin delegate cannot mint an administrator."""
    delegate = _payload(
        role="custom", permissions=["users.view", "users.manage", "employees.view"]
    )
    created = await client.post("/api/v1/users", headers=auth_headers, json=delegate)
    assert created.status_code == 201, created.text
    token = await _login(client, delegate["username"], delegate["password"])
    headers = {"Authorization": f"Bearer {token}"}

    escalated = await client.post(
        "/api/v1/users",
        headers=headers,
        json=_payload(role="admin", permissions=[]),
    )
    assert escalated.status_code == 403
    assert "permissions you do not hold" in escalated.json()["detail"]


async def test_permission_change_revokes_live_sessions(client, auth_headers) -> None:
    """Revoking a grant invalidates the account's existing tokens immediately."""
    payload = _payload(permissions=["employees.view", "reports.view"])
    created = await client.post("/api/v1/users", headers=auth_headers, json=payload)
    assert created.status_code == 201
    user_id = created.json()["id"]
    token = await _login(client, payload["username"], payload["password"])
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    updated = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=auth_headers,
        json={"permissions": []},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["effective_permissions"] == []
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_password_reset_revokes_sessions_and_rotates_credentials(
    client, auth_headers
) -> None:
    """An administrative reset invalidates old tokens and sets the new password."""
    payload = _payload(permissions=["employees.view"])
    created = await client.post("/api/v1/users", headers=auth_headers, json=payload)
    assert created.status_code == 201
    user_id = created.json()["id"]
    token = await _login(client, payload["username"], payload["password"])

    reset = await client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=auth_headers,
        json={"new_password": "AnotherPass456!"},
    )
    assert reset.status_code == 200, reset.text
    assert (
        await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    ).status_code == 401

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"username": payload["username"], "password": payload["password"]},
    )
    assert old_login.status_code == 401
    await _login(client, payload["username"], "AnotherPass456!")


async def test_self_lockout_is_prevented(client, auth_headers, admin_user) -> None:
    """Nobody can demote or deactivate their own account."""
    demote = await client.patch(
        f"/api/v1/users/{admin_user.id}", headers=auth_headers, json={"role": "viewer"}
    )
    assert demote.status_code == 400
    deactivate = await client.delete(f"/api/v1/users/{admin_user.id}", headers=auth_headers)
    assert deactivate.status_code == 400


async def test_deactivation_blocks_sign_in_and_is_audited(
    client, auth_headers, db
) -> None:
    """Deactivating an account stops sign-in and writes an audit trail row."""
    payload = _payload(permissions=["employees.view"])
    created = await client.post("/api/v1/users", headers=auth_headers, json=payload)
    assert created.status_code == 201
    user_id = created.json()["id"]

    deactivated = await client.delete(f"/api/v1/users/{user_id}", headers=auth_headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": payload["username"], "password": payload["password"]},
    )
    assert login.status_code == 403

    rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.target_table == "users", AuditLog.target_id == user_id
            )
        )
    ).scalars().all()
    assert rows
    audit_payload = [row.new_value or {} for row in rows]
    assert all("password" not in str(value).lower() or "rotated" in str(value).lower() for value in audit_payload)
