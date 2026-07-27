from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_continuation_execution"
down_revision = "0014_continuation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("continuation_executions"):
        op.create_table(
            "continuation_executions",
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
                "checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=True,
            ),
            sa.Column(
                "schema_version",
                sa.String(50),
                nullable=False,
                server_default="continuation_execution.v1",
            ),
            sa.Column("task_mode", sa.String(32), nullable=False),
            sa.Column("request_verbatim", sa.Text(), nullable=False),
            sa.Column("request_normalized", sa.Text(), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("display_title", sa.String(180), nullable=False),
            sa.Column("contract_json", sa.Text(), nullable=False),
            sa.Column("contract_sha256", sa.String(64), nullable=False),
            sa.Column("prompt_markdown", sa.Text(), nullable=False),
            sa.Column("prompt_sha256", sa.String(64), nullable=False),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="compiled",
            ),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    execution_columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("continuation_executions")
    }
    if "status" not in execution_columns:
        with op.batch_alter_table("continuation_executions") as batch:
            if "quality_status" in execution_columns:
                batch.alter_column(
                    "quality_status",
                    new_column_name="status",
                    existing_type=sa.String(32),
                    existing_nullable=False,
                    existing_server_default="compiled",
                )
            else:
                batch.add_column(sa.Column(
                    "status",
                    sa.String(32),
                    nullable=False,
                    server_default="compiled",
                ))
    _index(
        bind,
        "ix_continuation_executions_workspace_created",
        "continuation_executions",
        ["workspace_id", "created_at"],
    )
    _index(
        bind,
        "ix_continuation_executions_context_pack",
        "continuation_executions",
        ["context_pack_id"],
    )
    _index(
        bind,
        "ix_continuation_executions_checkpoint",
        "continuation_executions",
        ["checkpoint_id"],
    )
    _index(
        bind,
        "ix_continuation_executions_request_sha256",
        "continuation_executions",
        ["request_sha256"],
    )
    _index(
        bind,
        "uq_continuation_executions_idempotency_key",
        "continuation_executions",
        ["idempotency_key"],
        unique=True,
    )

    if not sa.inspect(bind).has_table("continuation_requirements"):
        op.create_table(
            "continuation_requirements",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "continuation_execution_id",
                sa.Uuid(),
                sa.ForeignKey("continuation_executions.id"),
                nullable=False,
            ),
            sa.Column("requirement_key", sa.String(32), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("priority", sa.String(16), nullable=False),
            sa.Column(
                "source_span_ids_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "verification_ids_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    _index(
        bind,
        "uq_continuation_requirements_execution_key",
        "continuation_requirements",
        ["continuation_execution_id", "requirement_key"],
        unique=True,
    )
    _index(
        bind,
        "ix_continuation_requirements_execution_priority",
        "continuation_requirements",
        ["continuation_execution_id", "priority"],
    )

    agent_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("agent_runs")
    }
    with op.batch_alter_table("agent_runs") as batch:
        if "continuation_execution_id" not in agent_columns:
            batch.add_column(sa.Column(
                "continuation_execution_id",
                sa.Uuid(),
                nullable=True,
            ))
            batch.create_foreign_key(
                "fk_agent_runs_continuation_execution",
                "continuation_executions",
                ["continuation_execution_id"],
                ["id"],
            )
        if "parent_agent_run_id" not in agent_columns:
            batch.add_column(sa.Column(
                "parent_agent_run_id",
                sa.Uuid(),
                nullable=True,
            ))
            batch.create_foreign_key(
                "fk_agent_runs_parent_agent_run",
                "agent_runs",
                ["parent_agent_run_id"],
                ["id"],
            )
        if "attempt_index" not in agent_columns:
            batch.add_column(sa.Column(
                "attempt_index",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ))
        if "provider_session_id" not in agent_columns:
            batch.add_column(sa.Column(
                "provider_session_id",
                sa.String(255),
                nullable=True,
            ))
    _index(
        bind,
        "uq_agent_runs_execution_attempt",
        "agent_runs",
        ["continuation_execution_id", "attempt_index"],
        unique=True,
        sqlite_where=sa.text("continuation_execution_id IS NOT NULL"),
        postgresql_where=sa.text("continuation_execution_id IS NOT NULL"),
    )
    _index(
        bind,
        "ix_agent_runs_parent_attempt",
        "agent_runs",
        ["parent_agent_run_id"],
    )

    if not sa.inspect(bind).has_table("requirement_evidence"):
        op.create_table(
            "requirement_evidence",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "continuation_execution_id",
                sa.Uuid(),
                sa.ForeignKey("continuation_executions.id"),
                nullable=False,
            ),
            sa.Column(
                "continuation_requirement_id",
                sa.Uuid(),
                sa.ForeignKey("continuation_requirements.id"),
                nullable=False,
            ),
            sa.Column(
                "agent_run_id",
                sa.Uuid(),
                sa.ForeignKey("agent_runs.id"),
                nullable=True,
            ),
            sa.Column(
                "run_observation_id",
                sa.Uuid(),
                sa.ForeignKey("run_observations.id"),
                nullable=True,
            ),
            sa.Column("verifier_id", sa.String(100), nullable=False),
            sa.Column("verifier_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column(
                "required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "evidence_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("evidence_sha256", sa.String(64), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    evidence_columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("requirement_evidence")
    }
    if (
        "evidence_json" not in evidence_columns
        or "required" not in evidence_columns
    ):
        with op.batch_alter_table("requirement_evidence") as batch:
            if "evidence_json" not in evidence_columns:
                if "payload_json" in evidence_columns:
                    batch.alter_column(
                        "payload_json",
                        new_column_name="evidence_json",
                        existing_type=sa.Text(),
                        existing_nullable=False,
                        existing_server_default="{}",
                    )
                else:
                    batch.add_column(sa.Column(
                        "evidence_json",
                        sa.Text(),
                        nullable=False,
                        server_default="{}",
                    ))
            if "required" not in evidence_columns:
                batch.add_column(sa.Column(
                    "required",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ))
    _index(
        bind,
        "ix_requirement_evidence_execution_created",
        "requirement_evidence",
        ["continuation_execution_id", "created_at"],
    )
    _index(
        bind,
        "ix_requirement_evidence_requirement_created",
        "requirement_evidence",
        ["continuation_requirement_id", "created_at"],
    )
    _index(
        bind,
        "ix_requirement_evidence_agent_run",
        "requirement_evidence",
        ["agent_run_id"],
    )
    _index(
        bind,
        "ix_requirement_evidence_run_observation",
        "requirement_evidence",
        ["run_observation_id"],
    )
    _index(
        bind,
        "uq_requirement_evidence_attempt_verifier",
        "requirement_evidence",
        ["continuation_requirement_id", "agent_run_id", "verifier_id"],
        unique=True,
        sqlite_where=sa.text("agent_run_id IS NOT NULL"),
        postgresql_where=sa.text("agent_run_id IS NOT NULL"),
    )

    if not sa.inspect(bind).has_table("continuation_outcomes"):
        op.create_table(
            "continuation_outcomes",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "continuation_execution_id",
                sa.Uuid(),
                sa.ForeignKey("continuation_executions.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column(
                "mandatory_total",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "mandatory_passed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "mandatory_failed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "mandatory_unproven",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "blocker_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "summary_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
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
    outcome_columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("continuation_outcomes")
    }
    missing_outcome_columns = {
        "mandatory_total",
        "mandatory_passed",
        "mandatory_failed",
        "mandatory_unproven",
        "blocker_json",
        "updated_at",
    } - outcome_columns
    if missing_outcome_columns:
        outcome_additions = {
            "mandatory_total": sa.Column(
                "mandatory_total",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            "mandatory_passed": sa.Column(
                "mandatory_passed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            "mandatory_failed": sa.Column(
                "mandatory_failed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            "mandatory_unproven": sa.Column(
                "mandatory_unproven",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            "blocker_json": sa.Column(
                "blocker_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            "updated_at": sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        }
        with op.batch_alter_table("continuation_outcomes") as batch:
            for column in (
                "mandatory_total",
                "mandatory_passed",
                "mandatory_failed",
                "mandatory_unproven",
                "blocker_json",
                "updated_at",
            ):
                if column in missing_outcome_columns:
                    batch.add_column(outcome_additions[column])
    _index(
        bind,
        "uq_continuation_outcomes_execution",
        "continuation_outcomes",
        ["continuation_execution_id"],
        unique=True,
    )
    _index(
        bind,
        "ix_continuation_outcomes_status_created",
        "continuation_outcomes",
        ["status", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("continuation_outcomes"):
        op.drop_table("continuation_outcomes")
    if sa.inspect(bind).has_table("requirement_evidence"):
        op.drop_table("requirement_evidence")

    removed_agent_columns = {
        "continuation_execution_id",
        "parent_agent_run_id",
        "attempt_index",
        "provider_session_id",
    }
    for index in sa.inspect(bind).get_indexes("agent_runs"):
        if removed_agent_columns & set(index.get("column_names") or ()):
            op.drop_index(index["name"], table_name="agent_runs")

    agent_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("agent_runs")
    }
    with op.batch_alter_table("agent_runs") as batch:
        if "provider_session_id" in agent_columns:
            batch.drop_column("provider_session_id")
        if "attempt_index" in agent_columns:
            batch.drop_column("attempt_index")
        if "parent_agent_run_id" in agent_columns:
            batch.drop_column("parent_agent_run_id")
        if "continuation_execution_id" in agent_columns:
            batch.drop_column("continuation_execution_id")

    if sa.inspect(bind).has_table("continuation_requirements"):
        op.drop_table("continuation_requirements")
    if sa.inspect(bind).has_table("continuation_executions"):
        op.drop_table("continuation_executions")


def _index(
    bind,
    name: str,
    table: str,
    columns: list[str],
    **kwargs,
) -> None:
    if name not in {
        item["name"] for item in sa.inspect(bind).get_indexes(table)
    }:
        op.create_index(name, table, columns, **kwargs)
