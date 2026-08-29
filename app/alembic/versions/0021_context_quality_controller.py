from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_context_quality_controller"
down_revision = "0020_waitlist_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("context_observation_bundles"):
        op.create_table(
            "context_observation_bundles",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("context_kind", sa.String(32), nullable=False),
            sa.Column("scope_key_sha256", sa.String(64), nullable=False),
            sa.Column("access_scope_sha256", sa.String(64), nullable=False),
            sa.Column("delivery_profile_sha256", sa.String(64), nullable=False),
            sa.Column(
                "checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=True,
            ),
            sa.Column(
                "boundary_event_id",
                sa.Uuid(),
                sa.ForeignKey("session_events.id"),
                nullable=True,
            ),
            sa.Column("repository_identity_sha256", sa.String(64), nullable=True),
            sa.Column("repository_snapshot_sha256", sa.String(64), nullable=True),
            sa.Column(
                "schema_version",
                sa.String(64),
                nullable=False,
                server_default="context_observation.v1",
            ),
            sa.Column(
                "observation_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("observation_sha256", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not sa.inspect(bind).has_table("context_artifact_candidates"):
        op.create_table(
            "context_artifact_candidates",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "observation_bundle_id",
                sa.Uuid(),
                sa.ForeignKey("context_observation_bundles.id"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("context_kind", sa.String(32), nullable=False),
            sa.Column("scope_key_sha256", sa.String(64), nullable=False),
            sa.Column("access_scope_sha256", sa.String(64), nullable=False),
            sa.Column("delivery_profile_sha256", sa.String(64), nullable=False),
            sa.Column(
                "context_pack_id",
                sa.Uuid(),
                sa.ForeignKey("context_packs.id"),
                nullable=True,
            ),
            sa.Column(
                "checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=True,
            ),
            sa.Column("artifact_schema_version", sa.String(64), nullable=False),
            sa.Column("generator_version", sa.String(100), nullable=False),
            sa.Column("compiler_version", sa.String(100), nullable=False),
            sa.Column("renderer_version", sa.String(100), nullable=False),
            sa.Column("policy_version", sa.String(100), nullable=False),
            sa.Column(
                "artifact_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("artifact_sha256", sa.String(64), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("semantic_sha256", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not sa.inspect(bind).has_table("context_artifact_claims"):
        op.create_table(
            "context_artifact_claims",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=False,
            ),
            sa.Column("claim_key", sa.String(512), nullable=False),
            sa.Column("section", sa.String(120), nullable=False),
            sa.Column("claim_kind", sa.String(120), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("statement_sha256", sa.String(64), nullable=False),
            sa.Column("authority", sa.String(50), nullable=False),
            sa.Column("truth_state", sa.String(32), nullable=False),
            sa.Column(
                "criticality",
                sa.String(32),
                nullable=False,
                server_default="normal",
            ),
            sa.Column(
                "selection_decision",
                sa.String(32),
                nullable=False,
                server_default="included",
            ),
            sa.Column("exclusion_reason", sa.String(120), nullable=True),
            sa.Column("exclusion_detail", sa.Text(), nullable=True),
            sa.Column(
                "evidence_refs_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column("evidence_refs_sha256", sa.String(64), nullable=False),
            sa.Column("repository_snapshot_sha256", sa.String(64), nullable=True),
            sa.Column("session_boundary_id", sa.String(64), nullable=True),
            sa.Column(
                "primary_claim_id",
                sa.Uuid(),
                sa.ForeignKey("claims.id"),
                nullable=True,
            ),
            sa.Column(
                "primary_evidence_span_id",
                sa.Uuid(),
                sa.ForeignKey("evidence_spans.id"),
                nullable=True,
            ),
            sa.Column(
                "primary_source_document_id",
                sa.Uuid(),
                sa.ForeignKey("source_documents.id"),
                nullable=True,
            ),
            sa.Column(
                "primary_session_event_id",
                sa.Uuid(),
                sa.ForeignKey("session_events.id"),
                nullable=True,
            ),
            sa.Column(
                "primary_checkpoint_item_id",
                sa.Uuid(),
                sa.ForeignKey("checkpoint_items.id"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not sa.inspect(bind).has_table("context_candidate_evaluations"):
        op.create_table(
            "context_candidate_evaluations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=False,
            ),
            sa.Column(
                "baseline_candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=True,
            ),
            sa.Column(
                "baseline_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("policy_name", sa.String(100), nullable=False),
            sa.Column("policy_version", sa.String(100), nullable=False),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column(
                "diff_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "hard_failures_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "warnings_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "metrics_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("evaluation_sha256", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    inspector = sa.inspect(bind)
    claim_columns = {
        item["name"] for item in inspector.get_columns("context_artifact_claims")
    }
    if "repository_snapshot_sha256" not in claim_columns:
        op.add_column(
            "context_artifact_claims",
            sa.Column("repository_snapshot_sha256", sa.String(64), nullable=True),
        )
    if "session_boundary_id" not in claim_columns:
        op.add_column(
            "context_artifact_claims",
            sa.Column("session_boundary_id", sa.String(64), nullable=True),
        )
    evaluation_columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("context_candidate_evaluations")
    }
    if "baseline_generation" not in evaluation_columns:
        op.add_column(
            "context_candidate_evaluations",
            sa.Column(
                "baseline_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if not sa.inspect(bind).has_table("active_context_pointers"):
        op.create_table(
            "active_context_pointers",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("context_kind", sa.String(32), nullable=False),
            sa.Column("scope_key_sha256", sa.String(64), nullable=False),
            sa.Column("access_scope_sha256", sa.String(64), nullable=False),
            sa.Column("delivery_profile_sha256", sa.String(64), nullable=False),
            sa.Column(
                "active_candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=True,
            ),
            sa.Column(
                "active_evaluation_id",
                sa.Uuid(),
                sa.ForeignKey("context_candidate_evaluations.id"),
                nullable=True,
            ),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
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

    if not sa.inspect(bind).has_table("context_activation_events"):
        op.create_table(
            "context_activation_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "pointer_id",
                sa.Uuid(),
                sa.ForeignKey("active_context_pointers.id"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspaces.id"),
                nullable=False,
            ),
            sa.Column("context_kind", sa.String(32), nullable=False),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column(
                "from_candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=True,
            ),
            sa.Column(
                "to_candidate_id",
                sa.Uuid(),
                sa.ForeignKey("context_artifact_candidates.id"),
                nullable=True,
            ),
            sa.Column(
                "evaluation_id",
                sa.Uuid(),
                sa.ForeignKey("context_candidate_evaluations.id"),
                nullable=True,
            ),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(255), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    indexes = (
        (
            "ix_context_observation_bundles_workspace_id",
            "context_observation_bundles",
            ("workspace_id",),
            False,
        ),
        (
            "ix_context_observation_bundles_workspace_kind_created",
            "context_observation_bundles",
            ("workspace_id", "context_kind", "created_at"),
            False,
        ),
        (
            "ix_context_observation_bundles_scope_created",
            "context_observation_bundles",
            (
                "workspace_id",
                "context_kind",
                "scope_key_sha256",
                "access_scope_sha256",
                "delivery_profile_sha256",
                "created_at",
            ),
            False,
        ),
        (
            "ix_context_observation_bundles_checkpoint",
            "context_observation_bundles",
            ("checkpoint_id",),
            False,
        ),
        (
            "ix_context_observation_bundles_boundary_event",
            "context_observation_bundles",
            ("boundary_event_id",),
            False,
        ),
        (
            "uq_context_observation_bundles_idempotency_key",
            "context_observation_bundles",
            ("idempotency_key",),
            True,
        ),
        (
            "ix_context_artifact_candidates_workspace_id",
            "context_artifact_candidates",
            ("workspace_id",),
            False,
        ),
        (
            "ix_context_artifact_candidates_workspace_kind_created",
            "context_artifact_candidates",
            ("workspace_id", "context_kind", "created_at"),
            False,
        ),
        (
            "ix_context_artifact_candidates_scope_created",
            "context_artifact_candidates",
            (
                "workspace_id",
                "context_kind",
                "scope_key_sha256",
                "access_scope_sha256",
                "delivery_profile_sha256",
                "created_at",
            ),
            False,
        ),
        (
            "ix_context_artifact_candidates_observation",
            "context_artifact_candidates",
            ("observation_bundle_id",),
            False,
        ),
        (
            "ix_context_artifact_candidates_context_pack",
            "context_artifact_candidates",
            ("context_pack_id",),
            False,
        ),
        (
            "ix_context_artifact_candidates_checkpoint",
            "context_artifact_candidates",
            ("checkpoint_id",),
            False,
        ),
        (
            "ix_context_artifact_candidates_semantic",
            "context_artifact_candidates",
            ("semantic_sha256",),
            False,
        ),
        (
            "uq_context_artifact_candidates_idempotency_key",
            "context_artifact_candidates",
            ("idempotency_key",),
            True,
        ),
        (
            "uq_context_artifact_claims_candidate_key",
            "context_artifact_claims",
            ("candidate_id", "claim_key"),
            True,
        ),
        (
            "ix_context_artifact_claims_candidate_section_ordinal",
            "context_artifact_claims",
            ("candidate_id", "section", "ordinal"),
            False,
        ),
        (
            "ix_context_artifact_claims_candidate_selection",
            "context_artifact_claims",
            ("candidate_id", "selection_decision"),
            False,
        ),
        (
            "ix_context_artifact_claims_primary_claim",
            "context_artifact_claims",
            ("primary_claim_id",),
            False,
        ),
        (
            "ix_context_artifact_claims_primary_evidence_span",
            "context_artifact_claims",
            ("primary_evidence_span_id",),
            False,
        ),
        (
            "ix_context_artifact_claims_primary_source_document",
            "context_artifact_claims",
            ("primary_source_document_id",),
            False,
        ),
        (
            "ix_context_artifact_claims_primary_session_event",
            "context_artifact_claims",
            ("primary_session_event_id",),
            False,
        ),
        (
            "ix_context_artifact_claims_primary_checkpoint_item",
            "context_artifact_claims",
            ("primary_checkpoint_item_id",),
            False,
        ),
        (
            "ix_context_candidate_evaluations_candidate_created",
            "context_candidate_evaluations",
            ("candidate_id", "created_at"),
            False,
        ),
        (
            "ix_context_candidate_evaluations_baseline",
            "context_candidate_evaluations",
            ("baseline_candidate_id",),
            False,
        ),
        (
            "ix_context_candidate_evaluations_decision_created",
            "context_candidate_evaluations",
            ("decision", "created_at"),
            False,
        ),
        (
            "uq_context_candidate_evaluations_idempotency_key",
            "context_candidate_evaluations",
            ("idempotency_key",),
            True,
        ),
        (
            "ix_active_context_pointers_workspace_id",
            "active_context_pointers",
            ("workspace_id",),
            False,
        ),
        (
            "ix_active_context_pointers_workspace_kind",
            "active_context_pointers",
            ("workspace_id", "context_kind"),
            False,
        ),
        (
            "ix_active_context_pointers_active_candidate",
            "active_context_pointers",
            ("active_candidate_id",),
            False,
        ),
        (
            "ix_active_context_pointers_active_evaluation",
            "active_context_pointers",
            ("active_evaluation_id",),
            False,
        ),
        (
            "uq_active_context_pointers_scope",
            "active_context_pointers",
            (
                "workspace_id",
                "context_kind",
                "scope_key_sha256",
                "access_scope_sha256",
                "delivery_profile_sha256",
            ),
            True,
        ),
        (
            "ix_context_activation_events_workspace_id",
            "context_activation_events",
            ("workspace_id",),
            False,
        ),
        (
            "ix_context_activation_events_pointer_created",
            "context_activation_events",
            ("pointer_id", "created_at"),
            False,
        ),
        (
            "ix_context_activation_events_workspace_kind_created",
            "context_activation_events",
            ("workspace_id", "context_kind", "created_at"),
            False,
        ),
        (
            "ix_context_activation_events_from_candidate",
            "context_activation_events",
            ("from_candidate_id",),
            False,
        ),
        (
            "ix_context_activation_events_to_candidate",
            "context_activation_events",
            ("to_candidate_id",),
            False,
        ),
        (
            "ix_context_activation_events_evaluation",
            "context_activation_events",
            ("evaluation_id",),
            False,
        ),
        (
            "uq_context_activation_events_idempotency_key",
            "context_activation_events",
            ("idempotency_key",),
            True,
        ),
    )
    for name, table_name, columns, unique in indexes:
        _create_index_if_missing(bind, name, table_name, columns, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "context_activation_events",
        "active_context_pointers",
        "context_candidate_evaluations",
        "context_artifact_claims",
        "context_artifact_candidates",
        "context_observation_bundles",
    ):
        if sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)


def _create_index_if_missing(
    bind,
    name: str,
    table_name: str,
    columns: tuple[str, ...],
    *,
    unique: bool,
) -> None:
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, list(columns), unique=unique)
