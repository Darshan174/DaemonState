from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def database_wall_clock_expression(dialect_name: str):
    """Return a transaction-independent UTC database clock expression."""
    if dialect_name == "postgresql":
        # PostgreSQL now()/CURRENT_TIMESTAMP is fixed at transaction start.
        # Lease decisions need the actual statement-time wall clock.
        return func.timezone("UTC", func.clock_timestamp())
    # SQLite CURRENT_TIMESTAMP has one-second precision; leases carry
    # microseconds and must not be treated as active for an extra second.
    return func.strftime("%Y-%m-%d %H:%M:%f", "now")


async def database_wall_clock(session: AsyncSession):
    value = await session.scalar(
        select(database_wall_clock_expression(session.get_bind().dialect.name))
    )
    return value


def _make_async_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername in {"postgresql", "postgres"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
    if parsed.drivername == "postgresql+asyncpg":
        # SQLAlchemy passes URL query parameters to ``asyncpg.connect`` as
        # keyword arguments. Translate libpq's TLS name and remove
        # ``application_name`` because asyncpg does not accept that keyword;
        # create_database_engine sets it through server_settings instead.
        query = dict(parsed.query)
        ssl_mode = query.pop("sslmode", None)
        if ssl_mode is not None:
            query.setdefault("ssl", ssl_mode)
        query.pop("application_name", None)
        parsed = parsed.set(query=query)
    return parsed.render_as_string(hide_password=False)


def _ensure_sqlite_parent_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database = parsed.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


_db_url = _make_async_url(settings.database_url)
_ensure_sqlite_parent_dir(_db_url)


def create_database_engine(
    url: str,
    *,
    application_name: str = "context-engine-api",
    statement_timeout_ms: int | None = None,
    lock_timeout_ms: int | None = None,
) -> AsyncEngine:
    async_url = _make_async_url(url)
    parsed = make_url(async_url)
    options: dict = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "postgresql":
        effective_statement_timeout = (
            settings.database_statement_timeout_ms
            if statement_timeout_ms is None
            else max(0, statement_timeout_ms)
        )
        server_settings = {
            "application_name": application_name,
            "statement_timeout": str(effective_statement_timeout),
            "idle_in_transaction_session_timeout": str(
                max(1_000, settings.database_statement_timeout_ms * 2)
            ),
        }
        if lock_timeout_ms is not None:
            server_settings["lock_timeout"] = str(max(0, lock_timeout_ms))
        options.update({
            "pool_size": max(1, settings.database_pool_size),
            "max_overflow": max(0, settings.database_max_overflow),
            "pool_timeout": max(1.0, settings.database_pool_timeout_seconds),
            "pool_recycle": max(30, settings.database_pool_recycle_seconds),
            "pool_use_lifo": True,
            "connect_args": {
                "timeout": max(1.0, settings.database_connect_timeout_seconds),
                "server_settings": server_settings,
            },
        })
    return create_async_engine(async_url, **options)


def expected_schema_revisions() -> frozenset[str]:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return frozenset(script.get_heads())


async def current_schema_revisions(conn: AsyncConnection) -> frozenset[str]:
    has_version_table = await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).has_table("alembic_version")
    )
    if not has_version_table:
        return frozenset()
    result = await conn.execute(text("SELECT version_num FROM alembic_version"))
    return frozenset(str(row[0]) for row in result if row[0])


async def schema_is_current(conn: AsyncConnection) -> bool:
    return await current_schema_revisions(conn) == expected_schema_revisions()


engine = create_database_engine(_db_url)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
