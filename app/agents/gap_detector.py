from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship, SourceDocument
from app.services.access import AccessScope, source_access_predicate
from app.services.prompt_artifacts import (
    PromptArtifact,
    PromptOutputValidationError,
    invoke_prompt_artifact,
    provider_response_mode,
    provider_supports_json_schema,
)
from app.taxonomy import canonical_model_name, model_bucket
from app.services.workspace_scope import (
    filter_components_for_workspace,
    normalize_workspace_id,
    workspace_connector_types,
)


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


GAP_PROMPT_ID = "gap.detector"
GAP_PROMPT_VERSION = "1.1.0"
GAP_ENTITY_TYPE_LIMIT = 15
GAP_ENTITIES_PER_TYPE_LIMIT = 8
GAP_RELATIONSHIP_LIMIT = 50

GAP_SYSTEM_INSTRUCTION = """You are a startup CEO analyzing a bounded knowledge-graph snapshot.

Identify the most critical evidence-backed gaps, risks, and opportunities:
1. missing_owner: a Feature, Task, or Decision with no Person linked
2. unimplemented_decision: a Decision with no related Task or PR
3. blocked: a Task or Feature blocked by an unresolved Risk
4. repeated_failure: Agent Sessions repeatedly encountering the same problem
5. unactioned_pain: a Customer or Risk item with no linked Feature or Task
6. orphaned: a PR, Issue, or Task disconnected from a Decision or Feature

Also identify Features or Tasks that appear ready to ship and items blocked by a Risk.
Use only evidence in the supplied entity and relationship records. Use entity names exactly
as supplied. Do not invent entities, links, owners, blockers, or completion state. A graph
snapshot can be truncated; when its snapshot metadata shows omitted records, do not treat
absence from the snapshot as definitive evidence. Keep the summary executive-level and
make every recommendation a concrete next action."""

GAP_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1500,
        },
        "gaps": {
            "type": "array",
            "maxItems": 20,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "missing_owner",
                            "unimplemented_decision",
                            "blocked",
                            "repeated_failure",
                            "unactioned_pain",
                            "orphaned",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                    "detail": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "entity_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "recommendation": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                    },
                },
                "required": [
                    "category",
                    "severity",
                    "title",
                    "detail",
                    "entity_name",
                    "recommendation",
                ],
                "additionalProperties": False,
            },
        },
        "ready_to_ship": {
            "type": "array",
            "maxItems": 5,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "blocked": {
            "type": "array",
            "maxItems": 5,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
    },
    "required": ["summary", "gaps", "ready_to_ship", "blocked"],
    "additionalProperties": False,
}


