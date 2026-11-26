"""Operator account administration and delegated permissions.

Every endpoint here is gated by an explicit permission from
:mod:`app.permissions`; ``users.manage`` is required to change anything.  The
module enforces the least-privilege rules that a UI alone cannot guarantee:

* an operator can only grant permissions it already holds;
* only an administrator may create or promote another administrator;
* nobody can demote, deactivate or delete the last active administrator of an
  organization, nor their own account;
* every mutation is written to ``audit_logs`` (never with a password), bumps
  the account's token generation and therefore invalidates its live sessions.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import effective_permissions, rate_limit, require_permissions, require_roles
from app.logging_config import get_logger
from app.models import User
from app.permissions import (
    normalize_permissions,
    permission_catalog,
    role_default_permissions,
)
from app.schemas import RegisterRequest, UserPublic
from app.schemas.users import (
    AdminPasswordResetRequest,
    PermissionCatalog,
    UserAdminPublic,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.security import hash_password
from app.services.audit_service import log_audit

logger = get_logger(__name__)
router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(rate_limit(scope="users"))],
)


def _admin_public(user: User) -> UserAdminPublic:
    """Serialise an account with its grants and effective permissions."""
    return UserAdminPublic.model_validate(user)


def _snapshot(user: User) -> dict:
    """Return the auditable projection of an account (never secrets)."""
    return {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "permissions": normalize_permissions(user.permissions),
        "organization_id": str(user.organization_id) if user.organization_id else None,
    }


def _assert_same_organization(actor: User, target: User) -> None:
    """Reject cross-tenant administration."""
    if actor.organization_id is not None and target.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage accounts in your own organization",
        )


def _assert_within_authority(actor: User, role: str, grants: list[str]) -> None:
    """Reject privilege escalation.

    The requested role preset and grants must be a subset of the actor's own
    effective permissions, unless the actor is an administrator.

    Raises:
        HTTPException: 403 when the actor tries to hand out more than it holds.
    """
    if (actor.role or "").lower() == "admin":
        return
    authority = set(effective_permissions(actor))
    requested = set(role_default_permissions(role)) | set(normalize_permissions(grants))
    excess = sorted(requested - authority)
    if excess:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot grant permissions you do not hold: " + ", ".join(excess)
            ),
        )


async def _active_admin_count(db: AsyncSession, organization_id: uuid.UUID | None) -> int:
    """Count the active administrators of one organization."""
    query = select(func.count(User.id)).where(
        func.lower(User.role) == "admin", User.is_active.is_(True)
    )
    if organization_id is not None:
        query = query.where(User.organization_id == organization_id)
    return int(await db.scalar(query) or 0)


async def _get_target(db: AsyncSession, user_id: uuid.UUID, actor: User) -> User:
    """Load an account and assert the actor may administer it."""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _assert_same_organization(actor, target)
    return target


async def _assert_unique_identity(
    db: AsyncSession,
    username: str | None,
    email: str | None,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Reject a duplicate username or e-mail (case-insensitive)."""
    conditions = []
    if username:
        conditions.append(func.lower(User.username) == username.lower())
    if email:
        conditions.append(func.lower(User.email) == email.lower())
    if not conditions:
        return
    query = select(User.id).where(*conditions)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username or email already exists",
        )


@router.get(
    "/permissions",
    response_model=PermissionCatalog,
    summary="Permission catalog and role presets",
)
async def get_permission_catalog(
    user: User = Depends(require_permissions("settings.view")),
) -> PermissionCatalog:
    """Return every permission and the default grants of each role."""
    return PermissionCatalog.model_validate(permission_catalog())


@router.get("", response_model=list[UserAdminPublic], summary="List operator accounts")
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_permissions("users.view")),
) -> list[UserAdminPublic]:
    """Return the accounts of the caller's organization."""
    query = select(User).order_by(User.created_at.asc())
    if admin.organization_id is not None:
        query = query.where(User.organization_id == admin.organization_id)
    rows = (await db.execute(query)).scalars().all()
    return [_admin_public(row) for row in rows]


