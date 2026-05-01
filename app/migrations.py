from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def run_migrations(conn: AsyncConnection) -> None:
    await _migrate_relationships_confidence_evidence(conn)


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


async def _get_table_columns(conn: AsyncConnection, table_name: str) -> set[str]:
    try:
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        rows = result.fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()
