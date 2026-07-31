from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_prompt_snippets"
down_revision = "0018_waitlist_signups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("prompt_snippets"):
        op.create_table(
            "prompt_snippets",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column(
                "use_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("prompt_snippets")
    }
    if "ix_prompt_snippets_workspace_id" not in indexes:
        op.create_index(
            "ix_prompt_snippets_workspace_id",
            "prompt_snippets",
            ["workspace_id"],
        )
    if "uq_prompt_snippets_workspace_sha256" not in indexes:
        op.create_index(
            "uq_prompt_snippets_workspace_sha256",
            "prompt_snippets",
            ["workspace_id", "content_sha256"],
            unique=True,
        )
    if "ix_prompt_snippets_workspace_last_used" not in indexes:
        op.create_index(
            "ix_prompt_snippets_workspace_last_used",
            "prompt_snippets",
            ["workspace_id", "last_used_at", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("prompt_snippets"):
        op.drop_table("prompt_snippets")
