from __future__ import annotations

import hashlib
import os
import tempfile

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import (
    _backfill_source_document_revisions,
    _migrate_query_and_sync_indexes,
    run_migrations,
)
from app.source_identity import canonical_source_identity_sha256


async def test_source_revision_migration_is_repeatable_and_preserves_legacy_rows():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE source_documents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    source_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    ingested_at TEXT
                )
            """))
            await conn.execute(text("""
                INSERT INTO source_documents
                    (id, workspace_id, source_type, external_id, content,
                     content_sha256, metadata, ingested_at)
                VALUES
                    ('00000000-0000-0000-0000-000000000001', NULL, 'github',
                     'issue:7', 'old content', 'stale-hash', '{}', '2026-01-01T00:00:00'),
                    ('00000000-0000-0000-0000-000000000002', NULL, 'github',
                     'issue:7', 'new content', NULL, '{}', '2026-01-02T00:00:00')
            """))

        async with engine.begin() as conn:
            await run_migrations(conn)
        async with engine.connect() as conn:
            first = (
                await conn.execute(text("""
                    SELECT id, content, content_sha256, source_identity_sha256,
                           revision_number, supersedes_source_document_id
                    FROM source_documents ORDER BY revision_number
                """))
            ).fetchall()
            indexes = (await conn.execute(text("PRAGMA index_list(source_documents)"))).fetchall()

        async with engine.begin() as conn:
            await run_migrations(conn)
        async with engine.connect() as conn:
            second = (
                await conn.execute(text("""
                    SELECT id, content, content_sha256, source_identity_sha256,
                           revision_number, supersedes_source_document_id
                    FROM source_documents ORDER BY revision_number
                """))
            ).fetchall()

        assert second == first
        assert len(first) == 2
        assert first[0][2] == hashlib.sha256(b"old content").hexdigest()
        assert first[1][2] == hashlib.sha256(b"new content").hexdigest()
        assert first[0][3] == first[1][3]
        assert [row[4] for row in first] == [1, 2]
        assert first[0][5] is None
        assert first[1][5] == first[0][0]
        unique_revision_indexes = [
            row for row in indexes if row[1] == "uq_source_documents_identity_revision"
        ]
        unique_predecessor_indexes = [
            row for row in indexes if row[1] == "uq_source_documents_superseded_once"
        ]
        assert len(unique_revision_indexes) == 1
        assert unique_revision_indexes[0][2] == 1
        assert len(unique_predecessor_indexes) == 1
        assert unique_predecessor_indexes[0][2] == 1
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_repeat_migration_preserves_an_existing_valid_chain_with_tied_timestamps():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    identity = canonical_source_identity_sha256(None, "slack", "slack:C1:1.0")
    first_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    second_id = "00000000-0000-0000-0000-000000000001"
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE source_documents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    source_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT,
                    source_identity_sha256 TEXT,
                    revision_number INTEGER NOT NULL DEFAULT 1,
                    supersedes_source_document_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    ingested_at TEXT
                )
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_source_documents_identity_revision
                ON source_documents (source_identity_sha256, revision_number)
            """))
            await conn.execute(
                text("""
                    INSERT INTO source_documents
                        (id, workspace_id, source_type, external_id, content,
                         content_sha256, source_identity_sha256, revision_number,
                         supersedes_source_document_id, metadata, ingested_at)
                    VALUES
                        (:first_id, NULL, 'slack', 'slack:C1:1.0', 'first',
                         'stale-one', :identity, 1, NULL, '{}', :ingested_at),
                        (:second_id, NULL, 'slack', 'slack:C1:1.0', 'second',
                         'stale-two', :identity, 2, :first_id, '{}', :ingested_at)
                """),
                {
                    "first_id": first_id,
                    "second_id": second_id,
                    "identity": identity,
                    "ingested_at": "2026-01-01T00:00:00",
                },
            )

        for _ in range(2):
            async with engine.begin() as conn:
                await run_migrations(conn)

        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("""
                    SELECT id, content_sha256, revision_number, supersedes_source_document_id
                    FROM source_documents ORDER BY revision_number
                """))
            ).fetchall()

        assert [row[0] for row in rows] == [first_id, second_id]
        assert [row[2] for row in rows] == [1, 2]
        assert rows[0][3] is None
        assert rows[1][3] == first_id
        assert rows[0][1] == hashlib.sha256(b"first").hexdigest()
        assert rows[1][1] == hashlib.sha256(b"second").hexdigest()
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_completed_source_revision_backfill_does_not_read_document_bodies(
    tmp_path,
):
    db_path = tmp_path / "completed-source-revisions.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    source_id = "00000000-0000-0000-0000-000000000001"
    content = "large source body"
    identity = canonical_source_identity_sha256(None, "slack", "slack:C1:1.0")
    statements: list[str] = []

    def record_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        statements.append(" ".join(statement.split()).lower())

    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE source_documents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    source_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT,
                    source_identity_sha256 TEXT,
                    revision_number INTEGER NOT NULL DEFAULT 1,
                    supersedes_source_document_id TEXT,
                    ingested_at TEXT
                )
            """))
            await conn.execute(
                text("""
                    INSERT INTO source_documents (
                        id, workspace_id, source_type, external_id, content,
                        content_sha256, source_identity_sha256, revision_number
                    )
                    VALUES (
                        :id, NULL, 'slack', 'slack:C1:1.0', :content,
                        :content_sha256, :identity, 1
                    )
                """),
                {
                    "id": source_id,
                    "content": content,
                    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "identity": identity,
                },
            )
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_source_documents_identity_revision
                ON source_documents (source_identity_sha256, revision_number)
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_source_documents_superseded_once
                ON source_documents (supersedes_source_document_id)
                WHERE supersedes_source_document_id IS NOT NULL
            """))

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )
        async with engine.begin() as conn:
            await _backfill_source_document_revisions(conn)
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )

        assert not any(
            "select id, workspace_id, source_type, external_id" in statement
            and "content, content_sha256" in statement
            for statement in statements
        )
        assert not any(
            statement.startswith("update source_documents")
            for statement in statements
        )
    finally:
        await engine.dispose()


async def test_completed_unique_index_migrations_skip_duplicate_cleanup_updates(
    tmp_path,
):
    db_path = tmp_path / "completed-unique-index-migrations.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    statements: list[str] = []

    def record_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        statements.append(" ".join(statement.split()).lower())

    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE sync_jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_sync_jobs_active_idempotency_key
                ON sync_jobs (idempotency_key)
                WHERE idempotency_key IS NOT NULL
                  AND status IN ('pending', 'retrying', 'running')
            """))
            await conn.execute(text("""
                CREATE TABLE context_packs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL
                )
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_context_packs_idempotency_key
                ON context_packs (idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """))
            await conn.execute(text("""
                CREATE TABLE run_observations (
                    id TEXT PRIMARY KEY,
                    agent_run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_run_observations_terminal_outcome
                ON run_observations (agent_run_id)
                WHERE event_type = 'outcome'
            """))

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )
        async with engine.begin() as conn:
            await _migrate_query_and_sync_indexes(conn)
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            record_statement,
        )

        assert not any(
            statement.startswith((
                "update sync_jobs as candidate",
                "update context_packs as candidate",
                "update run_observations as candidate",
            ))
            for statement in statements
        )
    finally:
        await engine.dispose()
