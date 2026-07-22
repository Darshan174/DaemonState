from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import Base
from app.services.identity import identity_key_for_component_name, normalize_identity_text
from app.services.vector_search import pgvector_index_dimension
from app.source_identity import canonical_source_identity_sha256
from app.taxonomy import default_trust_zone_for_source


async def run_migrations(conn: AsyncConnection) -> None:
    await _migrate_connectors_workspace_schema(conn)
    await _migrate_workspace_lifecycle_schema(conn)
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
    await _migrate_evidence_ledger_and_claim_graph(conn)
    await _migrate_unresolved_relationships_schema(conn)
    await _migrate_retrieval_events_schema(conn)
    await _migrate_pgvector_search_schema(conn)
    await _migrate_postgres_text_search_schema(conn)
    await _migrate_founder_oversight_schema(conn)
    await _migrate_workspace_goals_schema(conn)
    await _migrate_deterministic_project_compiler_schema(conn)
    await _migrate_truth_access_schema(conn)
    await _migrate_learning_loop_schema(conn)
    await _migrate_work_checkpoint_schema(conn)
    await _migrate_query_and_sync_indexes(conn)


async def _migrate_work_checkpoint_schema(conn: AsyncConnection) -> None:
    """Create the append-only session checkpoint ledger on existing installations."""

    required = {"workspaces", "source_documents", "run_observations"}
    available = {
        name for name in required if await _get_table_columns(conn, name)
    }
    if available != required:
        return

    def _create(sync_conn) -> None:
        for table_name in (
            "session_events",
            "work_checkpoints",
            "checkpoint_items",
            "checkpoint_evidence",
            "checkpoint_verifications",
        ):
            Base.metadata.tables[table_name].create(sync_conn, checkfirst=True)

    await conn.run_sync(_create)
    for table_name, index_name, columns in (
        (
            "session_events",
            "uq_session_events_provider_session_event",
            ("workspace_id", "provider", "session_id", "provider_event_id"),
        ),
        (
            "work_checkpoints",
            "uq_work_checkpoints_boundary_schema",
            (
                "workspace_id",
                "provider",
                "session_id",
                "boundary_event_id",
                "schema_version",
            ),
        ),
    ):
        existing_columns = await conn.run_sync(
            lambda sync_conn, table=table_name, index=index_name: next(
                (
                    tuple(item.get("column_names") or ())
                    for item in inspect(sync_conn).get_indexes(table)
                    if item.get("name") == index
                ),
                (),
            )
        )
        if existing_columns and existing_columns != columns:
            await conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        joined = ", ".join(columns)
        await conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({joined})"
        ))


async def _migrate_workspace_lifecycle_schema(conn: AsyncConnection) -> None:
    """Add project/sample identity and archive state to legacy workspaces."""
    columns = await _get_table_columns(conn, "workspaces")
    if not columns:
        return
    timestamp = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
    added_kind = "kind" not in columns
    if added_kind:
        await conn.execute(text(
            "ALTER TABLE workspaces ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'project'"
        ))
    if "status" not in columns:
        await conn.execute(text(
            "ALTER TABLE workspaces ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'active'"
        ))
    if "archived_at" not in columns:
        await conn.execute(text(
            f"ALTER TABLE workspaces ADD COLUMN archived_at {timestamp}"
        ))
    if added_kind:
        await conn.execute(text(
            "UPDATE workspaces SET kind = 'demo' "
            "WHERE lower(name) LIKE '%demo%' OR lower(slug) LIKE '%demo%'"
        ))
        await conn.execute(text(
            "UPDATE workspaces SET kind = 'sandbox' "
            "WHERE lower(name) = 'default' OR lower(slug) = 'default'"
        ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_workspaces_kind ON workspaces (kind)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_workspaces_status ON workspaces (status)"
    ))


async def _migrate_workspace_goals_schema(conn: AsyncConnection) -> None:
    """Create explicit workspace-goal history without inferring goals from packs."""
    timestamp = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
    uuid_type = "UUID" if conn.dialect.name == "postgresql" else "CHAR(32)"
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS workspace_goals (
            id {uuid_type} PRIMARY KEY,
            workspace_id {uuid_type} NOT NULL REFERENCES workspaces(id),
            title TEXT NOT NULL,
            component_id {uuid_type} REFERENCES components(id),
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            source_kind VARCHAR(32) NOT NULL DEFAULT 'user_selected',
            source_id VARCHAR(255),
            selected_by VARCHAR(255) NOT NULL DEFAULT 'local_user',
            selected_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at {timestamp},
            created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_workspace_goals_workspace_selected "
        "ON workspace_goals (workspace_id, selected_at)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_workspace_goals_component "
        "ON workspace_goals (component_id)"
    ))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_goals_one_active "
        "ON workspace_goals (workspace_id) WHERE status = 'active'"
    ))


async def _migrate_learning_loop_schema(conn: AsyncConnection) -> None:
    """Create durable open-loop and verified-playbook workflow tables."""
    timestamp = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
    uuid_type = "UUID" if conn.dialect.name == "postgresql" else "CHAR(32)"
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS open_loops (
            id {uuid_type} PRIMARY KEY,
            workspace_id {uuid_type} NOT NULL REFERENCES workspaces(id),
            natural_key VARCHAR(64) NOT NULL,
            rule_id VARCHAR(100) NOT NULL,
            rule_version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(32) NOT NULL DEFAULT 'open',
            severity VARCHAR(32) NOT NULL DEFAULT 'warning',
            title TEXT NOT NULL,
            explanation TEXT NOT NULL,
            next_action TEXT,
            context_pack_id {uuid_type} REFERENCES context_packs(id),
            run_id {uuid_type} REFERENCES agent_runs(id),
            focus_component_id {uuid_type} REFERENCES components(id),
            trigger_ids_json TEXT NOT NULL DEFAULT '[]',
            sources_json TEXT NOT NULL DEFAULT '[]',
            assigned_to VARCHAR(255),
            resolution_reason TEXT,
            resolution_source_document_id {uuid_type} REFERENCES source_documents(id),
            first_seen_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at {timestamp},
            created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_loops_natural_key "
        "ON open_loops (natural_key)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_open_loops_workspace_status "
        "ON open_loops (workspace_id, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_open_loops_focus_status "
        "ON open_loops (focus_component_id, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_open_loops_pack_rule "
        "ON open_loops (context_pack_id, rule_id)"
    ))

    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS verified_playbooks (
            id {uuid_type} PRIMARY KEY,
            workspace_id {uuid_type} NOT NULL REFERENCES workspaces(id),
            identity_key VARCHAR(64) NOT NULL,
            objective_fingerprint VARCHAR(64) NOT NULL,
            objective_pattern TEXT NOT NULL,
            repository_identity VARCHAR(512),
            repository_snapshot VARCHAR(255),
            status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
            ordered_steps_json TEXT NOT NULL DEFAULT '[]',
            verification_commands_json TEXT NOT NULL DEFAULT '[]',
            source_run_id {uuid_type} NOT NULL REFERENCES agent_runs(id),
            supporting_run_ids_json TEXT NOT NULL DEFAULT '[]',
            source_document_ids_json TEXT NOT NULL DEFAULT '[]',
            successful_run_count INTEGER NOT NULL DEFAULT 1,
            last_verified_at {timestamp} NOT NULL,
            approved_at {timestamp},
            review_reason TEXT,
            review_source_document_id {uuid_type} REFERENCES source_documents(id),
            created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_verified_playbooks_identity_key "
        "ON verified_playbooks (identity_key)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_verified_playbooks_workspace_status "
        "ON verified_playbooks (workspace_id, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_verified_playbooks_objective "
        "ON verified_playbooks (workspace_id, objective_fingerprint)"
    ))


