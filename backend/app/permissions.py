"""Granular permission catalog and role presets.

The platform authorises every operator action with an explicit permission key
rather than a coarse role check.  A user's *effective* permissions are the
union of the role preset and the per-account grants stored in
``users.permissions``.  Unknown keys are ignored so a stale grant can never
grant access that no longer exists.

The catalog is deliberately declarative: the API exposes it to the settings UI
so the permission matrix is never duplicated (and therefore never drifts) in
the frontend.
"""
from __future__ import annotations

from collections.abc import Iterable

#: Every permission the platform understands, with its bilingual label.
PERMISSIONS: dict[str, dict[str, str]] = {
    # Human assets
    "employees.view": {"ar": "عرض الموظفين", "en": "View human assets"},
    "employees.manage": {"ar": "إنشاء وتعديل الموظفين", "en": "Create and edit human assets"},
    "employees.delete": {"ar": "حذف الموظفين", "en": "Delete human assets"},
    # Templates
    "templates.view": {"ar": "عرض القوالب", "en": "View templates"},
    "templates.manage": {"ar": "إنشاء وتعديل القوالب", "en": "Manage templates"},
    # Campaigns
    "campaigns.view": {"ar": "عرض الحملات", "en": "View campaigns"},
    "campaigns.manage": {"ar": "إنشاء وتعديل الحملات", "en": "Manage campaigns"},
    "campaigns.launch": {"ar": "إطلاق الحملات", "en": "Launch campaigns"},
    "campaigns.delete": {"ar": "حذف الحملات", "en": "Delete campaigns"},
    # Reports
    "reports.view": {"ar": "عرض التقارير", "en": "View reports"},
    "reports.export": {"ar": "تصدير التقارير", "en": "Export reports"},
    # Awareness / LMS
    "lms.view": {"ar": "عرض التدريب", "en": "View awareness content"},
    "lms.manage": {"ar": "إدارة التدريب", "en": "Manage awareness content"},
    # Report inbox
    "inbox.view": {"ar": "عرض البلاغات", "en": "View the report inbox"},
    "inbox.manage": {"ar": "فرز البلاغات", "en": "Triage reported phishing"},
    # Containment / SOC
    "containment.view": {"ar": "عرض الاحتواء", "en": "View containment policy"},
    "containment.execute": {"ar": "تنفيذ الاحتواء", "en": "Execute containment"},
    # Organization settings
    "settings.view": {"ar": "عرض الإعدادات", "en": "View settings"},
    "settings.branding": {"ar": "تعديل الهوية البصرية", "en": "Edit branding"},
    "settings.guardrails": {"ar": "تعديل ضوابط الحملات", "en": "Edit campaign guardrails"},
    "settings.diagnostics": {"ar": "التشخيص والاتصال", "en": "Run diagnostics"},
    # Operator administration
    "users.view": {"ar": "عرض المستخدمين", "en": "View operator accounts"},
    "users.manage": {"ar": "إدارة المستخدمين", "en": "Manage operator accounts and permissions"},
    # Audit trail
    "audit.view": {"ar": "عرض سجل التدقيق", "en": "View the audit trail"},
}

#: Ordered groups for the permission matrix in the UI.
PERMISSION_GROUPS: list[dict] = [
    {
        "key": "employees",
        "ar": "الموظفون",
        "en": "Human assets",
        "permissions": ["employees.view", "employees.manage", "employees.delete"],
    },
    {
        "key": "templates",
        "ar": "القوالب",
        "en": "Templates",
        "permissions": ["templates.view", "templates.manage"],
    },
    {
        "key": "campaigns",
        "ar": "الحملات",
        "en": "Campaigns",
        "permissions": [
            "campaigns.view",
            "campaigns.manage",
            "campaigns.launch",
            "campaigns.delete",
        ],
    },
    {
        "key": "reports",
        "ar": "التقارير",
        "en": "Reports",
        "permissions": ["reports.view", "reports.export"],
    },
    {
        "key": "awareness",
        "ar": "التوعية والتدريب",
        "en": "Awareness",
        "permissions": ["lms.view", "lms.manage"],
    },
    {
        "key": "inbox",
        "ar": "صندوق البلاغات",
        "en": "Report inbox",
        "permissions": ["inbox.view", "inbox.manage"],
    },
    {
        "key": "containment",
        "ar": "الاحتواء الاستباقي",
        "en": "Containment",
        "permissions": ["containment.view", "containment.execute"],
    },
    {
        "key": "settings",
        "ar": "الإعدادات",
        "en": "Settings",
        "permissions": [
            "settings.view",
            "settings.branding",
            "settings.guardrails",
            "settings.diagnostics",
        ],
    },
    {
        "key": "administration",
        "ar": "إدارة المنصة",
        "en": "Administration",
        "permissions": ["users.view", "users.manage", "audit.view"],
    },
]

