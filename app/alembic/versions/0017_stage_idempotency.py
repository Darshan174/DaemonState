from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_stage_idempotency"
down_revision = "0016_daemonstate_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("continuation_stage_requests"):
        op.create_table(
            "continuation_stage_requests",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column(
                "context_pack_id",
                sa.Uuid(),
                sa.ForeignKey("context_packs.id"),
                nullable=False,
            ),
            sa.Column(
                "continuation_execution_id",
                sa.Uuid(),
                sa.ForeignKey("continuation_executions.id"),
                nullable=False,
            ),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("target_provider", sa.String(32), nullable=False),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "response_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "error_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
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
        for item in sa.inspect(bind).get_indexes("continuation_stage_requests")
    }
    if "uq_continuation_stage_requests_workspace_key" not in indexes:
        op.create_index(
            "uq_continuation_stage_requests_workspace_key",
            "continuation_stage_requests",
            ["workspace_id", "idempotency_key"],
            unique=True,
        )
    if "ix_continuation_stage_requests_workspace_created" not in indexes:
        op.create_index(
            "ix_continuation_stage_requests_workspace_created",
            "continuation_stage_requests",
            ["workspace_id", "created_at"],
        )
    if "uq_continuation_stage_requests_workspace_current" not in indexes:
        op.create_index(
            "uq_continuation_stage_requests_workspace_current",
            "continuation_stage_requests",
            ["workspace_id"],
            unique=True,
            sqlite_where=sa.text(
                "status IN ('pending','succeeded','failed')"
            ),
            postgresql_where=sa.text(
                "status IN ('pending','succeeded','failed')"
            ),
        )
    for name, column in (
        ("ix_continuation_stage_requests_workspace_id", "workspace_id"),
        ("ix_continuation_stage_requests_context_pack_id", "context_pack_id"),
        (
            "ix_continuation_stage_requests_continuation_execution_id",
            "continuation_execution_id",
        ),
    ):
        if name not in indexes:
            op.create_index(name, "continuation_stage_requests", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("continuation_stage_requests"):
        op.drop_table("continuation_stage_requests")
