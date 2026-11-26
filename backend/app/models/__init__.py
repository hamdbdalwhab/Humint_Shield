"""ORM model package.

Importing this package registers every model with the declarative ``Base``
metadata, which is required for Alembic autogeneration and ``create_all``.
"""
from __future__ import annotations

from app.database import Base
from app.models.audit import AuditLog, TokenRevocation
from app.models.email_campaign import (
    CAMPAIGN_STATUSES,
    CHANNELS,
    DEFAULT_CHANNEL,
    SIMULATION_CHANNELS,
    EmailCampaign,
    EmailTracking,
    QRScan,
    TrainingInteraction,
)
from app.models.email_template import DEFAULT_VARIABLES, EmailTemplate
from app.models.human_asset import HumanAsset
from app.models.lms import PhishingReport, TrainingAssignment, TrainingModule
from app.models.monthly_archive import MonthlyArchive
from app.models.organization import Organization
from app.models.short_link import ShortLink
from app.models.user import User

__all__ = [
    "AuditLog",
    "Base",
    "CAMPAIGN_STATUSES",
    "CHANNELS",
    "DEFAULT_CHANNEL",
    "DEFAULT_VARIABLES",
    "EmailCampaign",
    "EmailTemplate",
    "EmailTracking",
    "HumanAsset",
    "MonthlyArchive",
    "Organization",
    "PhishingReport",
    "QRScan",
    "ShortLink",
    "SIMULATION_CHANNELS",
    "TrainingAssignment",
    "TokenRevocation",
    "TrainingInteraction",
    "TrainingModule",
    "User",
]
