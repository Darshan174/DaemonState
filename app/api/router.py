from __future__ import annotations

from fastapi import APIRouter

from app.api import sources, graph, query, repo

api_router = APIRouter()
api_router.include_router(sources.router, prefix="", tags=["sources"])
api_router.include_router(graph.router, prefix="", tags=["graph"])
api_router.include_router(query.router, prefix="", tags=["query"])
api_router.include_router(repo.router, prefix="", tags=["repo"])
