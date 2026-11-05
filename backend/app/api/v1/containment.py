"""Enterprise Directory & SOAR Containment API Endpoints."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, User
from app.services.enterprise_identity_service import (
    ContainmentAction,
    enterprise_identity_service,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/containment",
    tags=["enterprise-containment"],
    dependencies=[Depends(rate_limit(scope="containment"))],
)


class PasswordPolicySchema(BaseModel):
    min_length: int = Field(16, ge=8, le=64, description="Minimum password characters")
    require_symbols: bool = Field(True, description="Require symbols !@#$%^&*")
    require_numbers: bool = Field(True, description="Require digits 0-9")
    require_uppercase: bool = Field(True, description="Require uppercase letters A-Z")
    require_lowercase: bool = Field(True, description="Require lowercase letters a-z")
    history_count: int = Field(10, ge=0, le=30, description="Prevent reuse of last N passwords")
    max_age_days: int = Field(30, ge=1, le=365, description="Maximum password age in days")
    lockout_threshold: int = Field(5, ge=1, le=20, description="Failed attempts before account lockout")


class RemediationPolicySchema(BaseModel):
    auto_containment_enabled: bool = Field(True, description="Enable automatic containment on breach")
    force_password_reset: bool = Field(True, description="Force user to set new password at next logon")
    revoke_sessions: bool = Field(True, description="Revoke all active tokens and sessions")
    quarantine_account: bool = Field(False, description="Temporarily suspend/freeze user account")
    enforce_strict_password: bool = Field(True, description="Apply fine-grained strict password policy")
    enforce_mfa: bool = Field(True, description="Enforce step-up multi-factor authentication")
    notify_soar: bool = Field(True, description="Dispatch real-time alert to SOC / SOAR webhook")
    password_policy: PasswordPolicySchema | None = Field(None, description="Password complexity rules")


class TriggerContainmentRequest(BaseModel):
    target_identity: str = Field(..., description="Target email or AD username")
    breach_type: str = Field("simulated_attack", description="Attack type (e.g., badusb_hid, usb_baiting, phish)")
    campaign_id: str | None = Field(None, description="Optional Campaign UUID")
    tracking_uuid: str | None = Field(None, description="Optional Tracking UUID")
    actions: list[str] | None = Field(
        None,
        description="List of actions: force_password_reset, revoke_sessions, quarantine_account, enforce_high_risk_policy, notify_soar_webhook",
    )
    policy_override: RemediationPolicySchema | None = Field(
        None,
        description="Optional policy override for this execution",
    )


class TestProviderRequest(BaseModel):
    provider: str = Field(..., description="'entra_id', 'active_directory', or 'soar'")
    test_identity: str = Field("test.user@company.local", description="Sample username or email for validation")


@router.get("/status")
async def get_containment_status(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the configuration status of Active Directory, Entra ID, and SOAR."""
    return enterprise_identity_service.get_status()


@router.get("/policy")
async def get_remediation_policy(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve the active admin remediation policy and password complexity rules."""
    return enterprise_identity_service.get_policy()


@router.post("/policy")
async def update_remediation_policy(
    payload: RemediationPolicySchema,
    current_user: User = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Update admin remediation rules and password complexity requirements."""
    data = payload.model_dump(exclude_unset=True)
    updated = enterprise_identity_service.update_policy(data)
    return updated


@router.post("/trigger")
async def trigger_containment_action(
    payload: TriggerContainmentRequest,
    current_user: User = Depends(require_roles("admin", "operator")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute enterprise automated containment on a target account based on admin policy."""
    target = payload.target_identity.strip()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target identity (email or username) is required.",
        )

    # If policy override provided, apply it
    if payload.policy_override:
        enterprise_identity_service.update_policy(payload.policy_override.model_dump(exclude_unset=True))

    # Validate actions if provided
    valid_actions = {a.value for a in ContainmentAction}
    if payload.actions:
        invalid = [a for a in payload.actions if a not in valid_actions]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid containment actions: {invalid}. Supported: {list(valid_actions)}",
            )

    report = await enterprise_identity_service.execute_containment(
        target_identity=target,
        breach_type=payload.breach_type,
        tracking_uuid=payload.tracking_uuid or str(uuid.uuid4()),
        actions=payload.actions,
        context={
            "triggered_by": current_user.email,
            "campaign_id": payload.campaign_id,
            "mode": "admin_interactive_trigger",
        },
    )

    # If associated with a tracking record, store the action in its client_context
    if payload.tracking_uuid:
        try:
            uid = uuid.UUID(payload.tracking_uuid)
            tracking_row = await db.scalar(
                select(EmailTracking).where(EmailTracking.tracking_uuid == uid)
            )
            if tracking_row:
                ctx = dict(tracking_row.client_context or {})
                history = list(ctx.get("containment_history") or [])
                history.append(report.to_dict())
                ctx["containment_history"] = history
                ctx["last_containment"] = report.to_dict()
                tracking_row.client_context = ctx
                await db.commit()
        except Exception as exc:
            logger.warning("failed_to_attach_containment_to_tracking", error=str(exc))

    return report.to_dict()


@router.get("/campaign-log/{campaign_id}")
async def get_campaign_containment_logs(
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve all automated containment events recorded for a campaign."""
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid campaign ID")

    stmt = select(EmailTracking).where(EmailTracking.campaign_id == cid)
    result = await db.scalars(stmt)
    records = result.all()

    logs: list[dict[str, Any]] = []
    for r in records:
        ctx = r.client_context or {}
        if "last_containment" in ctx:
            logs.append(ctx["last_containment"])
        elif "containment_history" in ctx:
            logs.extend(ctx.get("containment_history", []))

    return logs
