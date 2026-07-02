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

from app.database import AsyncSessionLocal
from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import HashingEmbedder, cosine_similarity
from app.services.query import QueryService

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
            name="query_context",
            description=(
                "Ask a natural-language question over the knowledge graph. "
                "Returns the same versioned query trace as the HTTP API: "
                "facts used, source IDs, and relationship evidence. Use this "
                "when an AI agent needs a grounded answer or context pack seed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language question to answer from the graph",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top facts to retrieve, from 1 to 20. Default 8.",
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Minimum component confidence, from 0.0 to 1.0. Default 0.0.",
                    },
                    "hybrid": {
                        "type": "boolean",
                        "description": "Whether to combine embedding and lexical overlap. Default true.",
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
    elif name == "query_context":
        return await _query_context(
            arguments["query"],
            top_k=arguments.get("top_k", 8),
            min_confidence=arguments.get("min_confidence", 0.0),
            hybrid=arguments.get("hybrid", True),
        )
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


async def _query_context(
    query: str,
    top_k: int = 8,
    min_confidence: float = 0.0,
    hybrid: bool = True,
) -> list[TextContent]:
    try:
        async with AsyncSessionLocal() as session:
            svc = QueryService(session, embedder=HashingEmbedder())
            result = await svc.query(
                query,
                top_k=top_k,
                min_confidence=min_confidence,
                hybrid=hybrid,
            )

        return _json_text({
            "schema_version": result.schema_version,
            "question": result.question,
            "answer": result.answer,
            "confidence": result.confidence,
            "components": [
                {
                    "id": str(component.id),
                    "entity_id": str(component.entity_id) if component.entity_id else None,
                    "identity_key": component.identity_key,
                    "model_name": component.model_name,
                    "name": component.name,
                    "value": component.value,
                    "fact_type": component.fact_type,
                    "confidence": component.confidence,
                    "status": component.status,
                    "source_document_id": str(component.source_document_id) if component.source_document_id else None,
                    "source_type": component.source_label,
                    "source_url": component.source_url,
                    "provenance": component.provenance,
                    "excerpt": component.excerpt,
                    "rank": component.rank,
                    "score": component.score,
                    "matched": component.matched,
                    "relationship_type": component.relationship_type,
                    "relationship_evidence": component.relationship_evidence,
                    "relationship_origin": component.relationship_origin,
                }
                for component in result.components
            ],
            "sources": result.sources,
            "trace": {
                "retrieval_strategy": result.trace.retrieval_strategy,
                "vector_candidate_count": result.trace.vector_candidate_count,
                "text_candidate_count": result.trace.text_candidate_count,
                "vector_prefilter_limit": result.trace.vector_prefilter_limit,
                "text_prefilter_limit": result.trace.text_prefilter_limit,
                "top_k": result.trace.top_k,
                "min_confidence": result.trace.min_confidence,
                "hybrid": result.trace.hybrid,
                "candidate_component_count": result.trace.candidate_component_count,
                "scoped_component_count": result.trace.scoped_component_count,
                "scored_component_count": result.trace.scored_component_count,
                "entity_group_count": result.trace.entity_group_count,
                "entity_duplicate_count": result.trace.entity_duplicate_count,
                "matched_component_count": result.trace.matched_component_count,
                "returned_component_count": result.trace.returned_component_count,
                "expanded_relationship_count": result.trace.expanded_relationship_count,
                "facts_used": [
                    {
                        "rank": fact.rank,
                        "component_id": str(fact.component_id),
                        "entity_id": str(fact.entity_id) if fact.entity_id else None,
                        "identity_key": fact.identity_key,
                        "model_name": fact.model_name,
                        "name": fact.name,
                        "value": fact.value,
                        "score": fact.score,
                        "semantic_score": fact.semantic_score,
                        "lexical_score": fact.lexical_score,
                        "confidence": fact.confidence,
                        "authority_weight": fact.authority_weight,
                        "source_document_id": str(fact.source_document_id) if fact.source_document_id else None,
                        "source_type": fact.source_type,
                        "source_url": fact.source_url,
                    }
                    for fact in result.trace.facts_used
                ],
                "relationships_used": [
                    {
                        "id": str(rel.id),
                        "source_component_id": str(rel.source_component_id),
                        "target_component_id": str(rel.target_component_id),
                        "relationship_type": rel.relationship_type,
                        "confidence": rel.confidence,
                        "evidence": rel.evidence,
                        "origin": rel.origin,
                    }
                    for rel in result.trace.relationships_used
                ],
            },
        })

    except Exception as exc:
        logger.exception("query_context failed")
        return _text(f"Error: {exc}")


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
                "entity_id": str(comp.entity_id) if comp.entity_id else None,
                "identity_key": comp.identity_key,
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
                        "entity_id": str(nb.entity_id) if nb.entity_id else None,
                        "identity_key": nb.identity_key,
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
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                    "origin": r.origin,
                    "direction": "outgoing",
                })
            for r in incoming_rels:
                edges.append({
                    "source": str(r.source_component_id),
                    "target": str(r.target_component_id),
                    "type": r.relationship_type,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                    "origin": r.origin,
                    "direction": "incoming",
                })

        return _json_text({
            "node": {
                "id": str(comp.id),
                "entity_id": str(comp.entity_id) if comp.entity_id else None,
                "identity_key": comp.identity_key,
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
