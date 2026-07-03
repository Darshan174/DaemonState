from __future__ import annotations

import os
import tempfile
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import run_migrations
from app.models import Connector, SyncJob


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
            await conn.execute(text(
                "INSERT INTO source_documents "
                "(id, source_type, external_id, content, metadata) "
                "VALUES "
                "('00000000-0000-0000-0000-000000000001', 'local', 'doc1', 'test', '{}')"
            ))
            await conn.execute(text(
                "INSERT INTO models (id, name) VALUES "
                "('00000000-0000-0000-0000-000000000002', 'TestModel')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('00000000-0000-0000-0000-000000000003', "
                "'00000000-0000-0000-0000-000000000002', "
                "'00000000-0000-0000-0000-000000000001', "
                "'A', 'Component A', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('00000000-0000-0000-0000-000000000004', "
                "'00000000-0000-0000-0000-000000000002', "
                "'00000000-0000-0000-0000-000000000001', "
                "'B', 'Component B', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO relationships "
                "(id, source_component_id, target_component_id, relationship_type) "
                "VALUES "
                "('00000000-0000-0000-0000-000000000005', "
                "'00000000-0000-0000-0000-000000000003', "
                "'00000000-0000-0000-0000-000000000004', "
                "'depends_on')"
            ))
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
            result = await conn.execute(text(
                "SELECT confidence, evidence, status FROM relationships "
                "WHERE id = '00000000-0000-0000-0000-000000000005'"
            ))
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.7
            assert row[1] == "backfill: schema migration"
            assert row[2] == "active"

    async def test_migration_is_idempotent(self, legacy_engine):
        engine, _ = legacy_engine

        async with engine.connect() as conn:
            await conn.execute(text(
                "INSERT INTO source_documents "
                "(id, source_type, external_id, content, metadata) "
                "VALUES ('10000000-0000-0000-0000-000000000001', 'local', 'doc2', 'test', '{}')"
            ))
            await conn.execute(text(
                "INSERT INTO models (id, name) VALUES "
                "('10000000-0000-0000-0000-000000000002', 'Model2')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('10000000-0000-0000-0000-000000000003', "
                "'10000000-0000-0000-0000-000000000002', "
                "'10000000-0000-0000-0000-000000000001', "
                "'X', 'X', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('10000000-0000-0000-0000-000000000004', "
                "'10000000-0000-0000-0000-000000000002', "
                "'10000000-0000-0000-0000-000000000001', "
                "'Y', 'Y', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO relationships "
                "(id, source_component_id, target_component_id, relationship_type) "
                "VALUES "
                "('10000000-0000-0000-0000-000000000005', "
                "'10000000-0000-0000-0000-000000000003', "
                "'10000000-0000-0000-0000-000000000004', "
                "'enables')"
            ))
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)
        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT confidence, evidence FROM relationships "
                "WHERE id = '10000000-0000-0000-0000-000000000005'"
            ))
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.7
            assert "backfill" in row[1]

    async def test_migration_does_not_overwrite_existing_values(self, legacy_engine):
        engine, _ = legacy_engine

        async with engine.connect() as conn:
            await conn.execute(text(
                "INSERT INTO source_documents "
                "(id, source_type, external_id, content, metadata) "
                "VALUES ('20000000-0000-0000-0000-000000000001', 'local', 'doc3', 'test', '{}')"
            ))
            await conn.execute(text(
                "INSERT INTO models (id, name) VALUES "
                "('20000000-0000-0000-0000-000000000002', 'Model3')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('20000000-0000-0000-0000-000000000003', "
                "'20000000-0000-0000-0000-000000000002', "
                "'20000000-0000-0000-0000-000000000001', "
                "'Z', 'Z', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO components "
                "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                "VALUES "
                "('20000000-0000-0000-0000-000000000004', "
                "'20000000-0000-0000-0000-000000000002', "
                "'20000000-0000-0000-0000-000000000001', "
                "'W', 'W', 'fact', 0.8, 'active')"
            ))
            await conn.execute(text(
                "INSERT INTO relationships "
                "(id, source_component_id, target_component_id, relationship_type) "
                "VALUES "
                "('20000000-0000-0000-0000-000000000005', "
                "'20000000-0000-0000-0000-000000000003', "
                "'20000000-0000-0000-0000-000000000004', "
                "'blocked_by')"
            ))
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            await conn.execute(text(
                "UPDATE relationships SET confidence = 0.95, "
                "evidence = 'custom evidence text' "
                "WHERE id = '20000000-0000-0000-0000-000000000005'"
            ))
            await conn.commit()

        async with engine.begin() as conn:
            await run_migrations(conn)

        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT confidence, evidence FROM relationships "
                "WHERE id = '20000000-0000-0000-0000-000000000005'"
            ))
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
                await conn.execute(text("""
                    CREATE TABLE workspaces (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """))
                await conn.execute(text("""
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
                """))
                await conn.execute(text("""
                    INSERT INTO connectors (
                        id, connector_type, status, config, credentials, items_synced
                    ) VALUES (
                        'legacy-github', 'github', 'connected',
                        '{"repositories":["owner/repo"]}', '{"access_token":"old"}', 7
                    )
                """))

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

                row = (await conn.execute(text("""
                    SELECT workspace_id, config_json, credentials_json
                    FROM connectors WHERE id = 'legacy-github'
                """))).fetchone()
                assert row is not None
                assert row[0]
                assert "owner/repo" in row[1]
                assert "old" in row[2]

            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(Connector(
                    workspace_id=UUID("00000000-0000-0000-0000-000000000000"),
                    connector_type="zoom",
                    status="connected",
                ))
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
                await conn.execute(text("""
                    CREATE TABLE workspaces (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """))
                await conn.execute(text("""
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
                """))
                await conn.execute(text("""
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
                """))
                await conn.execute(text("""
                    INSERT INTO connectors (
                        id, workspace_id, connector_type, status, config_json, credentials_json
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000000',
                        'github', 'connected', '{}', '{}'
                    )
                """))
                await conn.execute(text("""
                    INSERT INTO sync_jobs (
                        id, connector_id, status, result_metadata
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000002',
                        '00000000-0000-0000-0000-000000000001',
                        'completed',
                        :metadata
                    )
                """), {"metadata": '{"documents_fetched":1}'})

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

                row = (await conn.execute(text("""
                    SELECT workspace_id, job_type, idempotency_key, attempt_count,
                           max_attempts, result_metadata_json, queued_at
                    FROM sync_jobs
                    WHERE id = '00000000-0000-0000-0000-000000000002'
                """))).fetchone()
                assert row is not None
                assert row[0] == "00000000-0000-0000-0000-000000000000"
                assert row[1] == "connector_sync"
                assert row[2] == "connector_sync:00000000-0000-0000-0000-000000000001"
                assert row[3] == 0
                assert row[4] == 3
                assert "documents_fetched" in row[5]
                assert row[6] is not None

            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(SyncJob(
                    workspace_id=UUID("00000000-0000-0000-0000-000000000000"),
                    connector_id=UUID("00000000-0000-0000-0000-000000000001"),
                    job_type="connector_sync",
                    idempotency_key="connector_sync:00000000-0000-0000-0000-000000000001",
                    status="pending",
                ))
                await session.commit()
        finally:
            await engine.dispose()
            try:
                os.unlink(path)
            except OSError:
                pass


