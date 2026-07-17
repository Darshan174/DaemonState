from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_workspace_goals"
down_revision = "0005_learning_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("workspace_goals"):
        op.create_table(
            "workspace_goals",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("component_id", sa.Uuid(), sa.ForeignKey("components.id"), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("source_kind", sa.String(32), nullable=False, server_default="user_selected"),
            sa.Column("source_id", sa.String(255), nullable=True),
            sa.Column("selected_by", sa.String(255), nullable=False, server_default="local_user"),
            sa.Column("selected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(bind, "ix_workspace_goals_workspace_selected", "workspace_goals", ["workspace_id", "selected_at"])
    _index(bind, "ix_workspace_goals_component", "workspace_goals", ["component_id"])
    if "uq_workspace_goals_one_active" not in {
        item["name"] for item in sa.inspect(bind).get_indexes("workspace_goals")
    }:
        op.create_index(
            "uq_workspace_goals_one_active",
            "workspace_goals",
            ["workspace_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("workspace_goals"):
        op.drop_table("workspace_goals")


def _index(bind, name: str, table: str, columns: list[str]) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns)
