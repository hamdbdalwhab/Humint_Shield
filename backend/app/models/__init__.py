"""ORM model package.

Importing this package registers every model with the declarative ``Base``
metadata, which is required for Alembic autogeneration and ``create_all``.
"""
from __future__ import annotations

from app.database import Base
from app.models.email_campaign import (
    CAMPAIGN_STATUSES,
    EmailCampaign,
    EmailTracking,
    TrainingInteraction,
)
from app.models.email_template import DEFAULT_VARIABLES, EmailTemplate
from app.models.human_asset import HumanAsset
from app.models.lms import PhishingReport, TrainingAssignment, TrainingModule
from app.models.organization import Organization
from app.models.user import User

__all__ = [
    "Base",
    "CAMPAIGN_STATUSES",
    "DEFAULT_VARIABLES",
    "EmailCampaign",
    "EmailTemplate",
    "EmailTracking",
    "HumanAsset",
    "Organization",
    "PhishingReport",
    "TrainingAssignment",
    "TrainingInteraction",
    "TrainingModule",
    "User",
]