class TestFactIdentityMigration:
    """Prove fact backfills work against tables created without DB defaults."""

    async def test_backfill_sets_extractor_version_without_database_default(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            async with engine.begin() as conn:
                await conn.run_sync(_create_legacy_schema)

            async with engine.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE facts (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT,
                        entity_id TEXT,
                        component_id TEXT NOT NULL UNIQUE,
                        source_document_id TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        fact_type TEXT NOT NULL DEFAULT 'fact',
                        confidence REAL NOT NULL DEFAULT 0.5,
                        status TEXT NOT NULL DEFAULT 'active',
                        provenance TEXT,
                        excerpt TEXT,
                        extractor_version TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """))
                await conn.execute(text(
                    "INSERT INTO source_documents "
                    "(id, source_type, external_id, content, metadata) "
                    "VALUES "
                    "('40000000-0000-0000-0000-000000000001', 'github_issue', "
                    "'issue-11', 'Issue #11: Codex/fix graph review: closed', '{}')"
                ))
                await conn.execute(text(
                    "INSERT INTO models (id, name) VALUES "
                    "('40000000-0000-0000-0000-000000000002', 'Issue')"
                ))
                await conn.execute(text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('40000000-0000-0000-0000-000000000003', "
                    "'40000000-0000-0000-0000-000000000002', "
                    "'40000000-0000-0000-0000-000000000001', "
                    "'Issue #11', 'Codex/fix graph review: closed', 'issue', 0.95, 'active')"
                ))

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                rows = (await conn.execute(text("""
                    SELECT claim, fact_type, confidence, extractor_version
                    FROM facts
                    WHERE component_id = '40000000-0000-0000-0000-000000000003'
                """))).fetchall()

            assert rows == [(
                "Issue #11: Codex/fix graph review: closed",
                "issue",
                0.95,
                "extractor.v1",
            )]
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
                unresolved_relationship_indexes = await _index_names(conn, "unresolved_relationships")
                unresolved_relationship_columns = await _table_columns(conn, "unresolved_relationships")
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
                await conn.execute(text("""
                    CREATE TABLE source_documents (
                        id TEXT PRIMARY KEY,
                        external_id TEXT NOT NULL
                    )
                """))

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
                await conn.execute(text(
                    "INSERT INTO source_documents "
                    "(id, source_type, external_id, content, metadata) "
                    "VALUES "
                    "('30000000-0000-0000-0000-000000000001', "
                    "'slack', 'slack:C1:1', 'Decision: Ship it.', :metadata)"
                ), {"metadata": f'{{"workspace_id":"{workspace_id}"}}'})
                await conn.execute(text(
                    "INSERT INTO models (id, name) VALUES "
                    "('30000000-0000-0000-0000-000000000002', 'Decision')"
                ))
                await conn.execute(text(
                    "INSERT INTO components "
                    "(id, model_id, source_document_id, name, value, fact_type, confidence, status) "
                    "VALUES "
                    "('30000000-0000-0000-0000-000000000003', "
                    "'30000000-0000-0000-0000-000000000002', "
                    "'30000000-0000-0000-0000-000000000001', "
                    "'Ship', 'Ship it.', 'decision', 0.8, 'active')"
                ))

            async with engine.begin() as conn:
                await run_migrations(conn)
            async with engine.begin() as conn:
                await run_migrations(conn)

            async with engine.connect() as conn:
                source_columns = {
                    row[1] for row in (await conn.execute(text("PRAGMA table_info(source_documents)"))).fetchall()
                }
                component_columns = {
                    row[1] for row in (await conn.execute(text("PRAGMA table_info(components)"))).fetchall()
                }
                entity_columns = {
                    row[1] for row in (await conn.execute(text("PRAGMA table_info(entities)"))).fetchall()
                }
                assert "workspace_id" in source_columns
                assert "workspace_id" in component_columns
                assert "identity_key" in component_columns
                assert "entity_id" in component_columns
                assert {"id", "workspace_id", "identity_key", "canonical_name"} <= entity_columns

                source_row = (await conn.execute(text(
                    "SELECT workspace_id FROM source_documents "
                    "WHERE id = '30000000-0000-0000-0000-000000000001'"
                ))).fetchone()
                component_row = (await conn.execute(text(
                    "SELECT workspace_id, identity_key, entity_id FROM components "
                    "WHERE id = '30000000-0000-0000-0000-000000000003'"
                ))).fetchone()
                assert source_row is not None
                assert component_row is not None
                assert source_row[0] == UUID(workspace_id).hex
                assert component_row[0] == UUID(workspace_id).hex
                assert component_row[1] == "component:ship"
                assert component_row[2]

                entity_row = (await conn.execute(text(
                    "SELECT workspace_id, identity_key, canonical_name FROM entities "
                    "WHERE id = :entity_id"
                ), {"entity_id": component_row[2]})).fetchone()
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


def _create_legacy_schema(connection):
    """Create the schema WITHOUT confidence and evidence on relationships."""
    connection.execute(text("""
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
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    connection.execute(text("""
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
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            source_component_id TEXT NOT NULL REFERENCES components(id),
            target_component_id TEXT NOT NULL REFERENCES components(id),
            relationship_type TEXT NOT NULL DEFAULT 'related_to',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    connection.execute(text("""
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
    """))
    connection.commit()


async def _index_names(conn, table_name: str) -> list[str]:
    result = await conn.execute(text(f"PRAGMA index_list({table_name})"))
    return [row[1] for row in result.fetchall()]


async def _table_columns(conn, table_name: str) -> list[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    return [row[1] for row in result.fetchall()]
