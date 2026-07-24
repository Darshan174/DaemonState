from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_source_sync_observations"
down_revision = "0011_digest_read_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("source_sync_observations"):
        op.create_table(
            "source_sync_observations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("connector_id", sa.Uuid(), nullable=False),
            sa.Column("sync_job_id", sa.Uuid(), nullable=True),
            sa.Column("sync_attempt_count", sa.Integer(), nullable=True),
            sa.Column("source_document_id", sa.Uuid(), nullable=False),
            sa.Column("source_identity_sha256", sa.String(length=64), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("provider_object_id", sa.String(length=512), nullable=False),
            sa.Column("provider_version", sa.String(length=255), nullable=True),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("scope_snapshot_sha256", sa.String(length=64), nullable=False),
            sa.Column("provider_account_fingerprint", sa.String(length=64), nullable=False),
            sa.Column(
                "observation_kind",
                sa.String(length=32),
                nullable=False,
                server_default="fetched",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"]),
            sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"]),
            sa.ForeignKeyConstraint(["sync_job_id"], ["sync_jobs.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_workspace_id",
        "source_sync_observations",
        ["workspace_id"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_connector_id",
        "source_sync_observations",
        ["connector_id"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_sync_job_id",
        "source_sync_observations",
        ["sync_job_id"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_source_document_id",
        "source_sync_observations",
        ["source_document_id"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_provider",
        "source_sync_observations",
        ["provider"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_observed_at",
        "source_sync_observations",
        ["observed_at"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_source_observed",
        "source_sync_observations",
        ["source_document_id", "observed_at"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_connector_observed",
        "source_sync_observations",
        ["connector_id", "observed_at"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_sync_observations_job_attempt",
        "source_sync_observations",
        ["sync_job_id", "sync_attempt_count"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("source_sync_observations"):
        op.drop_table("source_sync_observations")


def _create_index_if_missing(
    bind,
    name: str,
    table_name: str,
    columns: list[str],
) -> None:
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns)
