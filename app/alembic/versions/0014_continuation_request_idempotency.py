from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_continuation_idempotency"
down_revision = "0013_source_ingestion_jobs"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_agent_runs_continuation_request_key"


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        item["name"] for item in sa.inspect(bind).get_indexes("agent_runs")
    }
    if INDEX_NAME not in existing:
        predicate = sa.text(
            "workspace_id IS NOT NULL AND run_key LIKE 'continuation:%'"
        )
        op.create_index(
            INDEX_NAME,
            "agent_runs",
            ["workspace_id", "run_key"],
            unique=True,
            sqlite_where=predicate,
            postgresql_where=predicate,
        )


def downgrade() -> None:
    existing = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes("agent_runs")
    }
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="agent_runs")
