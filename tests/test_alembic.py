from __future__ import annotations

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_bootstraps_current_sqlite_schema(tmp_path):
    db_path = tmp_path / "context.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "workspaces",
            "connectors",
            "source_documents",
            "components",
            "entity_aliases",
            "facts",
            "mentions",
            "relationships",
            "unresolved_relationships",
            "retrieval_events",
            "open_loops",
            "verified_playbooks",
            "workspace_goals",
            "session_events",
            "work_checkpoints",
            "checkpoint_items",
            "checkpoint_evidence",
            "checkpoint_verifications",
            "memory_review_events",
            "source_sync_observations",
            "alembic_version",
        } <= tables

        component_columns = {column["name"] for column in inspector.get_columns("components")}
        assert {
            "workspace_id",
            "entity_id",
            "identity_key",
            "embedding",
            "provenance",
            "excerpt",
        } <= component_columns

        source_columns = {column["name"] for column in inspector.get_columns("source_documents")}
        assert "workspace_id" in source_columns
        assert "metadata" in source_columns

        pack_columns = {column["name"] for column in inspector.get_columns("context_packs")}
        assert {
            "focus_component_id", "objective_origin", "objective_source_document_id",
            "objective_evidence_span_id",
        } <= pack_columns
        observation_columns = {
            column["name"] for column in inspector.get_columns("run_observations")
        }
        assert {"event_key", "payload_json", "observed_at"} <= observation_columns
        file_columns = {column["name"] for column in inspector.get_columns("code_files")}
        symbol_columns = {column["name"] for column in inspector.get_columns("code_symbols")}
        edge_columns = {column["name"] for column in inspector.get_columns("code_edges")}
        assert {"identity_key", "is_test"} <= file_columns
        assert "identity_key" in symbol_columns
        assert {
            "edge_key", "rule_id", "rule_version", "evidence_json",
            "evidence_sha256", "snapshot_fingerprint",
        } <= edge_columns

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        workspace_columns = {column["name"] for column in inspector.get_columns("workspaces")}
        assert {"kind", "status", "archived_at"} <= workspace_columns
        source_indexes = {
            item["name"] for item in inspector.get_indexes("source_documents")
        }
        session_event_indexes = {
            item["name"] for item in inspector.get_indexes("session_events")
        }
        assert "ix_source_documents_workspace_type_ingested" in source_indexes
        assert "ix_session_events_source_type_sequence" in session_event_indexes

        sync_observation_columns = {
            column["name"]
            for column in inspector.get_columns("source_sync_observations")
        }
        assert {
            "workspace_id",
            "connector_id",
            "sync_job_id",
            "sync_attempt_count",
            "source_document_id",
            "source_identity_sha256",
            "content_sha256",
            "provider",
            "provider_object_id",
            "provider_version",
            "observed_at",
            "scope_snapshot_sha256",
            "provider_account_fingerprint",
            "observation_kind",
            "created_at",
        } <= sync_observation_columns
        sync_observation_indexes = {
            item["name"]
            for item in inspector.get_indexes("source_sync_observations")
        }
        assert {
            "ix_source_sync_observations_workspace_id",
            "ix_source_sync_observations_connector_id",
            "ix_source_sync_observations_sync_job_id",
            "ix_source_sync_observations_source_document_id",
            "ix_source_sync_observations_provider",
            "ix_source_sync_observations_observed_at",
            "ix_source_sync_observations_source_observed",
            "ix_source_sync_observations_connector_observed",
            "ix_source_sync_observations_job_attempt",
        } <= sync_observation_indexes
        sync_observation_foreign_keys = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys("source_sync_observations")
        }
        assert {
            (("workspace_id",), "workspaces", ("id",)),
            (("connector_id",), "connectors", ("id",)),
            (("sync_job_id",), "sync_jobs", ("id",)),
            (("source_document_id",), "source_documents", ("id",)),
        } <= sync_observation_foreign_keys

        assert version == "0013_source_ingestion_jobs"
    finally:
        engine.dispose()


