from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, briefing, connectors, decisions, evals, graph, knowledge, query, trust


api_router = APIRouter()
api_router.include_router(knowledge.router, prefix="", tags=["knowledge"])
api_router.include_router(graph.router, prefix="", tags=["graph"])
api_router.include_router(connectors.router, prefix="", tags=["connectors"])
api_router.include_router(trust.router, prefix="", tags=["trust"])
api_router.include_router(decisions.router, prefix="", tags=["decisions"])
api_router.include_router(briefing.router, prefix="", tags=["briefing"])
api_router.include_router(query.router, prefix="", tags=["query"])
api_router.include_router(evals.router, prefix="", tags=["evals"])
api_router.include_router(admin.router, prefix="", tags=["admin"])
