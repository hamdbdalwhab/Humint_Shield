"""Shared FastAPI dependencies: authentication, authorization, rate limiting."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.logging_config import get_logger
from app.models import Organization, TokenRevocation, User
from app.security import TokenError, claim_version, decode_token
from app.services.rate_limit import RateLimitExceeded, get_rate_limiter

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    """Extract the client IP without trusting client-supplied headers.

    Behind a reverse proxy (nginx in the Docker stack, Cloudflare in front of
    it) the socket address is the proxy's, so the forwarded headers are used
    when :attr:`Settings.trust_proxy_headers` is enabled.  Only the **rightmost**
    ``X-Forwarded-For`` entry is trusted: it is the address appended by the
    proxy closest to us, while anything a client sends to the left of it is
    attacker-controlled and would otherwise let a caller pick its own
    rate-limit bucket.
    """
    settings: Settings = get_settings()
    socket_ip = request.client.host if request.client else "unknown"
    if not settings.trust_proxy_headers:
        return socket_ip
    for header in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        val = request.headers.get(header)
        if val and val.strip():
            return val.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidates = [part.strip() for part in forwarded.split(",") if part.strip()]
        if candidates:
            return candidates[-1]
    return socket_ip


async def enforce_rate_limit(
    request: Request,
    limit: int | None = None,
    window: int | None = None,
    scope: str = "global",
) -> None:
    """Apply the shared sliding-window limiter to a request.

    Args:
        request: Incoming request.
        limit: Optional per-call limit.
        window: Optional per-call window in seconds.
        scope: Bucket name used to build the limiter key.

    Raises:
        HTTPException: 429 when the budget is exhausted.
    """
    settings: Settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    key = f"{scope}:{_client_ip(request)}"
    try:
        await get_rate_limiter().check(key, limit=limit, window=window)
    except RateLimitExceeded as exc:
        logger.warning("rate_limit_exceeded", scope=scope, key=key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def rate_limit(limit: int | None = None, window: int | None = None, scope: str = "global") -> Callable:
    """Build a rate-limit dependency.

    Args:
        limit: Maximum requests per window.
        window: Window length in seconds.
        scope: Bucket name.

    Returns:
        A FastAPI dependency callable.
    """

    async def _dependency(request: Request) -> None:
        await enforce_rate_limit(request, limit=limit, window=window, scope=scope)

    return _dependency


def auth_rate_limit() -> Callable:
    """Return a stricter rate limiter for authentication endpoints."""
    settings = get_settings()

    async def _dependency(request: Request) -> None:
        await enforce_rate_limit(
            request,
            limit=settings.rate_limit_auth_requests,
            window=settings.rate_limit_window_seconds,
            scope="auth",
        )

    return _dependency


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a bearer access token.

    Args:
        credentials: Parsed ``Authorization: Bearer`` header.
        db: Active session.

    Returns:
        The authenticated :class:`~app.models.User`.

    Raises:
        HTTPException: 401 when the token is missing, invalid or the user is
            missing/inactive.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials)
    except TokenError:
        raise unauthorized from None
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    subject = payload.get("sub")
    try:
        user_id = uuid.UUID(str(subject))
    except (ValueError, TypeError):
        raise unauthorized from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    # A token issued before the last logout / password change is revoked even
    # though its signature and expiry are still valid.
    if claim_version(payload) != int(user.token_version or 0):
        raise unauthorized
    # Per-token revocation log: logout can invalidate exactly the presented
    # session without bumping the account-wide generation counter.
    jti = payload.get("jti")
    if jti:
        revoked = await db.scalar(
            select(TokenRevocation.id)
            .where(TokenRevocation.token_jti == str(jti))
            .limit(1)
        )
        if revoked is not None:
            raise unauthorized
    return user


async def get_token_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Return the verified claims of the presented access token.

    Used by endpoints that must act on the token itself (logout, password
    change) and therefore need its ``jti``.

    Args:
        credentials: Parsed ``Authorization: Bearer`` header.

    Returns:
        The decoded JWT claims.

    Raises:
        HTTPException: 401 when the header is missing or the token is invalid.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def effective_permissions(user: User) -> set[str]:
    """Return the permission keys an account actually holds.

    Args:
        user: Authenticated account.

    Returns:
        The role preset unioned with the account's explicit grants.
    """
    from app.permissions import effective_permissions as resolve

    return set(resolve(user.role, user.permissions))


def user_has_permission(user: User, permission: str) -> bool:
    """Return whether ``user`` holds ``permission``."""
    return permission in effective_permissions(user)


def require_permissions(*permissions: str) -> Callable:
    """Build a dependency that requires every listed permission.

    This is the least-privilege gate used by every privileged endpoint: a
    viewer with an explicit grant passes, an administrator without the grant in
    its preset fails.  Permission keys come from :mod:`app.permissions`.

    Args:
        *permissions: Permission keys the caller must hold.

    Returns:
        A FastAPI dependency callable returning the authenticated user.
    """
    required = tuple(permissions)

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        held = effective_permissions(user)
        missing = [permission for permission in required if permission not in held]
        if missing:
            logger.warning(
                "permission_denied",
                user_id=str(user.id),
                missing=missing,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have permission to perform this action "
                    f"(missing: {', '.join(missing)})"
                ),
            )
        return user

    return _dependency


def require_roles(*roles: str) -> Callable:
    """Build a dependency that restricts a route to specific roles.

    Args:
        *roles: Allowed roles (``admin``, ``manager``, ``viewer``).

    Returns:
        A FastAPI dependency callable returning the authenticated user.
    """
    allowed = {r.lower() for r in roles}

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role.lower() not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return _dependency


async def get_organization_or_404(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Organization:
    """Load an organization and assert the caller may access it.

    Args:
        org_id: Organization id from the path.
        db: Active session.
        user: Authenticated user.

    Returns:
        The organization.

    Raises:
        HTTPException: 404 when absent, 403 when the caller is not a member.
    """
    organization = await db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if user.organization_id is not None and user.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )
    return organization


async def get_first_organization(db: AsyncSession, user: User) -> Organization | None:
    """Return the user's organization, or the first organization as a fallback.

    Args:
        db: Active session.
        user: Authenticated user.

    Returns:
        The organization or ``None`` when the database is empty.
    """
    if user.organization_id is not None:
        return await db.get(Organization, user.organization_id)
    return await db.scalar(select(Organization).order_by(Organization.created_at.asc()).limit(1))
