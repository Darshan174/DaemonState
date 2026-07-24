from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_digest_read_indexes"
down_revision = "0010_production_worker_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    _create_index_if_missing(
        bind,
        "ix_source_documents_workspace_type_ingested",
        "source_documents",
        ["workspace_id", "source_type", "ingested_at", "id"],
    )
    _create_index_if_missing(
        bind,
        "ix_session_events_source_type_sequence",
        "session_events",
        ["source_document_id", "event_type", "sequence_number"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, index_name in (
        ("session_events", "ix_session_events_source_type_sequence"),
        ("source_documents", "ix_source_documents_workspace_type_ingested"),
    ):
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes(table_name)
        }
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)


def _create_index_if_missing(
    bind,
    name: str,
    table_name: str,
    columns: list[str],
) -> None:
    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes(table_name)
    }
    if name not in indexes:
        op.create_index(name, table_name, columns)
