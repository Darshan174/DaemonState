from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.database import engine
from app.models import Base

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        try:
            await conn.execute(text(
                "ALTER TABLE components ADD COLUMN IF NOT EXISTS temporal VARCHAR(20) NOT NULL DEFAULT 'unknown'"
            ))
        except Exception:
            pass
    yield


app = FastAPI(title="Context Engine", lifespan=lifespan)
app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


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