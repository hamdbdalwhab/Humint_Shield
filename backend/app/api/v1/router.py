"""API v1 router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, campaigns, email_templates, employees, lms, test, tracking

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(employees.router)
api_router.include_router(email_templates.router)
api_router.include_router(campaigns.router)
api_router.include_router(tracking.router)
api_router.include_router(lms.router)
api_router.include_router(test.router)

__all__ = ["api_router"]
