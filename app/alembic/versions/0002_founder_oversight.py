from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_founder_oversight"
down_revision = "0001_bootstrap_current_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "context_packs")
    if "focus_component_id" not in columns:
        op.add_column(
            "context_packs",
            sa.Column("focus_component_id", sa.Uuid(), sa.ForeignKey("components.id"), nullable=True),
        )
    if "objective_origin" not in columns:
        op.add_column("context_packs", sa.Column("objective_origin", sa.String(32), nullable=True))
    if "objective_source_document_id" not in columns:
        op.add_column(
            "context_packs",
            sa.Column(
                "objective_source_document_id", sa.Uuid(),
                sa.ForeignKey("source_documents.id"), nullable=True,
            ),
        )
    if "objective_evidence_span_id" not in columns:
        op.add_column(
            "context_packs",
            sa.Column(
                "objective_evidence_span_id", sa.Uuid(),
                sa.ForeignKey("evidence_spans.id"), nullable=True,
            ),
        )
    _create_index_if_missing(bind, "ix_context_packs_focus_component", "context_packs", ["focus_component_id"])
    _create_index_if_missing(bind, "ix_context_packs_objective_origin", "context_packs", ["objective_origin"])

    if "manifest_item_id" not in _columns(bind, "context_pack_items"):
        op.add_column("context_pack_items", sa.Column("manifest_item_id", sa.String(255), nullable=True))
    _create_index_if_missing(
        bind,
        "uq_context_pack_items_manifest_item_id",
        "context_pack_items",
        ["context_pack_id", "manifest_item_id"],
        unique=True,
        sqlite_where=sa.text("manifest_item_id IS NOT NULL"),
        postgresql_where=sa.text("manifest_item_id IS NOT NULL"),
    )

    if "run_key" not in _columns(bind, "agent_runs"):
        op.add_column("agent_runs", sa.Column("run_key", sa.String(255), nullable=True))
    _create_index_if_missing(
        bind,
        "uq_agent_runs_context_pack_run_key",
        "agent_runs",
        ["context_pack_id", "run_key"],
        unique=True,
        sqlite_where=sa.text("run_key IS NOT NULL"),
        postgresql_where=sa.text("run_key IS NOT NULL"),
    )

    observation_columns = _columns(bind, "run_observations")
    if "event_key" not in observation_columns:
        op.add_column("run_observations", sa.Column("event_key", sa.String(255), nullable=True))
    if "payload_json" not in observation_columns:
        op.add_column(
            "run_observations",
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        )
    if "observed_at" not in observation_columns:
        op.add_column("run_observations", sa.Column("observed_at", sa.DateTime(), nullable=True))
    _create_index_if_missing(bind, "ix_run_observations_observed_at", "run_observations", ["observed_at"])
    _create_index_if_missing(
        bind,
        "uq_run_observations_agent_run_event_key",
        "run_observations",
        ["agent_run_id", "event_key"],
        unique=True,
        sqlite_where=sa.text("event_key IS NOT NULL"),
        postgresql_where=sa.text("event_key IS NOT NULL"),
    )


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _create_index_if_missing(
    bind,
    name: str,
    table_name: str,
    columns: list[str],
    **kwargs,
) -> None:
    existing = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, **kwargs)


def downgrade() -> None:
    op.drop_index("uq_run_observations_agent_run_event_key", table_name="run_observations")
    op.drop_index("ix_run_observations_observed_at", table_name="run_observations")
    op.drop_column("run_observations", "observed_at")
    op.drop_column("run_observations", "payload_json")
    op.drop_column("run_observations", "event_key")

    op.drop_index("uq_agent_runs_context_pack_run_key", table_name="agent_runs")
    op.drop_column("agent_runs", "run_key")

    op.drop_index("uq_context_pack_items_manifest_item_id", table_name="context_pack_items")
    op.drop_column("context_pack_items", "manifest_item_id")

    op.drop_index("ix_context_packs_objective_origin", table_name="context_packs")
    op.drop_index("ix_context_packs_focus_component", table_name="context_packs")
    op.drop_column("context_packs", "objective_evidence_span_id")
    op.drop_column("context_packs", "objective_source_document_id")
    op.drop_column("context_packs", "objective_origin")
    op.drop_column("context_packs", "focus_component_id")
