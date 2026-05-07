from __future__ import annotations

import json
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship
from app.taxonomy import canonical_model_name, canonical_relationship_type


RELATIONSHIP_PROMPT = """You are analyzing a startup knowledge graph to find HIDDEN relationships that haven't been explicitly captured.

Current entities:
{entities}

Already-known relationships:
{known_relationships}

Find relationships that SHOULD exist but are missing. Look for:
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

Only suggest relationships between entities that actually exist in the list above.
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
        by_type: dict[str, list[str]] = {}
        for c in components:
            t = canonical_model_name(c.model.name if c.model else "Unknown")
            by_type.setdefault(t, []).append(f'"{c.name}" — {c.value[:100]}')

        entities_text = "\n".join(
            f"{t}: {', '.join(names[:6])}"
            for t, names in list(by_type.items())[:12]
        )

        known = "\n".join(
            f"- {r.source_component.name if r.source_component else '?'} --[{r.relationship_type}]--> {r.target_component.name if r.target_component else '?'}"
            for r in relationships[:30]
        )

        try:
            from litellm import acompletion
            prompt = RELATIONSHIP_PROMPT.format(entities=entities_text, known_relationships=known)
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
