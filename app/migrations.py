from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def run_migrations(conn: AsyncConnection) -> None:
    await _migrate_connectors_workspace_schema(conn)
    await _migrate_sync_jobs_result_metadata(conn)
    await _migrate_model_taxonomy(conn)
    await _migrate_components_temporal(conn)
    await _migrate_relationships_confidence_evidence(conn)
    await _migrate_components_provenance_excerpt(conn)
    await _migrate_relationships_origin(conn)
    await _migrate_query_and_sync_indexes(conn)


async def _migrate_connectors_workspace_schema(conn: AsyncConnection) -> None:
    """Upgrade pre-workspace connector rows to the workspace-aware schema."""
    columns = await _get_table_columns(conn, "connectors")
    if not columns:
        return

    default_workspace_id = await _ensure_default_workspace(conn)

    if "workspace_id" not in columns:
        await conn.execute(text("ALTER TABLE connectors ADD COLUMN workspace_id CHAR(32)"))
        await conn.execute(
            text("UPDATE connectors SET workspace_id = :workspace_id WHERE workspace_id IS NULL"),
            {"workspace_id": default_workspace_id},
        )

    if "config_json" not in columns:
        await conn.execute(text("ALTER TABLE connectors ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'"))
        if "config" in columns:
            await conn.execute(text(
                "UPDATE connectors SET config_json = config "
                "WHERE config IS NOT NULL AND config != ''"
            ))

    if "credentials_json" not in columns:
        await conn.execute(text("ALTER TABLE connectors ADD COLUMN credentials_json TEXT NOT NULL DEFAULT '{}'"))

    updated_columns = await _get_table_columns(conn, "connectors")
    legacy_columns = {"config", "credentials", "items_synced"}
    if updated_columns & legacy_columns:
        await _rebuild_connectors_table(conn, updated_columns, default_workspace_id)