class GapDetectorAgent:
    def __init__(
        self,
        session: AsyncSession,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.session = session
        self.api_key = api_key
        self.model = model
        self.last_prompt_artifact: PromptArtifact | None = None
        self.last_prompt_audit_metadata: dict[str, Any] | None = None

    async def run(
        self,
        *,
        workspace_id: str | UUID | None = None,
        access_scope: AccessScope | None = None,
    ) -> GapReport:
        self.last_prompt_artifact = None
        self.last_prompt_audit_metadata = None
        if access_scope is None and workspace_id is None:
            components, relationships = await self._load_graph()
        else:
            components, relationships = await self._load_graph(
                workspace_id=workspace_id,
                access_scope=access_scope,
            )
        stats = self._compute_stats(components, relationships)

        rule_gaps = self._rule_based_gaps(components, relationships)

        if self.api_key and self.model:
            ai_report = await self._ai_analysis(components, relationships)
            if ai_report:
                return GapReport(
                    summary=ai_report["summary"],
                    gaps=[GapItem(**gap) for gap in ai_report["gaps"]],
                    ready_to_ship=ai_report["ready_to_ship"],
                    blocked=ai_report["blocked"],
                    stats=self._with_prompt_audit(stats),
                )

        return GapReport(
            summary=self._rule_summary(rule_gaps, stats),
            gaps=rule_gaps,
            ready_to_ship=self._find_ready(components, relationships),
            blocked=self._find_blocked(components, relationships),
            stats=self._with_prompt_audit(stats),
        )

    def _with_prompt_audit(self, stats: dict[str, Any]) -> dict[str, Any]:
        if self.last_prompt_audit_metadata is None:
            return stats
        return {
            **stats,
            "prompt_artifact": dict(self.last_prompt_audit_metadata),
        }

    async def _load_graph(
        self,
        *,
        workspace_id: str | UUID | None = None,
        access_scope: AccessScope | None = None,
    ):
        scope = access_scope or AccessScope.local()
        workspace_uuid: UUID | None = None
        if workspace_id is not None:
            _, workspace_uuid = normalize_workspace_id(workspace_id)
            if not scope.allows_workspace(workspace_uuid):
                raise LookupError("Workspace not found")
        elif not scope.unrestricted:
            raise ValueError("workspace_id is required")

        component_query = select(Component).options(
            selectinload(Component.model),
            selectinload(Component.source_document),
        )
        if not scope.unrestricted:
            component_query = component_query.join(
                SourceDocument,
                Component.source_document_id == SourceDocument.id,
            ).where(source_access_predicate(
                scope,
                workspace_id=workspace_uuid,
            ))
        comp_result = await self.session.execute(component_query)
        components = comp_result.scalars().all()
        if scope.unrestricted and workspace_uuid is not None:
            workspace_id_str, connector_types = await workspace_connector_types(
                self.session,
                workspace_uuid,
            )
            components = filter_components_for_workspace(
                components,
                workspace_id_str,
                connector_types,
            )
        component_ids = {component.id for component in components}

        rel_result = await self.session.execute(
            select(Relationship).where(
                Relationship.source_component_id.in_(component_ids),
                Relationship.target_component_id.in_(component_ids),
            ).options(
                selectinload(Relationship.source_component).selectinload(
                    Component.model
                ),
                selectinload(Relationship.target_component).selectinload(
                    Component.model
                ),
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
        self.last_prompt_artifact = None
        self.last_prompt_audit_metadata = None
        try:
            target_model = str(self.model or "").strip()
            if not target_model:
                return None
            artifact = _gap_prompt_artifact(
                components=components,
                relationships=relationships,
                target_model=target_model,
            )
            self.last_prompt_artifact = artifact
            self.last_prompt_audit_metadata = artifact.audit_metadata()
            output = await invoke_prompt_artifact(
                artifact,
                response_mode=provider_response_mode(
                    artifact.target_model,
                    supports_json_schema=provider_supports_json_schema(
                        artifact.target_model
                    ),
                ),
                api_key=self.api_key,
            )
            return _validated_gap_output(
                output,
                graph=artifact.data_payload()["graph"],
            )
        except Exception:
            return None


def _gap_prompt_artifact(
    *,
    components: list[Component],
    relationships: list[Relationship],
    target_model: str,
) -> PromptArtifact:
    """Build the exact versioned artifact used by the gap-detector runtime."""

    entities_by_type: dict[str, list[Component]] = {}
    for component in components:
        entity_type = canonical_model_name(
            component.model.name if component.model else "Unknown"
        )
        entities_by_type.setdefault(entity_type, []).append(component)

    entity_records: list[dict[str, str]] = []
    for entity_type in sorted(
        entities_by_type,
        key=str.casefold,
    )[:GAP_ENTITY_TYPE_LIMIT]:
        type_components = sorted(
            entities_by_type[entity_type],
            key=lambda component: (
                str(component.name or "").casefold(),
                str(component.id),
            ),
        )
        for component in type_components[:GAP_ENTITIES_PER_TYPE_LIMIT]:
            entity_records.append({
                "id": str(component.id),
                "type": entity_type,
                "name": str(component.name or ""),
                "value": str(component.value or "")[:120],
                "temporal": str(component.temporal or "unknown"),
                "status": str(component.status or "active"),
            })

    relationship_records = sorted(
        (_relationship_prompt_record(relationship) for relationship in relationships),
        key=lambda relationship: (
            relationship["source_name"].casefold(),
            relationship["target_name"].casefold(),
            relationship["relationship_type"].casefold(),
            relationship["source_id"],
            relationship["target_id"],
        ),
    )[:GAP_RELATIONSHIP_LIMIT]

    graph = {
        "snapshot": {
            "total_entities": len(components),
            "included_entities": len(entity_records),
            "total_relationships": len(relationships),
            "included_relationships": len(relationship_records),
        },
        "entities": entity_records,
        "relationships": relationship_records,
    }
    return PromptArtifact(
        prompt_id=GAP_PROMPT_ID,
        prompt_version=GAP_PROMPT_VERSION,
        input_contract_version="gap_snapshot.v2",
        semantic_validator_version="gap_graph_rules.v2",
        target_model=target_model,
        system_instruction=GAP_SYSTEM_INSTRUCTION,
        untrusted_data={"graph": graph},
        output_schema=GAP_OUTPUT_SCHEMA,
        temperature=0.1,
        max_tokens=1500,
    )


def _relationship_prompt_record(relationship: Relationship) -> dict[str, str]:
    source = relationship.source_component
    target = relationship.target_component
    return {
        "source_id": str(relationship.source_component_id),
        "source_name": str(source.name or "") if source else "",
        "source_type": canonical_model_name(
            source.model.name if source and source.model else "Unknown"
        ),
        "relationship_type": str(relationship.relationship_type or "related_to"),
        "target_id": str(relationship.target_component_id),
        "target_name": str(target.name or "") if target else "",
        "target_type": canonical_model_name(
            target.model.name if target and target.model else "Unknown"
        ),
    }


def _validated_gap_output(
    output: dict[str, Any],
    *,
    graph: dict[str, Any],
) -> dict[str, Any]:
    name_types: dict[str, set[str]] = {}
    entities_by_name: dict[str, list[dict[str, Any]]] = {}
    for entity in graph["entities"]:
        name_types.setdefault(entity["name"], set()).add(entity["type"])
        entities_by_name.setdefault(entity["name"], []).append(entity)
    for relationship in graph["relationships"]:
        for endpoint in ("source", "target"):
            name = relationship[f"{endpoint}_name"]
            if name:
                name_types.setdefault(name, set()).add(
                    relationship[f"{endpoint}_type"]
                )

    snapshot = graph["snapshot"]
    snapshot_complete = (
        snapshot["total_entities"] == snapshot["included_entities"]
        and snapshot["total_relationships"]
        == snapshot["included_relationships"]
    )
    absence_categories = {
        "missing_owner",
        "unimplemented_decision",
        "unactioned_pain",
        "orphaned",
    }

    for gap in output["gaps"]:
        entity_name = gap["entity_name"]
        category = gap["category"]
        if entity_name not in name_types:
            raise PromptOutputValidationError(
                "gap entity_name must reference a supplied entity"
            )
        if category in absence_categories and not snapshot_complete:
            raise PromptOutputValidationError(
                "absence-based gaps require a complete graph snapshot"
            )
        if category == "missing_owner":
            _require_gap_entity_type(
                entity_name,
                name_types,
                {"feature", "task", "decision"},
            )
            if _has_neighbor_bucket(graph, entity_name, {"person"}):
                raise PromptOutputValidationError(
                    "missing_owner conflicts with a supplied Person relationship"
                )
        elif category == "unimplemented_decision":
            _require_gap_entity_type(entity_name, name_types, {"decision"})
            if _has_neighbor_bucket(graph, entity_name, {"task", "pr"}):
                raise PromptOutputValidationError(
                    "unimplemented_decision conflicts with supplied implementation work"
                )
        elif category == "blocked":
            _require_gap_entity_type(entity_name, name_types, {"feature", "task"})
            if not _has_active_risk_neighbor(
                graph,
                entity_name,
                entities_by_name,
            ):
                raise PromptOutputValidationError(
                    "blocked gaps require a supplied unresolved Risk relationship"
                )
        elif category == "repeated_failure":
            _require_gap_entity_type(entity_name, name_types, {"agent session"})
            session_count = sum(
                1
                for entity in graph["entities"]
                if model_bucket(entity["type"]) == "agent session"
            )
            if session_count < 2:
                raise PromptOutputValidationError(
                    "repeated_failure requires at least two supplied Agent Sessions"
                )
        elif category == "unactioned_pain":
            _require_gap_entity_type(entity_name, name_types, {"customer", "risk"})
            if _has_neighbor_bucket(graph, entity_name, {"feature", "task"}):
                raise PromptOutputValidationError(
                    "unactioned_pain conflicts with supplied action relationships"
                )
        elif category == "orphaned":
            _require_gap_entity_type(entity_name, name_types, {"pr", "issue", "task"})
            if _has_neighbor_bucket(graph, entity_name, {"decision", "feature"}):
                raise PromptOutputValidationError(
                    "orphaned conflicts with a supplied product relationship"
                )

    ready_names = set(output["ready_to_ship"])
    blocked_names = set(output["blocked"])
    for name in ready_names:
        if not snapshot_complete:
            raise PromptOutputValidationError(
                "ready_to_ship requires a complete graph snapshot"
            )
        if name not in name_types or not _has_model_bucket(
            name_types[name],
            {"feature", "task"},
        ):
            raise PromptOutputValidationError(
                "ready_to_ship must reference a supplied Feature or Task"
            )
        if _has_active_risk_neighbor(graph, name, entities_by_name):
            raise PromptOutputValidationError(
                "ready_to_ship cannot have an unresolved Risk relationship"
            )
        if not any(
            entity.get("temporal") in {"current", "future"}
            and entity.get("status") not in {"closed", "rejected", "resolved"}
            for entity in entities_by_name.get(name, [])
        ):
            raise PromptOutputValidationError(
                "ready_to_ship must reference active current or future work"
            )
    for name in blocked_names:
        if name not in name_types or not _has_model_bucket(
            name_types[name],
            {"feature", "task"},
        ):
            raise PromptOutputValidationError(
                "blocked must reference a supplied Feature or Task"
            )
        if not _has_active_risk_neighbor(graph, name, entities_by_name):
            raise PromptOutputValidationError(
                "blocked items require a supplied unresolved Risk relationship"
            )
    if ready_names & blocked_names:
        raise PromptOutputValidationError(
            "an entity cannot be both ready_to_ship and blocked"
        )
    return output


def _has_model_bucket(model_names: set[str], allowed: set[str]) -> bool:
    return any(model_bucket(model_name) in allowed for model_name in model_names)


def _require_gap_entity_type(
    entity_name: str,
    name_types: dict[str, set[str]],
    allowed: set[str],
) -> None:
    if not _has_model_bucket(name_types[entity_name], allowed):
        raise PromptOutputValidationError(
            "gap category does not match the supplied entity type"
        )


def _has_neighbor_bucket(
    graph: dict[str, Any],
    entity_name: str,
    buckets: set[str],
) -> bool:
    for relationship in graph["relationships"]:
        if relationship["source_name"] == entity_name:
            neighbor_type = relationship["target_type"]
        elif relationship["target_name"] == entity_name:
            neighbor_type = relationship["source_type"]
        else:
            continue
        if model_bucket(neighbor_type) in buckets:
            return True
    return False


def _has_active_risk_neighbor(
    graph: dict[str, Any],
    entity_name: str,
    entities_by_name: dict[str, list[dict[str, Any]]],
) -> bool:
    risk_names: set[str] = set()
    for relationship in graph["relationships"]:
        if relationship["source_name"] == entity_name and model_bucket(
            relationship["target_type"]
        ) == "risk":
            risk_names.add(relationship["target_name"])
        elif relationship["target_name"] == entity_name and model_bucket(
            relationship["source_type"]
        ) == "risk":
            risk_names.add(relationship["source_name"])
    return any(
        entity.get("status") not in {"closed", "rejected", "resolved"}
        for risk_name in risk_names
        for entity in entities_by_name.get(risk_name, [])
        if model_bucket(entity["type"]) == "risk"
    )