ALL_PERMISSIONS: frozenset[str] = frozenset(PERMISSIONS)

#: Role presets.  ``custom`` intentionally starts empty: a custom account holds
#: exactly what an administrator grants it (least privilege by construction).
ROLE_PRESETS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "manager": frozenset(
        {
            "employees.view",
            "employees.manage",
            "templates.view",
            "templates.manage",
            "campaigns.view",
            "campaigns.manage",
            "campaigns.launch",
            "reports.view",
            "reports.export",
            "lms.view",
            "lms.manage",
            "inbox.view",
            "inbox.manage",
            "containment.view",
            "containment.execute",
            "settings.view",
            "settings.branding",
            "settings.guardrails",
            "settings.diagnostics",
            "users.view",
        }
    ),
    "viewer": frozenset(
        {
            "employees.view",
            "templates.view",
            "campaigns.view",
            "reports.view",
            "lms.view",
            "inbox.view",
            "containment.view",
            "settings.view",
        }
    ),
    "custom": frozenset(),
}

ROLE_LABELS: dict[str, dict[str, str]] = {
    "admin": {"ar": "مدير النظام", "en": "Administrator"},
    "manager": {"ar": "مسؤول أمني", "en": "Security manager"},
    "viewer": {"ar": "مُشاهد (قراءة فقط)", "en": "Read-only viewer"},
    "custom": {"ar": "مخصّص", "en": "Custom"},
}

ROLES: tuple[str, ...] = tuple(ROLE_PRESETS)


def normalize_permissions(values: Iterable[str] | None) -> list[str]:
    """Return the known permission keys from ``values``, deduplicated and sorted.

    Args:
        values: Raw grants (may contain ``None`` entries or unknown keys).

    Returns:
        A stable, catalog-ordered list of valid permission keys.
    """
    if not values:
        return []
    wanted = {str(value).strip() for value in values if value}
    return [key for key in PERMISSIONS if key in wanted]


def effective_permissions(role: str | None, grants: Iterable[str] | None = None) -> list[str]:
    """Resolve the permissions an account actually holds.

    Args:
        role: The account's role (``admin``, ``manager``, ``viewer``, ``custom``).
        grants: Explicit per-account grants.

    Returns:
        The union of the role preset and the grants, catalog-ordered.
    """
    normalized_role = (role or "viewer").strip().lower()
    allowed = set(ROLE_PRESETS.get(normalized_role, frozenset()))
    allowed.update(normalize_permissions(grants))
    return [key for key in PERMISSIONS if key in allowed]


def role_default_permissions(role: str | None) -> list[str]:
    """Return the preset permissions of ``role``."""
    preset = ROLE_PRESETS.get((role or "").strip().lower(), frozenset())
    return [key for key in PERMISSIONS if key in preset]


def permission_catalog() -> dict:
    """Build the machine-readable catalog consumed by the settings UI."""
    return {
        "roles": [
            {
                "key": role,
                "label_ar": ROLE_LABELS[role]["ar"],
                "label_en": ROLE_LABELS[role]["en"],
                "default_permissions": role_default_permissions(role),
            }
            for role in ROLES
        ],
        "groups": [
            {
                "key": group["key"],
                "label_ar": group["ar"],
                "label_en": group["en"],
                "permissions": [
                    {
                        "key": key,
                        "label_ar": PERMISSIONS[key]["ar"],
                        "label_en": PERMISSIONS[key]["en"],
                    }
                    for key in group["permissions"]
                ],
            }
            for group in PERMISSION_GROUPS
        ],
        "total_permissions": len(PERMISSIONS),
    }


__all__ = [
    "ALL_PERMISSIONS",
    "PERMISSIONS",
    "PERMISSION_GROUPS",
    "ROLES",
    "ROLE_LABELS",
    "ROLE_PRESETS",
    "effective_permissions",
    "normalize_permissions",
    "permission_catalog",
    "role_default_permissions",
]