async def _rebuild_connectors_table(
    conn: AsyncConnection,
    columns: set[str],
    default_workspace_id: str,
) -> None:
    """Remove obsolete connector columns whose legacy constraints break inserts."""
    exprs = {
        "id": "id" if "id" in columns else "lower(hex(randomblob(16)))",
        "workspace_id": "workspace_id" if "workspace_id" in columns else f"'{default_workspace_id}'",
        "connector_type": "connector_type" if "connector_type" in columns else "'unknown'",
        "status": "status" if "status" in columns else "'disconnected'",
        "config_json": (
            "CASE WHEN config_json IS NOT NULL AND config_json NOT IN ('', '{}') THEN config_json "
            "WHEN config IS NOT NULL AND config != '' THEN config ELSE '{}' END"
            if "config" in columns
            else "COALESCE(NULLIF(config_json, ''), '{}')"
        ),
        "credentials_json": (
            "CASE WHEN credentials_json IS NOT NULL AND credentials_json NOT IN ('', '{}') THEN credentials_json "
            "WHEN credentials IS NOT NULL AND credentials != '' THEN credentials ELSE '{}' END"
            if "credentials" in columns
            else "COALESCE(NULLIF(credentials_json, ''), '{}')"
        ),
        "last_sync_at": "last_sync_at" if "last_sync_at" in columns else "NULL",
        "created_at": "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP",
        "updated_at": "updated_at" if "updated_at" in columns else "CURRENT_TIMESTAMP",
    }

    await conn.execute(text("""
        CREATE TABLE connectors_new (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32) NOT NULL,
            connector_type VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'disconnected',
            config_json TEXT NOT NULL DEFAULT '{}',
            credentials_json TEXT NOT NULL DEFAULT '{}',
            last_sync_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """))
    await conn.execute(text(f"""
        INSERT INTO connectors_new (
            id, workspace_id, connector_type, status, config_json,
            credentials_json, last_sync_at, created_at, updated_at
        )
        SELECT
            {exprs["id"]},
            {exprs["workspace_id"]},
            {exprs["connector_type"]},
            {exprs["status"]},
            {exprs["config_json"]},
            {exprs["credentials_json"]},
            {exprs["last_sync_at"]},
            {exprs["created_at"]},
            {exprs["updated_at"]}
        FROM connectors
    """))
    await conn.execute(text("DROP TABLE connectors"))
    await conn.execute(text("ALTER TABLE connectors_new RENAME TO connectors"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_connectors_workspace_id ON connectors (workspace_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_connectors_connector_type ON connectors (connector_type)"
    ))


async def _migrate_sync_jobs_result_metadata(conn: AsyncConnection) -> None:
    """Rename legacy result_metadata payloads by copying into the new column."""
    columns = await _get_table_columns(conn, "sync_jobs")
    if not columns:
        return

    if "result_metadata_json" not in columns:
        await conn.execute(text(
            "ALTER TABLE sync_jobs ADD COLUMN result_metadata_json TEXT NOT NULL DEFAULT '{}'"
        ))
        if "result_metadata" in columns:
            await conn.execute(text(
                "UPDATE sync_jobs SET result_metadata_json = result_metadata "
                "WHERE result_metadata IS NOT NULL AND result_metadata != ''"
            ))
        columns = await _get_table_columns(conn, "sync_jobs")

    if "result_metadata" in columns:
        await _rebuild_sync_jobs_table(conn, columns)


async def _rebuild_sync_jobs_table(conn: AsyncConnection, columns: set[str]) -> None:
    """Drop obsolete result_metadata whose NOT NULL constraint breaks inserts."""
    exprs = {
        "id": "id" if "id" in columns else "lower(hex(randomblob(16)))",
        "connector_id": "connector_id" if "connector_id" in columns else "''",
        "status": "status" if "status" in columns else "'pending'",
        "error_type": "error_type" if "error_type" in columns else "NULL",
        "error_message": "error_message" if "error_message" in columns else "NULL",
        "result_metadata_json": (
            "CASE WHEN result_metadata_json IS NOT NULL AND result_metadata_json NOT IN ('', '{}') THEN result_metadata_json "
            "WHEN result_metadata IS NOT NULL AND result_metadata != '' THEN result_metadata ELSE '{}' END"
            if "result_metadata" in columns
            else "COALESCE(NULLIF(result_metadata_json, ''), '{}')"
        ),
        "created_at": "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP",
        "started_at": "started_at" if "started_at" in columns else "NULL",
        "completed_at": "completed_at" if "completed_at" in columns else "NULL",
    }

    await conn.execute(text("""
        CREATE TABLE sync_jobs_new (
            id CHAR(32) NOT NULL,
            connector_id CHAR(32) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            error_type VARCHAR(100),
            error_message TEXT,
            result_metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            started_at DATETIME,
            completed_at DATETIME,
            PRIMARY KEY (id),
            FOREIGN KEY(connector_id) REFERENCES connectors (id)
        )
    """))
    await conn.execute(text(f"""
        INSERT INTO sync_jobs_new (
            id, connector_id, status, error_type, error_message,
            result_metadata_json, created_at, started_at, completed_at
        )
        SELECT
            {exprs["id"]},
            {exprs["connector_id"]},
            {exprs["status"]},
            {exprs["error_type"]},
            {exprs["error_message"]},
            {exprs["result_metadata_json"]},
            {exprs["created_at"]},
            {exprs["started_at"]},
            {exprs["completed_at"]}
        FROM sync_jobs
    """))
    await conn.execute(text("DROP TABLE sync_jobs"))
    await conn.execute(text("ALTER TABLE sync_jobs_new RENAME TO sync_jobs"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_connector_id ON sync_jobs (connector_id)"
    ))


async def _migrate_components_temporal(conn: AsyncConnection) -> None:
    """Add temporal column to existing components table if missing."""
    columns = await _get_table_columns(conn, "components")
    if not columns or "temporal" in columns:
        return

    await conn.execute(text(
        "ALTER TABLE components ADD COLUMN temporal VARCHAR(20) NOT NULL DEFAULT 'unknown'"
    ))


async def _migrate_model_taxonomy(conn: AsyncConnection) -> None:
    columns = await _get_table_columns(conn, "models")
    if not columns:
        return

    alias_rows = [
        ("Actions", "Task"),
        ("Action", "Task"),
        ("Action Items", "Task"),
        ("Blockers", "Risk"),
        ("Blocker", "Risk"),
        ("Decisions", "Decision"),
        ("Outcomes", "Decision"),
        ("Outcome", "Decision"),
        ("General", "Document"),
        ("Points", "Document"),
    ]

    for legacy, canonical in alias_rows:
        legacy_id = await conn.scalar(
            text("SELECT id FROM models WHERE lower(name) = lower(:name)"),
            {"name": legacy},
        )
        if not legacy_id:
            continue

        canonical_id = await conn.scalar(
            text("SELECT id FROM models WHERE lower(name) = lower(:name)"),
            {"name": canonical},
        )
        if canonical_id and canonical_id != legacy_id:
            await conn.execute(
                text("UPDATE components SET model_id = :canonical_id WHERE model_id = :legacy_id"),
                {"canonical_id": canonical_id, "legacy_id": legacy_id},
            )
            await conn.execute(
                text("DELETE FROM models WHERE id = :legacy_id"),
                {"legacy_id": legacy_id},
            )
        else:
            await conn.execute(
                text("UPDATE models SET name = :canonical WHERE id = :legacy_id"),
                {"canonical": canonical, "legacy_id": legacy_id},
            )


async def _migrate_relationships_confidence_evidence(conn: AsyncConnection) -> None:
    """Add confidence and evidence columns to existing relationships table if missing."""
    columns = await _get_table_columns(conn, "relationships")
    if not columns:
        return

    if "confidence" not in columns:
        await conn.execute(text(
            "ALTER TABLE relationships ADD COLUMN confidence FLOAT NOT NULL DEFAULT 0.7"
        ))
        await conn.execute(text(
            "UPDATE relationships SET confidence = 0.7 WHERE confidence IS NULL"
        ))

    if "evidence" not in columns:
        await conn.execute(text(
            "ALTER TABLE relationships ADD COLUMN evidence TEXT"
        ))
        await conn.execute(text(
            "UPDATE relationships SET evidence = 'backfill: schema migration' "
            "WHERE evidence IS NULL"
        ))

    if "status" not in columns:
        await conn.execute(text(
            "ALTER TABLE relationships ADD COLUMN status VARCHAR(50) NOT NULL DEFAULT 'active'"
        ))


async def _get_table_columns(conn: AsyncConnection, table_name: str) -> set[str]:
    try:
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        rows = result.fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()


async def _ensure_default_workspace(conn: AsyncConnection) -> str:
    rows = (await conn.execute(text("PRAGMA table_info(workspaces)"))).fetchall()
    if not rows:
        return ""

    workspace_id = await conn.scalar(text(
        "SELECT id FROM workspaces ORDER BY created_at LIMIT 1"
    ))
    if workspace_id:
        return str(workspace_id)

    workspace_id = "00000000000000000000000000000000"
    await conn.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Default', 'default')"),
        {"id": workspace_id},
    )
    return workspace_id


