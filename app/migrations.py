from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.services.identity import identity_key_for_component_name, normalize_identity_text
from app.services.vector_search import pgvector_index_dimension


async def run_migrations(conn: AsyncConnection) -> None:
    await _migrate_connectors_workspace_schema(conn)
    await _migrate_workspace_ownership_columns(conn)
    await _migrate_sync_jobs_result_metadata(conn)
    await _migrate_sync_jobs_durable_schema(conn)
    await _migrate_model_taxonomy(conn)
    await _migrate_components_temporal(conn)
    await _migrate_component_identity_keys(conn)
    await _migrate_entities_schema(conn)
    await _migrate_fact_identity_schema(conn)
    await _migrate_relationships_confidence_evidence(conn)
    await _migrate_components_provenance_excerpt(conn)
    await _migrate_relationships_origin(conn)
    await _migrate_retrieval_events_schema(conn)
    await _migrate_pgvector_search_schema(conn)
    await _migrate_postgres_text_search_schema(conn)
    await _migrate_query_and_sync_indexes(conn)


async def _migrate_workspace_ownership_columns(conn: AsyncConnection) -> None:
    """Add real workspace ownership columns and backfill from legacy metadata."""
    source_columns = await _get_table_columns(conn, "source_documents")
    if source_columns:
        if "workspace_id" not in source_columns:
            await conn.execute(text("ALTER TABLE source_documents ADD COLUMN workspace_id CHAR(32)"))
        if {"id", "source_type", "metadata"} <= source_columns:
            await _backfill_source_document_workspace_ids(conn)

    component_columns = await _get_table_columns(conn, "components")
    if component_columns:
        if "workspace_id" not in component_columns:
            await conn.execute(text("ALTER TABLE components ADD COLUMN workspace_id CHAR(32)"))
            component_columns = await _get_table_columns(conn, "components")
        updated_source_columns = await _get_table_columns(conn, "source_documents")
        if {"source_document_id", "workspace_id"} <= component_columns and "workspace_id" in updated_source_columns:
            await conn.execute(text("""
                UPDATE components
                SET workspace_id = (
                    SELECT source_documents.workspace_id
                    FROM source_documents
                    WHERE source_documents.id = components.source_document_id
                )
                WHERE workspace_id IS NULL
                  AND source_document_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1
                    FROM source_documents
                    WHERE source_documents.id = components.source_document_id
                      AND source_documents.workspace_id IS NOT NULL
                  )
            """))


async def _backfill_source_document_workspace_ids(conn: AsyncConnection) -> None:
    connector_workspaces = await _connector_workspaces_by_type(conn)
    result = await conn.execute(text("""
        SELECT id, source_type, metadata, workspace_id
        FROM source_documents
        WHERE workspace_id IS NULL
    """))
    rows = result.fetchall()

    for row in rows:
        metadata = _loads_json_dict(row[2])
        workspace_id = _workspace_storage_id(metadata.get("workspace_id"))
        if workspace_id is None:
            workspace_id = _single_connector_workspace(
                str(row[1] or ""),
                connector_workspaces,
            )
        if workspace_id is None:
            continue
        await conn.execute(
            text("UPDATE source_documents SET workspace_id = :workspace_id WHERE id = :id"),
            {"workspace_id": workspace_id, "id": row[0]},
        )


async def _connector_workspaces_by_type(conn: AsyncConnection) -> dict[str, set[str]]:
    columns = await _get_table_columns(conn, "connectors")
    if not {"connector_type", "workspace_id"} <= columns:
        return {}

    result = await conn.execute(text("""
        SELECT connector_type, workspace_id
        FROM connectors
        WHERE workspace_id IS NOT NULL
    """))
    workspaces: dict[str, set[str]] = {}
    for connector_type, workspace_id in result.fetchall():
        normalized = _workspace_storage_id(workspace_id)
        if not connector_type or not normalized:
            continue
        workspaces.setdefault(str(connector_type).lower(), set()).add(normalized)
    return workspaces


def _single_connector_workspace(
    source_type: str,
    connector_workspaces: dict[str, set[str]],
) -> str | None:
    candidates = _connector_candidates_for_source_type(source_type)
    workspace_ids: set[str] = set()
    for candidate in candidates:
        workspace_ids.update(connector_workspaces.get(candidate, set()))
    if len(workspace_ids) == 1:
        return next(iter(workspace_ids))
    return None


