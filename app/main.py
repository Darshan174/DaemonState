from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from redis import asyncio as redis
from sqlalchemy import text

from app.api.router import api_router
from app.config import settings
from app.database import engine


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title=settings.project_name)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness_check() -> dict[str, object]:
    status_map = {"database": "ok", "redis": "ok"}
    errors: dict[str, str] = {}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - simple health check
        status_map["database"] = "error"
        errors["database"] = str(exc)

    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception as exc:  # pragma: no cover - simple health check
        status_map["redis"] = "error"
        errors["redis"] = str(exc)
    finally:
        await redis_client.aclose()

    if errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "checks": status_map,
                "errors": errors,
            },
        )

    return {"status": "ready", "checks": status_map}


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend_route(path: str) -> FileResponse:
        protected_prefixes = (
            settings.api_prefix.strip("/"),
            "health",
            "docs",
            "redoc",
            "openapi.json",
        )
        if path == "" or path.split("/", 1)[0] in protected_prefixes:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return FileResponse(FRONTEND_DIST / "index.html")
