from __future__ import annotations

import json
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.semantic_linker import SemanticCandidate, SemanticRelationshipLinker
from app.models import Component, Relationship
from app.taxonomy import canonical_model_name, canonical_relationship_type


RELATIONSHIP_PROMPT = """You are analyzing candidate pairs from a startup knowledge graph.

Candidate pairs:
{candidate_pairs}

Already-known relationships:
{known_relationships}

Validate only the candidate pairs above. Find relationships that SHOULD exist but are missing. Look for:
1. A Slack/Email complaint that maps to a GitHub Issue
2. A Decision that caused a specific PR or Feature
3. An Agent Session that solved a specific Bug or Task
4. A Customer pain point with no linked Feature
5. A Task that is blocked by an unresolved Decision
6. Duplicate entities that refer to the same real-world thing

Return JSON:
{{
  "suggested_relationships": [
    {{
      "source_name": "exact name from entities list",
      "target_name": "exact name from entities list",
      "relationship_type": "causes|blocks|solves|relates_to|duplicates|implements|generated_by",
      "confidence": 0.0-1.0,
      "reasoning": "why these two are related"
    }}
  ],
  "duplicates": [
    {{
      "entity_a": "name",
      "entity_b": "name",
      "reason": "why they appear to be the same thing"
    }}
  ]
}}

Only suggest relationships between source_name and target_name values that actually appear in the candidate pairs above.
Do not suggest a relationship just because vector similarity is high; require semantic evidence in the names, values, source metadata, or relationship context.
"""


@dataclass
class SuggestedRelationship:
    source_name: str
    target_name: str
    relationship_type: str
    confidence: float
    reasoning: str


@dataclass
class RelationshipReport:
    suggested: list[SuggestedRelationship]
    duplicates: list[dict]
    message: str


class RelationshipAgent:
    def __init__(self, session: AsyncSession, api_key: str | None = None, model: str | None = None):
        self.session = session
        self.api_key = api_key
        self.model = model

    async def run(self) -> RelationshipReport:
        comp_result = await self.session.execute(
            select(Component).options(selectinload(Component.model))
        )
        components = comp_result.scalars().all()

        rel_result = await self.session.execute(
            select(Relationship).options(
                selectinload(Relationship.source_component),
                selectinload(Relationship.target_component),
            )
        )
        relationships = rel_result.scalars().all()

        if not self.api_key or not self.model:
            return RelationshipReport(
                suggested=[],
                duplicates=[],
                message="Configure an AI key to enable relationship discovery.",
            )

        result = await self._ai_discover(components, relationships)
        if not result:
            return RelationshipReport(suggested=[], duplicates=[], message="Analysis failed — check your AI key.")

        suggestions = [
            SuggestedRelationship(
                source_name=r.get("source_name", ""),
                target_name=r.get("target_name", ""),
                relationship_type=canonical_relationship_type(r.get("relationship_type")),
                confidence=min(max(float(r.get("confidence", 0.0)), 0.0), 1.0),
                reasoning=r.get("reasoning", ""),
            )
            for r in result.get("suggested_relationships", [])
            if r.get("source_name") and r.get("target_name")
        ]
        persisted = await self._persist_suggestions(suggestions, components)

        return RelationshipReport(
            suggested=suggestions,
            duplicates=result.get("duplicates", []),
            message=(
                f"Found {len(suggestions)} suggested relationships and "
                f"{len(result.get('duplicates', []))} potential duplicates. "
                f"Persisted {persisted} as proposed graph relationships."
            ),
        )

    async def _ai_discover(self, components, relationships) -> dict | None:
        candidates = await self._candidate_pairs()
        if not candidates:
            return {"suggested_relationships": [], "duplicates": []}

        candidate_pairs = "\n".join(
            _candidate_line(candidate)
            for candidate in candidates[:80]
        )

        known = "\n".join(
            f"- {r.source_component.name if r.source_component else '?'} --[{r.relationship_type}]--> {r.target_component.name if r.target_component else '?'}"
            for r in relationships[:50]
        )

        try:
            from litellm import acompletion
            prompt = RELATIONSHIP_PROMPT.format(candidate_pairs=candidate_pairs, known_relationships=known)
            response = await acompletion(
                model=self.model,
                api_key=self.api_key,
                messages=[
                    {"role": "system", "content": "Find hidden relationships in startup knowledge graphs. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(raw)
        except Exception:
            return None

    async def _candidate_pairs(self) -> list[SemanticCandidate]:
        return await SemanticRelationshipLinker(
            self.session,
            threshold=0.68,
            max_candidates=120,
            require_cross_source_type=False,
        ).candidates()

    async def _persist_suggestions(
        self,
        suggestions: list[SuggestedRelationship],
        components: list[Component],
    ) -> int:
        by_name = {c.name.strip().lower(): c for c in components}
        persisted = 0

        for suggestion in suggestions:
            if suggestion.confidence < 0.6:
                continue

            source = by_name.get(suggestion.source_name.strip().lower())
            target = by_name.get(suggestion.target_name.strip().lower())
            if not source or not target or source.id == target.id:
                continue

            rel_type = canonical_relationship_type(suggestion.relationship_type)
            exists = await self.session.scalar(
                select(Relationship).where(
                    Relationship.source_component_id == source.id,
                    Relationship.target_component_id == target.id,
                    Relationship.relationship_type == rel_type,
                )
            )
            if exists:
                continue

            self.session.add(Relationship(
                source_component_id=source.id,
                target_component_id=target.id,
                relationship_type=rel_type,
                confidence=suggestion.confidence,
                evidence=suggestion.reasoning or "Suggested by Relationship Agent",
                status="proposed",
                origin="ai_proposed",
            ))
            persisted += 1

        if persisted:
            await self.session.flush()
            await self.session.commit()
        return persisted


def _candidate_line(candidate: SemanticCandidate) -> str:
    source_model = canonical_model_name(candidate.source.model.name if candidate.source.model else "Unknown")
    target_model = canonical_model_name(candidate.target.model.name if candidate.target.model else "Unknown")
    source_type = candidate.source.source_document.source_type if candidate.source.source_document else "unknown"
    target_type = candidate.target.source_document.source_type if candidate.target.source_document else "unknown"
    return (
        f"- source_name: \"{candidate.source.name}\" | source_type: {source_type} | "
        f"source_model: {source_model} | source_value: {candidate.source.value[:180]}\n"
        f"  target_name: \"{candidate.target.name}\" | target_type: {target_type} | "
        f"target_model: {target_model} | target_value: {candidate.target.value[:180]}\n"
        f"  vector_similarity: {candidate.score:.2f}"
    )
