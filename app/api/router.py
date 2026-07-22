from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    agents_api,
    checkpoints,
    connectors,
    context,
    context_digest,
    demo,
    graph,
    models_api,
    query,
    repo,
    session_library,
    sources,
    workspace_goals,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(checkpoints.router, prefix="", tags=["checkpoints"])
api_router.include_router(sources.router, prefix="", tags=["sources"])
api_router.include_router(graph.router, prefix="", tags=["graph"])
api_router.include_router(context_digest.router, prefix="", tags=["context"])
api_router.include_router(context.router, prefix="", tags=["context"])
api_router.include_router(workspace_goals.router, prefix="", tags=["workspaces"])
api_router.include_router(workspaces.router, prefix="", tags=["workspaces"])
api_router.include_router(query.router, prefix="", tags=["query"])
api_router.include_router(repo.router, prefix="", tags=["repo"])
api_router.include_router(session_library.router, prefix="", tags=["session-library"])
api_router.include_router(connectors.router, prefix="", tags=["connectors"])
api_router.include_router(models_api.router, prefix="", tags=["models"])
api_router.include_router(agents_api.router, prefix="", tags=["agents"])
api_router.include_router(demo.router, prefix="", tags=["demo"])
