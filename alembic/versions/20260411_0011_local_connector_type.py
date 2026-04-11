"""Add local to connector_type_enum.

Revision ID: 20260411_0011
Revises: 20260401_0010
Create Date: 2026-04-11 14:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "20260411_0011"
down_revision = "20260401_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE connector_type_enum ADD VALUE IF NOT EXISTS 'local'")


def downgrade() -> None:
    op.execute("DELETE FROM source_documents WHERE connector_type = 'local'")
    op.execute("DELETE FROM connectors WHERE connector_type = 'local'")
    op.execute(
        "CREATE TYPE connector_type_enum_old AS ENUM "
        "('slack', 'notion', 'zoom', 'github', 'gdrive', 'gong')"
    )
    op.execute(
        "ALTER TABLE connectors "
        "ALTER COLUMN connector_type TYPE connector_type_enum_old "
        "USING connector_type::text::connector_type_enum_old"
    )
    op.execute(
        "ALTER TABLE source_documents "
        "ALTER COLUMN connector_type TYPE connector_type_enum_old "
        "USING connector_type::text::connector_type_enum_old"
    )
    op.execute("DROP TYPE connector_type_enum")
    op.execute("ALTER TYPE connector_type_enum_old RENAME TO connector_type_enum")
