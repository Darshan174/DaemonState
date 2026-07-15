from __future__ import annotations

import hashlib
import json
import os
import tempfile
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import selectinload

from app.migrations import run_migrations
from app.models import (
    AgentRun,
    Base,
    Claim,
    ClaimRevision,
    CodeEdge,
    CodeFile,
    CodeSymbol,
    Component,
    Connector,
    ContextPack,
    ContextPackItem,
    EvidenceSpan,
    Model,
    RepoEvent,
    RunObservation,
    SourceDocument,
    SyncJob,
    Workspace,
)


class TestRelationshipConfidenceEvidenceMigration:
    """Prove existing DB compatibility: migration adds missing columns and backfills them."""

    @pytest.fixture
    async def legacy_engine(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db_url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(db_url)

        async with engine.begin() as conn:
            await conn.run_sync(_create_legacy_schema)

        yield engine, db_url

        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass

    async def test_migration_adds_missing_columns(self, legacy_engine):
        engine, _ = legacy_engine

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO source_documents "
                    "(id, source_type, external_id, content, metadata) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000001', 'local', 'doc1', 'test', '{}')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO models (id, name) VALUES "
                    "('00000000-0000-0000-0000-000000000002', 'TestModel')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000003', "
                    "'00000000-0000-0000-0000-000000000002', "
                    "'00000000-0000-0000-0000-000000000001', "
                    "'A', 'Component A', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000004', "
                    "'00000000-0000-0000-0000-000000000002', "
                    "'00000000-0000-0000-0000-000000000001', "
                    "'B', 'Component B', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO relationships "
                    "(id, source_component_id, target_component_id, relationship_type) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000005', "
                    "'00000000-0000-0000-0000-000000000003', "
                    "'00000000-0000-0000-0000-000000000004', "
                    "'depends_on')"
                )
            )
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA table_info(relationships)"))
            columns = {row[1] for row in result.fetchall()}
            assert "confidence" in columns
            assert "evidence" in columns
            assert "status" in columns

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT confidence, evidence, status FROM relationships "
                    "WHERE id = '00000000-0000-0000-0000-000000000005'"
                )
            )
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.7
            assert row[1] == "backfill: schema migration"
            assert row[2] == "active"

    async def test_migration_is_idempotent(self, legacy_engine):
        engine, _ = legacy_engine

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO source_documents "
                    "(id, source_type, external_id, content, metadata) "
                    "VALUES ('10000000-0000-0000-0000-000000000001', 'local', 'doc2', 'test', '{}')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO models (id, name) VALUES "
                    "('10000000-0000-0000-0000-000000000002', 'Model2')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('10000000-0000-0000-0000-000000000003', "
                    "'10000000-0000-0000-0000-000000000002', "
                    "'10000000-0000-0000-0000-000000000001', "
                    "'X', 'X', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('10000000-0000-0000-0000-000000000004', "
                    "'10000000-0000-0000-0000-000000000002', "
                    "'10000000-0000-0000-0000-000000000001', "
                    "'Y', 'Y', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO relationships "
                    "(id, source_component_id, target_component_id, relationship_type) "
                    "VALUES "
                    "('10000000-0000-0000-0000-000000000005', "
                    "'10000000-0000-0000-0000-000000000003', "
                    "'10000000-0000-0000-0000-000000000004', "
                    "'enables')"
                )
            )
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)
        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT confidence, evidence FROM relationships "
                    "WHERE id = '10000000-0000-0000-0000-000000000005'"
                )
            )
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.7
            assert "backfill" in row[1]

    async def test_migration_does_not_overwrite_existing_values(self, legacy_engine):
        engine, _ = legacy_engine

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO source_documents "
                    "(id, source_type, external_id, content, metadata) "
                    "VALUES ('20000000-0000-0000-0000-000000000001', 'local', 'doc3', 'test', '{}')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO models (id, name) VALUES "
                    "('20000000-0000-0000-0000-000000000002', 'Model3')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('20000000-0000-0000-0000-000000000003', "
                    "'20000000-0000-0000-0000-000000000002', "
                    "'20000000-0000-0000-0000-000000000001', "
                    "'Z', 'Z', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('20000000-0000-0000-0000-000000000004', "
                    "'20000000-0000-0000-0000-000000000002', "
                    "'20000000-0000-0000-0000-000000000001', "
                    "'W', 'W', 'fact', 0.8, 'active')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO relationships "
                    "(id, source_component_id, target_component_id, relationship_type) "
                    "VALUES "
                    "('20000000-0000-0000-0000-000000000005', "
                    "'20000000-0000-0000-0000-000000000003', "
                    "'20000000-0000-0000-0000-000000000004', "
                    "'blocked_by')"
                )
            )
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "UPDATE relationships SET confidence = 0.95, "
                    "evidence = 'custom evidence text' "
                    "WHERE id = '20000000-0000-0000-0000-000000000005'"
                )
            )
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT confidence, evidence FROM relationships "
                    "WHERE id = '20000000-0000-0000-0000-000000000005'"
                )
            )
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.95
            assert row[1] == "custom evidence text"

    async def test_migration_noops_when_relationships_table_missing(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA table_info(relationships)"))
                assert result.fetchall() == []
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestConnectorWorkspaceMigration:
    """Prove old connector columns do not break new workspace-aware inserts."""

    async def test_migration_removes_legacy_connector_constraints(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                    CREATE TABLE workspaces (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TABLE connectors (
                        id TEXT PRIMARY KEY,
                        connector_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'disconnected',
                        config TEXT NOT NULL,
                        credentials TEXT NOT NULL,
                        items_synced INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                )
                await conn.execute(
                    text("""
                    INSERT INTO connectors (
                        id, connector_type, status, config, credentials, items_synced
                    ) VALUES (
                        'legacy-github', 'github', 'connected',
                        '{"repositories":["owner/repo"]}', '{"access_token":"old"}', 7
                    )
                """)
                )

            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA table_info(connectors)"))
                columns = {row[1] for row in result.fetchall()}
                assert "workspace_id" in columns
                assert "config_json" in columns
                assert "credentials_json" in columns
                assert "config" not in columns
                assert "credentials" not in columns
                assert "items_synced" not in columns

                row = (
                    await conn.execute(
                        text("""
                    SELECT workspace_id, config_json, credentials_json
                    FROM connectors WHERE id = 'legacy-github'
                """)
                    )
                ).fetchone()
                assert row is not None
                assert row[0]
                assert "owner/repo" in row[1]
                assert "old" in row[2]

            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(
                    Connector(
                        workspace_id=UUID("00000000-0000-0000-0000-000000000000"),
                        connector_type="zoom",
                        status="connected",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestSyncJobMigration:
    """Prove legacy sync_jobs.result_metadata constraints do not break new inserts."""

    async def test_migration_removes_legacy_result_metadata_column(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                    CREATE TABLE workspaces (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TABLE connectors (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        connector_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'disconnected',
                        config_json TEXT NOT NULL DEFAULT '{}',
                        credentials_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TABLE sync_jobs (
                        id TEXT PRIMARY KEY,
                        connector_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        error_type TEXT,
                        error_message TEXT,
                        result_metadata TEXT NOT NULL,
                        result_metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        started_at TEXT,
                        completed_at TEXT
                    )
                """)
                )
                await conn.execute(
                    text("""
                    INSERT INTO connectors (
                        id, workspace_id, connector_type, status, config_json, credentials_json
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000000',
                        'github', 'connected', '{}', '{}'
                    )
                """)
                )
                await conn.execute(
                    text("""
                    INSERT INTO sync_jobs (
                        id, connector_id, status, result_metadata
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000002',
                        '00000000-0000-0000-0000-000000000001',
                        'completed',
                        :metadata
                    )
                """),
                    {"metadata": '{"documents_fetched":1}'},
                )

            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                result = await conn.execute(text("PRAGMA table_info(sync_jobs)"))
                columns = {row[1] for row in result.fetchall()}
                assert "result_metadata_json" in columns
                assert "result_metadata" not in columns
                assert "workspace_id" in columns
                assert "job_type" in columns
                assert "idempotency_key" in columns
                assert "attempt_count" in columns
                assert "max_attempts" in columns
                assert "queued_at" in columns
                assert "available_at" in columns
                assert "lease_expires_at" in columns
                assert "locked_by" in columns
                assert "dead_lettered_at" in columns

                row = (
                    await conn.execute(
                        text("""
                    SELECT workspace_id, job_type, idempotency_key, attempt_count,
                           max_attempts, result_metadata_json, queued_at
                    FROM sync_jobs
                    WHERE id = '00000000-0000-0000-0000-000000000002'
                """)
                    )
                ).fetchone()
                assert row is not None
                assert row[0] == "00000000-0000-0000-0000-000000000000"
                assert row[1] == "connector_sync"
                assert row[2] == "connector_sync:00000000-0000-0000-0000-000000000001"
                assert row[3] == 0
                assert row[4] == 3
                assert "documents_fetched" in row[5]
                assert row[6] is not None

            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(
                    SyncJob(
                        workspace_id=UUID("00000000-0000-0000-0000-000000000000"),
                        connector_id=UUID("00000000-0000-0000-0000-000000000001"),
                        job_type="connector_sync",
                        idempotency_key="connector_sync:00000000-0000-0000-0000-000000000001",
                        status="pending",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestQueryAndSyncIndexMigration:
    """Prove existing graph databases get launch-critical query indexes safely."""

    async def test_migration_creates_graph_query_indexes_once(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.run_sync(_create_legacy_schema)

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                source_indexes = await _index_names(conn, "source_documents")
                component_indexes = await _index_names(conn, "components")
                relationship_indexes = await _index_names(conn, "relationships")
                unresolved_relationship_indexes = await _index_names(
                    conn, "unresolved_relationships"
                )
                unresolved_relationship_columns = await _table_columns(
                    conn, "unresolved_relationships"
                )
                retrieval_event_columns = await _table_columns(conn, "retrieval_events")
                retrieval_event_indexes = await _index_names(conn, "retrieval_events")
                sync_job_indexes = await _index_names(conn, "sync_jobs")
                entity_alias_indexes = await _index_names(conn, "entity_aliases")
                fact_indexes = await _index_names(conn, "facts")
                mention_indexes = await _index_names(conn, "mentions")

            expected_source_indexes = {
                "ix_source_documents_source_type_external_id",
                "ix_source_documents_processed_at",
                "ix_source_documents_ingested_at",
            }
            expected_component_indexes = {
                "ix_components_status_confidence",
                "ix_components_model_status",
                "ix_components_source_status",
            }
            expected_relationship_indexes = {
                "ix_relationships_status_origin",
                "ix_relationships_source_status",
                "ix_relationships_target_status",
                "ix_relationships_source_target_type",
            }
            expected_unresolved_relationship_columns = {
                "source_component_id",
                "source_document_id",
                "target_name",
                "target_identity_key",
                "relationship_type",
                "confidence",
                "evidence",
                "origin",
                "status",
                "resolved_relationship_id",
            }
            expected_unresolved_relationship_indexes = {
                "ix_unresolved_relationships_workspace_status",
                "ix_unresolved_relationships_source_status",
                "ix_unresolved_relationships_source_document",
                "ix_unresolved_relationships_target_identity",
                "ix_unresolved_relationships_source_target_type",
            }
            expected_retrieval_event_columns = {
                "workspace_id",
                "question",
                "answer",
                "trace_json",
                "created_at",
            }
            expected_retrieval_event_indexes = {
                "ix_retrieval_events_workspace_created",
                "ix_retrieval_events_created_at",
            }
            expected_sync_job_indexes = {
                "ix_sync_jobs_workspace_status",
                "ix_sync_jobs_idempotency_key",
                "ix_sync_jobs_job_type_status",
                "ix_sync_jobs_queue_due",
                "ix_sync_jobs_lease_expires_at",
            }
            expected_entity_alias_indexes = {
                "ix_entity_aliases_workspace_normalized",
                "ix_entity_aliases_entity",
            }
            expected_fact_indexes = {
                "ix_facts_workspace_status_confidence",
                "ix_facts_workspace_entity",
                "ix_facts_source_document",
            }
            expected_mention_indexes = {
                "ix_mentions_workspace_normalized",
                "ix_mentions_entity",
                "ix_mentions_source_document",
            }

            assert expected_source_indexes <= set(source_indexes)
            assert expected_component_indexes <= set(component_indexes)
            assert expected_relationship_indexes <= set(relationship_indexes)
            assert expected_unresolved_relationship_columns <= set(unresolved_relationship_columns)
            assert expected_unresolved_relationship_indexes <= set(unresolved_relationship_indexes)
            assert expected_retrieval_event_columns <= set(retrieval_event_columns)
            assert expected_retrieval_event_indexes <= set(retrieval_event_indexes)
            assert expected_sync_job_indexes <= set(sync_job_indexes)
            assert expected_entity_alias_indexes <= set(entity_alias_indexes)
            assert expected_fact_indexes <= set(fact_indexes)
            assert expected_mention_indexes <= set(mention_indexes)
            for index_name in (
                expected_source_indexes
                | expected_component_indexes
                | expected_relationship_indexes
                | expected_unresolved_relationship_indexes
                | expected_retrieval_event_indexes
                | expected_sync_job_indexes
                | expected_entity_alias_indexes
                | expected_fact_indexes
                | expected_mention_indexes
            ):
                all_indexes = (
                    source_indexes
                    + component_indexes
                    + relationship_indexes
                    + unresolved_relationship_indexes
                    + retrieval_event_indexes
                    + sync_job_indexes
                    + entity_alias_indexes
                    + fact_indexes
                    + mention_indexes
                )
                assert all_indexes.count(index_name) == 1
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass

    async def test_index_migration_noops_when_required_columns_are_missing(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                    CREATE TABLE source_documents (
                        id TEXT PRIMARY KEY,
                        external_id TEXT NOT NULL
                    )
                """)
                )

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                source_indexes = await _index_names(conn, "source_documents")
                assert "ix_source_documents_source_type_external_id" not in source_indexes
                assert "ix_source_documents_processed_at" not in source_indexes
                assert "ix_source_documents_ingested_at" not in source_indexes
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestWorkspaceOwnershipMigration:
    """Prove legacy metadata-scoped rows gain first-class workspace columns."""

    async def test_backfills_source_and_component_workspace_ids_from_metadata(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        workspace_id = "33333333-3333-3333-3333-333333333333"

        try:
            async with engine.begin() as conn:
                await conn.run_sync(_create_legacy_schema)

            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO source_documents "
                        "(id, source_type, external_id, content, metadata) "
                        "VALUES "
                        "('30000000-0000-0000-0000-000000000001', "
                        "'slack', 'slack:C1:1', 'Decision: Ship it.', :metadata)"
                    ),
                    {"metadata": f'{{"workspace_id":"{workspace_id}"}}'},
                )
                await conn.execute(
                    text(
                        "INSERT INTO models (id, name) VALUES "
                        "('30000000-0000-0000-0000-000000000002', 'Decision')"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO components "
                        "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                        "VALUES "
                        "('30000000-0000-0000-0000-000000000003', "
                        "'30000000-0000-0000-0000-000000000002', "
                        "'30000000-0000-0000-0000-000000000001', "
                        "'Ship', 'Ship it.', 'decision', 0.8, 'active')"
                    )
                )

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                source_columns = {
                    row[1]
                    for row in (
                        await conn.execute(text("PRAGMA table_info(source_documents)"))
                    ).fetchall()
                }
                component_columns = {
                    row[1]
                    for row in (
                        await conn.execute(text("PRAGMA table_info(components)"))
                    ).fetchall()
                }
                entity_columns = {
                    row[1]
                    for row in (await conn.execute(text("PRAGMA table_info(entities)"))).fetchall()
                }
                assert "workspace_id" in source_columns
                assert "workspace_id" in component_columns
                assert "identity_key" in component_columns
                assert "entity_id" in component_columns
                assert {"id", "workspace_id", "identity_key", "canonical_name"} <= entity_columns

                source_row = (
                    await conn.execute(
                        text(
                            "SELECT workspace_id FROM source_documents "
                            "WHERE id = '30000000-0000-0000-0000-000000000001'"
                        )
                    )
                ).fetchone()
                component_row = (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, identity_key, entity_id FROM components "
                            "WHERE id = '30000000-0000-0000-0000-000000000003'"
                        )
                    )
                ).fetchone()
                assert source_row is not None
                assert component_row is not None
                assert source_row[0] == UUID(workspace_id).hex
                assert component_row[0] == UUID(workspace_id).hex
                assert component_row[1] == "component:ship"
                assert component_row[2]

                entity_row = (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, identity_key, canonical_name FROM entities "
                            "WHERE id = :entity_id"
                        ),
                        {"entity_id": component_row[2]},
                    )
                ).fetchone()
                assert entity_row is not None
                assert entity_row[0] == UUID(workspace_id).hex
                assert entity_row[1] == "component:ship"
                assert entity_row[2] == "Ship"
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestEvidenceLedgerMigration:
    async def test_migration_adds_source_ledger_claim_and_runtime_tables(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.run_sync(_create_legacy_schema)

            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO source_documents "
                        "(id, source_type, external_id, content, metadata) "
                        "VALUES "
                        "('40000000-0000-0000-0000-000000000001', "
                        "'local', 'ledger-doc', 'Decision: Keep raw evidence.', "
                        '\'{"created_at":"2026-01-02T03:04:05+00:00"}\')'
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO models (id, name) VALUES "
                        "('40000000-0000-0000-0000-000000000002', 'Decision')"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO components "
                        "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                        "VALUES "
                        "('40000000-0000-0000-0000-000000000003', "
                        "'40000000-0000-0000-0000-000000000002', "
                        "'40000000-0000-0000-0000-000000000001', "
                        "'Keep raw evidence', 'Keep raw evidence.', 'decision', 0.9, 'active')"
                    )
                )

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                source_columns = await _table_columns(conn, "source_documents")
                component_columns = await _table_columns(conn, "components")
                evidence_columns = await _table_columns(conn, "evidence_spans")
                claim_columns = await _table_columns(conn, "claims")
                revision_columns = await _table_columns(conn, "claim_revisions")
                runtime_tables = {
                    name: await _table_columns(conn, name)
                    for name in (
                        "context_packs",
                        "context_pack_items",
                        "agent_runs",
                        "run_observations",
                        "code_files",
                        "code_symbols",
                        "code_edges",
                        "repo_events",
                        "open_loops",
                        "verified_playbooks",
                    )
                }
                deterministic_triggers = set((await conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ))).scalars())

                assert {"content_sha256", "trust_zone", "source_created_at"} <= set(source_columns)
                assert "claim_id" in component_columns
                assert {
                    "source_document_id",
                    "start_char",
                    "end_char",
                    "text",
                    "text_sha256",
                    "prompt_injection_risk_score",
                    "review_status",
                } <= set(evidence_columns)
                assert {
                    "identity_key",
                    "claim_type",
                    "status",
                    "current_revision_id",
                } <= set(claim_columns)
                assert {
                    "claim_id",
                    "evidence_span_id",
                    "operation",
                    "status_after",
                    "supersedes_claim_id",
                    "contradicts_claim_id",
                    "created_by",
                } <= set(revision_columns)
                assert {
                    "model_profile",
                    "repo_state_json",
                    "idempotency_key",
                    "markdown",
                    "manifest",
                    "health_score",
                } <= set(runtime_tables["context_packs"])
                assert {
                    "item_type",
                    "claim_id",
                    "component_id",
                    "evidence_span_id",
                    "source_document_id",
                    "score",
                    "inclusion_reason",
                    "token_cost",
                    "created_at",
                } <= set(runtime_tables["context_pack_items"])
                for columns in runtime_tables.values():
                    assert columns
                assert {
                    "trg_code_files_identity_key_not_null_insert",
                    "trg_code_files_identity_key_not_null_update",
                    "trg_code_symbols_identity_key_not_null_insert",
                    "trg_code_edges_edge_key_not_null_insert",
                    "trg_code_edges_rule_id_not_null_insert",
                    "trg_code_edges_rule_version_not_null_insert",
                    "trg_code_edges_evidence_sha256_not_null_insert",
                } <= deterministic_triggers

                row = (
                    await conn.execute(
                        text(
                            "SELECT content, content_sha256, trust_zone, source_created_at "
                            "FROM source_documents "
                            "WHERE id = '40000000-0000-0000-0000-000000000001'"
                        )
                    )
                ).fetchone()
                assert row is not None
                assert row[0] == "Decision: Keep raw evidence."
                assert row[1] == hashlib.sha256(row[0].encode("utf-8")).hexdigest()
                assert row[2] == "trusted_repo"
                assert row[3] is not None

                evidence_indexes = await _index_names(conn, "evidence_spans")
                claim_indexes = await _index_names(conn, "claims")
                pack_indexes = await _index_names(conn, "context_packs")
                item_indexes = await _index_names(conn, "context_pack_items")
                assert evidence_indexes.count("ix_evidence_spans_workspace_document") == 1
                assert claim_indexes.count("ix_claims_workspace_identity") == 1
                assert pack_indexes.count("ix_context_packs_workspace_target_created") == 1
                assert item_indexes.count("ix_context_pack_items_claim") == 1
                assert item_indexes.count("ix_context_pack_items_source_document") == 1
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass

    async def test_runtime_tables_round_trip_final_context_pack_contract(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await run_migrations(conn)

            workspace_id = uuid4()
            source_id = uuid4()
            evidence_id = uuid4()
            claim_id = uuid4()
            component_id = uuid4()
            pack_id = uuid4()
            run_id = uuid4()
            code_file_id = uuid4()
            symbol_a_id = uuid4()
            symbol_b_id = uuid4()
            manifest = {
                "schema_version": "context_pack.v2",
                "context_pack_id": str(pack_id),
                "selected_context": [{"id": "claim:launch", "claim_id": str(claim_id)}],
                "rendering": {"markdown_sha256": "abc123", "estimated_tokens": 128},
            }
            repo_state = {
                "branch": "agent/2-evidence-ledger-claim-graph",
                "head_commit": "def456",
                "dirty": True,
            }

            async with AsyncSession(engine, expire_on_commit=False) as session:
                workspace = Workspace(
                    id=workspace_id,
                    name="Runtime Round Trip",
                    slug=f"runtime-{workspace_id.hex}",
                )
                source = SourceDocument(
                    id=source_id,
                    workspace_id=workspace_id,
                    source_type="local",
                    external_id="runtime-source",
                    content="Decision: persist final context packs.",
                    metadata_json="{}",
                )
                evidence = EvidenceSpan(
                    id=evidence_id,
                    workspace_id=workspace_id,
                    source_document_id=source_id,
                    start_char=10,
                    end_char=38,
                    text="persist final context packs.",
                    text_sha256=hashlib.sha256(
                        "persist final context packs.".encode("utf-8")
                    ).hexdigest(),
                    evidence_type="source_quote",
                    authority_weight=0.9,
                    trust_zone="trusted_repo",
                    extraction_method="deterministic",
                    review_status="verified",
                )
                claim = Claim(
                    id=claim_id,
                    workspace_id=workspace_id,
                    identity_key="component:persist-final-context-packs",
                    claim_type="decision",
                    status="active",
                    temporal="current",
                    confidence=0.94,
                    authority_weight=0.9,
                )
                revision = ClaimRevision(
                    id=uuid4(),
                    claim_id=claim_id,
                    evidence_span_id=evidence_id,
                    value="Persist final context packs.",
                    operation="create",
                    confidence_delta=0.94,
                    status_after="active",
                    created_by="unit:test",
                )
                claim.current_revision_id = revision.id
                model = Model(id=uuid4(), name="Decision")
                component = Component(
                    id=component_id,
                    workspace_id=workspace_id,
                    model_id=model.id,
                    source_document_id=source_id,
                    claim_id=claim_id,
                    identity_key="component:persist-final-context-packs",
                    name="Persist final context packs",
                    value="Persist final context packs.",
                    fact_type="decision",
                    confidence=0.94,
                    authority_weight=0.9,
                    status="active",
                    provenance='{"source":"unit"}',
                    excerpt="persist final context packs.",
                )
                pack = ContextPack(
                    id=pack_id,
                    workspace_id=workspace_id,
                    objective="finish runtime persistence",
                    target_model="qwen2.5-coder-7b",
                    model_profile="small_coder_model",
                    token_budget=12000,
                    pack_version="context_pack.v2",
                    health_score=0.82,
                    markdown="# Objective\n\nFinish runtime persistence.",
                    manifest=json.dumps(manifest, sort_keys=True),
                    repo_state_json=json.dumps(repo_state, sort_keys=True),
                    idempotency_key="round-trip-key",
                )
                items = [
                    ContextPackItem(
                        id=uuid4(),
                        context_pack_id=pack_id,
                        item_type="claim",
                        claim_id=claim_id,
                        component_id=component_id,
                        evidence_span_id=evidence_id,
                        source_document_id=source_id,
                        score=0.94,
                        inclusion_reason="non_negotiable_runtime_persistence",
                        token_cost=48,
                    ),
                    ContextPackItem(
                        id=uuid4(),
                        context_pack_id=pack_id,
                        item_type="verification",
                        score=0.76,
                        inclusion_reason="required_test_command",
                        token_cost=16,
                    ),
                ]
                run = AgentRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    context_pack_id=pack_id,
                    tool="codex",
                    model="qwen2.5-coder-7b",
                    objective="finish runtime persistence",
                    branch="agent/2-evidence-ledger-claim-graph",
                    base_commit="abc123",
                    head_commit="def456",
                    status="completed",
                )
                observation = RunObservation(
                    id=uuid4(),
                    agent_run_id=run_id,
                    source_document_id=source_id,
                    event_type="test",
                    content="pytest passed",
                    files_json=json.dumps(["tests/test_migrations.py"]),
                    command="pytest -q tests/test_migrations.py",
                    exit_code=0,
                )
                code_file = CodeFile(
                    id=code_file_id,
                    workspace_id=workspace_id,
                    repo_root="/repo",
                    path="app/models.py",
                    language="python",
                    sha256="f" * 64,
                    last_commit="def456",
                    size=1234,
                )
                symbol_a = CodeSymbol(
                    id=symbol_a_id,
                    code_file_id=code_file_id,
                    symbol_type="class",
                    name="ContextPack",
                    qualified_name="app.models.ContextPack",
                    start_line=1,
                    end_line=10,
                )
                symbol_b = CodeSymbol(
                    id=symbol_b_id,
                    code_file_id=code_file_id,
                    symbol_type="class",
                    name="ContextPackItem",
                    qualified_name="app.models.ContextPackItem",
                    start_line=11,
                    end_line=20,
                )
                code_edge = CodeEdge(
                    id=uuid4(),
                    source_symbol_id=symbol_b_id,
                    target_symbol_id=symbol_a_id,
                    edge_type="references",
                )
                repo_event = RepoEvent(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    commit_sha="def456",
                    branch="agent/2-evidence-ledger-claim-graph",
                    author="unit",
                    message="runtime persistence",
                    changed_files_json=json.dumps(["app/models.py"]),
                )
                session.add_all(
                    [
                        workspace,
                        source,
                        evidence,
                        claim,
                        revision,
                        model,
                        component,
                        pack,
                        *items,
                        run,
                        observation,
                        code_file,
                        symbol_a,
                        symbol_b,
                        code_edge,
                        repo_event,
                    ]
                )
                await session.commit()

            async with AsyncSession(engine, expire_on_commit=False) as session:
                pack = await session.scalar(
                    select(ContextPack)
                    .options(selectinload(ContextPack.items), selectinload(ContextPack.agent_runs))
                    .where(ContextPack.id == pack_id)
                )
                stored_items = (
                    await session.scalars(
                        select(ContextPackItem)
                        .where(ContextPackItem.context_pack_id == pack_id)
                        .order_by(ContextPackItem.item_type)
                    )
                ).all()
                run = await session.scalar(
                    select(AgentRun)
                    .options(selectinload(AgentRun.observations))
                    .where(AgentRun.id == run_id)
                )
                code_file = await session.scalar(
                    select(CodeFile)
                    .options(selectinload(CodeFile.symbols))
                    .where(CodeFile.id == code_file_id)
                )
                edge = await session.get(CodeEdge, code_edge.id)
                repo_event = await session.get(RepoEvent, repo_event.id)

                assert pack is not None
                assert pack.markdown == "# Objective\n\nFinish runtime persistence."
                assert json.loads(pack.manifest) == manifest
                assert json.loads(pack.repo_state_json) == repo_state
                assert pack.model_profile == "small_coder_model"
                assert pack.idempotency_key == "round-trip-key"
                assert pack.health_score == 0.82
                claim_item = next(item for item in stored_items if item.item_type == "claim")
                assert claim_item.claim_id == claim_id
                assert claim_item.component_id == component_id
                assert claim_item.evidence_span_id == evidence_id
                assert claim_item.source_document_id == source_id
                assert claim_item.score == 0.94
                assert claim_item.inclusion_reason == "non_negotiable_runtime_persistence"
                assert claim_item.token_cost == 48
                assert claim_item.created_at is not None
                verification_item = next(
                    item for item in stored_items if item.item_type == "verification"
                )
                assert verification_item.score == 0.76
                assert run is not None
                assert run.context_pack_id == pack_id
                assert run.observations[0].content == "pytest passed"
                assert run.observations[0].exit_code == 0
                assert code_file is not None
                assert [symbol.name for symbol in code_file.symbols] == [
                    "ContextPack",
                    "ContextPackItem",
                ]
                assert edge.edge_type == "references"
                assert json.loads(repo_event.changed_files_json) == ["app/models.py"]
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