async def _migrate_truth_access_schema(conn: AsyncConnection) -> None:
    """Add conservative bi-temporal and evidence-permission storage."""
    timestamp = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
    uuid_type = "UUID" if conn.dialect.name == "postgresql" else "CHAR(32)"
    for table_name in ("source_documents", "evidence_spans"):
        columns = await _get_table_columns(conn, table_name)
        if not columns:
            continue
        additions = {
            "visibility_scope": "VARCHAR(32) NOT NULL DEFAULT 'workspace'",
            "permission_source": "VARCHAR(64) NOT NULL DEFAULT 'workspace_default'",
            "permission_observed_at": f"{timestamp} NULL",
            "permission_snapshot_sha256": "VARCHAR(64) NULL",
        }
        for name, ddl in additions.items():
            if name not in columns:
                await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))

    source_columns = await _get_table_columns(conn, "source_documents")
    if {"id", "ingested_at", "permission_snapshot_sha256"} <= source_columns:
        rows = (await conn.execute(text(
            "SELECT id, permission_snapshot_sha256 FROM source_documents"
        ))).all()
        for row in rows:
            snapshot = row[1] or _migration_canonical_hash([
                "workspace", "workspace_default", str(row[0])
            ])
            await conn.execute(text(
                "UPDATE source_documents SET visibility_scope='workspace', "
                "permission_source=COALESCE(permission_source, 'workspace_default'), "
                "permission_observed_at=COALESCE(permission_observed_at, ingested_at), "
                "permission_snapshot_sha256=:snapshot WHERE id=:id"
            ), {"snapshot": snapshot, "id": row[0]})
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_source_documents_visibility_scope "
            "ON source_documents (visibility_scope)"
        ))
    evidence_columns = await _get_table_columns(conn, "evidence_spans")
    if {"source_document_id", "permission_snapshot_sha256"} <= evidence_columns:
        await conn.execute(text(
            "UPDATE evidence_spans SET "
            "visibility_scope=(SELECT visibility_scope FROM source_documents WHERE "
            "source_documents.id=evidence_spans.source_document_id), "
            "permission_source=(SELECT permission_source FROM source_documents WHERE "
            "source_documents.id=evidence_spans.source_document_id), "
            "permission_observed_at=(SELECT permission_observed_at FROM source_documents WHERE "
            "source_documents.id=evidence_spans.source_document_id), "
            "permission_snapshot_sha256=(SELECT permission_snapshot_sha256 FROM source_documents "
            "WHERE source_documents.id=evidence_spans.source_document_id) "
            "WHERE permission_snapshot_sha256 IS NULL OR permission_snapshot_sha256=''"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_evidence_spans_visibility_scope "
            "ON evidence_spans (visibility_scope)"
        ))

    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS source_read_grants (
            id {uuid_type} PRIMARY KEY,
            workspace_id {uuid_type} NOT NULL REFERENCES workspaces(id),
            source_document_id {uuid_type} NOT NULL REFERENCES source_documents(id),
            principal_id VARCHAR(255) NOT NULL,
            grant_key VARCHAR(64) NOT NULL,
            permission_snapshot_sha256 VARCHAR(64) NOT NULL,
            created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_read_grants_grant_key "
        "ON source_read_grants (grant_key)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_source_read_grants_document_principal "
        "ON source_read_grants (source_document_id, principal_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_source_read_grants_workspace_principal "
        "ON source_read_grants (workspace_id, principal_id)"
    ))

    claim_columns = await _get_table_columns(conn, "claims")
    if claim_columns and "scope_identity_sha256" not in claim_columns:
        await conn.execute(text(
            "ALTER TABLE claims ADD COLUMN scope_identity_sha256 VARCHAR(64) NULL"
        ))
    if claim_columns:
        rows = (await conn.execute(text(
            "SELECT id, workspace_id, identity_key, claim_type, scope_identity_sha256 FROM claims"
        ))).all()
        seen: set[str] = set()
        for row in rows:
            key = row[4] or _migration_canonical_hash([
                _migration_uuid_text(row[1]) or "global", row[3], row[2]
            ])
            if key in seen:
                raise RuntimeError(
                    "duplicate claim identities detected; reconcile claims before migration"
                )
            seen.add(key)
            await conn.execute(text(
                "UPDATE claims SET scope_identity_sha256=:key WHERE id=:id"
            ), {"key": key, "id": row[0]})
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_claims_scope_identity_sha256 "
            "ON claims (scope_identity_sha256)"
        ))

    revision_columns = await _get_table_columns(conn, "claim_revisions")
    if revision_columns:
        additions = {
            "revision_key": "VARCHAR(64) NULL",
            "valid_from": f"{timestamp} NULL",
            "valid_to": f"{timestamp} NULL",
            "observed_at": f"{timestamp} NULL",
            "transaction_to": f"{timestamp} NULL",
            "validity_basis": "VARCHAR(32) NOT NULL DEFAULT 'unknown'",
        }
        for name, ddl in additions.items():
            if name not in revision_columns:
                await conn.execute(text(
                    f"ALTER TABLE claim_revisions ADD COLUMN {name} {ddl}"
                ))
        rows = (await conn.execute(text(
            "SELECT id, claim_id, evidence_span_id, operation, value, created_at, "
            "revision_key FROM claim_revisions"
        ))).all()
        for row in rows:
            key = row[6] or _migration_canonical_hash([
                "legacy", str(row[0]), str(row[1]), str(row[2]), row[3], row[4]
            ])
            await conn.execute(text(
                "UPDATE claim_revisions SET revision_key=:key, "
                "observed_at=COALESCE(observed_at, created_at), "
                "validity_basis=COALESCE(validity_basis, 'unknown') WHERE id=:id"
            ), {"key": key, "id": row[0]})
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_revisions_revision_key "
            "ON claim_revisions (revision_key)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_claim_revisions_claim_valid "
            "ON claim_revisions (claim_id, valid_from, valid_to)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_claim_revisions_claim_transaction "
            "ON claim_revisions (claim_id, created_at, transaction_to)"
        ))

    if conn.dialect.name == "postgresql":
        for table_name, column_names in {
            "source_documents": ("permission_observed_at", "permission_snapshot_sha256"),
            "evidence_spans": ("permission_observed_at", "permission_snapshot_sha256"),
            "claims": ("scope_identity_sha256",),
            "claim_revisions": ("revision_key", "observed_at"),
        }.items():
            columns = await _get_table_columns(conn, table_name)
            for column_name in column_names:
                if column_name in columns:
                    await conn.execute(text(
                        f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL"
                    ))


async def _migrate_deterministic_project_compiler_schema(conn: AsyncConnection) -> None:
    """Backfill stable code identities and source-backed deterministic edge fields."""
    additions = {
        "code_files": {
            "identity_key": "VARCHAR(64) NULL",
            "is_test": "BOOLEAN NOT NULL DEFAULT false",
        },
        "code_symbols": {"identity_key": "VARCHAR(64) NULL"},
        "code_edges": {
            "edge_key": "VARCHAR(64) NULL",
            "rule_id": "VARCHAR(100) NULL",
            "rule_version": "VARCHAR(32) NULL",
            "evidence_path": "TEXT NULL",
            "evidence_start_line": "INTEGER NULL",
            "evidence_end_line": "INTEGER NULL",
            "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
            "evidence_sha256": "VARCHAR(64) NULL",
            "snapshot_commit": "VARCHAR(100) NULL",
            "snapshot_dirty": "BOOLEAN NOT NULL DEFAULT false",
            "snapshot_fingerprint": "VARCHAR(64) NULL",
        },
    }
    for table_name, columns_to_add in additions.items():
        columns = await _get_table_columns(conn, table_name)
        if not columns:
            continue
        for column_name, ddl in columns_to_add.items():
            if column_name not in columns:
                await conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"
                ))

    file_columns = await _get_table_columns(conn, "code_files")
    if {"id", "workspace_id", "repo_root", "path", "identity_key"} <= file_columns:
        rows = (await conn.execute(text(
            "SELECT id, workspace_id, repo_root, path, identity_key FROM code_files"
        ))).all()
        natural_keys: set[tuple[object, object, str]] = set()
        for row in rows:
            natural_key = (
                _migration_uuid_text(row[1]),
                str(row[2]) if row[2] is not None else None,
                str(row[3]).replace("\\", "/"),
            )
            if natural_key in natural_keys:
                raise RuntimeError(
                    "duplicate code_files identities detected; re-index the workspace "
                    "before applying the deterministic project compiler migration"
                )
            natural_keys.add(natural_key)
            identity_key = row[4] or _migration_canonical_hash(list(natural_key))
            await conn.execute(
                text("UPDATE code_files SET identity_key = :key WHERE id = :id"),
                {"key": identity_key, "id": row[0]},
            )
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_code_files_identity_key "
            "ON code_files (identity_key)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_code_files_workspace_root_path "
            "ON code_files (workspace_id, repo_root, path)"
        ))

    symbol_columns = await _get_table_columns(conn, "code_symbols")
    required_symbols = {
        "id", "code_file_id", "symbol_type", "name", "qualified_name",
        "start_line", "end_line", "identity_key",
    }
    if required_symbols <= symbol_columns:
        rows = (await conn.execute(text(
            "SELECT id, code_file_id, symbol_type, name, qualified_name, "
            "start_line, end_line, identity_key FROM code_symbols"
        ))).all()
        for row in rows:
            identity_key = row[7] or _migration_canonical_hash([
                _migration_uuid_text(row[1]), row[2], row[4] or row[3], row[5], row[6]
            ])
            await conn.execute(
                text("UPDATE code_symbols SET identity_key = :key WHERE id = :id"),
                {"key": identity_key, "id": row[0]},
            )
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_code_symbols_identity_key "
            "ON code_symbols (identity_key)"
        ))

    edge_columns = await _get_table_columns(conn, "code_edges")
    if {"id", "edge_key", "rule_id", "rule_version", "evidence_json", "evidence_sha256"} <= edge_columns:
        rows = (await conn.execute(text(
            "SELECT id, edge_key, rule_id, rule_version, evidence_json, evidence_sha256 "
            "FROM code_edges"
        ))).all()
        for row in rows:
            evidence_json = row[4]
            if not evidence_json or evidence_json == "{}":
                evidence_json = json.dumps(
                    {"legacy_edge_id": str(row[0])},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            values = {
                "id": row[0],
                "edge_key": row[1] or _migration_canonical_hash(["legacy", str(row[0])]),
                "rule_id": row[2] or "legacy.unspecified",
                "rule_version": row[3] or "0",
                "evidence_json": evidence_json,
                "evidence_sha256": row[5] or hashlib.sha256(
                    evidence_json.encode("utf-8")
                ).hexdigest(),
            }
            await conn.execute(text(
                "UPDATE code_edges SET edge_key = :edge_key, rule_id = :rule_id, "
                "rule_version = :rule_version, evidence_json = :evidence_json, "
                "evidence_sha256 = :evidence_sha256 WHERE id = :id"
            ), values)
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_code_edges_edge_key "
            "ON code_edges (edge_key)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_code_edges_rule_source "
            "ON code_edges (rule_id, source_symbol_id)"
        ))
    await _enforce_deterministic_project_compiler_not_null(conn)