async def _migrate_components_provenance_excerpt(conn: AsyncConnection) -> None:
    columns = await _get_table_columns(conn, "components")
    if not columns:
        return

    if "provenance" not in columns:
        await conn.execute(text(
            "ALTER TABLE components ADD COLUMN provenance TEXT"
        ))

    if "excerpt" not in columns:
        await conn.execute(text(
            "ALTER TABLE components ADD COLUMN excerpt TEXT"
        ))


async def _migrate_relationships_origin(conn: AsyncConnection) -> None:
    columns = await _get_table_columns(conn, "relationships")
    if not columns:
        return

    if "origin" not in columns:
        await conn.execute(text(
            "ALTER TABLE relationships ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'proposed'"
        ))


async def _migrate_query_and_sync_indexes(conn: AsyncConnection) -> None:
    index_specs = [
        (
            "source_documents",
            "ix_source_documents_source_type_external_id",
            ("source_type", "external_id"),
        ),
        ("source_documents", "ix_source_documents_processed_at", ("processed_at",)),
        ("source_documents", "ix_source_documents_ingested_at", ("ingested_at",)),
        ("components", "ix_components_status_confidence", ("status", "confidence")),
        ("components", "ix_components_model_status", ("model_id", "status")),
        ("components", "ix_components_source_status", ("source_document_id", "status")),
        ("relationships", "ix_relationships_status_origin", ("status", "origin")),
        ("relationships", "ix_relationships_source_status", ("source_component_id", "status")),
        ("relationships", "ix_relationships_target_status", ("target_component_id", "status")),
        (
            "relationships",
            "ix_relationships_source_target_type",
            ("source_component_id", "target_component_id", "relationship_type"),
        ),
    ]

    for table_name, index_name, column_names in index_specs:
        await _create_index_if_columns_exist(conn, table_name, index_name, column_names)


async def _create_index_if_columns_exist(
    conn: AsyncConnection,
    table_name: str,
    index_name: str,
    column_names: tuple[str, ...],
) -> None:
    columns = await _get_table_columns(conn, table_name)
    if not columns or any(column_name not in columns for column_name in column_names):
        return

    quoted_columns = ", ".join(column_names)
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({quoted_columns})"
    ))
