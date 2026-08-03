from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_waitlist_tracking"
down_revision = "0019_prompt_snippets"
branch_labels = None
depends_on = None


_COLUMNS = (
    sa.Column("name", sa.String(255), nullable=True),
    sa.Column("role", sa.String(255), nullable=True),
    sa.Column("company", sa.String(255), nullable=True),
    sa.Column("team_size", sa.String(64), nullable=True),
    sa.Column("primary_tools", sa.Text(), nullable=True),
    sa.Column("main_problem", sa.Text(), nullable=True),
    sa.Column("referrer", sa.Text(), nullable=True),
    sa.Column("utm_source", sa.String(255), nullable=True),
    sa.Column("utm_medium", sa.String(255), nullable=True),
    sa.Column("utm_campaign", sa.String(255), nullable=True),
    sa.Column("utm_term", sa.String(255), nullable=True),
    sa.Column("utm_content", sa.String(255), nullable=True),
    sa.Column("status", sa.String(32), nullable=False, server_default="new"),
    sa.Column(
        "priority_score",
        sa.Integer(),
        nullable=False,
        server_default="0",
    ),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column("consent_at", sa.DateTime(), nullable=True),
    sa.Column("consent_version", sa.String(32), nullable=True),
    sa.Column("invited_at", sa.DateTime(), nullable=True),
    sa.Column("activated_at", sa.DateTime(), nullable=True),
    sa.Column("last_contacted_at", sa.DateTime(), nullable=True),
    sa.Column(
        "email_sync_status",
        sa.String(32),
        nullable=False,
        server_default="pending",
    ),
    sa.Column("email_synced_at", sa.DateTime(), nullable=True),
    sa.Column("email_sync_error", sa.Text(), nullable=True),
    sa.Column(
        "updated_at",
        sa.DateTime(),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("waitlist_signups"):
        return

    existing_columns = {
        item["name"] for item in inspector.get_columns("waitlist_signups")
    }
    for column in _COLUMNS:
        if column.name not in existing_columns:
            op.add_column("waitlist_signups", column)

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("waitlist_signups")
    }
    if "ix_waitlist_signups_status_created_at" not in indexes:
        op.create_index(
            "ix_waitlist_signups_status_created_at",
            "waitlist_signups",
            ["status", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("waitlist_signups"):
        return

    indexes = {
        item["name"] for item in inspector.get_indexes("waitlist_signups")
    }
    if "ix_waitlist_signups_status_created_at" in indexes:
        op.drop_index(
            "ix_waitlist_signups_status_created_at",
            table_name="waitlist_signups",
        )

    existing_columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("waitlist_signups")
    }
    removable = [
        column.name for column in reversed(_COLUMNS)
        if column.name in existing_columns
    ]
    if removable:
        with op.batch_alter_table("waitlist_signups") as batch_op:
            for column_name in removable:
                batch_op.drop_column(column_name)
