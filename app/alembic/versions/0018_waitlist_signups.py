from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_waitlist_signups"
down_revision = "0017_stage_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("waitlist_signups"):
        op.create_table(
            "waitlist_signups",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column(
                "source",
                sa.String(64),
                nullable=False,
                server_default="landing",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("waitlist_signups")
    }
    if "uq_waitlist_signups_email" not in indexes:
        op.create_index(
            "uq_waitlist_signups_email",
            "waitlist_signups",
            ["email"],
            unique=True,
        )
    if "ix_waitlist_signups_created_at" not in indexes:
        op.create_index(
            "ix_waitlist_signups_created_at",
            "waitlist_signups",
            ["created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("waitlist_signups"):
        op.drop_table("waitlist_signups")
