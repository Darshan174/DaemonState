from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_work_checkpoints"
down_revision = "0007_workspace_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("session_events"):
        op.create_table(
            "session_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column(
                "source_document_id",
                sa.Uuid(),
                sa.ForeignKey("source_documents.id"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("session_id", sa.String(255), nullable=False),
            sa.Column("provider_event_id", sa.String(255), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("role", sa.String(32), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("source_cursor", sa.Integer(), nullable=True),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(
        bind,
        "uq_session_events_provider_session_event",
        "session_events",
        ["workspace_id", "provider", "session_id", "provider_event_id"],
        unique=True,
    )
    _index(
        bind,
        "ix_session_events_workspace_session_sequence",
        "session_events",
        ["workspace_id", "provider", "session_id", "sequence_number"],
    )
    _index(bind, "ix_session_events_source_document", "session_events", ["source_document_id"])
    _index(bind, "ix_session_events_event_type", "session_events", ["event_type"])
    _index(bind, "ix_session_events_occurred_at", "session_events", ["occurred_at"])

    if not sa.inspect(bind).has_table("work_checkpoints"):
        op.create_table(
            "work_checkpoints",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column(
                "source_document_id",
                sa.Uuid(),
                sa.ForeignKey("source_documents.id"),
                nullable=False,
            ),
            sa.Column(
                "boundary_event_id",
                sa.Uuid(),
                sa.ForeignKey("session_events.id"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("session_id", sa.String(255), nullable=False),
            sa.Column("trigger", sa.String(50), nullable=False),
            sa.Column(
                "schema_version",
                sa.String(50),
                nullable=False,
                server_default="work_checkpoint.v5",
            ),
            sa.Column("capture_status", sa.String(32), nullable=False, server_default="complete"),
            sa.Column(
                "continuation_status",
                sa.String(32),
                nullable=False,
                server_default="review_required",
            ),
            sa.Column("repo_root", sa.Text(), nullable=True),
            sa.Column("branch", sa.String(255), nullable=True),
            sa.Column("head_commit", sa.String(100), nullable=True),
            sa.Column("worktree_fingerprint", sa.String(64), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("payload_sha256", sa.String(64), nullable=False),
            sa.Column(
                "supersedes_checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(
        bind,
        "uq_work_checkpoints_boundary_schema",
        "work_checkpoints",
        ["workspace_id", "provider", "session_id", "boundary_event_id", "schema_version"],
        unique=True,
    )
    _index(
        bind,
        "ix_work_checkpoints_workspace_created",
        "work_checkpoints",
        ["workspace_id", "created_at"],
    )
    _index(
        bind,
        "ix_work_checkpoints_session_created",
        "work_checkpoints",
        ["provider", "session_id", "created_at"],
    )
    _index(bind, "ix_work_checkpoints_source_document", "work_checkpoints", ["source_document_id"])
    _index(bind, "ix_work_checkpoints_boundary_event", "work_checkpoints", ["boundary_event_id"])
    _index(
        bind,
        "ix_work_checkpoints_supersedes",
        "work_checkpoints",
        ["supersedes_checkpoint_id"],
    )

    if not sa.inspect(bind).has_table("checkpoint_items"):
        op.create_table(
            "checkpoint_items",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=False,
            ),
            sa.Column("item_key", sa.String(100), nullable=False),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("state", sa.String(32), nullable=False, server_default="active"),
            sa.Column("truth_state", sa.String(32), nullable=False, server_default="reported"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(
        bind,
        "ix_checkpoint_items_checkpoint_category",
        "checkpoint_items",
        ["checkpoint_id", "category"],
    )
    _index(
        bind,
        "uq_checkpoint_items_checkpoint_item_key",
        "checkpoint_items",
        ["checkpoint_id", "item_key"],
        unique=True,
    )

    if not sa.inspect(bind).has_table("checkpoint_evidence"):
        op.create_table(
            "checkpoint_evidence",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "checkpoint_item_id",
                sa.Uuid(),
                sa.ForeignKey("checkpoint_items.id"),
                nullable=False,
            ),
            sa.Column("evidence_type", sa.String(50), nullable=False),
            sa.Column("session_event_id", sa.Uuid(), sa.ForeignKey("session_events.id"), nullable=True),
            sa.Column(
                "source_document_id",
                sa.Uuid(),
                sa.ForeignKey("source_documents.id"),
                nullable=True,
            ),
            sa.Column(
                "run_observation_id",
                sa.Uuid(),
                sa.ForeignKey("run_observations.id"),
                nullable=True,
            ),
            sa.Column("supports", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("locator_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("evidence_sha256", sa.String(64), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(bind, "ix_checkpoint_evidence_item", "checkpoint_evidence", ["checkpoint_item_id"])
    _index(
        bind,
        "ix_checkpoint_evidence_session_event",
        "checkpoint_evidence",
        ["session_event_id"],
    )
    _index(
        bind,
        "ix_checkpoint_evidence_source_document",
        "checkpoint_evidence",
        ["source_document_id"],
    )
    _index(
        bind,
        "ix_checkpoint_evidence_run_observation",
        "checkpoint_evidence",
        ["run_observation_id"],
    )

    if not sa.inspect(bind).has_table("checkpoint_verifications"):
        op.create_table(
            "checkpoint_verifications",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "checkpoint_id",
                sa.Uuid(),
                sa.ForeignKey("work_checkpoints.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("worktree_fingerprint", sa.String(64), nullable=True),
            sa.Column(
                "policy_version",
                sa.String(50),
                nullable=False,
                server_default="checkpoint_verifier.v1",
            ),
            sa.Column("results_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _index(
        bind,
        "ix_checkpoint_verifications_checkpoint_created",
        "checkpoint_verifications",
        ["checkpoint_id", "created_at"],
    )
    _index(
        bind,
        "ix_checkpoint_verifications_fingerprint",
        "checkpoint_verifications",
        ["worktree_fingerprint"],
    )
    _index(
        bind,
        "uq_checkpoint_verifications_idempotency",
        "checkpoint_verifications",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "checkpoint_verifications",
        "checkpoint_evidence",
        "checkpoint_items",
        "work_checkpoints",
        "session_events",
    ):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)


def _index(
    bind,
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns, unique=unique)
