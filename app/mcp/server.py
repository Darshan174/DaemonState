"""MCP (Model Context Protocol) server for Context Engine.

Exposes semantic search, graph expansion, model queries, and status
over stdio transport for Claude Desktop, Cursor, and other MCP clients.

Launch via: ``ctxe mcp``
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import HashingEmbedder, cosine_similarity

logger = logging.getLogger("context-engine.mcp")

server = Server("context-engine")


def _text(content: str) -> list[TextContent]:
    return [TextContent(type="text", text=content)]


def _json_text(data: Any) -> list[TextContent]:
    return _text(json.dumps(data, indent=2, default=str))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_nodes",
            description=(
                "Semantic search over components in the knowledge graph. "
                "Returns matching components ranked by relevance. Use this "
                "when you need to find facts, decisions, blockers, or any "
                "structured knowledge."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 10)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="expand_graph",
            description=(
                "Get 1-hop neighbors of a component. Returns the component "
                "itself plus all connected components via relationships. Use "
                "this to explore dependencies, blockers, and connections."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "UUID of the component to expand",
                    },
                },
                "required": ["node_id"],
            },
        ),
        Tool(
            name="get_model",
            description=(
                "Get all components belonging to a knowledge model by name. "
                "Use this to browse a domain like Pricing, Roadmap, or Decisions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Model name (case-insensitive partial match)",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="list_models",
            description=(
                "List all knowledge models with their component counts. "
                "Use this to discover what domains are available."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_status",
            description="Get counts of components, relationships, and sources in the knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search_nodes":
        return await _search_nodes(arguments["query"], arguments.get("limit", 10))
    elif name == "expand_graph":
        return await _expand_graph(arguments["node_id"])
    elif name == "get_model":
        return await _get_model(arguments["name"])
    elif name == "list_models":
        return await _list_models()
    elif name == "get_status":
        return await _get_status()
    else:
        return _text(f"Unknown tool: {name}")


async def _search_nodes(query: str, limit: int = 10) -> list[TextContent]:
    try:
        embedder = HashingEmbedder()
        query_vec = await embedder.embed_text(query)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Component)
                .where(Component.status == "active")
                .options(selectinload(Component.source_document))
            )
            components = result.scalars().all()

        scored: list[tuple[float, Component]] = []
        for comp in components:
            if not comp.embedding:
                continue
            try:
                vec = json.loads(comp.embedding)
                score = cosine_similarity(query_vec, vec)
                query_tokens = {t.lower() for t in query.split() if len(t) > 2}
                name_tokens = {t.lower() for t in comp.name.split()}
                lexical = len(name_tokens & query_tokens) * 2.5
                total = score * 2.25 + lexical + comp.authority_weight
                scored.append((total, comp))
            except (json.JSONDecodeError, TypeError):
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        if not top:
            return _text("No matching components found.")

        results = []
        for score, comp in top:
            entry = {
                "id": str(comp.id),
                "name": comp.name,
                "value": comp.value,
                "confidence": comp.confidence,
                "status": comp.status,
                "fact_type": comp.fact_type,
                "model_id": str(comp.model_id),
                "score": round(score, 4),
            }
            if comp.source_document:
                entry["source_type"] = comp.source_document.source_type
                entry["source_url"] = comp.source_document.source_url
            results.append(entry)

        return _json_text(results)

    except Exception as exc:
        logger.exception("search_nodes failed")
        return _text(f"Error: {exc}")


async def _expand_graph(node_id: str) -> list[TextContent]:
    try:
        try:
            uid = UUID(node_id)
        except ValueError:
            return _text(f"Invalid UUID: {node_id}")

        async with AsyncSessionLocal() as session:
            comp_result = await session.execute(
                select(Component)
                .where(Component.id == uid)
                .options(selectinload(Component.source_document))
            )
            comp = comp_result.scalar_one_or_none()
            if not comp:
                return _text(f"Component not found: {node_id}")

            outgoing = await session.execute(
                select(Relationship).where(Relationship.source_component_id == uid)
            )
            outgoing_rels = outgoing.scalars().all()

            incoming = await session.execute(
                select(Relationship).where(Relationship.target_component_id == uid)
            )
            incoming_rels = incoming.scalars().all()

            neighbor_ids = set()
            for r in outgoing_rels:
                neighbor_ids.add(r.target_component_id)
            for r in incoming_rels:
                neighbor_ids.add(r.source_component_id)

            neighbors = []
            if neighbor_ids:
                nb_result = await session.execute(
                    select(Component)
                    .where(Component.id.in_(neighbor_ids))
                    .options(selectinload(Component.source_document))
                )
                for nb in nb_result.scalars().all():
                    entry = {
                        "id": str(nb.id),
                        "name": nb.name,
                        "value": nb.value,
                        "confidence": nb.confidence,
                        "status": nb.status,
                        "fact_type": nb.fact_type,
                    }
                    if nb.source_document:
                        entry["source_type"] = nb.source_document.source_type
                    neighbors.append(entry)

            edges = []
            for r in outgoing_rels:
                edges.append({
                    "source": str(r.source_component_id),
                    "target": str(r.target_component_id),
                    "type": r.relationship_type,
                    "direction": "outgoing",
                })
            for r in incoming_rels:
                edges.append({
                    "source": str(r.source_component_id),
                    "target": str(r.target_component_id),
                    "type": r.relationship_type,
                    "direction": "incoming",
                })

        return _json_text({
            "node": {
                "id": str(comp.id),
                "name": comp.name,
                "value": comp.value,
                "confidence": comp.confidence,
                "status": comp.status,
                "fact_type": comp.fact_type,
                "model_id": str(comp.model_id),
            },
            "neighbors": neighbors,
            "edges": edges,
        })

    except Exception as exc:
        logger.exception("expand_graph failed")
        return _text(f"Error: {exc}")


async def _get_model(name: str) -> list[TextContent]:
    try:
        async with AsyncSessionLocal() as session:
            model_result = await session.execute(
                select(Model).where(Model.name.ilike(f"%{name}%"))
            )
            models = model_result.scalars().all()

            if not models:
                return _text(f"No model found matching: {name}")

            results = []
            for model in models:
                comp_result = await session.execute(
                    select(Component)
                    .where(Component.model_id == model.id)
                    .options(selectinload(Component.source_document))
                )
                components = comp_result.scalars().all()

                results.append({
                    "model": {
                        "id": str(model.id),
                        "name": model.name,
                        "description": model.description,
                    },
                    "components": [
                        {
                            "id": str(c.id),
                            "name": c.name,
                            "value": c.value,
                            "confidence": c.confidence,
                            "status": c.status,
                            "fact_type": c.fact_type,
                        }
                        for c in components
                    ],
                    "component_count": len(components),
                })

        return _json_text(results)

    except Exception as exc:
        logger.exception("get_model failed")
        return _text(f"Error: {exc}")


async def _list_models() -> list[TextContent]:
    try:
        async with AsyncSessionLocal() as session:
            model_result = await session.execute(select(Model).order_by(Model.name))
            models = model_result.scalars().all()

            results = []
            for model in models:
                comp_count = await session.scalar(
                    select(func.count(Component.id)).where(
                        Component.model_id == model.id,
                        Component.status == "active",
                    )
                )
                results.append({
                    "id": str(model.id),
                    "name": model.name,
                    "description": model.description,
                    "component_count": comp_count,
                })

        return _json_text(results)

    except Exception as exc:
        logger.exception("list_models failed")
        return _text(f"Error: {exc}")


async def _get_status() -> list[TextContent]:
    try:
        async with AsyncSessionLocal() as session:
            comp_count = await session.scalar(
                select(func.count(Component.id)).where(Component.status == "active")
            ) or 0

            rel_count = await session.scalar(
                select(func.count(Relationship.id))
            ) or 0

            src_count = await session.scalar(
                select(func.count(SourceDocument.id))
            ) or 0

            model_count = await session.scalar(
                select(func.count(Model.id))
            ) or 0

        return _json_text({
            "components": comp_count,
            "relationships": rel_count,
            "sources": src_count,
            "models": model_count,
        })

    except Exception as exc:
        logger.exception("get_status failed")
        return _text(f"Error: {exc}")


async def run_server() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_mcp_server() -> None:
    """Entry point for ``ctxe mcp`` CLI command."""
    logging.basicConfig(level=logging.INFO)
    await run_server()


def main() -> None:
    asyncio.run(run_server())


if __name__ == "__main__":
    main()