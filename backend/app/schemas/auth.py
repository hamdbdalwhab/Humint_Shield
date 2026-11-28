"""Pydantic v2 schemas: authentication."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.permissions import effective_permissions, normalize_permissions
from app.schemas.password_policy import (
    MAX_LENGTH as PASSWORD_MAX_LENGTH,
    MIN_LENGTH as PASSWORD_MIN_LENGTH,
    validate_password,
)
from app.schemas.sanitization import sanitize_plain_text


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    """Refresh token submitted to ``POST /auth/refresh``."""

    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    """Body for ``POST /auth/change-password``.

    The new password is validated against the shared policy in
    :mod:`app.schemas.password_policy` before the endpoint runs, so an invalid
    value is rejected with a specific 422 error.
    """

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        """Enforce the shared password policy."""
        return validate_password(value)


class UserPublic(BaseModel):
    """Public representation of a user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    role: str
    organization_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime
    #: Explicit per-account grants stored on the record.
    permissions: list[str] = Field(default_factory=list)
    #: Role preset ∪ grants — what the UI should use for every gate.
    effective_permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions", mode="before")
    @classmethod
    def _coerce_permissions(cls, value: object) -> list[str]:
        """Treat a NULL column as "no extra grants"."""
        return normalize_permissions(value if isinstance(value, list) else [])

    @model_validator(mode="after")
    def _resolve_permissions(self) -> "UserPublic":
        """Normalise the stored grants and derive the effective set."""
        grants = normalize_permissions(self.permissions)
        self.permissions = grants
        self.effective_permissions = effective_permissions(self.role, grants)
        return self


class TokenResponse(BaseModel):
    """Access/refresh token pair plus the authenticated user."""

    access: str
    refresh: str
    token_type: str = "bearer"
    user: UserPublic


class AccessTokenResponse(BaseModel):
    """A freshly minted access token."""

    access: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    """Create an operator account (admin only)."""

    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    role: str = Field(default="admin", pattern="^(admin|manager|viewer)$")
    organization_id: uuid.UUID | None = None

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        """Strip markup and reject active content in the account name."""
        cleaned = sanitize_plain_text(value, "username") or ""
        if len(cleaned) < 3:
            raise ValueError("username must be at least 3 characters long")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        """Enforce the shared password policy."""
        return validate_password(value)