def _create_legacy_schema(connection):
    """Create the schema WITHOUT confidence and evidence on relationships."""
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS source_documents (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT,
            source_url TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT
        )
    """)
    )
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    )
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS components (
            id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL REFERENCES models(id),
            source_document_id TEXT NOT NULL REFERENCES source_documents(id),
            name TEXT NOT NULL,
            value TEXT NOT NULL,
            fact_type TEXT NOT NULL DEFAULT 'fact',
            confidence REAL NOT NULL DEFAULT 0.5,
            authority_weight REAL NOT NULL DEFAULT 0.5,
            embedding TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            valid_from TEXT NOT NULL DEFAULT (datetime('now')),
            valid_to TEXT,
            superseded_by_id TEXT REFERENCES components(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    )
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            source_component_id TEXT NOT NULL REFERENCES components(id),
            target_component_id TEXT NOT NULL REFERENCES components(id),
            relationship_type TEXT NOT NULL DEFAULT 'related_to',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    )
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS sync_jobs (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            connector_id TEXT NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'connector_sync',
            idempotency_key TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            error_type TEXT,
            error_message TEXT,
            result_metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT
        )
    """)
    )
    connection.commit()


async def _index_names(conn, table_name: str) -> list[str]:
    result = await conn.execute(text(f"PRAGMA index_list({table_name})"))
    return [row[1] for row in result.fetchall()]


async def _table_columns(conn, table_name: str) -> list[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    return [row[1] for row in result.fetchall()]
