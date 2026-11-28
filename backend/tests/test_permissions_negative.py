"""Negative authorization tests (403/401) across every core module.

These tests prove the *absence* of access, which is the property that matters
for least privilege.  They are deliberately written against the real permission
catalog (:mod:`app.permissions`) rather than hard-coded role checks, so a future
preset edit that accidentally widens access fails here.
"""
from __future__ import annotations

import uuid

from app.models import EmailCampaign, Organization, User
from app.security import create_access_token, hash_password


def _headers(user: User) -> dict[str, str]:
    """Return a bearer header for ``user``."""
    token = create_access_token(str(user.id), {"role": user.role})
    return {"Authorization": f"Bearer {token}"}


async def _make_user(
    db,
    organization: Organization,
    *,
    role: str,
    permissions: list[str] | None = None,
    username: str | None = None,
) -> User:
    """Create an active account in ``organization`` and return it."""
    user = User(
        username=username or f"{role}_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@acmetest.example",
        password_hash=hash_password("Secret123!"),
        role=role,
        permissions=permissions or [],
        organization_id=organization.id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_campaign(db, organization: Organization, template, name: str) -> EmailCampaign:
    """Create a draft campaign so delete/launch routes have a real target."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=name,
        status="draft",
        target_employee_ids=[],
        total_targets=0,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


# --------------------------------------------------------------------------- #
# 1. Viewer cannot create an employee
# --------------------------------------------------------------------------- #
async def test_viewer_cannot_create_employee(
    client, db, organization, viewer_headers
) -> None:
    """A read-only viewer is refused at the permission layer (403)."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        headers=viewer_headers,
        json={"email": "denied@acmetest.example", "first_name": "Denied"},
    )
    assert response.status_code == 403
    assert "employees.manage" in response.json()["detail"]


