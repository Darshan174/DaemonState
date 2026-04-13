"""Top-level API router.

Stable founder-workflow contracts:
- workspace bootstrap: ``/api/workspaces`` and ``/api/seed-demo``
- local import: ``/api/imports``
- founder brief: ``/api/founder-brief``
- query: ``POST /api/query``
- decisions: ``/api/decisions``
- sources: ``/api/source-documents``

Compatibility and admin routes remain mounted below, but the contracts above
are the routes the frontend, CLI, bootstrap, and smoke flow should rely on.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import briefing, connectors, decisions, evals, graph, imports, knowledge, query, trust, workspaces


api_router = APIRouter()

# Stable founder-facing workflow routes.
# Note: ``connectors.router`` is mounted here because it owns
# ``GET /api/source-documents``. Compatibility-only upload routes remain
# isolated behind that module and are not part of the founder contract.
api_router.include_router(workspaces.router, prefix="", tags=["workspaces"])
api_router.include_router(imports.router, prefix="", tags=["imports"])
api_router.include_router(briefing.router, prefix="", tags=["briefing"])
api_router.include_router(decisions.router, prefix="", tags=["decisions"])
api_router.include_router(query.router, prefix="", tags=["query"])
api_router.include_router(connectors.router, prefix="", tags=["connectors"])

# Deeper operator and system routes.
api_router.include_router(knowledge.router, prefix="", tags=["knowledge"])
api_router.include_router(graph.router, prefix="", tags=["graph"])
api_router.include_router(trust.router, prefix="", tags=["trust"])
api_router.include_router(evals.router, prefix="", tags=["evals"])