async def _enforce_deterministic_project_compiler_not_null(
    conn: AsyncConnection,
) -> None:
    required = {
        "code_files": ("identity_key",),
        "code_symbols": ("identity_key",),
        "code_edges": ("edge_key", "rule_id", "rule_version", "evidence_sha256"),
    }
    if conn.dialect.name == "postgresql":
        for table_name, column_names in required.items():
            columns = await _get_table_columns(conn, table_name)
            for column_name in column_names:
                if column_name in columns:
                    await conn.execute(text(
                        f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL"
                    ))
        return
    if conn.dialect.name != "sqlite":
        return

    # SQLite cannot tighten an added column in place. Enforce the same write
    # invariant for upgraded databases with deterministic insert/update guards.
    for table_name, column_names in required.items():
        columns = await _get_table_columns(conn, table_name)
        for column_name in column_names:
            if column_name not in columns:
                continue
            for operation, reference in (("INSERT", "NEW"), ("UPDATE", "NEW")):
                trigger_name = (
                    f"trg_{table_name}_{column_name}_not_null_{operation.lower()}"
                )
                await conn.execute(text(f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE {operation} ON {table_name}
                    WHEN {reference}.{column_name} IS NULL
                    BEGIN
                        SELECT RAISE(ABORT, '{table_name}.{column_name} must not be null');
                    END
                """))


def _migration_canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _migration_uuid_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return str(value)


async def _migrate_founder_oversight_schema(conn: AsyncConnection) -> None:
    """Add nullable focus provenance and retry-safe runtime event identity."""
    uuid_type = "UUID" if conn.dialect.name == "postgresql" else "CHAR(32)"
    table_columns = {
        "context_packs": {
            "focus_component_id": f"{uuid_type} NULL",
            "objective_origin": "VARCHAR(32) NULL",
            "objective_source_document_id": f"{uuid_type} NULL",
            "objective_evidence_span_id": f"{uuid_type} NULL",
        },
        "context_pack_items": {
            "manifest_item_id": "VARCHAR(255) NULL",
        },
        "agent_runs": {
            "run_key": "VARCHAR(255) NULL",
        },
        "run_observations": {
            "event_key": "VARCHAR(255) NULL",
            "payload_json": "TEXT NOT NULL DEFAULT '{}'",
            "observed_at": "DATETIME NULL" if conn.dialect.name == "sqlite" else "TIMESTAMP NULL",
        },
    }
    for table_name, additions in table_columns.items():
        columns = await _get_table_columns(conn, table_name)
        if not columns:
            continue
        for column_name, ddl in additions.items():
            if column_name not in columns:
                await conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
                )

    context_pack_columns = await _get_table_columns(conn, "context_packs")
    if "focus_component_id" in context_pack_columns:
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_context_packs_focus_component
            ON context_packs (focus_component_id)
        """))
    if "objective_origin" in context_pack_columns:
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_context_packs_objective_origin
            ON context_packs (objective_origin)
        """))
    item_columns = await _get_table_columns(conn, "context_pack_items")
    if {"context_pack_id", "manifest_item_id"} <= item_columns:
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_context_pack_items_manifest_item_id
            ON context_pack_items (context_pack_id, manifest_item_id)
            WHERE manifest_item_id IS NOT NULL
        """))
    run_columns = await _get_table_columns(conn, "agent_runs")
    if {"context_pack_id", "run_key"} <= run_columns:
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_context_pack_run_key
            ON agent_runs (context_pack_id, run_key)
            WHERE run_key IS NOT NULL
        """))
    observation_columns = await _get_table_columns(conn, "run_observations")
    if "observed_at" in observation_columns:
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_run_observations_observed_at
            ON run_observations (observed_at)
        """))
    if {"agent_run_id", "event_key"} <= observation_columns:
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_run_observations_agent_run_event_key
            ON run_observations (agent_run_id, event_key)
            WHERE event_key IS NOT NULL
        """))


async def _migrate_workspace_ownership_columns(conn: AsyncConnection) -> None:
    """Add real workspace ownership columns and backfill from legacy metadata."""
    source_columns = await _get_table_columns(conn, "source_documents")
    if source_columns:
        if "workspace_id" not in source_columns:
            await conn.execute(
                text("ALTER TABLE source_documents ADD COLUMN workspace_id CHAR(32)")
            )
        if {"id", "source_type", "metadata"} <= source_columns:
            await _backfill_source_document_workspace_ids(conn)

    component_columns = await _get_table_columns(conn, "components")
    if component_columns:
        if "workspace_id" not in component_columns:
            await conn.execute(text("ALTER TABLE components ADD COLUMN workspace_id CHAR(32)"))
            component_columns = await _get_table_columns(conn, "components")
        updated_source_columns = await _get_table_columns(conn, "source_documents")
        if {
            "source_document_id",
            "workspace_id",
        } <= component_columns and "workspace_id" in updated_source_columns:
            await conn.execute(
                text("""
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
            """)
            )


async def _backfill_source_document_workspace_ids(conn: AsyncConnection) -> None:
    connector_workspaces = await _connector_workspaces_by_type(conn)
    result = await conn.execute(
        text("""
        SELECT id, source_type, metadata, workspace_id
        FROM source_documents
        WHERE workspace_id IS NULL
    """)
    )
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

    result = await conn.execute(
        text("""
        SELECT connector_type, workspace_id
        FROM connectors
        WHERE workspace_id IS NOT NULL
    """)
    )
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
        candidates.update(
            {
                "ai_context",
                "codex",
                "claude",
                "opencode",
                "ai_context_codex",
                "ai_context_claude_code",
                "ai_context_opencode",
            }
        )
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_created_at_from_metadata(metadata: dict) -> datetime | None:
    for key in ("source_created_at", "created_at", "timestamp", "ts"):
        value = metadata.get(key)
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


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
        await conn.execute(
            text("ALTER TABLE connectors ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'")
        )
        if "config" in columns:
            await conn.execute(
                text(
                    "UPDATE connectors SET config_json = config "
                    "WHERE config IS NOT NULL AND config != ''"
                )
            )

    if "credentials_json" not in columns:
        await conn.execute(
            text("ALTER TABLE connectors ADD COLUMN credentials_json TEXT NOT NULL DEFAULT '{}'")
        )

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
        "workspace_id": "workspace_id"
        if "workspace_id" in columns
        else f"'{default_workspace_id}'",
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

    await conn.execute(
        text("""
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
    """)
    )
    await conn.execute(
        text(f"""
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
    """)
    )
    await conn.execute(text("DROP TABLE connectors"))
    await conn.execute(text("ALTER TABLE connectors_new RENAME TO connectors"))
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_connectors_workspace_id ON connectors (workspace_id)")
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_connectors_connector_type ON connectors (connector_type)"
        )
    )


async def _migrate_sync_jobs_result_metadata(conn: AsyncConnection) -> None:
    """Rename legacy result_metadata payloads by copying into the new column."""
    columns = await _get_table_columns(conn, "sync_jobs")
    if not columns:
        return

    if "result_metadata_json" not in columns:
        await conn.execute(
            text("ALTER TABLE sync_jobs ADD COLUMN result_metadata_json TEXT NOT NULL DEFAULT '{}'")
        )
        if "result_metadata" in columns:
            await conn.execute(
                text(
                    "UPDATE sync_jobs SET result_metadata_json = result_metadata "
                    "WHERE result_metadata IS NOT NULL AND result_metadata != ''"
                )
            )
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
        await conn.execute(
            text(
                "ALTER TABLE sync_jobs ADD COLUMN job_type VARCHAR(50) NOT NULL DEFAULT 'connector_sync'"
            )
        )
    if "idempotency_key" not in columns:
        await conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN idempotency_key VARCHAR(255)"))
    if "attempt_count" not in columns:
        await conn.execute(
            text("ALTER TABLE sync_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
        )
    if "max_attempts" not in columns:
        await conn.execute(
            text("ALTER TABLE sync_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3")
        )
    if "queued_at" not in columns:
        await conn.execute(text(f"ALTER TABLE sync_jobs ADD COLUMN queued_at {datetime_type}"))
    if "available_at" not in columns:
        await conn.execute(text(f"ALTER TABLE sync_jobs ADD COLUMN available_at {datetime_type}"))
    if "lease_expires_at" not in columns:
        await conn.execute(
            text(f"ALTER TABLE sync_jobs ADD COLUMN lease_expires_at {datetime_type}")
        )
    if "locked_by" not in columns:
        await conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN locked_by VARCHAR(255)"))
    if "dead_lettered_at" not in columns:
        await conn.execute(
            text(f"ALTER TABLE sync_jobs ADD COLUMN dead_lettered_at {datetime_type}")
        )

    updated_columns = await _get_table_columns(conn, "sync_jobs")
    connector_columns = await _get_table_columns(conn, "connectors")
    if {"workspace_id", "connector_id"} <= updated_columns and "workspace_id" in connector_columns:
        await conn.execute(
            text("""
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
        """)
        )

    if {"idempotency_key", "job_type", "connector_id"} <= updated_columns:
        await conn.execute(
            text("""
            UPDATE sync_jobs
            SET idempotency_key = job_type || ':' || connector_id
            WHERE idempotency_key IS NULL
              AND connector_id IS NOT NULL
        """)
        )

    if {"queued_at", "created_at"} <= updated_columns:
        await conn.execute(
            text("""
            UPDATE sync_jobs
            SET queued_at = created_at
            WHERE queued_at IS NULL
        """)
        )
    if {"available_at", "created_at", "status"} <= updated_columns:
        await conn.execute(
            text("""
            UPDATE sync_jobs
            SET available_at = created_at
            WHERE available_at IS NULL
              AND status IN ('pending', 'retrying')
        """)
        )


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
            "queued_at"
            if "queued_at" in columns
            else ("created_at" if "created_at" in columns else "CURRENT_TIMESTAMP")
        ),
        "available_at": "available_at" if "available_at" in columns else "NULL",
        "lease_expires_at": "lease_expires_at" if "lease_expires_at" in columns else "NULL",
        "locked_by": "locked_by" if "locked_by" in columns else "NULL",
        "dead_lettered_at": "dead_lettered_at" if "dead_lettered_at" in columns else "NULL",
        "started_at": "started_at" if "started_at" in columns else "NULL",
        "completed_at": "completed_at" if "completed_at" in columns else "NULL",
    }

    await conn.execute(
        text("""
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
    """)
    )
    await conn.execute(
        text(f"""
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
    """)
    )
    await conn.execute(text("DROP TABLE sync_jobs"))
    await conn.execute(text("ALTER TABLE sync_jobs_new RENAME TO sync_jobs"))
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_sync_jobs_connector_id ON sync_jobs (connector_id)")
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_sync_jobs_workspace_status ON sync_jobs (workspace_id, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_sync_jobs_idempotency_key ON sync_jobs (idempotency_key)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_sync_jobs_job_type_status ON sync_jobs (job_type, status)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_sync_jobs_queue_due ON sync_jobs (job_type, status, available_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_sync_jobs_lease_expires_at ON sync_jobs (lease_expires_at)"
        )
    )


async def _migrate_components_temporal(conn: AsyncConnection) -> None:
    """Add temporal column to existing components table if missing."""
    columns = await _get_table_columns(conn, "components")
    if not columns or "temporal" in columns:
        return

    await conn.execute(
        text("ALTER TABLE components ADD COLUMN temporal VARCHAR(20) NOT NULL DEFAULT 'unknown'")
    )


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

    result = await conn.execute(
        text("""
        SELECT id, name
        FROM components
        WHERE identity_key IS NULL OR identity_key = ''
    """)
    )
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
    await conn.execute(
        text("""
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
    """)
    )

    component_columns = await _get_table_columns(conn, "components")
    if component_columns and "entity_id" not in component_columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN entity_id CHAR(32)"))
        component_columns = await _get_table_columns(conn, "components")

    if (
        not component_columns
        or not {"entity_id", "identity_key", "name", "model_id"} <= component_columns
    ):
        return

    workspace_expr = "workspace_id" if "workspace_id" in component_columns else "NULL"
    order_expr = "created_at" if "created_at" in component_columns else "id"
    component_rows = (
        await conn.execute(
            text(f"""
        SELECT {workspace_expr} AS workspace_id, identity_key, model_id, name
        FROM components
        WHERE identity_key IS NOT NULL
          AND identity_key != ''
        ORDER BY identity_key, {order_expr}
    """)
        )
    ).fetchall()

    rows_by_identity: dict[tuple[object, str], object] = {}
    for row in component_rows:
        key = (row[0], str(row[1]))
        rows_by_identity.setdefault(key, row)

    for workspace_id, identity_key, model_id, canonical_name in rows_by_identity.values():
        entity_id = await _entity_id_for_identity(conn, workspace_id, identity_key)
        if entity_id is None:
            entity_id = uuid4().hex
            await conn.execute(
                text("""
                INSERT INTO entities (
                    id, workspace_id, model_id, identity_key, canonical_name
                ) VALUES (
                    :id, :workspace_id, :model_id, :identity_key, :canonical_name
                )
            """),
                {
                    "id": entity_id,
                    "workspace_id": workspace_id,
                    "model_id": model_id,
                    "identity_key": identity_key,
                    "canonical_name": _canonical_entity_name(canonical_name, identity_key),
                },
            )

        if "workspace_id" in component_columns and workspace_id not in (None, ""):
            await conn.execute(
                text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
                  AND workspace_id = :workspace_id
            """),
                {
                    "entity_id": entity_id,
                    "identity_key": identity_key,
                    "workspace_id": workspace_id,
                },
            )
        elif "workspace_id" in component_columns:
            await conn.execute(
                text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
                  AND (workspace_id IS NULL OR workspace_id = '')
            """),
                {
                    "entity_id": entity_id,
                    "identity_key": identity_key,
                },
            )
        else:
            await conn.execute(
                text("""
                UPDATE components
                SET entity_id = :entity_id
                WHERE entity_id IS NULL
                  AND identity_key = :identity_key
            """),
                {
                    "entity_id": entity_id,
                    "identity_key": identity_key,
                },
            )


async def _entity_id_for_identity(
    conn: AsyncConnection,
    workspace_id: object,
    identity_key: str,
) -> str | None:
    if workspace_id in (None, ""):
        return await conn.scalar(
            text("""
            SELECT id FROM entities
            WHERE identity_key = :identity_key
              AND (workspace_id IS NULL OR workspace_id = '')
            ORDER BY created_at
            LIMIT 1
        """),
            {"identity_key": identity_key},
        )

    return await conn.scalar(
        text("""
        SELECT id FROM entities
        WHERE identity_key = :identity_key
          AND workspace_id = :workspace_id
        ORDER BY created_at
        LIMIT 1
    """),
        {
            "identity_key": identity_key,
            "workspace_id": workspace_id,
        },
    )


def _canonical_entity_name(value: object, identity_key: str) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        name = identity_key.removeprefix("component:").replace("-", " ")
    return name[:255]


async def _migrate_fact_identity_schema(conn: AsyncConnection) -> None:
    """Create alias, fact, and mention tables and backfill from components."""
    datetime_type = _datetime_column_type(conn)
    await conn.execute(
        text(f"""
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
    """)
    )
    await conn.execute(
        text(f"""
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
    """)
    )
    await conn.execute(
        text(f"""
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
    """)
    )

    component_columns = await _get_table_columns(conn, "components")
    if (
        not component_columns
        or not {"id", "name", "value", "source_document_id"} <= component_columns
    ):
        return

    workspace_expr = "workspace_id" if "workspace_id" in component_columns else "NULL"
    entity_expr = "entity_id" if "entity_id" in component_columns else "NULL"
    fact_type_expr = "fact_type" if "fact_type" in component_columns else "'fact'"
    confidence_expr = "confidence" if "confidence" in component_columns else "0.5"
    status_expr = "status" if "status" in component_columns else "'active'"
    provenance_expr = "provenance" if "provenance" in component_columns else "NULL"
    excerpt_expr = "excerpt" if "excerpt" in component_columns else "NULL"
    result = await conn.execute(
        text(f"""
        SELECT id, {workspace_expr} AS workspace_id, {entity_expr} AS entity_id,
               source_document_id, name, value, {fact_type_expr} AS fact_type,
               {confidence_expr} AS confidence, {status_expr} AS status,
               {provenance_expr} AS provenance, {excerpt_expr} AS excerpt
        FROM components
    """)
    )
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
    exists = await conn.scalar(
        text("""
        SELECT 1 FROM entity_aliases
        WHERE entity_id = :entity_id
          AND normalized_alias = :normalized_alias
        LIMIT 1
    """),
        {"entity_id": entity_id, "normalized_alias": normalized_alias},
    )
    if exists:
        return
    await conn.execute(
        text("""
        INSERT INTO entity_aliases (
            id, workspace_id, entity_id, source_document_id,
            alias, normalized_alias, confidence
        ) VALUES (
            :id, :workspace_id, :entity_id, :source_document_id,
            :alias, :normalized_alias, :confidence
        )
    """),
        {
            "id": uuid4().hex,
            "workspace_id": workspace_id,
            "entity_id": entity_id,
            "source_document_id": source_document_id,
            "alias": alias[:255] or normalized_alias[:255],
            "normalized_alias": normalized_alias[:255],
            "confidence": _safe_confidence(confidence, 1.0),
        },
    )


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
    exists = await conn.scalar(
        text("""
        SELECT 1 FROM facts
        WHERE component_id = :component_id
        LIMIT 1
    """),
        {"component_id": component_id},
    )
    if exists:
        return
    await conn.execute(
        text("""
        INSERT INTO facts (
            id, workspace_id, entity_id, component_id, source_document_id,
            claim, fact_type, confidence, status, provenance, excerpt
        ) VALUES (
            :id, :workspace_id, :entity_id, :component_id, :source_document_id,
            :claim, :fact_type, :confidence, :status, :provenance, :excerpt
        )
    """),
        {
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
        },
    )


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
    exists = await conn.scalar(
        text("""
        SELECT 1 FROM mentions
        WHERE component_id = :component_id
          AND normalized_mention = :normalized_mention
        LIMIT 1
    """),
        {
            "component_id": component_id,
            "normalized_mention": normalized_mention,
        },
    )
    if exists:
        return
    await conn.execute(
        text("""
        INSERT INTO mentions (
            id, workspace_id, entity_id, source_document_id, component_id,
            mention_text, normalized_mention, confidence
        ) VALUES (
            :id, :workspace_id, :entity_id, :source_document_id, :component_id,
            :mention_text, :normalized_mention, :confidence
        )
    """),
        {
            "id": uuid4().hex,
            "workspace_id": workspace_id,
            "entity_id": entity_id,
            "source_document_id": source_document_id,
            "component_id": component_id,
            "mention_text": (mention_text or normalized_mention)[:255],
            "normalized_mention": normalized_mention[:255],
            "confidence": _safe_confidence(confidence, 0.8),
        },
    )


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
        await conn.execute(
            text("ALTER TABLE relationships ADD COLUMN confidence FLOAT NOT NULL DEFAULT 0.7")
        )
        await conn.execute(
            text("UPDATE relationships SET confidence = 0.7 WHERE confidence IS NULL")
        )

    if "evidence" not in columns:
        await conn.execute(text("ALTER TABLE relationships ADD COLUMN evidence TEXT"))
        await conn.execute(
            text(
                "UPDATE relationships SET evidence = 'backfill: schema migration' "
                "WHERE evidence IS NULL"
            )
        )

    if "status" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE relationships ADD COLUMN status VARCHAR(50) NOT NULL DEFAULT 'active'"
            )
        )


async def _get_table_columns(conn: AsyncConnection, table_name: str) -> set[str]:
    if conn.dialect.name == "postgresql":
        try:
            result = await conn.execute(
                text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
            """),
                {"table_name": table_name},
            )
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

    workspace_id = await conn.scalar(text("SELECT id FROM workspaces ORDER BY created_at LIMIT 1"))
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
            result = await conn.execute(
                text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                )
            """),
                {"table_name": table_name},
            )
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
        await conn.execute(text("ALTER TABLE components ADD COLUMN provenance TEXT"))

    if "excerpt" not in columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN excerpt TEXT"))


async def _migrate_relationships_origin(conn: AsyncConnection) -> None:
    columns = await _get_table_columns(conn, "relationships")
    if not columns:
        return

    if "origin" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE relationships ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'proposed'"
            )
        )


async def _migrate_evidence_ledger_and_claim_graph(conn: AsyncConnection) -> None:
    """Add v2 source hashes, evidence spans, claims, and runtime persistence tables."""
    dt_type = _datetime_column_type(conn)
    uuid_type = "UUID" if conn.dialect.name == "postgresql" else "CHAR(32)"

    source_columns = await _get_table_columns(conn, "source_documents")
    if source_columns:
        if "content_sha256" not in source_columns:
            await conn.execute(
                text("ALTER TABLE source_documents ADD COLUMN content_sha256 VARCHAR(64)")
            )
        if "trust_zone" not in source_columns:
            await conn.execute(
                text("ALTER TABLE source_documents ADD COLUMN trust_zone VARCHAR(50)")
            )
        if "source_created_at" not in source_columns:
            await conn.execute(
                text(f"ALTER TABLE source_documents ADD COLUMN source_created_at {dt_type}")
            )
        if "source_identity_sha256" not in source_columns:
            await conn.execute(
                text("ALTER TABLE source_documents ADD COLUMN source_identity_sha256 VARCHAR(64)")
            )
        if "revision_number" not in source_columns:
            await conn.execute(
                text("ALTER TABLE source_documents ADD COLUMN revision_number INTEGER NOT NULL DEFAULT 1")
            )
        if "supersedes_source_document_id" not in source_columns:
            await conn.execute(
                text(
                    "ALTER TABLE source_documents "
                    f"ADD COLUMN supersedes_source_document_id {uuid_type}"
                )
            )
        await _backfill_source_document_ledger_columns(conn)
        await _backfill_source_document_revisions(conn)

    component_columns = await _get_table_columns(conn, "components")
    if component_columns and "claim_id" not in component_columns:
        await conn.execute(text("ALTER TABLE components ADD COLUMN claim_id CHAR(32)"))

    if not source_columns:
        return

    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS evidence_spans (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            source_document_id CHAR(32) NOT NULL,
            start_char INTEGER,
            end_char INTEGER,
            text TEXT,
            text_sha256 VARCHAR(64) NOT NULL,
            evidence_type VARCHAR(50) NOT NULL DEFAULT 'extracted_fact',
            authority_weight FLOAT NOT NULL DEFAULT 0.5,
            trust_zone VARCHAR(50) NOT NULL DEFAULT 'untrusted_external',
            prompt_injection_risk_score FLOAT NOT NULL DEFAULT 0.0,
            extraction_method VARCHAR(50) NOT NULL DEFAULT 'deterministic',
            review_status VARCHAR(50) NOT NULL DEFAULT 'verified',
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS claims (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            identity_key VARCHAR(255) NOT NULL,
            claim_type VARCHAR(50) NOT NULL DEFAULT 'fact',
            status VARCHAR(50) NOT NULL DEFAULT 'needs_review',
            temporal VARCHAR(20) NOT NULL DEFAULT 'unknown',
            confidence FLOAT NOT NULL DEFAULT 0.5,
            authority_weight FLOAT NOT NULL DEFAULT 0.5,
            current_revision_id CHAR(32),
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS claim_revisions (
            id CHAR(32) NOT NULL,
            claim_id CHAR(32) NOT NULL,
            evidence_span_id CHAR(32) NOT NULL,
            value TEXT NOT NULL,
            operation VARCHAR(50) NOT NULL DEFAULT 'create',
            confidence_delta FLOAT NOT NULL DEFAULT 0.0,
            status_after VARCHAR(50) NOT NULL DEFAULT 'needs_review',
            supersedes_claim_id CHAR(32),
            contradicts_claim_id CHAR(32),
            created_by VARCHAR(255),
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(claim_id) REFERENCES claims (id),
            FOREIGN KEY(evidence_span_id) REFERENCES evidence_spans (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS context_packs (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            objective TEXT NOT NULL,
            target_model VARCHAR(255),
            model_profile VARCHAR(100),
            token_budget INTEGER,
            pack_version VARCHAR(50) NOT NULL DEFAULT 'context_pack.v2',
            health_score FLOAT,
            markdown TEXT NOT NULL DEFAULT '',
            manifest TEXT NOT NULL DEFAULT '{{}}',
            repo_state_json TEXT NOT NULL DEFAULT '{{}}',
            idempotency_key VARCHAR(255),
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS context_pack_items (
            id CHAR(32) NOT NULL,
            context_pack_id CHAR(32) NOT NULL,
            item_type VARCHAR(50) NOT NULL DEFAULT 'component',
            claim_id CHAR(32),
            component_id CHAR(32),
            evidence_span_id CHAR(32),
            source_document_id CHAR(32),
            score FLOAT NOT NULL DEFAULT 0.0,
            inclusion_reason TEXT,
            token_cost INTEGER,
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(context_pack_id) REFERENCES context_packs (id),
            FOREIGN KEY(claim_id) REFERENCES claims (id),
            FOREIGN KEY(component_id) REFERENCES components (id),
            FOREIGN KEY(evidence_span_id) REFERENCES evidence_spans (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            context_pack_id CHAR(32),
            tool VARCHAR(100),
            model VARCHAR(255),
            objective TEXT,
            branch VARCHAR(255),
            base_commit VARCHAR(100),
            head_commit VARCHAR(100),
            started_at {dt_type},
            ended_at {dt_type},
            status VARCHAR(50) NOT NULL DEFAULT 'running',
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(context_pack_id) REFERENCES context_packs (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS run_observations (
            id CHAR(32) NOT NULL,
            agent_run_id CHAR(32) NOT NULL,
            source_document_id CHAR(32),
            event_type VARCHAR(50) NOT NULL,
            content TEXT,
            files_json TEXT NOT NULL DEFAULT '[]',
            command TEXT,
            exit_code INTEGER,
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(agent_run_id) REFERENCES agent_runs (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS code_files (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            repo_root TEXT,
            path TEXT NOT NULL,
            identity_key VARCHAR(64) NOT NULL,
            language VARCHAR(50),
            sha256 VARCHAR(64),
            last_commit VARCHAR(100),
            size INTEGER,
            is_test BOOLEAN NOT NULL DEFAULT false,
            updated_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS code_symbols (
            id CHAR(32) NOT NULL,
            code_file_id CHAR(32) NOT NULL,
            symbol_type VARCHAR(50) NOT NULL,
            name VARCHAR(255) NOT NULL,
            qualified_name VARCHAR(512),
            start_line INTEGER,
            end_line INTEGER,
            docstring TEXT,
            signature TEXT,
            identity_key VARCHAR(64) NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(code_file_id) REFERENCES code_files (id)
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS code_edges (
            id CHAR(32) NOT NULL,
            source_symbol_id CHAR(32) NOT NULL,
            target_symbol_id CHAR(32) NOT NULL,
            edge_type VARCHAR(50) NOT NULL DEFAULT 'references',
            edge_key VARCHAR(64) NOT NULL,
            rule_id VARCHAR(100) NOT NULL,
            rule_version VARCHAR(32) NOT NULL,
            evidence_path TEXT,
            evidence_start_line INTEGER,
            evidence_end_line INTEGER,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            evidence_sha256 VARCHAR(64) NOT NULL,
            snapshot_commit VARCHAR(100),
            snapshot_dirty BOOLEAN NOT NULL DEFAULT false,
            snapshot_fingerprint VARCHAR(64),
            PRIMARY KEY (id),
            FOREIGN KEY(source_symbol_id) REFERENCES code_symbols (id),
            FOREIGN KEY(target_symbol_id) REFERENCES code_symbols (id)
        )
    """)
    )
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS repo_events (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            commit_sha VARCHAR(100),
            branch VARCHAR(255),
            author VARCHAR(255),
            message TEXT,
            changed_files_json TEXT NOT NULL DEFAULT '[]',
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id)
        )
    """)
    )

    evidence_columns = await _get_table_columns(conn, "evidence_spans")
    if evidence_columns:
        if "text" not in evidence_columns:
            await conn.execute(text("ALTER TABLE evidence_spans ADD COLUMN text TEXT"))
        if "review_status" not in evidence_columns:
            await conn.execute(
                text(
                    "ALTER TABLE evidence_spans ADD COLUMN review_status VARCHAR(50) NOT NULL DEFAULT 'verified'"
                )
            )

    revision_columns = await _get_table_columns(conn, "claim_revisions")
    if revision_columns:
        if "status_after" not in revision_columns:
            await conn.execute(
                text(
                    "ALTER TABLE claim_revisions ADD COLUMN status_after VARCHAR(50) NOT NULL DEFAULT 'needs_review'"
                )
            )
        if "supersedes_claim_id" not in revision_columns:
            await conn.execute(
                text("ALTER TABLE claim_revisions ADD COLUMN supersedes_claim_id CHAR(32)")
            )
        if "contradicts_claim_id" not in revision_columns:
            await conn.execute(
                text("ALTER TABLE claim_revisions ADD COLUMN contradicts_claim_id CHAR(32)")
            )
        if "created_by" not in revision_columns:
            await conn.execute(
                text("ALTER TABLE claim_revisions ADD COLUMN created_by VARCHAR(255)")
            )

    context_pack_columns = await _get_table_columns(conn, "context_packs")
    if context_pack_columns:
        if "model_profile" not in context_pack_columns:
            await conn.execute(
                text("ALTER TABLE context_packs ADD COLUMN model_profile VARCHAR(100)")
            )
        if "repo_state_json" not in context_pack_columns:
            await conn.execute(
                text(
                    "ALTER TABLE context_packs ADD COLUMN repo_state_json TEXT NOT NULL DEFAULT '{}'"
                )
            )
        if "idempotency_key" not in context_pack_columns:
            await conn.execute(
                text("ALTER TABLE context_packs ADD COLUMN idempotency_key VARCHAR(255)")
            )

    item_columns = await _get_table_columns(conn, "context_pack_items")
    if item_columns:
        if "item_type" not in item_columns:
            await conn.execute(
                text(
                    "ALTER TABLE context_pack_items ADD COLUMN item_type VARCHAR(50) NOT NULL DEFAULT 'component'"
                )
            )
        if "claim_id" not in item_columns:
            await conn.execute(text("ALTER TABLE context_pack_items ADD COLUMN claim_id CHAR(32)"))
        if "source_document_id" not in item_columns:
            await conn.execute(
                text("ALTER TABLE context_pack_items ADD COLUMN source_document_id CHAR(32)")
            )
        if "created_at" not in item_columns:
            await conn.execute(
                text(f"ALTER TABLE context_pack_items ADD COLUMN created_at {dt_type}")
            )
            await conn.execute(
                text(
                    "UPDATE context_pack_items SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )
            )


async def _backfill_source_document_ledger_columns(conn: AsyncConnection) -> None:
    columns = await _get_table_columns(conn, "source_documents")
    if not {"id", "content", "source_type"} <= columns:
        return
    metadata_expr = "metadata" if "metadata" in columns else "'{}'"
    result = await conn.execute(
        text(f"""
        SELECT id, content, source_type, {metadata_expr} AS metadata, content_sha256, trust_zone, source_created_at
        FROM source_documents
        WHERE content_sha256 IS NULL
           OR content_sha256 = ''
           OR trust_zone IS NULL
           OR trust_zone = ''
           OR source_created_at IS NULL
    """)
    )
    for row in result.fetchall():
        metadata = _loads_json_dict(row[3])
        params = {
            "id": row[0],
            "content_sha256": row[4] or _sha256_text(str(row[1] or "")),
            "trust_zone": row[5] or default_trust_zone_for_source(str(row[2] or ""), metadata),
            "source_created_at": row[6] or _source_created_at_from_metadata(metadata),
        }
        await conn.execute(
            text("""
            UPDATE source_documents
            SET content_sha256 = :content_sha256,
                trust_zone = :trust_zone,
                source_created_at = COALESCE(source_created_at, :source_created_at)
            WHERE id = :id
        """),
            params,
        )


async def _backfill_source_document_revisions(conn: AsyncConnection) -> None:
    """Deterministically chain legacy rows without deleting or rewriting content."""
    columns = await _get_table_columns(conn, "source_documents")
    required = {
        "id",
        "workspace_id",
        "source_type",
        "external_id",
        "content",
        "content_sha256",
        "source_identity_sha256",
        "revision_number",
        "supersedes_source_document_id",
    }
    if not required <= columns:
        return

    ingested_expr = "ingested_at" if "ingested_at" in columns else "NULL"
    result = await conn.execute(
        text(f"""
        SELECT id, workspace_id, source_type, external_id, {ingested_expr} AS ingested_at,
               content, content_sha256, source_identity_sha256, revision_number,
               supersedes_source_document_id
        FROM source_documents
        ORDER BY ingested_at, id
    """)
    )
    grouped: dict[str, list[object]] = {}
    for row in result.fetchall():
        identity_sha256 = canonical_source_identity_sha256(
            row[1], str(row[2] or ""), str(row[3] or "")
        )
        grouped.setdefault(identity_sha256, []).append(row)

    for identity_sha256, rows in grouped.items():
        revision_order = sorted(rows, key=lambda row: (int(row[8] or 0), str(row[0])))
        valid_chain = (
            all(row[7] == identity_sha256 for row in revision_order)
            and [row[8] for row in revision_order] == list(range(1, len(rows) + 1))
            and all(
                (
                    row[9] is None
                    if index == 0
                    else str(row[9]) == str(revision_order[index - 1][0])
                )
                for index, row in enumerate(revision_order)
            )
        )
        if valid_chain:
            rows = revision_order
        else:
            rows.sort(key=lambda row: (str(row[4] or ""), str(row[0])))
        previous_id: object | None = None
        for revision, row in enumerate(rows, start=1):
            content_sha256 = _sha256_text(str(row[5] or ""))
            if (
                row[6] != content_sha256
                or row[7] != identity_sha256
                or row[8] != revision
                or row[9] != previous_id
            ):
                await conn.execute(
                    text("""
                    UPDATE source_documents
                    SET content_sha256 = :content_sha256,
                        source_identity_sha256 = :source_identity_sha256,
                        revision_number = :revision_number,
                        supersedes_source_document_id = :supersedes_source_document_id
                    WHERE id = :id
                """),
                    {
                        "id": row[0],
                        "content_sha256": content_sha256,
                        "source_identity_sha256": identity_sha256,
                        "revision_number": revision,
                        "supersedes_source_document_id": previous_id,
                    },
                )
            previous_id = row[0]

    await conn.execute(
        text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_source_documents_identity_revision
        ON source_documents (source_identity_sha256, revision_number)
    """)
    )


