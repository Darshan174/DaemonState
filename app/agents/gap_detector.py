from __future__ import annotations

import json
from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Model, Relationship
from app.taxonomy import canonical_model_name, model_bucket


@dataclass
class GapItem:
    category: str
    severity: str
    title: str
    detail: str
    entity_name: str = ""
    recommendation: str = ""


@dataclass
class GapReport:
    summary: str
    gaps: list[GapItem]
    ready_to_ship: list[str]
    blocked: list[str]
    stats: dict


GAP_PROMPT = """You are the CEO of a startup analyzing your knowledge graph. Below is a structured dump of all entities grouped by type.

Your job: identify the most critical gaps, risks, and opportunities.

Look for:
1. MISSING OWNERS — Features, Tasks, or Decisions with no Person linked
2. UNIMPLEMENTED DECISIONS — Decisions that have no related Task or PR
3. BLOCKED ITEMS — Tasks or Features blocked by unresolved Risks
4. REPEATED FAILURES — Agent Sessions hitting the same problem multiple times
5. CUSTOMER PAIN WITH NO ACTION — Customer/Risk items not linked to any Feature or Task
6. READY TO SHIP — Features/Tasks with no blockers and all dependencies resolved
7. ORPHANED WORK — PRs, Issues, or Tasks with no connection to a Decision or Feature

Entities:
{entities}

Relationships:
{relationships}

Return a JSON object with this exact structure:
{{
  "summary": "2-3 sentence CEO-level summary of the biggest issues",
  "gaps": [
    {{
      "category": "missing_owner|unimplemented_decision|blocked|repeated_failure|unactioned_pain|orphaned",
      "severity": "critical|high|medium|low",
      "title": "short title",
      "detail": "specific explanation referencing actual entity names",
      "entity_name": "the primary entity name this gap is about",
      "recommendation": "one concrete action to fix this"
    }}
  ],
  "ready_to_ship": ["entity name 1", "entity name 2"],
  "blocked": ["entity name 1", "entity name 2"]
}}

Return only JSON. Be specific — use actual names from the data.
"""


