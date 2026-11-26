"""Audit-trail helper used by privileged endpoints.

Callers add the returned row to their session and commit it together with the
mutation, so the audit trail can never drift from the data it describes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import AuditLog, TokenRevocation, User

logger = get_logger(__name__)

VALID_ACTIONS = {"CREATE", "UPDATE", "DELETE"}
#: Revoked-JTI rows only need to outlive the longest possible token lifetime.
_REVOCATION_RETENTION_DAYS = 30


def _json_safe(value: Any) -> dict | None:
    """Convert an arbitrary snapshot into JSON-serialisable data.

    UUIDs, ``Decimal`` and ``datetime`` values are normalised by FastAPI's
    encoder; anything it cannot handle is stringified rather than failing the
    business transaction.
    """
    if value is None:
        return None
    try:
        encoded = jsonable_encoder(value)
    except Exception:  # noqa: BLE001 - never block a write because of logging
        return {"snapshot": str(value)}
    return encoded if isinstance(encoded, dict) else {"value": encoded}


def _client_ip(request: Request | None) -> str | None:
    """Return the caller's address using the application's proxy policy."""
    if request is None:
        return None
    try:
        from app.deps import _client_ip as resolve_client_ip

        return resolve_client_ip(request)[:45]
    except Exception:  # noqa: BLE001 - auditing must never break a request
        return None


def log_audit(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    target_table: str,
    target_id: str | None = None,
    old: Any = None,
    new: Any = None,
    request: Request | None = None,
    organization_id: Any = None,
) -> AuditLog:
    """Stage an :class:`AuditLog` row on ``db``.

    Args:
        db: Session that owns the business transaction.
        user: Acting user (``None`` for system actions).
        action: ``CREATE``, ``UPDATE`` or ``DELETE``.
        target_table: Table whose row changed.
        target_id: Primary key of the changed row, stringified.
        old: Snapshot before the change.
        new: Snapshot after the change.
        request: Incoming request, used for IP and user agent.
        organization_id: Override; defaults to the acting user's organization.

    Returns:
        The staged (not yet committed) audit row.
    """
    normalized_action = (action or "").upper()
    if normalized_action not in VALID_ACTIONS:
        raise ValueError(f"unsupported audit action: {action!r}")
    row = AuditLog(
        user_id=getattr(user, "id", None),
        organization_id=organization_id or getattr(user, "organization_id", None),
        action=normalized_action,
        target_table=target_table[:64],
        target_id=str(target_id)[:64] if target_id is not None else None,
        old_value=_json_safe(old),
        new_value=_json_safe(new),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:512] if request else None) or None,
    )
    db.add(row)
    return row


async def revoke_token(
    db: AsyncSession,
    *,
    user: User,
    jti: str | None,
    reason: str,
) -> TokenRevocation | None:
    """Record a revoked JWT id and prune expired entries.

    Args:
        db: Active session.
        user: The token's owner.
        jti: The token id claim (``None`` for legacy tokens without one).
        reason: ``LOGOUT``, ``PASSWORD_CHANGE`` or ``ADMIN_ACTION``.

    Returns:
        The staged revocation row, or ``None`` when the token had no ``jti``.
    """
    if not jti:
        return None
    row = TokenRevocation(
        user_id=user.id, token_jti=str(jti)[:64], reason=reason.upper()[:32]
    )
    db.add(row)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_REVOCATION_RETENTION_DAYS)
    await db.execute(delete(TokenRevocation).where(TokenRevocation.revoked_at < cutoff))
    logger.info(
        "token_revoked",
        user_id=str(user.id),
        reason=row.reason,
        jti=row.token_jti,
    )
    return row


__all__ = ["VALID_ACTIONS", "log_audit", "revoke_token"]
