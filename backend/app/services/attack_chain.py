"""Derive the assets a simulated attacker 'gained' from a submission.

The function only runs when the tracking row has a real ``submitted_at`` marker.
It never decrypts or returns the secret itself; it uses the non-secret field
metadata (identifier, password length, field names) and the campaign/template
context to produce a short, understandable list for the training reveal.
"""
from __future__ import annotations

from app.models import EmailCampaign, EmailTemplate, EmailTracking

#: Maximum number of assets shown on the reveal page.
MAX_ASSETS = 6


def build_compromised_assets(
    tracking: EmailTracking,
    template: EmailTemplate | None = None,
    campaign: EmailCampaign | None = None,
) -> list[str]:
    """Return a de-duplicated list of simulated compromised assets.

    Args:
        tracking: The per-recipient tracking row.
        template: The template that was delivered, when available.
        campaign: The campaign that delivered it, when available.

    Returns:
        An empty list when nothing was submitted; otherwise Arabic labels for the
        account, password (if one was typed) and the most relevant business
        system inferred from the template/campaign context.
    """
    channel = (tracking.channel or "email").strip().lower()
    if channel == "qr":
        return (
            [
                "بيانات الدخول إلى بوابة الشركة",
                "الوصول إلى ملفات الموارد البشرية",
                "جلسة دخول دائمة على جهازك",
            ]
            if (tracking.clicked_at or tracking.reported_at or tracking.submitted_at)
            else []
        )
    if channel == "usb":
        return (
            [
                "التحكم الكامل في جهاز العمل",
                "ملفات العمل المخزنة على القرص",
                "بيانات الدخول المحفوظة في المتصفح",
                "جلسة الشبكة الداخلية للشركة",
            ]
            if (tracking.clicked_at or tracking.reported_at or tracking.submitted_at)
            else []
        )
    if channel == "vishing":
        return (
            [
                "رمز التحقق لمرة واحدة (OTP)",
                "الوصول إلى حساب الدعم الفني",
                "محاولة إعادة تعيين كلمة المرور",
            ]
            if (tracking.clicked_at or tracking.reported_at or tracking.submitted_at)
            else []
        )
    if channel == "pretexting":
        return (
            [
                "أموال الشركة عبر بطاقات الهدايا",
                "أكواد البطاقات — نقد فوري للمهاجم",
                "ثقة العلاقة مع الإدارة التنفيذية",
            ]
            if (tracking.clicked_at or tracking.reported_at or tracking.submitted_at)
            else []
        )

    if tracking.submitted_at is None:
        return []

    assets: list[str] = []
    fields = tracking.submitted_fields or {}

    if tracking.submitted_identifier:
        assets.append("بيانات حساب بريدك الإلكتروني")
    if (tracking.password_length or 0) > 0 or any(
        "password" in str(key).lower() for key in fields
    ):
        assets.append("كلمة مرور بريدك الإلكتروني")

    haystack = " ".join(
        part
        for part in (
            template.name if template is not None else "",
            template.subject if template is not None else "",
            campaign.name if campaign is not None else "",
        )
        if part
    ).lower()

    if any(
        token in haystack
        for token in ("hr", "human resources", "employee records", "payroll", "موارد بشرية", "رواتب")
    ):
        assets.append("الوصول إلى ملفات الموارد البشرية")
    elif any(
        token in haystack
        for token in ("finance", "invoice", "billing", "payment", "مالية", "فواتير", "مدفوعات")
    ):
        assets.append("الوصول إلى نظام الفواتير والبيانات المالية")
    elif any(
        token in haystack
        for token in ("ceo", "executive", "board", "الإدارة التنفيذية", "مجلس الإدارة")
    ):
        assets.append("الوصول إلى بريد الإدارة التنفيذية")
    elif any(
        token in haystack
        for token in ("drive", "document", "shared files", "ملفات", "مستندات")
    ):
        assets.append("الوصول إلى الملفات المشتركة")
    elif any(token in haystack for token in ("vpn", "network", "شبكة", "اتصال آمن")):
        assets.append("الوصول إلى شبكة الشركة عبر VPN")
    else:
        assets.append("الوصول إلى الأنظمة الداخلية المتاحة من حسابك")

    if any(str(key).lower() in {"remember", "remember_me"} for key in fields):
        assets.append("جلسة دخول دائمة (تذكرني)")
    if any(str(key).lower() in {"department", "office", "location"} for key in fields):
        assets.append("بيانات القسم ومكان العمل")

    deduped: list[str] = []
    for asset in assets:
        if asset not in deduped:
            deduped.append(asset)
    return deduped[:MAX_ASSETS]


__all__ = ["MAX_ASSETS", "build_compromised_assets"]