class GapDetectorAgent:
    def __init__(self, session: AsyncSession, api_key: str | None = None, model: str | None = None):
        self.session = session
        self.api_key = api_key
        self.model = model

    async def run(self) -> GapReport:
        components, relationships = await self._load_graph()
        stats = self._compute_stats(components, relationships)

        rule_gaps = self._rule_based_gaps(components, relationships)

        if self.api_key and self.model:
            ai_report = await self._ai_analysis(components, relationships)
            if ai_report:
                return GapReport(
                    summary=ai_report.get("summary", ""),
                    gaps=[GapItem(**g) for g in ai_report.get("gaps", [])],
                    ready_to_ship=ai_report.get("ready_to_ship", []),
                    blocked=ai_report.get("blocked", []),
                    stats=stats,
                )

        return GapReport(
            summary=self._rule_summary(rule_gaps, stats),
            gaps=rule_gaps,
            ready_to_ship=self._find_ready(components, relationships),
            blocked=self._find_blocked(components, relationships),
            stats=stats,
        )

    async def _load_graph(self):
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
        return components, relationships

    def _compute_stats(self, components, relationships) -> dict:
        by_type: dict[str, int] = {}
        for c in components:
            t = canonical_model_name(c.model.name if c.model else "Unknown")
            by_type[t] = by_type.get(t, 0) + 1

        connected_ids = set()
        for r in relationships:
            connected_ids.add(str(r.source_component_id))
            connected_ids.add(str(r.target_component_id))

        return {
            "total_entities": len(components),
            "total_relationships": len(relationships),
            "by_type": by_type,
            "isolated": len([c for c in components if str(c.id) not in connected_ids]),
        }

    def _rule_based_gaps(self, components, relationships) -> list[GapItem]:
        gaps: list[GapItem] = []

        connected_ids = set()
        for r in relationships:
            connected_ids.add(str(r.source_component_id))
            connected_ids.add(str(r.target_component_id))

        rel_map: dict[str, list[str]] = {}
        for r in relationships:
            sid = str(r.source_component_id)
            tid = str(r.target_component_id)
            rel_map.setdefault(sid, []).append(tid)
            rel_map.setdefault(tid, []).append(sid)

        type_map: dict[str, list[Component]] = {}
        for c in components:
            t = model_bucket(c.model.name if c.model else "Unknown")
            type_map.setdefault(t, []).append(c)

        person_ids = {str(c.id) for c in type_map.get("person", [])}
        task_ids = {str(c.id) for c in type_map.get("task", [])}
        risk_ids = {str(c.id) for c in type_map.get("risk", [])}

        for c in type_map.get("feature", []) + type_map.get("decision", []):
            neighbors = set(rel_map.get(str(c.id), []))
            if not neighbors & person_ids:
                gaps.append(GapItem(
                    category="missing_owner",
                    severity="high",
                    title=f"No owner: {c.name[:80]}",
                    detail=f"{canonical_model_name(c.model.name if c.model else 'Entity')} has no Person linked.",
                    entity_name=c.name,
                    recommendation="Assign an owner by linking a Person entity.",
                ))

        for c in type_map.get("decision", []):
            neighbors = set(rel_map.get(str(c.id), []))
            if not neighbors & task_ids:
                gaps.append(GapItem(
                    category="unimplemented_decision",
                    severity="high",
                    title=f"Decision with no tasks: {c.name[:80]}",
                    detail="This decision has no linked Tasks or PRs implementing it.",
                    entity_name=c.name,
                    recommendation="Create a Task for each action required by this decision.",
                ))

        for c in type_map.get("task", []) + type_map.get("feature", []):
            neighbors = set(rel_map.get(str(c.id), []))
            if neighbors & risk_ids:
                gaps.append(GapItem(
                    category="blocked",
                    severity="critical",
                    title=f"Blocked: {c.name[:80]}",
                    detail="This item is linked to an unresolved Risk.",
                    entity_name=c.name,
                    recommendation="Resolve the linked Risk before proceeding.",
                ))

        for c in components:
            if str(c.id) not in connected_ids:
                gaps.append(GapItem(
                    category="orphaned",
                    severity="low",
                    title=f"Isolated entity: {c.name[:80]}",
                    detail="No relationships to any other entity — context may be lost.",
                    entity_name=c.name,
                    recommendation="Link this to a related Decision, Feature, or Task.",
                ))

        gaps.sort(key=lambda g: {"critical": 0, "high": 1, "medium": 2, "low": 3}[g.severity])
        return gaps[:20]

    def _find_ready(self, components, relationships) -> list[str]:
        rel_map: dict[str, list[str]] = {}
        for r in relationships:
            rel_map.setdefault(str(r.source_component_id), []).append(str(r.target_component_id))
            rel_map.setdefault(str(r.target_component_id), []).append(str(r.source_component_id))

        risk_ids = {str(c.id) for c in components if c.model and model_bucket(c.model.name) == "risk"}
        ready = []
        for c in components:
            if c.model and model_bucket(c.model.name) in ("feature", "task"):
                neighbors = set(rel_map.get(str(c.id), []))
                if not (neighbors & risk_ids) and c.temporal in ("current", "future"):
                    ready.append(c.name)
        return ready[:5]

    def _find_blocked(self, components, relationships) -> list[str]:
        rel_map: dict[str, list[str]] = {}
        for r in relationships:
            rel_map.setdefault(str(r.source_component_id), []).append(str(r.target_component_id))
            rel_map.setdefault(str(r.target_component_id), []).append(str(r.source_component_id))

        risk_ids = {str(c.id) for c in components if c.model and model_bucket(c.model.name) == "risk"}
        blocked = []
        for c in components:
            if c.model and model_bucket(c.model.name) in ("feature", "task", "decision"):
                if set(rel_map.get(str(c.id), [])) & risk_ids:
                    blocked.append(c.name)
        return blocked[:5]

    def _rule_summary(self, gaps: list[GapItem], stats: dict) -> str:
        critical = sum(1 for g in gaps if g.severity == "critical")
        high = sum(1 for g in gaps if g.severity == "high")
        return (
            f"Found {len(gaps)} gaps across {stats['total_entities']} entities: "
            f"{critical} critical, {high} high priority. "
            f"{stats['isolated']} entities are isolated with no relationships."
        )

    async def _ai_analysis(self, components, relationships) -> dict | None:
        by_type: dict[str, list[str]] = {}
        for c in components:
            t = canonical_model_name(c.model.name if c.model else "Unknown")
            by_type.setdefault(t, []).append(f"- {c.name}: {c.value[:120]}")

        entities_text = ""
        for t, items in list(by_type.items())[:15]:
            entities_text += f"\n## {t}\n" + "\n".join(items[:8])

        rel_lines = []
        for r in relationships[:50]:
            src = r.source_component.name if r.source_component else "?"
            tgt = r.target_component.name if r.target_component else "?"
            rel_lines.append(f"- {src} --[{r.relationship_type}]--> {tgt}")
        rel_text = "\n".join(rel_lines)

        try:
            from litellm import acompletion
            prompt = GAP_PROMPT.format(entities=entities_text, relationships=rel_text)
            response = await acompletion(
                model=self.model,
                api_key=self.api_key,
                messages=[
                    {"role": "system", "content": "You are a startup CTO analyzing a knowledge graph. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(raw)
        except Exception:
            return None
