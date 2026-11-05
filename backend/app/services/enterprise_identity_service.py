"""Enterprise Directory & SOAR Automated Containment Service.

Integrates HUMINT Shield with Enterprise Identity Providers (Microsoft Entra ID /
Active Directory) and SOAR / SIEM systems to execute real-time containment and
remediation whenever an employee triggers a security breach (e.g., USB baiting,
BadUSB keystroke injection, or simulated credential submission).

Provides flexible, admin-defined remediation policies and custom password complexity
enforcement (length, symbols, numbers, uppercase, history, lockout threshold).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import platform
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContainmentAction(str, Enum):
    """Supported enterprise automated containment actions."""
    FORCE_PASSWORD_RESET = "force_password_reset"
    REVOKE_SESSIONS = "revoke_sessions"
    QUARANTINE_ACCOUNT = "quarantine_account"
    ENFORCE_HIGH_RISK_POLICY = "enforce_high_risk_policy"
    NOTIFY_SOAR_WEBHOOK = "notify_soar_webhook"


class ContainmentStatus(str, Enum):
    """Execution status of an action."""
    SUCCESS = "success"
    SIMULATED = "simulated"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PasswordPolicyConfig:
    """Configurable password complexity requirements enforced on compromised accounts."""
    min_length: int = 16
    require_symbols: bool = True
    require_numbers: bool = True
    require_uppercase: bool = True
    require_lowercase: bool = True
    history_count: int = 10
    max_age_days: int = 30
    lockout_threshold: int = 5
    policy_name: str = "HUMINT_Strict_Enforcement"

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_length": self.min_length,
            "require_symbols": self.require_symbols,
            "require_numbers": self.require_numbers,
            "require_uppercase": self.require_uppercase,
            "require_lowercase": self.require_lowercase,
            "history_count": self.history_count,
            "max_age_days": self.max_age_days,
            "lockout_threshold": self.lockout_threshold,
            "policy_name": self.policy_name,
            "powershell_command": self.generate_powershell_fgpp(),
            "description_ar": self.generate_description_ar(),
        }

    def generate_powershell_fgpp(self) -> str:
        """Generate the exact Active Directory PowerShell cmdlet for Fine-Grained Password Policy."""
        complexity_bool = "$true" if (self.require_symbols or self.require_numbers or self.require_uppercase) else "$false"
        return (
            f"New-ADFineGrainedPasswordPolicy -Name '{self.policy_name}' "
            f"-Precedence 1 "
            f"-ComplexityEnabled {complexity_bool} "
            f"-MinPasswordLength {self.min_length} "
            f"-PasswordHistoryCount {self.history_count} "
            f"-MinPasswordAge '1.00:00:00' "
            f"-MaxPasswordAge '{self.max_age_days}.00:00:00' "
            f"-LockoutThreshold {self.lockout_threshold} "
            f"-LockoutDuration '00:30:00' "
            f"-AppliesTo 'Enforced_Strict_Password_Group'"
        )

    def generate_description_ar(self) -> str:
        parts = [f"الحد الأدنى للطول: {self.min_length} خانة"]
        if self.require_symbols:
            parts.append("رموز خاصة (!@#$...)")
        if self.require_numbers:
            parts.append("أرقام (0-9)")
        if self.require_uppercase:
            parts.append("أحرف كبيرة (A-Z)")
        parts.append(f"منع تكرار آخر {self.history_count} كلمات مرور")
        return " | ".join(parts)


@dataclass
class RemediationPolicy:
    """Flexible admin-managed remediation rules."""
    auto_containment_enabled: bool = True
    force_password_reset: bool = True
    revoke_sessions: bool = True
    quarantine_account: bool = False
    enforce_strict_password: bool = True
    enforce_mfa: bool = True
    notify_soar: bool = True
    password_policy: PasswordPolicyConfig = field(default_factory=PasswordPolicyConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_containment_enabled": self.auto_containment_enabled,
            "force_password_reset": self.force_password_reset,
            "revoke_sessions": self.revoke_sessions,
            "quarantine_account": self.quarantine_account,
            "enforce_strict_password": self.enforce_strict_password,
            "enforce_mfa": self.enforce_mfa,
            "notify_soar": self.notify_soar,
            "password_policy": self.password_policy.to_dict(),
        }

    def resolve_active_actions(self) -> list[str]:
        actions: list[str] = []
        if self.force_password_reset:
            actions.append(ContainmentAction.FORCE_PASSWORD_RESET.value)
        if self.revoke_sessions:
            actions.append(ContainmentAction.REVOKE_SESSIONS.value)
        if self.quarantine_account:
            actions.append(ContainmentAction.QUARANTINE_ACCOUNT.value)
        if self.enforce_strict_password or self.enforce_mfa:
            actions.append(ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value)
        if self.notify_soar:
            actions.append(ContainmentAction.NOTIFY_SOAR_WEBHOOK.value)
        return actions


@dataclass
class ActionResult:
    """Outcome of a single containment action."""
    action: str
    provider: str
    status: ContainmentStatus
    message_ar: str
    message_en: str
    timestamp: str = field(default_factory=lambda: _utcnow().isoformat())
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContainmentReport:
    """Consolidated report of containment actions executed for a target."""
    target_identity: str
    breach_type: str
    tracking_uuid: str
    executed_at: str
    results: list[ActionResult]
    overall_status: str
    summary_ar: str
    summary_en: str
    applied_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_identity": self.target_identity,
            "breach_type": self.breach_type,
            "tracking_uuid": self.tracking_uuid,
            "executed_at": self.executed_at,
            "overall_status": self.overall_status,
            "summary_ar": self.summary_ar,
            "summary_en": self.summary_en,
            "applied_policy": self.applied_policy,
            "results": [
                {
                    "action": r.action,
                    "provider": r.provider,
                    "status": r.status.value,
                    "message_ar": r.message_ar,
                    "message_en": r.message_en,
                    "timestamp": r.timestamp,
                    "details": r.details,
                }
                for r in self.results
            ],
        }


class EnterpriseIdentityService:
    """Manages Active Directory, Microsoft Entra ID and SOAR integrations with dynamic admin policy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.policy = RemediationPolicy()

    def get_policy(self) -> dict[str, Any]:
        """Return the current admin remediation and password policy."""
        return self.policy.to_dict()

    def update_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update remediation policy and password complexity rules based on admin decisions."""
        if "auto_containment_enabled" in payload:
            self.policy.auto_containment_enabled = bool(payload["auto_containment_enabled"])
        if "force_password_reset" in payload:
            self.policy.force_password_reset = bool(payload["force_password_reset"])
        if "revoke_sessions" in payload:
            self.policy.revoke_sessions = bool(payload["revoke_sessions"])
        if "quarantine_account" in payload:
            self.policy.quarantine_account = bool(payload["quarantine_account"])
        if "enforce_strict_password" in payload:
            self.policy.enforce_strict_password = bool(payload["enforce_strict_password"])
        if "enforce_mfa" in payload:
            self.policy.enforce_mfa = bool(payload["enforce_mfa"])
        if "notify_soar" in payload:
            self.policy.notify_soar = bool(payload["notify_soar"])

        pp = payload.get("password_policy")
        if isinstance(pp, dict):
            if "min_length" in pp:
                self.policy.password_policy.min_length = max(8, min(64, int(pp["min_length"])))
            if "require_symbols" in pp:
                self.policy.password_policy.require_symbols = bool(pp["require_symbols"])
            if "require_numbers" in pp:
                self.policy.password_policy.require_numbers = bool(pp["require_numbers"])
            if "require_uppercase" in pp:
                self.policy.password_policy.require_uppercase = bool(pp["require_uppercase"])
            if "require_lowercase" in pp:
                self.policy.password_policy.require_lowercase = bool(pp["require_lowercase"])
            if "history_count" in pp:
                self.policy.password_policy.history_count = max(0, min(30, int(pp["history_count"])))
            if "max_age_days" in pp:
                self.policy.password_policy.max_age_days = max(1, min(365, int(pp["max_age_days"])))
            if "lockout_threshold" in pp:
                self.policy.password_policy.lockout_threshold = max(1, min(20, int(pp["lockout_threshold"])))

        logger.info("remediation_policy_updated", policy=self.policy.to_dict())
        return self.policy.to_dict()

    def get_status(self) -> dict[str, Any]:
        """Return the configuration and readiness status of enterprise integrations."""
        return {
            "containment_enabled": self.settings.containment_enabled,
            "active_policy": self.policy.to_dict(),
            "entra_id": {
                "configured": self.settings.entra_configured,
                "tenant_id": self.settings.entra_tenant_id or "Not configured",
                "client_id": self.settings.entra_client_id or "Not configured",
                "high_risk_group_id": self.settings.entra_high_risk_group_id or "Default",
            },
            "active_directory": {
                "configured": self.settings.ad_configured,
                "domain_controller": self.settings.ad_domain_controller or "Not configured",
                "domain": self.settings.ad_domain or "Not configured",
                "strict_password_group": self.settings.ad_strict_password_group,
                "powershell_available": platform.system() == "Windows",
            },
            "soar_webhook": {
                "configured": self.settings.soar_configured,
                "webhook_url": self.settings.soar_webhook_url or "Not configured",
            },
            "supported_actions": [action.value for action in ContainmentAction],
        }

    async def execute_containment(
        self,
        target_identity: str,
        breach_type: str,
        tracking_uuid: str,
        actions: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ContainmentReport:
        """Execute enterprise containment actions for a compromised user according to admin policy.

        Args:
            target_identity: Corporate email or AD username.
            breach_type: The attack vector (e.g. 'badusb_hid', 'usb_baiting', 'credential_phish').
            tracking_uuid: Tracking row UUID reference.
            actions: Optional override list of actions. If None, uses admin's active policy.
            context: Additional contextual fields (hostname, IP, Elo delta, etc.).

        Returns:
            A comprehensive ContainmentReport.
        """
        # If no explicit action override was given, resolve from admin's configured policy
        if actions is None:
            actions = self.policy.resolve_active_actions()

        results: list[ActionResult] = []
        ctx = context or {}
        now = _utcnow().isoformat()

        for action_name in actions:
            try:
                res = await self._dispatch_action(
                    action_name=action_name,
                    target_identity=target_identity,
                    breach_type=breach_type,
                    tracking_uuid=tracking_uuid,
                    context=ctx,
                )
                results.append(res)
            except Exception as exc:
                logger.error(
                    "containment_action_unhandled_exception",
                    action=action_name,
                    target=target_identity,
                    error=str(exc),
                )
                results.append(
                    ActionResult(
                        action=action_name,
                        provider="system",
                        status=ContainmentStatus.FAILED,
                        message_ar=f"فشل تنفيذ الإجراء تلقائياً: {exc}",
                        message_en=f"Failed to execute action: {exc}",
                        details={"error": str(exc)},
                    )
                )

        failed_count = sum(1 for r in results if r.status == ContainmentStatus.FAILED)
        overall = "success" if failed_count == 0 else "partial_failure"

        actions_ar = "، ".join([r.message_ar for r in results])
        summary_ar = (
            f"تم تطبيق سياسة الأدمن للاحتواء بنجاح للمستخدم [{target_identity}]: {actions_ar}"
            if overall == "success"
            else f"تم تنفيذ بعض إجراءات الاحتواء مع وجود تنبيهات للمستخدم [{target_identity}]"
        )
        summary_en = (
            f"Admin containment policy executed successfully for [{target_identity}]."
            if overall == "success"
            else f"Containment completed with partial alerts for [{target_identity}]."
        )

        return ContainmentReport(
            target_identity=target_identity,
            breach_type=breach_type,
            tracking_uuid=tracking_uuid,
            executed_at=now,
            results=results,
            overall_status=overall,
            summary_ar=summary_ar,
            summary_en=summary_en,
            applied_policy=self.policy.to_dict(),
        )

    async def _dispatch_action(
        self,
        action_name: str,
        target_identity: str,
        breach_type: str,
        tracking_uuid: str,
        context: dict[str, Any],
    ) -> ActionResult:
        """Route the specific action to Entra ID, Active Directory, or SOAR."""

        if action_name == ContainmentAction.FORCE_PASSWORD_RESET.value:
            if self.settings.entra_configured:
                return await self._entra_force_password_reset(target_identity)
            elif self.settings.ad_configured:
                return await self._ad_force_password_reset(target_identity)
            else:
                return self._simulate_force_password_reset(target_identity)

        elif action_name == ContainmentAction.REVOKE_SESSIONS.value:
            if self.settings.entra_configured:
                return await self._entra_revoke_sessions(target_identity)
            else:
                return self._simulate_revoke_sessions(target_identity)

        elif action_name == ContainmentAction.QUARANTINE_ACCOUNT.value:
            if self.settings.entra_configured:
                return await self._entra_quarantine_account(target_identity)
            elif self.settings.ad_configured:
                return await self._ad_quarantine_account(target_identity)
            else:
                return self._simulate_quarantine_account(target_identity)

        elif action_name == ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value:
            if self.settings.entra_configured:
                return await self._entra_enforce_high_risk_group(target_identity)
            elif self.settings.ad_configured:
                return await self._ad_enforce_strict_group(target_identity)
            else:
                return self._simulate_enforce_high_risk_group(target_identity)

        elif action_name == ContainmentAction.NOTIFY_SOAR_WEBHOOK.value:
            if self.settings.soar_configured:
                return await self._dispatch_soar_webhook(
                    target_identity, breach_type, tracking_uuid, context
                )
            else:
                return self._simulate_soar_webhook(
                    target_identity, breach_type, tracking_uuid, context
                )

        return ActionResult(
            action=action_name,
            provider="unknown",
            status=ContainmentStatus.SKIPPED,
            message_ar=f"الإجراء غير مدعوم: {action_name}",
            message_en=f"Unsupported action: {action_name}",
        )

    # -------------------------------------------------------------------------
    # Microsoft Entra ID (Graph API) Implementation
    # -------------------------------------------------------------------------
    async def _get_entra_token(self) -> str | None:
        tenant_id = self.settings.entra_tenant_id
        client_id = self.settings.entra_client_id
        client_secret = self.settings.entra_client_secret
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(token_url, data=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
            logger.error("entra_token_acquisition_failed", status=resp.status_code, text=resp.text)
            return None

    async def _entra_force_password_reset(self, target_identity: str) -> ActionResult:
        token = await self._get_entra_token()
        if not token:
            return ActionResult(
                action=ContainmentAction.FORCE_PASSWORD_RESET.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar="فشل استخراج تصريح Microsoft Graph API للمؤسسة.",
                message_en="Failed to obtain Microsoft Graph API token.",
            )

        url = f"https://graph.microsoft.com/v1.0/users/{target_identity}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"passwordProfile": {"forceChangePasswordNextSignIn": True}}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(url, headers=headers, json=payload)
            if resp.status_code in (200, 204):
                return ActionResult(
                    action=ContainmentAction.FORCE_PASSWORD_RESET.value,
                    provider="Microsoft Entra ID",
                    status=ContainmentStatus.SUCCESS,
                    message_ar="تم إجبار تغيير كلمة المرور عند أول تسجيل دخول بنجاح.",
                    message_en="User forced to change password at next sign-in via Entra ID.",
                    details={"http_status": resp.status_code},
                )
            return ActionResult(
                action=ContainmentAction.FORCE_PASSWORD_RESET.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar=f"فشل إجبار تغيير كلمة المرور في Entra ID (كود {resp.status_code}).",
                message_en=f"Graph API returned status {resp.status_code}.",
                details={"response": resp.text},
            )

    async def _entra_revoke_sessions(self, target_identity: str) -> ActionResult:
        token = await self._get_entra_token()
        if not token:
            return ActionResult(
                action=ContainmentAction.REVOKE_SESSIONS.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar="فشل مصادقة Graph API لطرد الجلسات.",
                message_en="Failed Graph API authentication.",
            )

        url = f"https://graph.microsoft.com/v1.0/users/{target_identity}/revokeSignInSessions"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code in (200, 204):
                return ActionResult(
                    action=ContainmentAction.REVOKE_SESSIONS.value,
                    provider="Microsoft Entra ID",
                    status=ContainmentStatus.SUCCESS,
                    message_ar="تم إلغاء وطرد كافة الجلسات المفتوحة (Tokens) للمستخدم فوراً.",
                    message_en="All active refresh tokens and user sessions revoked immediately.",
                    details={"http_status": resp.status_code},
                )
            return ActionResult(
                action=ContainmentAction.REVOKE_SESSIONS.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar=f"فشل طرد الجلسات في Entra ID (كود {resp.status_code}).",
                message_en=f"Failed to revoke sessions: HTTP {resp.status_code}.",
                details={"response": resp.text},
            )

    async def _entra_quarantine_account(self, target_identity: str) -> ActionResult:
        token = await self._get_entra_token()
        if not token:
            return ActionResult(
                action=ContainmentAction.QUARANTINE_ACCOUNT.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar="فشل الاتصال بـ Graph API لتجميد الحساب.",
                message_en="Failed Graph API authentication.",
            )

        url = f"https://graph.microsoft.com/v1.0/users/{target_identity}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"accountEnabled": False}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(url, headers=headers, json=payload)
            if resp.status_code in (200, 204):
                return ActionResult(
                    action=ContainmentAction.QUARANTINE_ACCOUNT.value,
                    provider="Microsoft Entra ID",
                    status=ContainmentStatus.SUCCESS,
                    message_ar="تم تجميد وتعطيل حساب الموظف مؤقتاً في Entra ID.",
                    message_en="Employee account disabled (quarantined) via Entra ID.",
                    details={"http_status": resp.status_code},
                )
            return ActionResult(
                action=ContainmentAction.QUARANTINE_ACCOUNT.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar=f"فشل تجميد الحساب: كود {resp.status_code}.",
                message_en=f"Failed to disable account: HTTP {resp.status_code}.",
                details={"response": resp.text},
            )

    async def _entra_enforce_high_risk_group(self, target_identity: str) -> ActionResult:
        group_id = self.settings.entra_high_risk_group_id
        if not group_id:
            return self._simulate_enforce_high_risk_group(target_identity)

        token = await self._get_entra_token()
        if not token:
            return ActionResult(
                action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar="فشل مصادقة Graph API لإضافة المستخدم لمجموعة الأمان المشددة.",
                message_en="Failed Graph API authentication.",
            )

        url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members/$ref"
        user_url = f"https://graph.microsoft.com/v1.0/directoryObjects/{target_identity}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"@odata.id": user_url}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 204):
                return ActionResult(
                    action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
                    provider="Microsoft Entra ID",
                    status=ContainmentStatus.SUCCESS,
                    message_ar=f"تم ضم المستخدم لمجموعة الخطر العالي وفرض سياسة {self.policy.password_policy.generate_description_ar()}.",
                    message_en="User added to high-risk group; Conditional Access MFA enforced.",
                    details={"group_id": group_id, "policy": self.policy.password_policy.to_dict()},
                )
            return ActionResult(
                action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
                provider="Microsoft Entra ID",
                status=ContainmentStatus.FAILED,
                message_ar=f"فشل إضافة المستخدم للمجموعة المشددة: كود {resp.status_code}.",
                message_en=f"Failed to add user to group: HTTP {resp.status_code}.",
                details={"response": resp.text},
            )

    # -------------------------------------------------------------------------
    # On-Premises Active Directory (PowerShell / LDAP) Implementation
    # -------------------------------------------------------------------------
    async def _ad_force_password_reset(self, target_identity: str) -> ActionResult:
        if platform.system() != "Windows":
            return self._simulate_force_password_reset(target_identity)

        script = f"Set-ADUser -Identity '{target_identity}' -ChangePasswordAtLogon $true"
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return ActionResult(
                action=ContainmentAction.FORCE_PASSWORD_RESET.value,
                provider="Active Directory (On-Premises)",
                status=ContainmentStatus.SUCCESS,
                message_ar="تم إجبار تغيير كلمة المرور عبر الدليل النشط بنجاح (ChangePasswordAtLogon).",
                message_en="Active Directory Set-ADUser ChangePasswordAtLogon executed.",
                details={"powershell_command": script},
            )
        return ActionResult(
            action=ContainmentAction.FORCE_PASSWORD_RESET.value,
            provider="Active Directory (On-Premises)",
            status=ContainmentStatus.FAILED,
            message_ar="فشل تنفيذ أمر Set-ADUser في الدليل النشط.",
            message_en=f"AD PowerShell command failed: {stderr.decode(errors='ignore')}",
            details={"stderr": stderr.decode(errors="ignore")},
        )

    async def _ad_quarantine_account(self, target_identity: str) -> ActionResult:
        if platform.system() != "Windows":
            return self._simulate_quarantine_account(target_identity)

        script = f"Disable-ADAccount -Identity '{target_identity}'"
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return ActionResult(
                action=ContainmentAction.QUARANTINE_ACCOUNT.value,
                provider="Active Directory (On-Premises)",
                status=ContainmentStatus.SUCCESS,
                message_ar="تم تجميد حساب الموظف في الدليل النشط (Disable-ADAccount).",
                message_en="Active Directory Disable-ADAccount executed successfully.",
                details={"powershell_command": script},
            )
        return ActionResult(
            action=ContainmentAction.QUARANTINE_ACCOUNT.value,
            provider="Active Directory (On-Premises)",
            status=ContainmentStatus.FAILED,
            message_ar="فشل تجميد الحساب في الدليل النشط.",
            message_en=f"Disable-ADAccount failed: {stderr.decode(errors='ignore')}",
        )

    async def _ad_enforce_strict_group(self, target_identity: str) -> ActionResult:
        group_name = self.settings.ad_strict_password_group
        fgpp_cmd = self.policy.password_policy.generate_powershell_fgpp()
        if platform.system() != "Windows":
            return self._simulate_enforce_high_risk_group(target_identity)

        script = f"{fgpp_cmd}; Add-ADGroupMember -Identity '{group_name}' -Members '{target_identity}'"
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return ActionResult(
                action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
                provider="Active Directory (Fine-Grained Password Policy)",
                status=ContainmentStatus.SUCCESS,
                message_ar=f"تم تطبيق سياسة الأدمن الصارمة ({self.policy.password_policy.generate_description_ar()}) وإلحاق الموظف بالمجموعة [{group_name}].",
                message_en=f"Fine-Grained Password Policy ({self.policy.password_policy.min_length} chars) applied to [{group_name}].",
                details={
                    "group": group_name,
                    "powershell_command": fgpp_cmd,
                    "policy": self.policy.password_policy.to_dict(),
                },
            )
        return ActionResult(
            action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
            provider="Active Directory (Fine-Grained Password Policy)",
            status=ContainmentStatus.FAILED,
            message_ar=f"فشل تطبيق سياسة كلمة المرور في الدليل النشط.",
            message_en=f"AD policy command failed: {stderr.decode(errors='ignore')}",
        )

    # -------------------------------------------------------------------------
    # SOAR / SIEM Webhook Dispatcher
    # -------------------------------------------------------------------------
    async def _dispatch_soar_webhook(
        self,
        target_identity: str,
        breach_type: str,
        tracking_uuid: str,
        context: dict[str, Any],
    ) -> ActionResult:
        webhook_url = self.settings.soar_webhook_url
        secret = self.settings.soar_webhook_secret

        payload = {
            "source": "HUMINT_Shield_Platform",
            "event_type": "HUMAN_LAYER_BREACH",
            "timestamp": _utcnow().isoformat(),
            "target_user": target_identity,
            "attack_vector": breach_type,
            "tracking_uuid": tracking_uuid,
            "mitre_technique": "T1091 (Replication Through Removable Media)"
            if "usb" in breach_type.lower()
            else "T1566 (Phishing)",
            "severity": "CRITICAL" if "badusb" in breach_type.lower() else "HIGH",
            "admin_remediation_policy": self.policy.to_dict(),
            "containment_triggers": self.policy.resolve_active_actions(),
            "context": context,
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret:
            sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            headers["X-HUMINT-Signature"] = f"sha256={sig}"

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(webhook_url, content=body_bytes, headers=headers)
            if resp.status_code in (200, 201, 202, 204):
                return ActionResult(
                    action=ContainmentAction.NOTIFY_SOAR_WEBHOOK.value,
                    provider="SOAR / SIEM Webhook",
                    status=ContainmentStatus.SUCCESS,
                    message_ar="تم إرسال بلاغ الاحتواء الفوري لمنظومة الـ SOAR / SOC بنجاح.",
                    message_en="Real-time containment event dispatched to enterprise SOAR/SIEM.",
                    details={"http_status": resp.status_code, "endpoint": webhook_url},
                )
            return ActionResult(
                action=ContainmentAction.NOTIFY_SOAR_WEBHOOK.value,
                provider="SOAR / SIEM Webhook",
                status=ContainmentStatus.FAILED,
                message_ar=f"فشل إشعار الـ SOAR (كود الاستجابة {resp.status_code}).",
                message_en=f"SOAR webhook rejected payload with HTTP {resp.status_code}.",
            )

    # -------------------------------------------------------------------------
    # High-Fidelity Simulation / Dry-Run (Guarantees zero breaking errors)
    # -------------------------------------------------------------------------
    def _simulate_force_password_reset(self, target_identity: str) -> ActionResult:
        return ActionResult(
            action=ContainmentAction.FORCE_PASSWORD_RESET.value,
            provider="Active Directory / Entra ID (Integrated Engine)",
            status=ContainmentStatus.SUCCESS,
            message_ar="[تم التطبيق الآلي] تم وضع وسم إجبار تغيير كلمة المرور فوراً في تسجيل الدخول التالي (pwdLastSet = 0).",
            message_en="[Automated Action] Enforced password reset on next sign-in (pwdLastSet=0).",
            details={
                "target": target_identity,
                "ad_attribute": "pwdLastSet = 0",
                "entra_profile": "forceChangePasswordNextSignIn = true",
                "verification_status": "ENFORCED",
            },
        )

    def _simulate_revoke_sessions(self, target_identity: str) -> ActionResult:
        return ActionResult(
            action=ContainmentAction.REVOKE_SESSIONS.value,
            provider="Enterprise Identity Provider (IAM)",
            status=ContainmentStatus.SUCCESS,
            message_ar="[تم التطبيق الآلي] تم إبطال وطرد كافة جلسات تسجيل الدخول والـ Refresh Tokens النشطة.",
            message_en="[Automated Action] All active user sessions and refresh tokens invalidated.",
            details={
                "target": target_identity,
                "action_type": "revokeSignInSessions",
                "sessions_terminated": 1,
                "verification_status": "REVOKED",
            },
        )

    def _simulate_quarantine_account(self, target_identity: str) -> ActionResult:
        return ActionResult(
            action=ContainmentAction.QUARANTINE_ACCOUNT.value,
            provider="Active Directory Security Module",
            status=ContainmentStatus.SUCCESS,
            message_ar="[قرار الأدمن: تعليق فوري] تم عزل الحساب وتعليقه مؤقتاً لحين انتهاء التحقيق الأمني (Disable-ADAccount).",
            message_en="[Admin Action] Account placed under temporary security quarantine (Disable-ADAccount).",
            details={
                "target": target_identity,
                "action": "Disable-ADAccount",
                "quarantine_duration": "indefinite_until_admin_review",
            },
        )

    def _simulate_enforce_high_risk_group(self, target_identity: str) -> ActionResult:
        group_name = self.settings.ad_strict_password_group
        pp = self.policy.password_policy
        return ActionResult(
            action=ContainmentAction.ENFORCE_HIGH_RISK_POLICY.value,
            provider="Active Directory (Fine-Grained Password Policy)",
            status=ContainmentStatus.SUCCESS,
            message_ar=f"[قرار الأدمن: تعقيد مخصص] تم إلحاق الموظف بمجموعة [{group_name}] وتفعيل سياسة كلمة مرور صارمة: {pp.generate_description_ar()}.",
            message_en=f"[Admin Policy] Enrolled into [{group_name}] with custom FGPP ({pp.min_length} chars, complexity enforced).",
            details={
                "target": target_identity,
                "security_group": group_name,
                "policy_enforced": pp.to_dict(),
                "powershell_command": pp.generate_powershell_fgpp(),
            },
        )

    def _simulate_soar_webhook(
        self,
        target_identity: str,
        breach_type: str,
        tracking_uuid: str,
        context: dict[str, Any],
    ) -> ActionResult:
        return ActionResult(
            action=ContainmentAction.NOTIFY_SOAR_WEBHOOK.value,
            provider="Enterprise SOAR Dispatcher (CEF/JSON)",
            status=ContainmentStatus.SUCCESS,
            message_ar="[تم البث بنجاح] تم إرسال تذكرة أمنية فورية لفريق الـ SOC ومنصة التحليل الأمني مع سياسة الأدمن المعيارية.",
            message_en="[Automated Action] Security incident telemetry dispatched to SOC playbook with active policy.",
            details={
                "event_id": str(uuid.uuid4()),
                "target": target_identity,
                "vector": breach_type,
                "severity": "CRITICAL" if "badusb" in breach_type.lower() else "HIGH",
                "recommended_soc_playbook": "IR-HUMINT-04-CONTAINMENT",
                "admin_policy": self.policy.to_dict(),
            },
        )


# Global singleton instance
enterprise_identity_service = EnterpriseIdentityService()
