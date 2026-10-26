"""Visual email designs and organization branding.

Revision ID: 0009_visual_templates_branding
Revises: 0008_elo_rating
Create Date: 2026-10-26 12:00:00

Adds the JSON design source used by the no-code editor and the organization
branding fields used to personalise every new template.  Existing templates are
backfilled with a ``mode="legacy"`` design wrapper so all thirteen built-ins can
be opened in the visual editor without losing their original HTML.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_visual_templates_branding"
down_revision: str | None = "0008_elo_rating"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATES = "templates"
ORGANIZATIONS = "organizations"
JSON_TYPE = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def _columns(table: str) -> set[str]:
    """Return the current column names for a table."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _legacy_payload(body_html: str) -> dict:
    """Build the JSON wrapper used for pre-editor templates."""
    return {
        "version": 1,
        "mode": "legacy",
        "settings": {
            "background_color": "#F2F4F7",
            "content_background_color": "#FFFFFF",
            "font_family": "Cairo",
            "text_color": "#344054",
            "link_color": "#0F6CBD",
            "width": 600,
            "content_padding": 32,
            "border_radius": 14,
            "preheader": "",
        },
        "blocks": [],
        "legacy_html": body_html or "",
    }


def upgrade() -> None:
    """Add design/branding columns and backfill legacy designs."""
    template_columns = _columns(TEMPLATES)
    if "design_json" not in template_columns:
        op.add_column(TEMPLATES, sa.Column("design_json", JSON_TYPE, nullable=True))

    organization_columns = _columns(ORGANIZATIONS)
    if "brand_primary_color" not in organization_columns:
        op.add_column(
            ORGANIZATIONS,
            sa.Column(
                "brand_primary_color",
                sa.String(7),
                nullable=False,
                server_default="#0F6CBD",
            ),
        )
    if "brand_support_email" not in organization_columns:
        op.add_column(
            ORGANIZATIONS, sa.Column("brand_support_email", sa.String(255), nullable=True)
        )
    if "brand_logo_data" not in organization_columns:
        op.add_column(ORGANIZATIONS, sa.Column("brand_logo_data", sa.LargeBinary(), nullable=True))
    if "brand_logo_mime" not in organization_columns:
        op.add_column(ORGANIZATIONS, sa.Column("brand_logo_mime", sa.String(80), nullable=True))
    if "brand_logo_updated_at" not in organization_columns:
        op.add_column(
            ORGANIZATIONS,
            sa.Column("brand_logo_updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TEMPLATES):
        return
    templates = sa.table(
        TEMPLATES,
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("body_html", sa.Text()),
        sa.column("design_json", JSON_TYPE),
    )
    rows = bind.execute(
        sa.select(templates.c.id, templates.c.body_html).where(
            sa.or_(
                templates.c.design_json.is_(None),
                sa.cast(templates.c.design_json, sa.Text) == "",
            )
        )
    ).all()
    for row in rows:
        payload = _legacy_payload(row.body_html)
        bind.execute(
            templates.update()
            .where(templates.c.id == row.id)
            .values(design_json=json.loads(json.dumps(payload)))
        )


def downgrade() -> None:
    """Remove visual-design and branding columns."""
    template_columns = _columns(TEMPLATES)
    if "design_json" in template_columns:
        with op.batch_alter_table(TEMPLATES) as batch:
            batch.drop_column("design_json")

    organization_columns = _columns(ORGANIZATIONS)
    for column in (
        "brand_logo_updated_at",
        "brand_logo_mime",
        "brand_logo_data",
        "brand_support_email",
        "brand_primary_color",
    ):
        if column in organization_columns:
            with op.batch_alter_table(ORGANIZATIONS) as batch:
                batch.drop_column(column)
