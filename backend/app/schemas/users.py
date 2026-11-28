"""Pydantic schemas for operator administration.

Kept separate from :mod:`app.schemas.auth` so the public login payload stays
small while the administration surface can expose grants, effective
permissions and account state.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.permissions import ALL_PERMISSIONS, ROLES, normalize_permissions
from app.schemas.auth import UserPublic
from app.schemas.password_policy import MAX_LENGTH, MIN_LENGTH, validate_password
from app.schemas.sanitization import sanitize_plain_text


def _clean_permissions(values: list[str] | None) -> list[str]:
    """Reject unknown permission keys instead of silently dropping them."""
    unknown = sorted({value for value in (values or []) if value not in ALL_PERMISSIONS})
    if unknown:
        raise ValueError(f"unknown permission(s): {', '.join(unknown)}")
    return normalize_permissions(values)


class UserAdminPublic(UserPublic):
    """An operator account as seen by an administrator."""

    permissions: list[str] = Field(default_factory=list)
    effective_permissions: list[str] = Field(default_factory=list)
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None


class UserCreateRequest(BaseModel):
    """Body for ``POST /users``.

    ``permissions`` are *additional* grants on top of the role preset; a
    ``custom`` account starts with exactly these grants.
    """

    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    role: str = Field(default="viewer")
    permissions: list[str] = Field(default_factory=list, max_length=64)
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in ROLES:
            raise ValueError(f"role must be one of: {', '.join(ROLES)}")
        return cleaned

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        cleaned = sanitize_plain_text(value, "username") or ""
        if len(cleaned) < 3:
            raise ValueError("username must be at least 3 characters long")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("permissions")
    @classmethod
    def _permissions(cls, value: list[str]) -> list[str]:
        return _clean_permissions(value)


class UserUpdateRequest(BaseModel):
    """Body for ``PATCH /users/{id}``; every field is optional."""

    email: EmailStr | None = None
    role: str | None = None
    permissions: list[str] | None = Field(default=None, max_length=64)
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned not in ROLES:
            raise ValueError(f"role must be one of: {', '.join(ROLES)}")
        return cleaned

    @field_validator("permissions")
    @classmethod
    def _permissions(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_permissions(value)


class AdminPasswordResetRequest(BaseModel):
    """Body for ``POST /users/{id}/reset-password``."""

    new_password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password(value)


class PermissionItem(BaseModel):
    """One permission in the catalog."""

    key: str
    label_ar: str
    label_en: str


class PermissionGroup(BaseModel):
    """A themed group of permissions."""

    key: str
    label_ar: str
    label_en: str
    permissions: list[PermissionItem]


class RolePreset(BaseModel):
    """A role and the permissions it grants by default."""

    key: str
    label_ar: str
    label_en: str
    default_permissions: list[str]


class PermissionCatalog(BaseModel):
    """The complete, frontend-consumable permission catalog."""

    roles: list[RolePreset]
    groups: list[PermissionGroup]
    total_permissions: int


__all__ = [
    "AdminPasswordResetRequest",
    "PermissionCatalog",
    "PermissionGroup",
    "PermissionItem",
    "RolePreset",
    "UserAdminPublic",
    "UserCreateRequest",
    "UserUpdateRequest",
]
