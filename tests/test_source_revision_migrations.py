from __future__ import annotations

import hashlib
import os
import tempfile

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import run_migrations
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
        assert len(unique_revision_indexes) == 1
        assert unique_revision_indexes[0][2] == 1
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