def _connector_candidates_for_source_type(source_type: str) -> set[str]:
    normalized = source_type.strip().lower()
    candidates = {normalized}
    if normalized in {"github", "github_issue", "github_pr"} or normalized.startswith("github_"):
        candidates.add("github")
    if normalized in {"gmail", "gdrive", "slack"}:
        candidates.add(normalized)
    if normalized == "agent_session" or normalized.startswith("ai_context"):
        candidates.update({
            "ai_context",
            "codex",
            "claude",
            "opencode",
            "ai_context_codex",
            "ai_context_claude_code",
            "ai_context_opencode",
        })
    return {candidate for candidate in candidates if candidate}


def _workspace_storage_id(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value)).hex
    except (TypeError, ValueError):
        return str(value)


def _loads_json_dict(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


async def _migrate_sync_jobs_durable_schema(conn: AsyncConnection) -> None:
    """Add durable job metadata used for idempotency, retries, and workspace scoping."""
    columns = await _get_table_columns(conn, "sync_jobs")
    if not columns:
        return

    datetime_type = _datetime_column_type(conn)
    if "workspace_id" not in columns:
        await conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN workspace_id CHAR(32)"))
    if "job_type" not in columns:
        await conn.execute(text(
            "ALTER TABLE sync_jobs ADD COLUMN job_type VARCHAR(50) NOT NULL DEFAULT 'connector_sync'"
        ))
    if "idempotency_key" not in columns:
        await conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN idempotency_key VARCHAR(255)"))
    if "attempt_count" not in columns:
        await conn.execute(text(
            "ALTER TABLE sync_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        ))
    if "max_attempts" not in columns:
        await conn.execute(text(
            "ALTER TABLE sync_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3"
        ))
    if "queued_at" not in columns:
        await conn.execute(text(
            f"ALTER TABLE sync_jobs ADD COLUMN queued_at {datetime_type}"
        ))
    if "available_at" not in columns:
        await conn.execute(text(
            f"ALTER TABLE sync_jobs ADD COLUMN available_at {datetime_type}"
        ))
    if "lease_expires_at" not in columns:
        await conn.execute(text(
            f"ALTER TABLE sync_jobs ADD COLUMN lease_expires_at {datetime_type}"
        ))
    if "locked_by" not in columns:
        await conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN locked_by VARCHAR(255)"))
    if "dead_lettered_at" not in columns:
        await conn.execute(text(
            f"ALTER TABLE sync_jobs ADD COLUMN dead_lettered_at {datetime_type}"
        ))

    updated_columns = await _get_table_columns(conn, "sync_jobs")
    connector_columns = await _get_table_columns(conn, "connectors")
    if (
        {"workspace_id", "connector_id"} <= updated_columns
        and "workspace_id" in connector_columns
    ):
        await conn.execute(text("""
            UPDATE sync_jobs
            SET workspace_id = (
                SELECT connectors.workspace_id
                FROM connectors
                WHERE connectors.id = sync_jobs.connector_id
            )
            WHERE workspace_id IS NULL
              AND connector_id IS NOT NULL
              AND EXISTS (
                SELECT 1
                FROM connectors
                WHERE connectors.id = sync_jobs.connector_id
                  AND connectors.workspace_id IS NOT NULL
              )
        """))

    if {"idempotency_key", "job_type", "connector_id"} <= updated_columns:
        await conn.execute(text("""
            UPDATE sync_jobs
            SET idempotency_key = job_type || ':' || connector_id
            WHERE idempotency_key IS NULL
              AND connector_id IS NOT NULL
        """))

    if {"queued_at", "created_at"} <= updated_columns:
        await conn.execute(text("""
            UPDATE sync_jobs
            SET queued_at = created_at
            WHERE queued_at IS NULL
        """))
    if {"available_at", "created_at", "status"} <= updated_columns:
        await conn.execute(text("""
            UPDATE sync_jobs
            SET available_at = created_at
            WHERE available_at IS NULL
              AND status IN ('pending', 'retrying')
        """))


async def _rebuild_sync_jobs_table(conn: AsyncConnection, columns: set[str]) -> None:
    """Drop obsolete result_metadata whose NOT NULL constraint breaks inserts."""
    exprs = {
        "id": "id" if "id" in columns else "lower(hex(randomblob(16)))",
        "workspace_id": "workspace_id" if "workspace_id" in columns else "NULL",
        "connector_id": "connector_id" if "connector_id" in columns else "''",
        "job_type": "job_type" if "job_type" in columns else "'connector_sync'",
        "idempotency_key": "idempotency_key" if "idempotency_key" in columns else "NULL",
        "status": "status" if "status" in columns else "'pending'",
        "attempt_count": "attempt_count" if "attempt_count" in columns else "0",
        "max_attempts": "max_attempts" if "max_attempts" in columns else "3",
        "error_type": "error_type" if "error_type" in columns else "NULL",
        "error_message": "error_message" if "error_message" in columns else "NULL",
        "result_metadata_json": (
            "CASE WHEN result_metadata_json IS NOT NULL AND result_metadata_json NOT IN ('', '{}') THEN result_metadata_json "
            "WHEN result_metadata IS NOT NULL AND result_metadata != '' THEN result_metadata ELSE '{}' END"
            if "result_metadata" in columns
            else "COALESCE(NULLIF(result_metadata_json, ''), '{}')"
        ),
        "created_at": "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP",
        "queued_at": (
            "queued_at" if "queued_at" in columns
            else ("created_at" if "created_at" in columns else "CURRENT_TIMESTAMP")
        ),
        "available_at": "available_at" if "available_at" in columns else "NULL",
        "lease_expires_at": "lease_expires_at" if "lease_expires_at" in columns else "NULL",
        "locked_by": "locked_by" if "locked_by" in columns else "NULL",
        "dead_lettered_at": "dead_lettered_at" if "dead_lettered_at" in columns else "NULL",
        "started_at": "started_at" if "started_at" in columns else "NULL",
        "completed_at": "completed_at" if "completed_at" in columns else "NULL",
    }

    await conn.execute(text("""
        CREATE TABLE sync_jobs_new (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            connector_id CHAR(32) NOT NULL,
            job_type VARCHAR(50) NOT NULL DEFAULT 'connector_sync',
            idempotency_key VARCHAR(255),
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            error_type VARCHAR(100),
            error_message TEXT,
            result_metadata_json TEXT NOT NULL DEFAULT '{}',
            queued_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            available_at DATETIME,
            lease_expires_at DATETIME,
            locked_by VARCHAR(255),
            dead_lettered_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            started_at DATETIME,
            completed_at DATETIME,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(connector_id) REFERENCES connectors (id)
        )
    """))
    await conn.execute(text(f"""
        INSERT INTO sync_jobs_new (
            id, workspace_id, connector_id, job_type, idempotency_key,
            status, attempt_count, max_attempts, error_type, error_message,
            result_metadata_json, queued_at, available_at, lease_expires_at,
            locked_by, dead_lettered_at, created_at, started_at, completed_at
        )
        SELECT
            {exprs["id"]},
            {exprs["workspace_id"]},
            {exprs["connector_id"]},
            {exprs["job_type"]},
            {exprs["idempotency_key"]},
            {exprs["status"]},
            {exprs["attempt_count"]},
            {exprs["max_attempts"]},
            {exprs["error_type"]},
            {exprs["error_message"]},
            {exprs["result_metadata_json"]},
            {exprs["queued_at"]},
            {exprs["available_at"]},
            {exprs["lease_expires_at"]},
            {exprs["locked_by"]},
            {exprs["dead_lettered_at"]},
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
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_workspace_status ON sync_jobs (workspace_id, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_idempotency_key ON sync_jobs (idempotency_key)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_job_type_status ON sync_jobs (job_type, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_queue_due ON sync_jobs (job_type, status, available_at)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_sync_jobs_lease_expires_at ON sync_jobs (lease_expires_at)"
    ))


async def _migrate_components_temporal(conn: AsyncConnection) -> None:
    """Add temporal column to existing components table if missing."""
    columns = await _get_table_columns(conn, "components")
    if not columns or "temporal" in columns:
        return

    await conn.execute(text(
        "ALTER TABLE components ADD COLUMN temporal VARCHAR(20) NOT NULL DEFAULT 'unknown'"
    ))


async def _migrate_component_identity_keys(conn: AsyncConnection) -> None:
    """Backfill deterministic component identity keys for relationship resolution."""
    columns = await _get_table_columns(conn, "components")
    if not columns:
        return

    if "identity_key" not in columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN identity_key VARCHAR(255)"))
        columns = await _get_table_columns(conn, "components")

    if "name" not in columns or "identity_key" not in columns:
        return

    result = await conn.execute(text("""
        SELECT id, name
        FROM components
        WHERE identity_key IS NULL OR identity_key = ''
    """))
    for component_id, name in result.fetchall():
        identity_key = identity_key_for_component_name(name)
        if not identity_key:
            continue
        await conn.execute(
            text("UPDATE components SET identity_key = :identity_key WHERE id = :id"),
            {"identity_key": identity_key, "id": component_id},
        )


async def _migrate_entities_schema(conn: AsyncConnection) -> None:
    """Create first-class entities and attach existing components by identity key."""
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS entities (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            model_id CHAR(32),
            identity_key VARCHAR(255) NOT NULL,
            canonical_name VARCHAR(255) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(model_id) REFERENCES models (id)
        )
    """))

    component_columns = await _get_table_columns(conn, "components")
    if component_columns and "entity_id" not in component_columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN entity_id CHAR(32)"))
        component_columns = await _get_table_columns(conn, "components")

    if not component_columns or not {"entity_id", "identity_key", "name", "model_id"} <= component_columns:
        return

    workspace_expr = "workspace_id" if "workspace_id" in component_columns else "NULL"
    order_expr = "created_at" if "created_at" in component_columns else "id"
    component_rows = (await conn.execute(text(f"""
        SELECT {workspace_expr} AS workspace_id, identity_key, model_id, name
        FROM components
        WHERE identity_key IS NOT NULL
          AND identity_key != ''
        ORDER BY identity_key, {order_expr}
    """))).fetchall()

    rows_by_identity: dict[tuple[object, str], object] = {}
    for row in component_rows:
        key = (row[0], str(row[1]))
        rows_by_identity.setdefault(key, row)

    for workspace_id, identity_key, model_id, canonical_name in rows_by_identity.values():
        entity_id = await _entity_id_for_identity(conn, workspace_id, identity_key)
        if entity_id is None:
            entity_id = uuid4().hex
            await conn.execute(text("""
                INSERT INTO entities (
                    id, workspace_id, model_id, identity_key, canonical_name
                ) VALUES (
                    :id, :workspace_id, :model_id, :identity_key, :canonical_name
                )
            """), {
                "id": entity_id,
                "workspace_id": workspace_id,
                "model_id": model_id,
                "identity_key": identity_key,
                "canonical_name": _canonical_entity_name(canonical_name, identity_key),
            })

        if "workspace_id" in component_columns and workspace_id not in (None, ""):
            await conn.execute(text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
                  AND workspace_id = :workspace_id
            """), {
                "entity_id": entity_id,
                "identity_key": identity_key,
                "workspace_id": workspace_id,
            })
        elif "workspace_id" in component_columns:
            await conn.execute(text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
                  AND (workspace_id IS NULL OR workspace_id = '')
            """), {
                "entity_id": entity_id,
                "identity_key": identity_key,
            })
        else:
            await conn.execute(text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
            """), {
                "entity_id": entity_id,
                "identity_key": identity_key,
            })


async def _entity_id_for_identity(
    conn: AsyncConnection,
    workspace_id: object,
    identity_key: str,
) -> str | None:
    if workspace_id in (None, ""):
        return await conn.scalar(text("""
            SELECT id FROM entities
            WHERE identity_key = :identity_key
              AND (workspace_id IS NULL OR workspace_id = '')
            ORDER BY created_at
            LIMIT 1
        """), {"identity_key": identity_key})

    return await conn.scalar(text("""
        SELECT id FROM entities
        WHERE identity_key = :identity_key
          AND workspace_id = :workspace_id
        ORDER BY created_at
        LIMIT 1
    """), {
        "identity_key": identity_key,
        "workspace_id": workspace_id,
    })


def _canonical_entity_name(value: object, identity_key: str) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        name = identity_key.removeprefix("component:").replace("-", " ")
    return name[:255]


async def _migrate_fact_identity_schema(conn: AsyncConnection) -> None:
    """Create alias, fact, and mention tables and backfill from components."""
    datetime_type = _datetime_column_type(conn)
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS entity_aliases (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            entity_id CHAR(32) NOT NULL,
            source_document_id CHAR(32),
            alias VARCHAR(255) NOT NULL,
            normalized_alias VARCHAR(255) NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 1.0,
            created_at {datetime_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(entity_id) REFERENCES entities (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id),
            UNIQUE(entity_id, normalized_alias)
        )
    """))
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS facts (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            entity_id CHAR(32),
            component_id CHAR(32) NOT NULL,
            source_document_id CHAR(32) NOT NULL,
            claim TEXT NOT NULL,
            fact_type VARCHAR(50) NOT NULL DEFAULT 'fact',
            confidence FLOAT NOT NULL DEFAULT 0.5,
            status VARCHAR(50) NOT NULL DEFAULT 'active',
            provenance TEXT,
            excerpt TEXT,
            extractor_version VARCHAR(50) NOT NULL DEFAULT 'extractor.v1',
            created_at {datetime_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at {datetime_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(entity_id) REFERENCES entities (id),
            FOREIGN KEY(component_id) REFERENCES components (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id),
            UNIQUE(component_id)
        )
    """))
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS mentions (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            entity_id CHAR(32),
            source_document_id CHAR(32) NOT NULL,
            component_id CHAR(32),
            mention_text VARCHAR(255) NOT NULL,
            normalized_mention VARCHAR(255) NOT NULL,
            start_char INTEGER,
            end_char INTEGER,
            confidence FLOAT NOT NULL DEFAULT 0.8,
            created_at {datetime_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(entity_id) REFERENCES entities (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id),
            FOREIGN KEY(component_id) REFERENCES components (id),
            UNIQUE(component_id, normalized_mention)
        )
    """))

    component_columns = await _get_table_columns(conn, "components")
    if not component_columns or not {"id", "name", "value", "source_document_id"} <= component_columns:
        return

    workspace_expr = "workspace_id" if "workspace_id" in component_columns else "NULL"
    entity_expr = "entity_id" if "entity_id" in component_columns else "NULL"
    fact_type_expr = "fact_type" if "fact_type" in component_columns else "'fact'"
    confidence_expr = "confidence" if "confidence" in component_columns else "0.5"
    status_expr = "status" if "status" in component_columns else "'active'"
    provenance_expr = "provenance" if "provenance" in component_columns else "NULL"
    excerpt_expr = "excerpt" if "excerpt" in component_columns else "NULL"
    result = await conn.execute(text(f"""
        SELECT id, {workspace_expr} AS workspace_id, {entity_expr} AS entity_id,
               source_document_id, name, value, {fact_type_expr} AS fact_type,
               {confidence_expr} AS confidence, {status_expr} AS status,
               {provenance_expr} AS provenance, {excerpt_expr} AS excerpt
        FROM components
    """))
    rows = result.fetchall()
    for row in rows:
        component_id = row[0]
        workspace_id = row[1]
        entity_id = row[2]
        source_document_id = row[3]
        name = str(row[4] or "").strip()
        value = str(row[5] or "").strip()
        normalized = normalize_identity_text(name)
        if entity_id and normalized:
            await _insert_entity_alias_if_missing(
                conn,
                workspace_id=workspace_id,
                entity_id=entity_id,
                source_document_id=source_document_id,
                alias=name,
                normalized_alias=normalized,
                confidence=row[7],
            )
        claim = f"{name}: {value}" if name and value else (name or value or "fact")
        await _insert_fact_if_missing(
            conn,
            workspace_id=workspace_id,
            entity_id=entity_id,
            component_id=component_id,
            source_document_id=source_document_id,
            claim=claim,
            fact_type=row[6] or "fact",
            confidence=row[7],
            status=row[8] or "active",
            provenance=row[9],
            excerpt=row[10],
        )
        if normalized:
            await _insert_mention_if_missing(
                conn,
                workspace_id=workspace_id,
                entity_id=entity_id,
                source_document_id=source_document_id,
                component_id=component_id,
                mention_text=name,
                normalized_mention=normalized,
                confidence=row[7],
            )


async def _insert_entity_alias_if_missing(
    conn: AsyncConnection,
    *,
    workspace_id: object,
    entity_id: object,
    source_document_id: object,
    alias: str,
    normalized_alias: str,
    confidence: object,
) -> None:
    exists = await conn.scalar(text("""
        SELECT 1 FROM entity_aliases
        WHERE entity_id = :entity_id
          AND normalized_alias = :normalized_alias
        LIMIT 1
    """), {"entity_id": entity_id, "normalized_alias": normalized_alias})
    if exists:
        return
    await conn.execute(text("""
        INSERT INTO entity_aliases (
            id, workspace_id, entity_id, source_document_id,
            alias, normalized_alias, confidence
        ) VALUES (
            :id, :workspace_id, :entity_id, :source_document_id,
            :alias, :normalized_alias, :confidence
        )
    """), {
        "id": uuid4().hex,
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "source_document_id": source_document_id,
        "alias": alias[:255] or normalized_alias[:255],
        "normalized_alias": normalized_alias[:255],
        "confidence": _safe_confidence(confidence, 1.0),
    })


async def _insert_fact_if_missing(
    conn: AsyncConnection,
    *,
    workspace_id: object,
    entity_id: object,
    component_id: object,
    source_document_id: object,
    claim: str,
    fact_type: object,
    confidence: object,
    status: object,
    provenance: object,
    excerpt: object,
) -> None:
    exists = await conn.scalar(text("""
        SELECT 1 FROM facts
        WHERE component_id = :component_id
        LIMIT 1
    """), {"component_id": component_id})
    if exists:
        return
    await conn.execute(text("""
        INSERT INTO facts (
            id, workspace_id, entity_id, component_id, source_document_id,
            claim, fact_type, confidence, status, provenance, excerpt,
            extractor_version
        ) VALUES (
            :id, :workspace_id, :entity_id, :component_id, :source_document_id,
            :claim, :fact_type, :confidence, :status, :provenance, :excerpt,
            :extractor_version
        )
    """), {
        "id": uuid4().hex,
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "component_id": component_id,
        "source_document_id": source_document_id,
        "claim": claim,
        "fact_type": str(fact_type or "fact")[:50],
        "confidence": _safe_confidence(confidence, 0.5),
        "status": str(status or "active")[:50],
        "provenance": provenance,
        "excerpt": excerpt,
        "extractor_version": "extractor.v1",
    })


async def _insert_mention_if_missing(
    conn: AsyncConnection,
    *,
    workspace_id: object,
    entity_id: object,
    source_document_id: object,
    component_id: object,
    mention_text: str,
    normalized_mention: str,
    confidence: object,
) -> None:
    exists = await conn.scalar(text("""
        SELECT 1 FROM mentions
        WHERE component_id = :component_id
          AND normalized_mention = :normalized_mention
        LIMIT 1
    """), {
        "component_id": component_id,
        "normalized_mention": normalized_mention,
    })
    if exists:
        return
    await conn.execute(text("""
        INSERT INTO mentions (
            id, workspace_id, entity_id, source_document_id, component_id,
            mention_text, normalized_mention, confidence
        ) VALUES (
            :id, :workspace_id, :entity_id, :source_document_id, :component_id,
            :mention_text, :normalized_mention, :confidence
        )
    """), {
        "id": uuid4().hex,
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "source_document_id": source_document_id,
        "component_id": component_id,
        "mention_text": (mention_text or normalized_mention)[:255],
        "normalized_mention": normalized_mention[:255],
        "confidence": _safe_confidence(confidence, 0.8),
    })


def _safe_confidence(value: object, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return min(max(confidence, 0.0), 1.0)


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
    if conn.dialect.name == "postgresql":
        try:
            result = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            """), {"table_name": table_name})
            return {str(row[0]) for row in result.fetchall()}
        except Exception:
            return set()

    try:
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        rows = result.fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()


def _datetime_column_type(conn: AsyncConnection) -> str:
    return "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"


async def _ensure_default_workspace(conn: AsyncConnection) -> str:
    if not await _table_exists(conn, "workspaces"):
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


async def _table_exists(conn: AsyncConnection, table_name: str) -> bool:
    if conn.dialect.name == "postgresql":
        try:
            result = await conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                )
            """), {"table_name": table_name})
            return bool(result.scalar())
        except Exception:
            return False

    rows = (await conn.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
    return bool(rows)


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


async def _migrate_retrieval_events_schema(conn: AsyncConnection) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS retrieval_events (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            schema_version VARCHAR(50) NOT NULL DEFAULT 'query.v1',
            confidence FLOAT NOT NULL DEFAULT 0.0,
            top_k INTEGER NOT NULL DEFAULT 8,
            min_confidence FLOAT NOT NULL DEFAULT 0.0,
            hybrid BOOLEAN NOT NULL DEFAULT 1,
            component_count INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0,
            trace_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """))


async def _migrate_pgvector_search_schema(conn: AsyncConnection) -> None:
    """Enable native Postgres vector retrieval when pgvector is installed."""
    if conn.dialect.name != "postgresql":
        return
    if not await _pgvector_extension_available(conn):
        return

    try:
        async with conn.begin_nested():
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        return

    columns = await _get_table_columns(conn, "components")
    if not columns:
        return

    if "embedding_vector" not in columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN embedding_vector vector"))

    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION ce_try_vector(raw text) RETURNS vector AS $$
        BEGIN
            IF raw IS NULL OR btrim(raw) = '' THEN
                RETURN NULL;
            END IF;
            RETURN raw::vector;
        EXCEPTION WHEN others THEN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE
    """))
    await conn.execute(text("""
        UPDATE components
        SET embedding_vector = ce_try_vector(embedding)
        WHERE embedding_vector IS NULL
          AND embedding IS NOT NULL
          AND embedding != ''
    """))
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION ce_sync_component_embedding_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.embedding_vector = ce_try_vector(NEW.embedding);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    await conn.execute(text("""
        DROP TRIGGER IF EXISTS trg_components_embedding_vector ON components
    """))
    await conn.execute(text("""
        CREATE TRIGGER trg_components_embedding_vector
        BEFORE INSERT OR UPDATE OF embedding ON components
        FOR EACH ROW
        EXECUTE FUNCTION ce_sync_component_embedding_vector()
    """))

    dimension = pgvector_index_dimension()
    await conn.execute(text(f"""
        CREATE INDEX IF NOT EXISTS ix_components_embedding_vector_hnsw
        ON components
        USING hnsw ((embedding_vector::vector({dimension})) vector_cosine_ops)
        WHERE embedding_vector IS NOT NULL
          AND vector_dims(embedding_vector) = {dimension}
    """))


