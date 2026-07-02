from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.config import settings
from app.database import engine
from app.migrations import run_migrations
from app.models import Base
from app.services.auth import (
    api_auth_enabled,
    api_rate_limit_enabled,
    check_api_rate_limit,
    request_has_valid_api_key,
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
    yield


app = FastAPI(title="Context Engine", lifespan=lifespan)


@app.middleware("http")
async def require_api_key_for_api_routes(request: Request, call_next):
    if request.url.path.startswith("/api") and request.method != "OPTIONS":
        if api_auth_enabled() and not request_has_valid_api_key(request):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if api_rate_limit_enabled():
            allowed, retry_after = check_api_rate_limit(request)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "API rate limit exceeded."},
                    headers={"Retry-After": str(retry_after)},
                )
    return await call_next(request)


app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "unavailable", "detail": str(exc)},
        )

    database_backend = engine.url.get_backend_name()
    return JSONResponse({
        "status": "ready",
        "database": database_backend,
        "api_auth_enabled": api_auth_enabled(),
        "api_rate_limit_per_minute": int(settings.api_rate_limit_per_minute or 0),
        "credential_encryption_enabled": bool(settings.encryption_key),
    })


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend_route(path: str) -> FileResponse:
        protected_prefixes = ("api", "health", "docs", "redoc", "openapi.json")
        if path == "" or path.split("/", 1)[0] in protected_prefixes:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return FileResponse(FRONTEND_DIST / "index.html")