def test_digest_read_indexes_downgrade_and_upgrade_cleanly(tmp_path):
    db_path = tmp_path / "context.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(config, "head")
    command.downgrade(config, "0010_production_worker_fencing")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        assert "ix_source_documents_workspace_type_ingested" not in {
            item["name"] for item in inspector.get_indexes("source_documents")
        }
        assert "ix_session_events_source_type_sequence" not in {
            item["name"] for item in inspector.get_indexes("session_events")
        }
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        assert "ix_source_documents_workspace_type_ingested" in {
            item["name"] for item in inspector.get_indexes("source_documents")
        }
        assert "ix_session_events_source_type_sequence" in {
            item["name"] for item in inspector.get_indexes("session_events")
        }
    finally:
        engine.dispose()


def test_source_sync_observation_migration_repairs_indexes_and_round_trips(tmp_path):
    db_path = tmp_path / "context.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0011_digest_read_indexes")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            assert inspect(conn).has_table("source_sync_observations")
            conn.execute(text(
                "DROP INDEX ix_source_sync_observations_source_observed"
            ))
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        indexes = {
            item["name"]
            for item in inspect(engine).get_indexes("source_sync_observations")
        }
        assert {
            "ix_source_sync_observations_workspace_id",
            "ix_source_sync_observations_connector_id",
            "ix_source_sync_observations_sync_job_id",
            "ix_source_sync_observations_source_document_id",
            "ix_source_sync_observations_provider",
            "ix_source_sync_observations_observed_at",
            "ix_source_sync_observations_source_observed",
            "ix_source_sync_observations_connector_observed",
            "ix_source_sync_observations_job_attempt",
        } <= indexes
    finally:
        engine.dispose()

    command.downgrade(config, "0011_digest_read_indexes")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert not inspect(engine).has_table("source_sync_observations")
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert inspect(engine).has_table("source_sync_observations")
    finally:
        engine.dispose()


def test_worker_fencing_migration_deduplicates_legacy_retrying_jobs(tmp_path):
    db_path = tmp_path / "context.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "head")
    command.downgrade(config, "0009_memory_review_events")

    workspace_id = uuid4().hex
    connector_id = uuid4().hex
    older_job_id = uuid4().hex
    newer_job_id = uuid4().hex
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO workspaces (id, name, slug)
                    VALUES (:id, 'Migration workspace', :slug)
                """),
                {"id": workspace_id, "slug": f"migration-{workspace_id}"},
            )
            conn.execute(
                text("""
                    INSERT INTO connectors (
                        id, workspace_id, connector_type, status,
                        config_json, credentials_json
                    )
                    VALUES (
                        :id, :workspace_id, 'local', 'connected', '{}', '{}'
                    )
                """),
                {"id": connector_id, "workspace_id": workspace_id},
            )
            for job_id, status, created_at in (
                (older_job_id, "pending", "2026-01-01 00:00:00"),
                (newer_job_id, "retrying", "2026-01-02 00:00:00"),
            ):
                conn.execute(
                    text("""
                        INSERT INTO sync_jobs (
                            id, workspace_id, connector_id, job_type,
                            idempotency_key, status, attempt_count, max_attempts,
                            result_metadata_json, created_at
                        )
                        VALUES (
                            :id, :workspace_id, :connector_id, 'connector_sync',
                            'same-active-key', :status, 0, 3, '{}', :created_at
                        )
                    """),
                    {
                        "id": job_id,
                        "workspace_id": workspace_id,
                        "connector_id": connector_id,
                        "status": status,
                        "created_at": created_at,
                    },
                )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, status, error_type
                FROM sync_jobs
                WHERE idempotency_key = 'same-active-key'
                ORDER BY created_at, id
            """)).mappings().all()
        assert [row["status"] for row in rows] == ["pending", "failed"]
        assert rows[1]["error_type"] == "duplicate_idempotency_key"
        assert "uq_sync_jobs_active_idempotency_key" in {
            item["name"] for item in inspect(engine).get_indexes("sync_jobs")
        }
    finally:
        engine.dispose()