async def _migrate_unresolved_relationships_schema(conn: AsyncConnection) -> None:
    if not await _table_exists(conn, "components"):
        return

    dt_type = _datetime_column_type(conn)
    await conn.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS unresolved_relationships (
            id CHAR(32) NOT NULL,
            workspace_id CHAR(32),
            source_component_id CHAR(32) NOT NULL,
            source_document_id CHAR(32),
            target_name VARCHAR(255) NOT NULL,
            target_identity_key VARCHAR(255),
            relationship_type VARCHAR(50) NOT NULL DEFAULT 'related_to',
            confidence FLOAT NOT NULL DEFAULT 0.7,
            evidence TEXT,
            origin VARCHAR(20) NOT NULL DEFAULT 'proposed',
            status VARCHAR(50) NOT NULL DEFAULT 'unresolved',
            resolution_note TEXT,
            resolved_relationship_id CHAR(32),
            created_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at {dt_type} DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY(source_component_id) REFERENCES components (id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents (id),
            FOREIGN KEY(resolved_relationship_id) REFERENCES relationships (id)
        )
    """)
    )


async def _migrate_retrieval_events_schema(conn: AsyncConnection) -> None:
    await conn.execute(
        text("""
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
    """)
    )


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

    await conn.execute(
        text("""
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
    """)
    )
    await conn.execute(
        text("""
        UPDATE components
        SET embedding_vector = ce_try_vector(embedding)
        WHERE embedding_vector IS NULL
          AND embedding IS NOT NULL
          AND embedding != ''
    """)
    )
    await conn.execute(
        text("""
        CREATE OR REPLACE FUNCTION ce_sync_component_embedding_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.embedding_vector = ce_try_vector(NEW.embedding);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    )
    await conn.execute(
        text("""
        DROP TRIGGER IF EXISTS trg_components_embedding_vector ON components
    """)
    )
    await conn.execute(
        text("""
        CREATE TRIGGER trg_components_embedding_vector
        BEFORE INSERT OR UPDATE OF embedding ON components
        FOR EACH ROW
        EXECUTE FUNCTION ce_sync_component_embedding_vector()
    """)
    )

    dimension = pgvector_index_dimension()
    await conn.execute(
        text(f"""
        CREATE INDEX IF NOT EXISTS ix_components_embedding_vector_hnsw
        ON components
        USING hnsw ((embedding_vector::vector({dimension})) vector_cosine_ops)
        WHERE embedding_vector IS NOT NULL
          AND vector_dims(embedding_vector) = {dimension}
    """)
    )


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

        await conn.execute(
            text("""
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
        """)
        )
        await conn.execute(
            text("""
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
        """)
        )
        await conn.execute(
            text("""
            UPDATE source_documents
            SET metadata_jsonb = ce_try_jsonb(metadata),
                search_tsv =
                    setweight(to_tsvector('english', coalesce(external_id, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(source_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(author, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(content, '')), 'D')
            WHERE metadata_jsonb IS NULL OR search_tsv IS NULL
        """)
        )
        await conn.execute(
            text("DROP TRIGGER IF EXISTS trg_source_documents_search ON source_documents")
        )
        await conn.execute(
            text("""
            CREATE TRIGGER trg_source_documents_search
            BEFORE INSERT OR UPDATE OF metadata, content, external_id, source_type, author
            ON source_documents
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_source_document_search()
        """)
        )
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_metadata_jsonb_gin
            ON source_documents USING gin (metadata_jsonb)
        """)
        )
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_search_tsv_gin
            ON source_documents USING gin (search_tsv)
        """)
        )

    component_columns = await _get_table_columns(conn, "components")
    if component_columns:
        if "search_tsv" not in component_columns:
            await conn.execute(text("ALTER TABLE components ADD COLUMN search_tsv tsvector"))

        await conn.execute(
            text("""
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
        """)
        )
        await conn.execute(
            text("""
            UPDATE components
            SET search_tsv =
                setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(fact_type, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(status, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(temporal, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(value, '')), 'D')
            WHERE search_tsv IS NULL
        """)
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_components_search ON components"))
        await conn.execute(
            text("""
            CREATE TRIGGER trg_components_search
            BEFORE INSERT OR UPDATE OF name, value, fact_type, status, temporal
            ON components
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_component_search()
        """)
        )
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_components_search_tsv_gin
            ON components USING gin (search_tsv)
        """)
        )


async def _pgvector_extension_available(conn: AsyncConnection) -> bool:
    try:
        result = await conn.execute(
            text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'vector'
            )
        """)
        )
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
        ("source_documents", "ix_source_documents_content_sha256", ("content_sha256",)),
        ("source_documents", "ix_source_documents_trust_zone", ("trust_zone",)),
        (
            "source_documents",
            "ix_source_documents_workspace_source_external_revision",
            ("workspace_id", "source_type", "external_id", "revision_number"),
        ),
        (
            "source_documents",
            "ix_source_documents_supersedes_source_document_id",
            ("supersedes_source_document_id",),
        ),
        ("components", "ix_components_workspace_id", ("workspace_id",)),
        ("components", "ix_components_entity_id", ("entity_id",)),
        ("components", "ix_components_claim_id", ("claim_id",)),
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
            "unresolved_relationships",
            "ix_unresolved_relationships_workspace_status",
            ("workspace_id", "status"),
        ),
        (
            "unresolved_relationships",
            "ix_unresolved_relationships_source_status",
            ("source_component_id", "status"),
        ),
        (
            "unresolved_relationships",
            "ix_unresolved_relationships_source_document",
            ("source_document_id",),
        ),
        (
            "unresolved_relationships",
            "ix_unresolved_relationships_target_identity",
            ("target_identity_key",),
        ),
        (
            "unresolved_relationships",
            "ix_unresolved_relationships_source_target_type",
            ("source_component_id", "target_identity_key", "relationship_type"),
        ),
        (
            "evidence_spans",
            "ix_evidence_spans_workspace_document",
            ("workspace_id", "source_document_id"),
        ),
        (
            "evidence_spans",
            "ix_evidence_spans_source_range",
            ("source_document_id", "start_char", "end_char"),
        ),
        ("evidence_spans", "ix_evidence_spans_text_sha256", ("text_sha256",)),
        (
            "evidence_spans",
            "ix_evidence_spans_trust_risk",
            ("trust_zone", "prompt_injection_risk_score"),
        ),
        ("claims", "ix_claims_workspace_identity", ("workspace_id", "identity_key")),
        ("claims", "ix_claims_workspace_status", ("workspace_id", "status")),
        ("claims", "ix_claims_type_status", ("claim_type", "status")),
        ("claims", "ix_claims_current_revision_id", ("current_revision_id",)),
        ("claim_revisions", "ix_claim_revisions_claim_created", ("claim_id", "created_at")),
        ("claim_revisions", "ix_claim_revisions_evidence_span", ("evidence_span_id",)),
        ("claim_revisions", "ix_claim_revisions_supersedes_claim_id", ("supersedes_claim_id",)),
        ("claim_revisions", "ix_claim_revisions_contradicts_claim_id", ("contradicts_claim_id",)),
        ("context_packs", "ix_context_packs_workspace_created", ("workspace_id", "created_at")),
        ("context_packs", "ix_context_packs_target_model", ("target_model",)),
        (
            "context_packs",
            "ix_context_packs_workspace_target_created",
            ("workspace_id", "target_model", "created_at"),
        ),
        ("context_packs", "ix_context_packs_idempotency_key", ("idempotency_key",)),
        ("context_pack_items", "ix_context_pack_items_pack", ("context_pack_id",)),
        ("context_pack_items", "ix_context_pack_items_claim", ("claim_id",)),
        ("context_pack_items", "ix_context_pack_items_component", ("component_id",)),
        ("context_pack_items", "ix_context_pack_items_evidence", ("evidence_span_id",)),
        (
            "context_pack_items",
            "ix_context_pack_items_source_document",
            ("source_document_id",),
        ),
        ("agent_runs", "ix_agent_runs_workspace_started", ("workspace_id", "started_at")),
        ("agent_runs", "ix_agent_runs_context_pack", ("context_pack_id",)),
        ("agent_runs", "ix_agent_runs_status", ("status",)),
        (
            "run_observations",
            "ix_run_observations_agent_run_created",
            ("agent_run_id", "created_at"),
        ),
        ("run_observations", "ix_run_observations_source_document", ("source_document_id",)),
        ("run_observations", "ix_run_observations_event_type", ("event_type",)),
        ("code_files", "ix_code_files_workspace_path", ("workspace_id", "path")),
        ("code_files", "ix_code_files_sha256", ("sha256",)),
        ("code_symbols", "ix_code_symbols_file", ("code_file_id",)),
        ("code_symbols", "ix_code_symbols_qualified_name", ("qualified_name",)),
        (
            "code_edges",
            "ix_code_edges_source_target_type",
            ("source_symbol_id", "target_symbol_id", "edge_type"),
        ),
        ("code_edges", "ix_code_edges_target", ("target_symbol_id",)),
        ("repo_events", "ix_repo_events_workspace_commit", ("workspace_id", "commit_sha")),
        ("repo_events", "ix_repo_events_workspace_created", ("workspace_id", "created_at")),
        (
            "retrieval_events",
            "ix_retrieval_events_workspace_created",
            ("workspace_id", "created_at"),
        ),
        ("retrieval_events", "ix_retrieval_events_created_at", ("created_at",)),
    ]

    for table_name, index_name, column_names in index_specs:
        await _create_index_if_columns_exist(conn, table_name, index_name, column_names)

    sync_columns = await _get_table_columns(conn, "sync_jobs")
    if {"idempotency_key", "status"} <= sync_columns:
        await conn.execute(text("""
            UPDATE sync_jobs AS candidate
            SET status = 'failed'
            WHERE candidate.idempotency_key IS NOT NULL
              AND candidate.status IN ('pending', 'running')
              AND EXISTS (
                  SELECT 1 FROM sync_jobs AS winner
                  WHERE winner.idempotency_key = candidate.idempotency_key
                    AND winner.status IN ('pending', 'running')
                    AND (
                        winner.created_at < candidate.created_at
                        OR (
                            winner.created_at = candidate.created_at
                            AND CAST(winner.id AS TEXT) < CAST(candidate.id AS TEXT)
                        )
                    )
              )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_sync_jobs_active_idempotency_key
            ON sync_jobs (idempotency_key)
            WHERE idempotency_key IS NOT NULL AND status IN ('pending', 'running')
        """))
    pack_columns = await _get_table_columns(conn, "context_packs")
    if "idempotency_key" in pack_columns:
        await conn.execute(text("""
            UPDATE context_packs AS candidate
            SET idempotency_key = NULL
            WHERE candidate.idempotency_key IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM context_packs AS winner
                  WHERE winner.idempotency_key = candidate.idempotency_key
                    AND (
                        winner.created_at < candidate.created_at
                        OR (
                            winner.created_at = candidate.created_at
                            AND CAST(winner.id AS TEXT) < CAST(candidate.id AS TEXT)
                        )
                    )
              )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_context_packs_idempotency_key
            ON context_packs (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """))
    observation_columns = await _get_table_columns(conn, "run_observations")
    if {"agent_run_id", "event_type"} <= observation_columns:
        await conn.execute(text("""
            UPDATE run_observations AS candidate
            SET event_type = 'outcome_duplicate_legacy'
            WHERE candidate.event_type = 'outcome'
              AND EXISTS (
                  SELECT 1 FROM run_observations AS winner
                  WHERE winner.agent_run_id = candidate.agent_run_id
                    AND winner.event_type = 'outcome'
                    AND (
                        winner.created_at < candidate.created_at
                        OR (
                            winner.created_at = candidate.created_at
                            AND CAST(winner.id AS TEXT) < CAST(candidate.id AS TEXT)
                        )
                    )
              )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_run_observations_terminal_outcome
            ON run_observations (agent_run_id)
            WHERE event_type = 'outcome'
        """))
    source_columns = await _get_table_columns(conn, "source_documents")
    if "supersedes_source_document_id" in source_columns:
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_source_documents_superseded_once
            ON source_documents (supersedes_source_document_id)
            WHERE supersedes_source_document_id IS NOT NULL
        """))


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
    await conn.execute(
        text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({quoted_columns})")
    )
