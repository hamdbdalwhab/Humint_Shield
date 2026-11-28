"""Recipient-facing forensic evidence for one simulation interaction.

The training experience has to *prove* the risk, not describe it.  This module
builds the evidence report the recipient sees after falling for a simulation:
exactly which values they typed (masked), the device and network the request
came from, how fast they acted, and the measurable impact on their own score
and on their department.

Only the recipient's own interaction is returned and the tracking UUID is the
bearer secret, exactly like ``/track/context``.  Passwords are never returned:
only their length and a strength label.  Identifiers are masked so the page can
show "this is what someone now holds about you" without printing the value
verbatim.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    TrainingInteraction,
)
from app.services.attack_chain import build_compromised_assets
from app.services.elo_engine import (
    QR_CREDENTIAL_ELO_DELTA,
    SMS_CREDENTIAL_ELO_DELTA,
    USB_OPEN_ELO_DELTA,
    VISHING_CREDENTIAL_ELO_DELTA,
    threat_label,
    threat_level_for_elo,
)

#: Elo penalty applied when a recipient hands over credentials, per channel.
_CHANNEL_PENALTY: dict[str, int] = {
    "sms": SMS_CREDENTIAL_ELO_DELTA,
    "qr": QR_CREDENTIAL_ELO_DELTA,
    "vishing": VISHING_CREDENTIAL_ELO_DELTA,
    "pretexting": VISHING_CREDENTIAL_ELO_DELTA,
    "usb": USB_OPEN_ELO_DELTA,
}

#: What a real attacker does with the captured material, per channel.
_NEXT_STEPS: dict[str, list[str]] = {
    "sms": [
        "تسجيل الدخول إلى بريد العمل من شبكة بعيدة دون أي تنبيه فوري",
        "إعادة تعيين كلمة مرور الأنظمة المرتبطة بالحساب نفسه",
        "إرسال رسائل تصيّد لزملائك من حسابك الموثوق",
        "طلب تحويل مالي أو بيانات عملاء باسمك",
    ],
    "qr": [
        "استخدام الجلسة المفتوحة للوصول إلى ملفات الموارد البشرية",
        "تصدير بيانات الموظفين والرواتب",
        "تثبيت جلسة دائمة على الجهاز للعودة لاحقًا",
    ],
    "vishing": [
        "استخدام رمز التحقق لتجاوز المصادقة الثنائية",
        "إعادة تعيين كلمة المرور قبل انتهاء صلاحية الرمز",
        "التواصل مع فريق الدعم باسمك لتوسيع الوصول",
    ],
    "usb": [
        "التحكم في جهاز العمل عن بعد",
        "نسخ ملفات العمل وبيانات الدخول المحفوظة",
        "التحرك داخل الشبكة الداخلية للشركة",
    ],
}
_DEFAULT_NEXT_STEPS = _NEXT_STEPS["sms"]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _aware(value: datetime | None) -> datetime | None:
    """Return a timezone-aware datetime for a possibly naive value."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def mask_identifier(value: str | None) -> str | None:
    """Mask an email, phone or username while keeping it recognisable.

    Args:
        value: The raw value the recipient typed.

    Returns:
        A masked rendering (``ha****@gmail.com``, ``+96*****78``) or ``None``.
    """
    text = (value or "").strip()
    if not text:
        return None
    if _EMAIL_RE.match(text):
        local, _, domain = text.partition("@")
        keep = local[:2]
        return f"{keep}{'*' * max(3, len(local) - 2)}@{domain}"
    digits = re.sub(r"\D", "", text)
    if digits and len(digits) >= len(text) - 2:
        return f"{text[:3]}{'*' * max(3, len(text) - 5)}{text[-2:]}"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def password_strength(length: int | None) -> str | None:
    """Return an Arabic strength label for a typed password length.

    Args:
        length: Number of characters submitted (never the value itself).

    Returns:
        ``ضعيفة جدًا``/``ضعيفة``/``متوسطة``/``قوية``, or ``None`` when no
        password was typed.
    """
    if not length or length <= 0:
        return None
    if length < 8:
        return "ضعيفة جدًا"
    if length < 10:
        return "ضعيفة"
    if length < 14:
        return "متوسطة"
    return "قوية"


def describe_user_agent(user_agent: str | None) -> dict[str, str | None]:
    """Summarise a User-Agent into browser, OS and device labels.

    Args:
        user_agent: Raw User-Agent header stored on the interaction.

    Returns:
        ``{"browser": ..., "os": ..., "device": ...}`` with ``None`` for the
        parts that cannot be identified.
    """
    raw = (user_agent or "").strip()
    if not raw:
        return {"browser": None, "os": None, "device": None}
    lowered = raw.lower()
    browser: str | None = None
    for token, label in (
        ("edg/", "Microsoft Edge"),
        ("opr/", "Opera"),
        ("chrome/crios", "Chrome (iOS)"),
        ("chrome/", "Google Chrome"),
        ("firefox/", "Firefox"),
        ("safari/", "Safari"),
    ):
        if token in lowered:
            browser = label
            break
    os_label: str | None = None
    for token, label in (
        ("android", "Android"),
        ("iphone", "iOS"),
        ("ipad", "iPadOS"),
        ("windows", "Windows"),
        ("mac os x", "macOS"),
        ("linux", "Linux"),
    ):
        if token in lowered:
            os_label = label
            break
    device = "هاتف محمول" if ("mobile" in lowered or "android" in lowered or "iphone" in lowered) else "حاسوب"
    return {"browser": browser, "os": os_label, "device": device}


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    """Return ``end - start`` in whole seconds."""
    start_aware, end_aware = _aware(start), _aware(end)
    if start_aware is None or end_aware is None:
        return None
    delta = (end_aware - start_aware).total_seconds()
    return round(delta, 1) if delta >= 0 else None