@router.post(
    "",
    response_model=UserAdminPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create an operator account",
)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permissions("users.manage")),
) -> UserAdminPublic:
    """Create an account with an explicit role and permission grants.

    Raises:
        HTTPException: 403 on privilege escalation, 409 on a duplicate identity.
    """
    grants = normalize_permissions(payload.permissions)
    _assert_within_authority(actor, payload.role, grants)
    await _assert_unique_identity(db, payload.username, str(payload.email))

    user = User(
        id=uuid.uuid4(),
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role=payload.role,
        organization_id=actor.organization_id,
        is_active=payload.is_active,
        permissions=grants,
    )
    db.add(user)
    await db.flush()

    log_audit(
        db,
        user=actor,
        action="CREATE",
        target_table="users",
        target_id=str(user.id),
        new=_snapshot(user),
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    logger.info("user_created", user_id=str(user.id), created_by=str(actor.id))
    return _admin_public(user)


@router.post(
    "/invite",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create an operator account (admin only, legacy alias)",
)
async def invite_user(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
) -> UserPublic:
    """Create an account inside the administrator's organization.

    Retained for compatibility with the original administration screen; new
    integrations should call ``POST /users`` with explicit grants.
    """
    organization_id = payload.organization_id or admin.organization_id
    if (
        admin.organization_id is not None
        and organization_id is not None
        and organization_id != admin.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only invite users into your own organization",
        )
    await _assert_unique_identity(db, payload.username, str(payload.email))

    user = User(
        id=uuid.uuid4(),
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role=payload.role,
        organization_id=organization_id,
        is_active=True,
        permissions=[],
    )
    db.add(user)
    await db.flush()

    log_audit(
        db,
        user=admin,
        action="CREATE",
        target_table="users",
        target_id=str(user.id),
        new=_snapshot(user),
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    logger.info("user_invited", user_id=str(user.id), invited_by=str(admin.id))
    return UserPublic.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserAdminPublic,
    summary="Update an account's role, grants or state",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permissions("users.manage")),
) -> UserAdminPublic:
    """Apply a partial update to an account.

    Raises:
        HTTPException: 400 when a self-lockout would result, 403 on privilege
            escalation, 404 when the account does not exist.
    """
    target = await _get_target(db, user_id, actor)
    before = _snapshot(target)
    is_self = target.id == actor.id

    next_role = payload.role if payload.role is not None else target.role
    next_grants = (
        normalize_permissions(payload.permissions)
        if payload.permissions is not None
        else normalize_permissions(target.permissions)
    )
    next_active = payload.is_active if payload.is_active is not None else target.is_active

    if is_self and next_role != target.role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role",
        )
    if is_self and next_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    _assert_within_authority(actor, next_role, next_grants)
    await _assert_unique_identity(
        db,
        None,
        str(payload.email) if payload.email else None,
        exclude_id=target.id,
    )
    if payload.email is not None:
        target.email = str(payload.email)

    losing_last_admin = (
        (target.role or "").lower() == "admin"
        and (next_role != "admin" or next_active is False)
    )
    if losing_last_admin and await _active_admin_count(db, target.organization_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active administrator must remain in the organization",
        )

    permissions_changed = next_grants != normalize_permissions(target.permissions)
    target.role = next_role
    target.permissions = next_grants
    target.is_active = next_active
    if permissions_changed or next_role != before["role"] or next_active is not True:
        # Invalidate every live session so a revoked permission takes effect now.
        target.token_version = int(target.token_version or 0) + 1
        target.failed_login_attempts = 0
        if next_active:
            target.locked_until = None

    await db.flush()
    log_audit(
        db,
        user=actor,
        action="UPDATE",
        target_table="users",
        target_id=str(target.id),
        old=before,
        new=_snapshot(target),
        request=request,
    )
    await db.commit()
    await db.refresh(target)
    logger.info("user_updated", user_id=str(target.id), updated_by=str(actor.id))
    return _admin_public(target)


@router.post(
    "/{user_id}/reset-password",
    response_model=UserAdminPublic,
    summary="Reset an account's password",
)
async def reset_password(
    user_id: uuid.UUID,
    payload: AdminPasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permissions("users.manage")),
) -> UserAdminPublic:
    """Set a new password and revoke every session of the account."""
    target = await _get_target(db, user_id, actor)
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the change-password screen to rotate your own password",
        )
    if (target.role or "").lower() == "admin" and (actor.role or "").lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can reset another administrator's password",
        )
    target.password_hash = hash_password(payload.new_password)
    target.token_version = int(target.token_version or 0) + 1
    target.failed_login_attempts = 0
    target.locked_until = None
    await db.flush()
    log_audit(
        db,
        user=actor,
        action="UPDATE",
        target_table="users",
        target_id=str(target.id),
        old={"password": "rotated"},
        new={"password": "rotated", "sessions_revoked": True},
        request=request,
    )
    await db.commit()
    await db.refresh(target)
    logger.info("user_password_reset", user_id=str(target.id), by=str(actor.id))
    return _admin_public(target)


@router.delete(
    "/{user_id}",
    response_model=UserAdminPublic,
    summary="Deactivate an account",
)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permissions("users.manage")),
) -> UserAdminPublic:
    """Deactivate an account without deleting its audit history."""
    target = await _get_target(db, user_id, actor)
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    if (
        (target.role or "").lower() == "admin"
        and await _active_admin_count(db, target.organization_id) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active administrator must remain in the organization",
        )
    before = _snapshot(target)
    target.is_active = False
    target.token_version = int(target.token_version or 0) + 1
    await db.flush()
    log_audit(
        db,
        user=actor,
        action="DELETE",
        target_table="users",
        target_id=str(target.id),
        old=before,
        new=_snapshot(target),
        request=request,
    )
    await db.commit()
    await db.refresh(target)
    logger.info("user_deactivated", user_id=str(target.id), by=str(actor.id))
    return _admin_public(target)


__all__ = ["router"]