async def test_viewer_can_still_read_employees(
    client, db, organization, viewer_headers, employee
) -> None:
    """The same viewer keeps read access — the gate is least privilege, not denial."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees",
        headers=viewer_headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


# --------------------------------------------------------------------------- #
# 2. Viewer cannot delete a campaign
# --------------------------------------------------------------------------- #
async def test_viewer_cannot_delete_campaign(
    client, db, organization, viewer_headers, custom_template
) -> None:
    """Deleting a campaign requires ``campaigns.delete``."""
    campaign = await _make_campaign(db, organization, custom_template, "Protected draft")
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}",
        headers=viewer_headers,
    )
    assert response.status_code == 403
    assert "campaigns.delete" in response.json()["detail"]

    still_there = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}",
        headers=viewer_headers,
    )
    assert still_there.status_code == 200


# --------------------------------------------------------------------------- #
# 3. Manager edits but cannot delete an employee
# --------------------------------------------------------------------------- #
async def test_manager_cannot_delete_employee(
    client, db, organization, employee
) -> None:
    """``employees.delete`` is deliberately absent from the manager preset."""
    manager = await _make_user(db, organization, role="manager")

    update = await client.put(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}",
        headers=_headers(manager),
        json={"department": "Compliance"},
    )
    assert update.status_code == 200

    denied = await client.delete(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}",
        headers=_headers(manager),
    )
    assert denied.status_code == 403
    assert "employees.delete" in denied.json()["detail"]


async def test_manager_cannot_delete_campaign(
    client, db, organization, custom_template
) -> None:
    """The manager preset includes manage/launch but never delete."""
    manager = await _make_user(db, organization, role="manager")
    campaign = await _make_campaign(db, organization, custom_template, "Manager draft")
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}",
        headers=_headers(manager),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# 4. A custom account with no grants can reach nothing
# --------------------------------------------------------------------------- #
async def test_custom_user_without_grants_is_denied_everywhere(
    client, db, organization, custom_template
) -> None:
    """An empty custom account is the purest least-privilege subject."""
    campaign = await _make_campaign(db, organization, custom_template, "Unreachable")
    ghost = await _make_user(db, organization, role="custom", permissions=[])
    headers = _headers(ghost)
    base = f"/api/v1/organizations/{organization.id}"

    checks = [
        ("get", f"{base}/employees"),
        ("get", f"{base}/email-campaigns"),
        ("get", f"{base}/training-modules"),
        ("get", f"{base}/assignments"),
        ("get", f"{base}/reports"),
        ("get", f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}"),
        ("get", f"{base}/employees/{uuid.uuid4()}"),
        ("post", f"{base}/email-campaigns/{campaign.id}/launch"),
    ]
    for method, url in checks:
        response = await getattr(client, method)(url, headers=headers)
        assert response.status_code == 403, f"{method.upper()} {url} -> {response.status_code}"


async def test_custom_user_gets_exactly_the_granted_permission(
    client, db, organization, employee
) -> None:
    """One grant opens one module and nothing else."""
    reader = await _make_user(
        db, organization, role="custom", permissions=["employees.view"]
    )
    headers = _headers(reader)
    base = f"/api/v1/organizations/{organization.id}"

    allowed = await client.get(f"{base}/employees", headers=headers)
    assert allowed.status_code == 200

    forbidden = await client.get(f"{base}/email-campaigns", headers=headers)
    assert forbidden.status_code == 403
    assert "campaigns.view" in forbidden.json()["detail"]


# --------------------------------------------------------------------------- #
# 5. Unauthenticated requests are 401, not 403
# --------------------------------------------------------------------------- #
async def test_unauthenticated_cannot_reach_protected_routes(
    client, organization
) -> None:
    """No token means 401 on every protected surface."""
    base = f"/api/v1/organizations/{organization.id}"
    for url in (f"{base}/employees", f"{base}/email-campaigns", f"{base}/training-modules"):
        response = await client.get(url)
        assert response.status_code == 401

    forged = await client.get(
        f"{base}/employees", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert forged.status_code == 401


# --------------------------------------------------------------------------- #
# 6. Admin retains full access
# --------------------------------------------------------------------------- #
async def test_admin_can_access_every_module(
    client, db, organization, auth_headers, custom_template
) -> None:
    """The administrator holds every catalogued permission."""
    campaign = await _make_campaign(db, organization, custom_template, "Admin view")
    base = f"/api/v1/organizations/{organization.id}"

    for url in (
        f"{base}/employees",
        f"{base}/email-campaigns",
        f"{base}/training-modules",
        f"{base}/assignments",
        f"{base}/reports",
        f"{base}/email-campaigns/{campaign.id}",
    ):
        response = await client.get(url, headers=auth_headers)
        assert response.status_code == 200, f"GET {url} -> {response.status_code}"

    report = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}", headers=auth_headers
    )
    # Reaching the PDF service (and not the permission gate) is what is asserted.
    assert report.status_code in {200, 500}, report.text


async def test_admin_can_delete_employee(
    client, db, organization, auth_headers, employee
) -> None:
    """Only the administrator preset carries ``employees.delete``."""
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}",
        headers=auth_headers,
    )
    assert response.status_code == 204


# --------------------------------------------------------------------------- #
# 7. Cross-organization access is blocked
# --------------------------------------------------------------------------- #
async def test_cross_organization_access_is_blocked(
    client, db, organization, employee, custom_template
) -> None:
    """A privileged account from org B still cannot touch org A's data."""
    other = Organization(name="Other Org", domain="other-org.example")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    outsider = await _make_user(db, other, role="admin")
    headers = _headers(outsider)
    base = f"/api/v1/organizations/{organization.id}"

    listing = await client.get(f"{base}/employees", headers=headers)
    assert listing.status_code == 403

    fetch_one = await client.get(f"{base}/employees/{employee.id}", headers=headers)
    assert fetch_one.status_code == 403

    campaign = await _make_campaign(db, organization, custom_template, "Tenant A draft")
    report = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}", headers=headers
    )
    # A foreign campaign is indistinguishable from a missing one.
    assert report.status_code == 404
