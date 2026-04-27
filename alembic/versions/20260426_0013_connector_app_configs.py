"""Add connector app configuration storage.

Revision ID: 20260426_0013
Revises: 20260425_0012
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0013"
down_revision = "20260425_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_app_configs",
        sa.Column(
            "connector_type",
            postgresql.ENUM(
                "slack",
                "notion",
                "gdrive",
                "gong",
                "zoom",
                "github",
                "local",
                name="connector_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("connector_type", name=op.f("pk_connector_app_configs")),
        sa.UniqueConstraint("connector_type", name=op.f("uq_connector_app_configs_connector_type")),
    )


def downgrade() -> None:
    op.drop_table("connector_app_configs")
