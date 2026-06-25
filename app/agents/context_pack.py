from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship
from app.services.workspace_scope import (
    filter_components_for_workspace,
    workspace_connector_types,
)
from app.taxonomy import canonical_model_name, model_bucket


CONTEXT_PACK_PROMPT = """You are generating a perfect AI coding agent handoff document.

Based on the startup knowledge graph data below, generate a structured context pack.

Entities:
{entities}

Relationships:
{relationships}

Generate a context pack with these exact sections:
1. PROJECT GOAL — What are we building and why (inferred from entities)
2. CURRENT STATE — What's done, what's in progress
3. OPEN DECISIONS — Unresolved decisions that affect work
4. ACTIVE BLOCKERS — Risks and blockers that need resolving
5. PAST AI AGENT ATTEMPTS — What has already been tried (Agent Sessions)
6. NEXT 5 TASKS — Most important things to do next, numbered

Be specific — use actual names and values from the data. This will be pasted into a coding agent prompt.
Format as clean markdown with ## headers.
"""


@dataclass
class ContextPack:
    content: str
    entity_count: int
    generated_at: str


class ContextPackAgent:
    def __init__(self, session: AsyncSession, api_key: str | None = None, model: str | None = None):
        self.session = session
        self.api_key = api_key
        self.model = model

    async def run(
        self,
        component_ids: list[str | UUID] | None = None,
        workspace_id: str | UUID | None = None,
    ) -> ContextPack:
        components, relationships = await self._load_graph(component_ids, workspace_id)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        if self.api_key and self.model:
            content = await self._ai_pack(components, relationships)
            if content:
                return ContextPack(content=content, entity_count=len(components), generated_at=now)

        return ContextPack(
            content=self._rule_pack(components, relationships, now),
            entity_count=len(components),
            generated_at=now,
        )

    async def _load_graph(
        self,
        component_ids: list[str | UUID] | None = None,
        workspace_id: str | UUID | None = None,
    ):
        selected_ids = {UUID(str(cid)) for cid in (component_ids or [])}
        if selected_ids:
            seed_relationships = list(await self.session.scalars(
                select(Relationship)
                .where(Relationship.status != "rejected")
                .where(
                    Relationship.source_component_id.in_(selected_ids)
                    | Relationship.target_component_id.in_(selected_ids)
                )
            ))
            included_ids = set(selected_ids)
            for rel in seed_relationships:
                included_ids.add(rel.source_component_id)
                included_ids.add(rel.target_component_id)

            comp_result = await self.session.execute(
                select(Component)
                .where(Component.id.in_(included_ids))
                .options(selectinload(Component.model), selectinload(Component.source_document))
            )
            components = comp_result.scalars().all()
            rel_result = await self.session.execute(
                select(Relationship)
                .where(Relationship.status != "rejected")
                .where(
                    Relationship.source_component_id.in_(included_ids),
                    Relationship.target_component_id.in_(included_ids),
                )
                .options(
                    selectinload(Relationship.source_component),
                    selectinload(Relationship.target_component),
                )
            )
            relationships = rel_result.scalars().all()
            return await self._apply_workspace_scope(components, relationships, workspace_id)

        comp_result = await self.session.execute(
            select(Component).options(selectinload(Component.model), selectinload(Component.source_document))
        )
        components = comp_result.scalars().all()
        rel_result = await self.session.execute(
            select(Relationship).options(
                selectinload(Relationship.source_component),
                selectinload(Relationship.target_component),
            )
        )
        relationships = rel_result.scalars().all()
        return await self._apply_workspace_scope(components, relationships, workspace_id)

    async def _apply_workspace_scope(self, components, relationships, workspace_id):
        if not workspace_id:
            return components, relationships
        workspace_id_str, connector_types = await workspace_connector_types(self.session, workspace_id)
        scoped_components = filter_components_for_workspace(
            components,
            workspace_id_str,
            connector_types,
        )
        component_ids = {component.id for component in scoped_components}
        scoped_relationships = [
            rel for rel in relationships
            if rel.source_component_id in component_ids and rel.target_component_id in component_ids
        ]
        return scoped_components, scoped_relationships

    def _rule_pack(self, components, relationships, now: str) -> str:
        by_type: dict[str, list[Component]] = {}
        for c in components:
            t = model_bucket(c.model.name if c.model else "Unknown")
            by_type.setdefault(t, []).append(c)

        def fmt(items, limit=5):
            return "\n".join(f"- {c.value[:150]}" for c in items[:limit])

        sections = [f"# Context Pack — {now}\n"]

        features = by_type.get("feature", [])
        if features:
            sections.append(f"## Current State\n{fmt(features)}")

        decisions = by_type.get("decision", [])
        if decisions:
            sections.append(f"## Open Decisions\n{fmt(decisions)}")

        risks = by_type.get("risk", [])
        if risks:
            sections.append(f"## Active Blockers\n{fmt(risks)}")

        sessions = by_type.get("agent session", [])
        if sessions:
            sections.append(f"## Past AI Agent Attempts\n{fmt(sessions)}")

        tasks = [c for c in by_type.get("task", []) if c.temporal in ("current", "future")]
        if tasks:
            numbered = "\n".join(f"{i+1}. {c.value[:150]}" for i, c in enumerate(tasks[:5]))
            sections.append(f"## Next 5 Tasks\n{numbered}")

        rel_lines = []
        for r in relationships[:20]:
            src = r.source_component.name if r.source_component else "?"
            tgt = r.target_component.name if r.target_component else "?"
            rel_lines.append(f"- {src} → {tgt} ({r.relationship_type})")
        if rel_lines:
            sections.append("## Key Relationships\n" + "\n".join(rel_lines))

        sections.append("\n---\n*Generated by Context Engine — paste this into your AI coding agent.*")
        return "\n\n".join(sections)

    async def _ai_pack(self, components, relationships) -> str | None:
        by_type: dict[str, list[str]] = {}
        for c in components:
            t = canonical_model_name(c.model.name if c.model else "Unknown")
            by_type.setdefault(t, []).append(f"- {c.name}: {c.value[:120]}")

        entities_text = ""
        for t, items in list(by_type.items())[:12]:
            entities_text += f"\n## {t}\n" + "\n".join(items[:6])

        rel_lines = [
            f"- {r.source_component.name if r.source_component else '?'} --[{r.relationship_type}]--> {r.target_component.name if r.target_component else '?'}"
            for r in relationships[:40]
        ]

        try:
            from litellm import acompletion
            prompt = CONTEXT_PACK_PROMPT.format(
                entities=entities_text,
                relationships="\n".join(rel_lines),
            )
            response = await acompletion(
                model=self.model,
                api_key=self.api_key,
                messages=[
                    {"role": "system", "content": "Generate a precise, useful AI coding agent handoff document. Be specific. Use markdown."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return None
