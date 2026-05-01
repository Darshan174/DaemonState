from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import run_migrations


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

        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT confidence, evidence FROM relationships "
                "WHERE id = '00000000-0000-0000-0000-000000000005'"
            ))
            row = result.fetchone()
            assert row is not None
            assert float(row[0]) == 0.7
            assert row[1] == "backfill: schema migration"

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
    connection.commit()
