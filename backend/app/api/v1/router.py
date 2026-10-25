"""API v1 router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    campaigns,
    email_templates,
    employees,
    lms,
    reports,
    test,
    tracking,
)
from app.api.v1.webhooks import vonage as vonage_webhooks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(ai.router)
api_router.include_router(employees.router)
api_router.include_router(email_templates.router)
api_router.include_router(campaigns.router)
api_router.include_router(tracking.router)
api_router.include_router(vonage_webhooks.router)
api_router.include_router(lms.router)
api_router.include_router(reports.router)
api_router.include_router(test.router)

__all__ = ["api_router"]
