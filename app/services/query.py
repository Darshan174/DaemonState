from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder, cosine_similarity


@dataclass
class QueryComponent:
    id: UUID
    model_name: str
    name: str
    value: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None
    source_label: str | None


@dataclass
class QueryResult:
    question: str
    answer: str
    confidence: float
    components: list[QueryComponent]
    sources: list[dict]


ANSWER_PROMPT = """You are a knowledge graph assistant for a startup. Answer the user's question using ONLY the facts provided below. Be direct and specific. If the facts don't contain enough information to answer, say so clearly.

Question: {question}

Relevant facts from the knowledge graph:
{facts}

Instructions:
- Answer the question directly in 1-3 sentences
- Reference specific facts by name when relevant
- If multiple facts are contradictory, note the conflict
- Do NOT make up information beyond what the facts contain
- Do NOT explain what you're doing — just answer
"""


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: BaseEmbedder | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.session = session
        self._embedder = embedder or build_default_embedder()
        self._api_key = api_key
        self._model = model

    async def query(self, question: str) -> QueryResult:
        q_embedding = await self._embedder.embed_text(question)

        components = list(await self.session.scalars(
            select(Component)
            .options(
                selectinload(Component.model),
                selectinload(Component.source_document),
                selectinload(Component.outgoing_relationships).selectinload(Relationship.target_component),
                selectinload(Component.incoming_relationships).selectinload(Relationship.source_component),
            )
            .where(Component.status.in_(["active", "needs_review"]))
        ))

        scored = []
        for c in components:
            c_embedding = _parse_embedding(c.embedding)
            sem = cosine_similarity(q_embedding, c_embedding)
            score = sem * 2.0 + c.confidence * 0.5 + c.authority_weight * 0.3
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:8]

        if not top:
            return QueryResult(
                question=question,
                answer=f'No matching context found for "{question}".',
                confidence=0.0,
                components=[],
                sources=[],
            )

        related_ids = set()
        for _, c in top:
            for rel in c.outgoing_relationships:
                related_ids.add(rel.target_component_id)
            for rel in c.incoming_relationships:
                related_ids.add(rel.source_component_id)

        if related_ids:
            related = list(await self.session.scalars(
                select(Component)
                .options(selectinload(Component.model), selectinload(Component.source_document))
                .where(Component.id.in_(related_ids))
            ))
        else:
            related = []

        result_components = []
        sources_seen: set[UUID] = set()

        for score, c in top:
            src_label = None
            src_id = None
            if c.source_document:
                src_label = c.source_document.source_type
                src_id = c.source_document.id
                if src_id not in sources_seen:
                    sources_seen.add(src_id)

            result_components.append(QueryComponent(
                id=c.id,
                model_name=c.model.name if c.model else "Unknown",
                name=c.name,
                value=c.value,
                confidence=c.confidence,
                authority_weight=c.authority_weight,
                status=c.status,
                source_document_id=src_id,
                source_label=src_label,
            ))

        for c in related:
            if c.id not in {rc.id for rc in result_components}:
                src_label = None
                src_id = None
                if c.source_document:
                    src_label = c.source_document.source_type
                    src_id = c.source_document.id
                result_components.append(QueryComponent(
                    id=c.id,
                    model_name=c.model.name if c.model else "Unknown",
                    name=c.name,
                    value=c.value,
                    confidence=c.confidence,
                    authority_weight=c.authority_weight,
                    status=c.status,
                    source_document_id=src_id,
                    source_label=src_label,
                ))

        sources = []
        for sid in sources_seen:
            doc = await self.session.get(SourceDocument, sid)
            if doc:
                sources.append({"id": str(doc.id), "type": doc.source_type, "url": doc.source_url})

        avg_conf = sum(c.confidence for _, c in top) / len(top)

        # Try LLM-based answer synthesis
        answer = await self._generate_answer(question, top)

        return QueryResult(
            question=question,
            answer=answer,
            confidence=round(avg_conf, 2),
            components=result_components,
            sources=sources,
        )

    async def _generate_answer(self, question: str, top: list[tuple[float, Component]]) -> str:
        """Generate a coherent answer using LLM if API key available, else summarise top facts."""
        facts_text = "\n".join(
            f"- [{c.model.name if c.model else 'Unknown'}] {c.name}: {c.value}"
            for _, c in top[:6]
        )

        if self._api_key and self._model:
            model = _normalize_model(self._model)
            try:
                from litellm import acompletion
                prompt = ANSWER_PROMPT.format(question=question, facts=facts_text)
                response = await acompletion(
                    model=model,
                    api_key=self._api_key,
                    messages=[
                        {"role": "system", "content": "You are a startup knowledge graph assistant. Answer questions using only the provided facts. Be concise and direct."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=300,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                err = str(e)
                if "NotFoundError" in err or "does not exist" in err or "model" in err.lower():
                    return (
                        f"Model \"{model}\" is not accessible on your API key. "
                        f"Open Configure AI and switch to gpt-4o or gpt-4o-mini (OpenAI) "
                        f"or claude-3-5-haiku-20241022 (Anthropic).\n\n"
                        f"Top matching facts:\n{facts_text}"
                    )
                return f"AI error: {err}\n\nTop matching facts:\n{facts_text}"

        # No LLM — return a readable summary of the top facts
        if not top:
            return "No relevant facts found."
        lines = [f"Top {min(3, len(top))} matching facts from your knowledge graph:\n"]
        for i, (score, c) in enumerate(top[:3], 1):
            model_name = c.model.name if c.model else "Unknown"
            lines.append(f"{i}. [{model_name}] {c.name}\n   {c.value}")
        lines.append("\nTip: Configure an AI key (Configure AI button) to get synthesized answers.")
        return "\n".join(lines)


def _normalize_model(model: str) -> str:
    """Map legacy/inaccessible model names to modern equivalents."""
    mapping = {
        "gpt-4":          "gpt-4o",
        "gpt-4-0314":     "gpt-4o",
        "gpt-4-0613":     "gpt-4o",
        "gpt-3.5-turbo":  "gpt-4o-mini",
        "claude-2":       "claude-3-5-haiku-20241022",
        "claude-instant":  "claude-3-5-haiku-20241022",
    }
    return mapping.get(model, model)


def _parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
