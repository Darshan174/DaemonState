from __future__ import annotations

from fastapi import APIRouter

from app.api import agents_api, connectors, graph, models_api, query, repo, sources

api_router = APIRouter()
api_router.include_router(sources.router, prefix="", tags=["sources"])
api_router.include_router(graph.router, prefix="", tags=["graph"])
api_router.include_router(query.router, prefix="", tags=["query"])
api_router.include_router(repo.router, prefix="", tags=["repo"])
api_router.include_router(connectors.router, prefix="", tags=["connectors"])
api_router.include_router(models_api.router, prefix="", tags=["models"])
api_router.include_router(agents_api.router, prefix="", tags=["agents"])