async def build_evidence(
    db: AsyncSession, tracking_uuid: str | uuid.UUID
) -> dict[str, Any]:
    """Build the evidence report for one tracking row.

    Args:
        db: Active session.
        tracking_uuid: The recipient's tracking UUID (bearer secret).

    Returns:
        A JSON-serialisable report, or ``{"found": False}`` for an unknown or
        malformed identifier.
    """
    try:
        uid = uuid.UUID(str(tracking_uuid))
    except (TypeError, ValueError):
        return {"found": False}

    row = (
        await db.execute(
            select(EmailTracking, HumanAsset, EmailCampaign, EmailTemplate)
            .outerjoin(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
            .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
            .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
            .where(EmailTracking.tracking_uuid == uid)
        )
    ).first()
    if row is None:
        return {"found": False}
    tracking, employee, campaign, template = row

    channel = (tracking.channel or "email").strip().lower()
    # The newest ledger row carries the observation (IP / device / payload).
    ledger = (
        await db.execute(
            select(TrainingInteraction)
            .where(TrainingInteraction.tracking_id == tracking.id)
            .order_by(TrainingInteraction.occurred_at.desc())
            .limit(1)
        )
    ).scalars().first()

    user_agent = (ledger.user_agent if ledger is not None else None) or tracking.last_user_agent
    ip_address = (ledger.ip_address if ledger is not None else None) or tracking.last_ip_address
    observed_at = _aware(ledger.occurred_at if ledger is not None else tracking.submitted_at)
    device = describe_user_agent(user_agent)

    fields: list[str] = []
    if tracking.submitted_identifier:
        fields.append("اسم المستخدم أو البريد الإلكتروني")
    if tracking.password_length:
        fields.append("كلمة المرور")
    if tracking.otp_submitted:
        fields.append("رمز التحقق لمرة واحدة (OTP)")
    if tracking.submitted_email and not tracking.submitted_identifier:
        fields.append("البريد الإلكتروني")

    # --- Impact: personal score -------------------------------------------------
    penalty = _CHANNEL_PENALTY.get(channel, 0)
    submitted = tracking.submitted_at is not None
    elo_now = int(employee.elo_score) if employee is not None and employee.elo_score is not None else None
    elo_delta = penalty if submitted else 0
    elo_before = (elo_now - elo_delta) if elo_now is not None else None

    # --- Impact: department and organization ------------------------------------
    dept_submitted = dept_targeted = org_submitted = org_targeted = 0
    if employee is not None and employee.department:
        dept_rows = (
            await db.execute(
                select(
                    func.count(EmailTracking.id),
                    func.count(EmailTracking.submitted_at),
                )
                .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .where(
                    EmailTracking.campaign_id == campaign.id,
                    HumanAsset.department == employee.department,
                )
            )
        ).first()
        if dept_rows is not None:
            dept_targeted, dept_submitted = int(dept_rows[0] or 0), int(dept_rows[1] or 0)
    org_rows = (
        await db.execute(
            select(
                func.count(EmailTracking.id),
                func.count(EmailTracking.submitted_at),
            ).where(EmailTracking.campaign_id == campaign.id)
        )
    ).first()
    if org_rows is not None:
        org_targeted, org_submitted = int(org_rows[0] or 0), int(org_rows[1] or 0)

    level = threat_level_for_elo(elo_now) if elo_now is not None else None
    return {
        "found": True,
        "case_id": f"HS-{uid.hex[:10].upper()}",
        "channel": channel,
        "campaign_name": campaign.name,
        "template_name": template.name if template is not None else None,
        "department": (employee.department if employee is not None else None),
        "employee_name": (employee.full_name if employee is not None else None),
        "captured": {
            "submitted": submitted,
            "identifier_masked": mask_identifier(tracking.submitted_identifier),
            "email_masked": mask_identifier(tracking.submitted_email),
            "password_length": tracking.password_length,
            "password_strength": password_strength(tracking.password_length),
            "otp_submitted": bool(tracking.otp_submitted),
            "fields": fields,
            "submitted_at": _aware(tracking.submitted_at),
            "attempts": int(tracking.submission_count or 0),
            "seconds_to_submit": _seconds_between(tracking.clicked_at, tracking.submitted_at),
            "storage_note": "لم تُخزَّن كلمة المرور: النظام يحفظ طولها فقط لإثبات ما كان المهاجم سيملكه.",
        },
        "attacker_view": {
            "ip_address": ip_address,
            "user_agent": user_agent,
            "browser": device["browser"],
            "os": device["os"],
            "device": device["device"],
            "observed_at": observed_at,
            "seconds_since_click": _seconds_between(tracking.clicked_at, observed_at),
        },
        "impact": {
            "elo_before": elo_before,
            "elo_now": elo_now,
            "elo_delta": -abs(elo_delta) if elo_delta else 0,
            "threat_level": level,
            "threat_label": threat_label(elo_now, arabic=True) if elo_now is not None else None,
            "department_submitted": dept_submitted,
            "department_targeted": dept_targeted,
            "org_submitted": org_submitted,
            "org_targeted": org_targeted,
        },
        "exposure": build_compromised_assets(tracking, template, campaign),
        "next_steps": _NEXT_STEPS.get(channel, _DEFAULT_NEXT_STEPS),
    }


__all__ = [
    "build_evidence",
    "describe_user_agent",
    "mask_identifier",
    "password_strength",
]
