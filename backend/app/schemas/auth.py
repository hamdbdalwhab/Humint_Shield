"""Pydantic v2 schemas: authentication."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    """Refresh token submitted to ``POST /auth/refresh``."""

    refresh_token: str = Field(min_length=1)


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
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="admin", pattern="^(admin|manager|viewer)$")
    organization_id: uuid.UUID | None = None
