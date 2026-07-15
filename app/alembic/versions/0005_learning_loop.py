from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_learning_loop"
down_revision = "0004_truth_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("open_loops"):
        op.create_table(
            "open_loops",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("natural_key", sa.String(64), nullable=False),
            sa.Column("rule_id", sa.String(100), nullable=False),
            sa.Column("rule_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(32), nullable=False, server_default="open"),
            sa.Column("severity", sa.String(32), nullable=False, server_default="warning"),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("next_action", sa.Text(), nullable=True),
            sa.Column("context_pack_id", sa.Uuid(), sa.ForeignKey("context_packs.id"), nullable=True),
            sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=True),
            sa.Column("focus_component_id", sa.Uuid(), sa.ForeignKey("components.id"), nullable=True),
            sa.Column("trigger_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("sources_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("assigned_to", sa.String(255), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column("resolution_source_document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(bind, "uq_open_loops_natural_key", "open_loops", ["natural_key"], unique=True)
    _index(bind, "ix_open_loops_workspace_status", "open_loops", ["workspace_id", "status"])
    _index(bind, "ix_open_loops_focus_status", "open_loops", ["focus_component_id", "status"])
    _index(bind, "ix_open_loops_pack_rule", "open_loops", ["context_pack_id", "rule_id"])

    if not sa.inspect(bind).has_table("verified_playbooks"):
        op.create_table(
            "verified_playbooks",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("identity_key", sa.String(64), nullable=False),
            sa.Column("objective_fingerprint", sa.String(64), nullable=False),
            sa.Column("objective_pattern", sa.Text(), nullable=False),
            sa.Column("repository_identity", sa.String(512), nullable=True),
            sa.Column("repository_snapshot", sa.String(255), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
            sa.Column("ordered_steps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("verification_commands_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("source_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=False),
            sa.Column("supporting_run_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("source_document_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("successful_run_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("last_verified_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("review_reason", sa.Text(), nullable=True),
            sa.Column("review_source_document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(bind, "uq_verified_playbooks_identity_key", "verified_playbooks", ["identity_key"], unique=True)
    _index(bind, "ix_verified_playbooks_workspace_status", "verified_playbooks", ["workspace_id", "status"])
    _index(bind, "ix_verified_playbooks_objective", "verified_playbooks", ["workspace_id", "objective_fingerprint"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("verified_playbooks"):
        op.drop_table("verified_playbooks")
    if sa.inspect(bind).has_table("open_loops"):
        op.drop_table("open_loops")


def _index(bind, name: str, table: str, columns: list[str], **kwargs) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns, **kwargs)
