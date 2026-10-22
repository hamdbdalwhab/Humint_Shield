#!/usr/bin/env python
"""End-to-end deliverability and tracking verification for HUMINT Shield.

Run this against a live, Brevo-configured deployment to produce the evidence
required by the acceptance checklist:

1.  administrator authentication                 (JWT access token)
2.  runtime configuration snapshot               (sender identity, flags)
3.  dependency health                            (database, redis)
4.  Brevo API-key validation                     (account call)
5.  diagnostic test email                        (single message, message_id)
6.  target employee resolution / creation
7.  campaign creation against a built-in template
8.  campaign launch                              (real send, per-recipient result)
9.  open tracking                                (1x1 pixel -> opened_count)
10. click tracking                               (302 -> training page -> clicked_count)
11. completion tracking                          (POST complete -> completed_count)

Usage
-----
    # from the repository root, with the backend dependencies installed
    python scripts/verify_brevo.py --to you@your-domain.com

    # custom deployment
    python scripts/verify_brevo.py \
        --to you@your-domain.com \
        --base-url https://humint.example.com \
        --username admin --password 'ChangeMe123!'

Exit code is ``0`` only when every step succeeds.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

# Allow running the script directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

STEP = 0


def step(title: str) -> None:
    """Print a numbered checkpoint banner."""
    global STEP
    STEP += 1
    print(f"\n[{STEP:02d}] {title}")
    print("-" * 68)


def ok(message: str) -> None:
    """Print a success line."""
    print(f"  \u2713 {message}")


def fail(message: str) -> None:
    """Print a failure line."""
    print(f"  \u2717 {message}")


class VerificationError(RuntimeError):
    """Raised when a verification step fails."""


async def _tracking_uuid_for(campaign_id: uuid.UUID, employee_id: uuid.UUID) -> uuid.UUID | None:
    """Read the per-recipient tracking UUID straight from the database.

    The tracking UUID is deliberately never exposed through the API, so the
    verification script reads it from the persistence layer to simulate the
    recipient's browser.

    Args:
        campaign_id: Campaign identifier.
        employee_id: Target employee identifier.

    Returns:
        The tracking UUID, or ``None`` when no tracking row exists.
    """
    from sqlalchemy import select

    from app.database import get_session_factory
    from app.models import EmailTracking

    async with get_session_factory()() as session:
        return await session.scalar(
            select(EmailTracking.tracking_uuid).where(
                EmailTracking.campaign_id == campaign_id,
                EmailTracking.employee_id == employee_id,
            )
        )


async def run(to_email: str, base_url: str, username: str, password: str, campaign_name: str) -> None:
    """Execute the full verification sequence.

    Args:
        to_email: Recipient address for the real test message.
        base_url: Public base URL of the backend.
        username: Bootstrap administrator username.
        password: Bootstrap administrator password.
        campaign_name: Name for the throw-away verification campaign.

    Raises:
        VerificationError: When any step fails.
    """
    api = f"{base_url.rstrip('/')}/api/v1"
    async with httpx.AsyncClient(base_url=api, timeout=60.0, follow_redirects=False) as client:
        # 1 - authentication -------------------------------------------------
        step("Administrator authentication")
        response = await client.post("/auth/login", json={"username": username, "password": password})
        if response.status_code != 200:
            fail(f"login failed: HTTP {response.status_code} {response.text[:200]}")
            raise VerificationError("authentication failed")
        token = response.json()["access"]
        me = response.json()["user"]
        org_id = me.get("organization_id")
        if not org_id:
            fail("the administrator is not attached to an organization")
            raise VerificationError("missing organization")
        client.headers["Authorization"] = f"Bearer {token}"
        ok(f"authenticated as {me['username']} ({me['role']}), org {org_id}")

        # 2 - runtime configuration ------------------------------------------
        step("Runtime configuration")
        config = (await client.get("/test/config")).json()
        ok(f"from: {config['from_name']} <{config['from_email']}>")
        ok(f"base_url: {config['base_url']}")
        if not config["brevo_configured"]:
            fail("BREVO_API_KEY is not configured — set it in .env and restart")
            raise VerificationError("Brevo not configured")
        if config["email_dry_run"]:
            fail("EMAIL_DRY_RUN=true — no real message will be delivered")
            raise VerificationError("dry-run mode enabled")
        ok("Brevo configured, live sending enabled")

        # 3 - dependency health ----------------------------------------------
        step("Dependency health")
        health = (await client.get("/test/health")).json()
        ok(f"status={health['status']} db={health['db']['ok']} redis={health['redis']['ok']}")
        if not health["db"]["ok"]:
            raise VerificationError("database unreachable")

        # 4 - Brevo API key validation ---------------------------------------
        step("Brevo API-key validation")
        verify = (await client.get("/test/brevo/verify")).json()
        if not verify.get("valid"):
            fail(f"Brevo rejected the API key: {verify.get('error')}")
            raise VerificationError("invalid Brevo API key")
        ok(f"API key valid ({str(verify.get('detail'))[:80]})")

        # 5 - diagnostic test email ------------------------------------------
        step("Diagnostic test email")
        test_result = (await client.post("/test/brevo", json={"to_email": to_email})).json()
        if not test_result.get("success"):
            fail(f"test email failed: {test_result.get('error')}")
            raise VerificationError("test email failed")
        ok(f"dispatched, message_id={test_result.get('message_id')}")

        # 6 - target employee -------------------------------------------------
        step("Target employee resolution")
        listing = (
            await client.get(f"/organizations/{org_id}/employees", params={"search": to_email})
        ).json()
        employee: dict[str, Any] | None = next(
            (item for item in listing.get("items", []) if item["email"].lower() == to_email.lower()),
            None,
        )
        if employee is None:
            created = await client.post(
                f"/organizations/{org_id}/employees",
                json={"email": to_email, "first_name": "Verification", "last_name": "Recipient"},
            )
            if created.status_code not in (200, 201):
                fail(f"could not create employee: HTTP {created.status_code} {created.text[:200]}")
                raise VerificationError("employee creation failed")
            employee = created.json()
            ok(f"created employee {employee['id']}")
        else:
            ok(f"using existing employee {employee['id']}")
        employee_id = uuid.UUID(employee["id"])

        # 7 - campaign --------------------------------------------------------
        step("Campaign creation")
        templates = (await client.get(f"/organizations/{org_id}/email-templates")).json()
        if not templates:
            fail("no templates available — built-in templates are seeded on startup")
            raise VerificationError("no templates")
        template = templates[0]
        created_campaign = await client.post(
            f"/organizations/{org_id}/email-campaigns",
            json={
                "name": campaign_name,
                "template_id": template["id"],
                "difficulty_level": template["difficulty_level"],
                "target_employee_ids": [employee["id"]],
            },
        )
        if created_campaign.status_code not in (200, 201):
            fail(f"campaign creation failed: HTTP {created_campaign.status_code}")
            raise VerificationError("campaign creation failed")
        campaign = created_campaign.json()
        campaign_id = uuid.UUID(campaign["id"])
        ok(f"campaign {campaign_id} using template {template['name']!r}")

        # 8 - launch ----------------------------------------------------------
        step("Campaign launch (real delivery)")
        launch = await client.post(f"/organizations/{org_id}/email-campaigns/{campaign_id}/launch")
        body = launch.json()
        if launch.status_code != 200 or body.get("sent", 0) < 1:
            fail(f"launch failed: HTTP {launch.status_code} {body}")
            raise VerificationError("launch failed")
        ok(f"sent={body['sent']} failed={body['failed']} total={body['total']}")
        if body.get("failures"):
            print(f"    failures: {body['failures']}")

        # 9-11 - tracking -----------------------------------------------------
        tracking_uuid = await _tracking_uuid_for(campaign_id, employee_id)
        if tracking_uuid is None:
            fail("no tracking row was created for the recipient")
            raise VerificationError("missing tracking row")
        ok(f"tracking uuid {tracking_uuid}")

        step("Open tracking (1x1 pixel)")
        pixel = await client.get(f"/track/open/{tracking_uuid}")
        if pixel.status_code != 200 or pixel.headers.get("content-type") != "image/gif":
            fail(f"unexpected pixel response: HTTP {pixel.status_code}")
            raise VerificationError("open tracking failed")
        ok(f"pixel returned ({len(pixel.content)} bytes, image/gif)")

        step("Click tracking (302 to the training page)")
        click = await client.get(f"/track/click/{tracking_uuid}", params={"url": "https://evil.example/"})
        location = click.headers.get("location", "")
        if click.status_code != 302 or f"/training/{tracking_uuid}" not in location:
            fail(f"unexpected redirect: HTTP {click.status_code} -> {location}")
            raise VerificationError("click tracking failed")
        ok(f"302 -> {location}")

        step("Completion tracking")
        completion = await client.post(f"/track/complete/{tracking_uuid}")
        completion_body = completion.json()
        if completion.status_code != 200 or not completion_body.get("success"):
            fail(f"completion failed: {completion_body}")
            raise VerificationError("completion tracking failed")
        ok(f"completion recorded: {completion_body.get('message')}")

        # 12 - verify counters ------------------------------------------------
        step("Counter reconciliation")
        results = (await client.get(f"/organizations/{org_id}/email-campaigns/{campaign_id}/results")).json()
        stats = results["stats"]
        expected = {
            "sent": 1,
            "opened": 1,
            "clicked": 1,
            "completed": 1,
        }
        for key, value in expected.items():
            actual = stats.get(key)
            mark = ok if actual == value else fail
            mark(f"{key}: {actual} (expected {value})")
        if any(stats.get(key) != value for key, value in expected.items()):
            raise VerificationError("tracking counters did not reconcile")

        print("\n" + "=" * 68)
        print("  VERIFICATION PASSED — delivery and tracking are fully functional.")
        print(f"  Check the inbox at {to_email} to confirm the message arrived,")
        print("  then review Images/links in the client to confirm live tracking.")
        print("=" * 68 + "\n")


def main() -> int:
    """Parse arguments and run the verification.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description="HUMINT Shield Brevo verification")
    parser.add_argument("--to", required=True, help="recipient address for the test message")
    parser.add_argument("--base-url", default=None, help="backend base URL (default: from settings)")
    parser.add_argument("--username", default=None, help="admin username (default: from settings)")
    parser.add_argument("--password", default=None, help="admin password (default: from settings)")
    parser.add_argument(
        "--campaign-name",
        default=f"Verification {uuid.uuid4().hex[:8]}",
        help="name for the verification campaign",
    )
    args = parser.parse_args()

    from app.config import get_settings

    settings = get_settings()
    base_url = args.base_url or settings.base_url
    username = args.username or settings.bootstrap_admin_username
    password = args.password or settings.bootstrap_admin_password

    print("\nHUMINT Shield — Brevo end-to-end verification")
    print(f"target: {base_url}   recipient: {args.to}")

    try:
        asyncio.run(run(args.to, base_url, username, password, args.campaign_name))
    except VerificationError as exc:
        print(f"\n  VERIFICATION FAILED: {exc}\n")
        return 1
    except httpx.HTTPError as exc:
        print(f"\n  VERIFICATION FAILED (network): {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