async def _migrate_postgres_text_search_schema(conn: AsyncConnection) -> None:
    """Add Postgres-native full-text and metadata indexes."""
    if conn.dialect.name != "postgresql":
        return

    source_columns = await _get_table_columns(conn, "source_documents")
    if source_columns:
        if "metadata_jsonb" not in source_columns:
            await conn.execute(text("ALTER TABLE source_documents ADD COLUMN metadata_jsonb jsonb"))
        if "search_tsv" not in source_columns:
            await conn.execute(text("ALTER TABLE source_documents ADD COLUMN search_tsv tsvector"))

        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION ce_try_jsonb(raw text) RETURNS jsonb AS $$
            BEGIN
                IF raw IS NULL OR btrim(raw) = '' THEN
                    RETURN '{}'::jsonb;
                END IF;
                RETURN raw::jsonb;
            EXCEPTION WHEN others THEN
                RETURN '{}'::jsonb;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE
        """))
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION ce_sync_source_document_search()
            RETURNS trigger AS $$
            BEGIN
                NEW.metadata_jsonb = ce_try_jsonb(NEW.metadata);
                NEW.search_tsv =
                    setweight(to_tsvector('english', coalesce(NEW.external_id, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.source_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.author, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.content, '')), 'D');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        await conn.execute(text("""
            UPDATE source_documents
            SET metadata_jsonb = ce_try_jsonb(metadata),
                search_tsv =
                    setweight(to_tsvector('english', coalesce(external_id, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(source_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(author, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(content, '')), 'D')
            WHERE metadata_jsonb IS NULL OR search_tsv IS NULL
        """))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_source_documents_search ON source_documents"))
        await conn.execute(text("""
            CREATE TRIGGER trg_source_documents_search
            BEFORE INSERT OR UPDATE OF metadata, content, external_id, source_type, author
            ON source_documents
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_source_document_search()
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_metadata_jsonb_gin
            ON source_documents USING gin (metadata_jsonb)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_search_tsv_gin
            ON source_documents USING gin (search_tsv)
        """))

    component_columns = await _get_table_columns(conn, "components")
    if component_columns:
        if "search_tsv" not in component_columns:
            await conn.execute(text("ALTER TABLE components ADD COLUMN search_tsv tsvector"))

        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION ce_sync_component_search()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_tsv =
                    setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.fact_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.status, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.temporal, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.value, '')), 'D');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        await conn.execute(text("""
            UPDATE components
            SET search_tsv =
                setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(fact_type, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(status, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(temporal, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(value, '')), 'D')
            WHERE search_tsv IS NULL
        """))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_components_search ON components"))
        await conn.execute(text("""
            CREATE TRIGGER trg_components_search
            BEFORE INSERT OR UPDATE OF name, value, fact_type, status, temporal
            ON components
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_component_search()
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_components_search_tsv_gin
            ON components USING gin (search_tsv)
        """))


async def _pgvector_extension_available(conn: AsyncConnection) -> bool:
    try:
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'vector'
            )
        """))
        return bool(result.scalar())
    except Exception:
        return False


async def _migrate_query_and_sync_indexes(conn: AsyncConnection) -> None:
    index_specs = [
        ("source_documents", "ix_source_documents_workspace_id", ("workspace_id",)),
        (
            "source_documents",
            "ix_source_documents_workspace_source_external",
            ("workspace_id", "source_type", "external_id"),
        ),
        (
            "source_documents",
            "ix_source_documents_source_type_external_id",
            ("source_type", "external_id"),
        ),
        ("source_documents", "ix_source_documents_processed_at", ("processed_at",)),
        ("source_documents", "ix_source_documents_ingested_at", ("ingested_at",)),
        ("components", "ix_components_workspace_id", ("workspace_id",)),
        ("components", "ix_components_entity_id", ("entity_id",)),
        ("components", "ix_components_identity_key", ("identity_key",)),
        (
            "components",
            "ix_components_workspace_status_confidence",
            ("workspace_id", "status", "confidence"),
        ),
        (
            "components",
            "ix_components_workspace_model_status",
            ("workspace_id", "model_id", "status"),
        ),
        (
            "components",
            "ix_components_workspace_identity_status",
            ("workspace_id", "identity_key", "status"),
        ),
        (
            "components",
            "ix_components_workspace_entity_status",
            ("workspace_id", "entity_id", "status"),
        ),
        ("components", "ix_components_status_confidence", ("status", "confidence")),
        ("components", "ix_components_model_status", ("model_id", "status")),
        ("components", "ix_components_source_status", ("source_document_id", "status")),
        ("entities", "ix_entities_workspace_id", ("workspace_id",)),
        ("entities", "ix_entities_model_id", ("model_id",)),
        ("entities", "ix_entities_identity_key", ("identity_key",)),
        (
            "entities",
            "ix_entities_workspace_identity",
            ("workspace_id", "identity_key"),
        ),
        (
            "entity_aliases",
            "ix_entity_aliases_workspace_normalized",
            ("workspace_id", "normalized_alias"),
        ),
        ("entity_aliases", "ix_entity_aliases_entity", ("entity_id",)),
        (
            "facts",
            "ix_facts_workspace_status_confidence",
            ("workspace_id", "status", "confidence"),
        ),
        ("facts", "ix_facts_workspace_entity", ("workspace_id", "entity_id")),
        ("facts", "ix_facts_source_document", ("source_document_id",)),
        (
            "mentions",
            "ix_mentions_workspace_normalized",
            ("workspace_id", "normalized_mention"),
        ),
        ("mentions", "ix_mentions_entity", ("entity_id",)),
        ("mentions", "ix_mentions_source_document", ("source_document_id",)),
        ("sync_jobs", "ix_sync_jobs_workspace_status", ("workspace_id", "status")),
        ("sync_jobs", "ix_sync_jobs_idempotency_key", ("idempotency_key",)),
        ("sync_jobs", "ix_sync_jobs_job_type_status", ("job_type", "status")),
        ("sync_jobs", "ix_sync_jobs_queue_due", ("job_type", "status", "available_at")),
        ("sync_jobs", "ix_sync_jobs_lease_expires_at", ("lease_expires_at",)),
        ("relationships", "ix_relationships_status_origin", ("status", "origin")),
        ("relationships", "ix_relationships_source_status", ("source_component_id", "status")),
        ("relationships", "ix_relationships_target_status", ("target_component_id", "status")),
        (
            "relationships",
            "ix_relationships_source_target_type",
            ("source_component_id", "target_component_id", "relationship_type"),
        ),
        (
            "retrieval_events",
            "ix_retrieval_events_workspace_created",
            ("workspace_id", "created_at"),
        ),
        ("retrieval_events", "ix_retrieval_events_created_at", ("created_at",)),
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
