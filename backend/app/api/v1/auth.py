"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import auth_rate_limit, get_current_user
from app.logging_config import get_logger
from app.models import User
from app.schemas import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserPublic,
)
from app.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


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
    if user is None or not verify_password(payload.password, user.password_hash):
        logger.warning("login_failed", username=username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    subject = str(user.id)
    extra = {"role": user.role, "org": str(user.organization_id) if user.organization_id else None}
    logger.info("login_succeeded", username=user.username, role=user.role)
    return TokenResponse(
        access=create_access_token(subject, extra),
        refresh=create_refresh_token(subject, extra),
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

    extra = {"role": user.role, "org": str(user.organization_id) if user.organization_id else None}
    return AccessTokenResponse(access=create_access_token(str(user.id), extra))


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Invalidate the current session")
async def logout(user: User = Depends(get_current_user)) -> dict[str, bool]:
    """Acknowledge logout.

    Tokens are stateless; the client discards them.  The endpoint exists so
    clients have a deterministic place to clear server-side context.

    Args:
        user: Authenticated user.

    Returns:
        ``{"success": True}``.
    """
    logger.info("logout", username=user.username)
    return {"success": True}


@router.get("/me", response_model=UserPublic, summary="Return the authenticated user")
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the current user's profile.

    Args:
        user: Authenticated user.

    Returns:
        The public user record.
    """
    return UserPublic.model_validate(user)
