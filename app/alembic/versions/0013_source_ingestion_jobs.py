from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0013_source_ingestion_jobs"
down_revision = "0012_source_sync_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("source_ingestion_jobs"):
        op.create_table(
            "source_ingestion_jobs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("source_document_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=50),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "max_attempts",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
            sa.Column("available_at", sa.DateTime(), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(length=255), nullable=True),
            sa.Column("claim_token", sa.String(length=64), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column("error_type", sa.String(length=100), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "queued_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("dead_lettered_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["source_document_id"],
                ["source_documents.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index_if_missing(
        bind,
        "uq_source_ingestion_jobs_source_document_id",
        "source_ingestion_jobs",
        ["source_document_id"],
        unique=True,
    )
    _create_index_if_missing(
        bind,
        "ix_source_ingestion_jobs_workspace_id",
        "source_ingestion_jobs",
        ["workspace_id"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_ingestion_jobs_queue_due",
        "source_ingestion_jobs",
        ["status", "available_at", "created_at"],
    )
    _create_index_if_missing(
        bind,
        "ix_source_ingestion_jobs_lease_expires_at",
        "source_ingestion_jobs",
        ["lease_expires_at"],
    )
    _backfill_unprocessed_documents(bind)


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("source_ingestion_jobs"):
        op.drop_table("source_ingestion_jobs")


def _backfill_unprocessed_documents(bind) -> None:
    jobs = sa.table(
        "source_ingestion_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("source_document_id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
    )
    documents = bind.execute(sa.text("""
        SELECT source.id, source.workspace_id
        FROM source_documents AS source
        WHERE source.processed_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_ingestion_jobs AS job
              WHERE replace(CAST(job.source_document_id AS TEXT), '-', '') =
                    replace(CAST(source.id AS TEXT), '-', '')
          )
        ORDER BY source.ingested_at, source.id
    """))
    while rows := documents.fetchmany(500):
        bind.execute(
            jobs.insert(),
            [
                {
                    "id": uuid4(),
                    "source_document_id": _uuid_or_none(row[0]),
                    "workspace_id": _uuid_or_none(row[1]),
                    "status": "pending",
                    "attempt_count": 0,
                    "max_attempts": 5,
                }
                for row in rows
            ],
        )


def _uuid_or_none(value):
    from uuid import UUID

    return UUID(str(value)) if value is not None else None


def _create_index_if_missing(
    bind,
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes(table_name)
    }
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=unique)
