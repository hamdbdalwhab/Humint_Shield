"""Department management endpoints.

Departments are the canonical grouping for human assets.  The legacy free-text
``human_assets.department`` column is kept in sync on every write so imports,
filters and reports that predate this table keep working unchanged.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_organization_or_404, rate_limit, require_permissions
from app.logging_config import get_logger
from app.models import Department, HumanAsset, User
from app.services.audit_service import log_audit

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/departments",
    tags=["departments"],
    dependencies=[Depends(rate_limit(scope="departments"))],
)


class DepartmentCreate(BaseModel):
    """Payload for creating a department."""

    name: str = Field(min_length=1, max_length=150)
    manager_name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=500)


class DepartmentUpdate(BaseModel):
    """Payload for renaming or annotating a department."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    manager_name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=500)


class DepartmentPublic(BaseModel):
    """Serialized department with its live headcount."""

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    manager_name: str | None = None
    description: str | None = None
    employee_count: int = 0


async def _get_department(
    db: AsyncSession, org_id: uuid.UUID, department_id: uuid.UUID
) -> Department:
    """Load a department inside ``org_id`` or raise ``404``."""
    department = await db.get(Department, department_id)
    if department is None or department.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found"
        )
    return department


async def _headcount(db: AsyncSession, department_id: uuid.UUID) -> int:
    """Return the number of human assets linked to a department."""
    return int(
        await db.scalar(
            select(func.count(HumanAsset.id)).where(
                HumanAsset.department_id == department_id
            )
        )
        or 0
    )


async def _sync_employees(
    db: AsyncSession, org_id: uuid.UUID, department: Department, previous_name: str | None
) -> None:
    """Relink employees after a rename.

    Matches both the foreign key and the legacy text value so employees created
    before the department row existed are adopted automatically.
    """
    filters = [HumanAsset.department_id == department.id]
    if previous_name:
        filters.append(HumanAsset.department == previous_name)
    from sqlalchemy import or_

    rows = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == org_id, or_(*filters)
            )
        )
    ).scalars().all()
    for employee in rows:
        employee.department_id = department.id
        employee.department = department.name


@router.get("", response_model=list[DepartmentPublic], summary="List departments")
async def list_departments(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
) -> list[DepartmentPublic]:
    """Return every department with its headcount."""
    rows = (
        await db.execute(
            select(Department, func.count(HumanAsset.id))
            .outerjoin(HumanAsset, HumanAsset.department_id == Department.id)
            .where(Department.organization_id == org_id)
            .group_by(Department.id)
            .order_by(Department.name.asc())
        )
    ).all()
    return [
        DepartmentPublic(
            id=department.id,
            organization_id=department.organization_id,
            name=department.name,
            manager_name=department.manager_name,
            description=department.description,
            employee_count=int(count or 0),
        )
        for department, count in rows
    ]


@router.post(
    "",
    response_model=DepartmentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a department",
)
async def create_department(
    org_id: uuid.UUID,
    payload: DepartmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
) -> DepartmentPublic:
    """Create a department, adopting employees that already use the name."""
    name = payload.name.strip()
    existing = await db.scalar(
        select(Department).where(
            Department.organization_id == org_id, Department.name == name
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A department with this name already exists",
        )
    department = Department(
        organization_id=org_id,
        name=name,
        manager_name=payload.manager_name,
        description=payload.description,
    )
    db.add(department)
    await db.flush()
    await _sync_employees(db, org_id, department, previous_name=name)
    log_audit(
        db,
        user=user,
        action="CREATE",
        target_table="departments",
        target_id=str(department.id),
        new={"name": department.name, "organization_id": str(org_id)},
        request=request,
    )
    await db.commit()
    await db.refresh(department)
    logger.info("department_created", department_id=str(department.id), org_id=str(org_id))
    return DepartmentPublic(
        id=department.id,
        organization_id=department.organization_id,
        name=department.name,
        manager_name=department.manager_name,
        description=department.description,
        employee_count=await _headcount(db, department.id),
    )


@router.patch(
    "/{department_id}", response_model=DepartmentPublic, summary="Update a department"
)
async def update_department(
    org_id: uuid.UUID,
    department_id: uuid.UUID,
    payload: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
) -> DepartmentPublic:
    """Rename or annotate a department and relink its employees."""
    department = await _get_department(db, org_id, department_id)
    previous_name = department.name
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        new_name = data["name"].strip()
        clash = await db.scalar(
            select(Department).where(
                Department.organization_id == org_id,
                Department.name == new_name,
                Department.id != department_id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another department uses this name",
            )
        department.name = new_name
    for field in ("manager_name", "description"):
        if field in data:
            setattr(department, field, data[field])
    await db.flush()
    await _sync_employees(db, org_id, department, previous_name=previous_name)
    await db.commit()
    await db.refresh(department)
    return DepartmentPublic(
        id=department.id,
        organization_id=department.organization_id,
        name=department.name,
        manager_name=department.manager_name,
        description=department.description,
        employee_count=await _headcount(db, department.id),
    )


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a department",
)
async def delete_department(
    org_id: uuid.UUID,
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
) -> None:
    """Delete the department; employees keep their legacy text value."""
    department = await _get_department(db, org_id, department_id)
    rows = (
        await db.execute(
            select(HumanAsset).where(HumanAsset.department_id == department.id)
        )
    ).scalars().all()
    for employee in rows:
        employee.department_id = None
    await db.delete(department)
    await db.commit()
    logger.info("department_deleted", department_id=str(department_id))


__all__ = ["router"]
