"""Authentication endpoints."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import auth_rate_limit, get_current_user, get_token_claims
from app.logging_config import get_logger
from app.schemas.password_policy import password_strength_error
from app.services.audit_service import revoke_token
from app.models import User
from app.schemas import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserPublic,
)
from app.security import (
    TokenError,
    claim_version,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: Lock the account after this many consecutive failed sign-ins.
MAX_FAILED_LOGIN_ATTEMPTS = 5
#: Lock duration, in minutes (OWASP: temporary, not permanent, lockout).
LOCKOUT_MINUTES = 15


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Return a throwaway bcrypt hash used to equalise login timing.

    Verifying against a real hash even when the username does not exist keeps
    the response time for unknown and known accounts indistinguishable, so the
    login endpoint cannot be used to enumerate valid usernames.
    """
    return hash_password("timing-equaliser-value-not-a-password")


def _password_strength_error(password: str) -> str | None:
    """Return the first unmet password rule, or ``None`` when compliant."""
    return password_strength_error(password)


def _aware(value: datetime | None) -> datetime | None:
    """Treat a naive ``locked_until`` (SQLite) as UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(auth_rate_limit())],
    summary="Exchange credentials for an access/refresh token pair",
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Authenticate a user and return tokens.

    Args:
        payload: Username and password.
        db: Active session.

    Returns:
        Access token, refresh token and the public user record.

    Raises:
        HTTPException: 401 when the credentials are invalid.
    """
    username = payload.username.strip()
    user = await db.scalar(select(User).where(User.username == username))
    now = datetime.now(timezone.utc)

    # --- account lockout ------------------------------------------------- #
    locked_until = _aware(user.locked_until) if user is not None else None
    if user is not None and locked_until is not None:
        if locked_until > now:
            remaining = max(1, math.ceil((locked_until - now).total_seconds() / 60))
            logger.warning("login_blocked_locked", username=username)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=(
                    "Account locked after repeated failed sign-ins. "
                    f"Try again in {remaining} minute(s)."
                ),
                headers={"Retry-After": str(remaining * 60)},
            )
        # The lockout expired: start a fresh budget.
        user.locked_until = None
        user.failed_login_attempts = 0

    # Always run bcrypt once so the timing of a failed login does not reveal
    # whether the account exists.
    password_ok = verify_password(
        payload.password,
        user.password_hash if user is not None else _dummy_password_hash(),
    )
    if user is None or not password_ok:
        if user is not None:
            attempts = int(user.failed_login_attempts or 0) + 1
            user.failed_login_attempts = attempts
            if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                logger.warning(
                    "account_locked",
                    username=user.username,
                    attempts=attempts,
                    minutes=LOCKOUT_MINUTES,
                )
            db.add(user)
            await db.commit()
        logger.warning("login_failed", username=username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    # Successful sign-in clears the failure counter and records the timestamp
    # shown in operator administration.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.add(user)
    await db.commit()
    await db.refresh(user)

    subject = str(user.id)
    extra = {"role": user.role, "org": str(user.organization_id) if user.organization_id else None}
    logger.info("login_succeeded", username=user.username, role=user.role)
    version = int(user.token_version or 0)
    return TokenResponse(
        access=create_access_token(subject, extra, version),
        refresh=create_refresh_token(subject, extra, version),
        user=UserPublic.model_validate(user),
    )


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    dependencies=[Depends(auth_rate_limit())],
    summary="Exchange a refresh token for a new access token",
)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    """Issue a new access token from a valid refresh token.

    Args:
        payload: The refresh token.
        db: Active session.

    Returns:
        A new access token.

    Raises:
        HTTPException: 401 when the refresh token is invalid or the user is gone.
    """
    try:
        claims = decode_token(payload.refresh_token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    import uuid as _uuid

    try:
        user_id = _uuid.UUID(str(claims.get("sub")))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable")
    if claim_version(claims) != int(user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token was revoked"
        )

    extra = {"role": user.role, "org": str(user.organization_id) if user.organization_id else None}
    return AccessTokenResponse(
        access=create_access_token(str(user.id), extra, int(user.token_version or 0))
    )


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Invalidate the current session")
async def logout(
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_token_claims),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Revoke every token issued to the account.

    JWT access tokens are stateless, so logging out increments the account's
    ``token_version``: the current access token, any refresh token and every
    token held by another device stop validating immediately.

    Args:
        user: Authenticated user.
        db: Active session.

    Returns:
        ``{"success": True}``.
    """
    user.token_version = int(user.token_version or 0) + 1
    db.add(user)
    await revoke_token(db, user=user, jti=claims.get("jti"), reason="LOGOUT")
    await db.commit()
    logger.info("logout", username=user.username)
    return {"success": True}


@router.post(
    "/change-password",
    response_model=TokenResponse,
    dependencies=[Depends(auth_rate_limit())],
    summary="Change the signed-in user's password and rotate their sessions",
)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_token_claims),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Change the caller's own password.

    The old password is required, the new one must satisfy the minimum policy
    and differ from the current one, and every previously issued token is
    revoked: the response carries a fresh pair so this client stays signed in.

    Raises:
        HTTPException: 400 for a weak/reused password, 401 when the current
            password is wrong.
    """
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must differ from the current one",
        )
    problem = _password_strength_error(payload.new_password)
    if problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)

    user.password_hash = hash_password(payload.new_password)
    user.token_version = int(user.token_version or 0) + 1
    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(user)
    # Log the presented token as revoked even though ``token_version`` already
    # invalidates the whole generation: the record carries the reason.
    await revoke_token(
        db, user=user, jti=claims.get("jti"), reason="PASSWORD_CHANGE"
    )
    await db.commit()
    await db.refresh(user)

    subject = str(user.id)
    extra = {"role": user.role, "org": str(user.organization_id) if user.organization_id else None}
    version = int(user.token_version or 0)
    logger.info("password_changed", username=user.username)
    return TokenResponse(
        access=create_access_token(subject, extra, version),
        refresh=create_refresh_token(subject, extra, version),
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic, summary="Return the authenticated user")
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the current user's profile.

    Args:
        user: Authenticated user.

    Returns:
        The public user record.
    """
    return UserPublic.model_validate(user)
