from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_workspace_lifecycle"
down_revision = "0006_workspace_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("workspaces")}
    if "kind" not in columns:
        op.add_column(
            "workspaces",
            sa.Column("kind", sa.String(32), nullable=False, server_default="project"),
        )
    if "status" not in columns:
        op.add_column(
            "workspaces",
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        )
    if "archived_at" not in columns:
        op.add_column("workspaces", sa.Column("archived_at", sa.DateTime(), nullable=True))
    bind.execute(sa.text(
        "UPDATE workspaces SET kind = 'demo' "
        "WHERE lower(name) LIKE '%demo%' OR lower(slug) LIKE '%demo%'"
    ))
    bind.execute(sa.text(
        "UPDATE workspaces SET kind = 'sandbox' "
        "WHERE lower(name) = 'default' OR lower(slug) = 'default'"
    ))
    _index(bind, "ix_workspaces_kind", "workspaces", ["kind"])
    _index(bind, "ix_workspaces_status", "workspaces", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("workspaces")}
    for name in ("ix_workspaces_kind", "ix_workspaces_status"):
        if name in indexes:
            op.drop_index(name, table_name="workspaces")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("archived_at")
        batch.drop_column("status")
        batch.drop_column("kind")


def _index(bind, name: str, table: str, columns: list[str]) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns)
