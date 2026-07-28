from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Relationship, SourceDocument
from app.schemas.continuation_execution import (
    MAX_DISPLAY_TITLE,
    normalize_request_for_matching,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.workspace_scope import current_source_documents


TASK_FACT_TYPES = frozenset(
    {
        "action_item",
        "ai_task",
        "feature",
        "github_issue",
        "issue",
        "requirement",
        "task",
    }
)
DEPENDENCY_RELATIONSHIP_TYPES = frozenset(
    {"blocked_by", "blocks", "depends_on"}
)
TRUSTED_RELATIONSHIP_ORIGINS = frozenset(
    {"deterministic", "human_verified"}
)
COMPLETED_STATUSES = frozenset(
    {
        "closed",
        "complete",
        "completed",
        "done",
        "passed",
        "resolved",
        "succeeded",
        "success",
    }
)
PAUSED_STATUSES = frozenset(
    {"deferred", "on_hold", "on hold", "paused"}
)
DROPPED_STATUSES = frozenset(
    {
        "abandoned",
        "canceled",
        "cancelled",
        "deprecated",
        "dismissed",
        "dropped",
        "rejected",
        "superseded",
    }
)
ACTIONABLE_STATUSES = frozenset(
    {
        "active",
        "in_progress",
        "in progress",
        "needs_review",
        "open",
        "pending",
        "proposed",
        "ready",
    }
)
WORKFLOW_SCHEMA_VERSION = "task_workflow.v1"
MAX_BUCKET_ITEMS = 8
MAX_AFFECTED_TASKS = 12
MAX_GRAPH_TASKS = 64


@dataclass(frozen=True)
class WorkflowResolution:
    workflow: dict[str, Any]
    selected_objective: str
    execution_objective: str
    selected_component_id: UUID | None
    execution_component_id: UUID | None
    blocking_issues: list[dict[str, Any]]


@dataclass(frozen=True)
class _TaskNode:
    component_id: UUID | None
    title: str
    objective: str
    status: str
    lifecycle: str
    fact_type: str
    source_document_id: UUID | None

    @property
    def id(self) -> str:
        if self.component_id is not None:
            return str(self.component_id)
        digest = hashlib.sha256(self.objective.casefold().encode("utf-8")).hexdigest()
        return f"objective:{digest[:24]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component_id": (
                str(self.component_id) if self.component_id is not None else None
            ),
            "title": self.title,
            "objective": self.objective,
            "status": self.status,
            "lifecycle": self.lifecycle,
            "fact_type": self.fact_type,
            "source_document_id": (
                str(self.source_document_id)
                if self.source_document_id is not None
                else None
            ),
            "source_backed": self.source_document_id is not None,
        }


class TaskWorkflowService:
    """Resolve one safe execution task from trusted source-backed dependencies."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        access_scope: AccessScope,
        selected_objective: str,
        selected_component_id: UUID | str | None = None,
    ) -> WorkflowResolution:
        normalized_objective = normalize_request_for_matching(
            str(selected_objective or "")
        )
        if not normalized_objective:
            raise ValueError("selected_objective must contain visible characters")
        fallback = _TaskNode(
            component_id=None,
            title=_clean_text(normalized_objective, MAX_DISPLAY_TITLE),
            objective=normalized_objective,
            status="active",
            lifecycle="active",
            fact_type="objective",
            source_document_id=None,
        )
        components = await self._accessible_task_components(
            workspace_id=workspace_id,
            access_scope=access_scope,
        )
        nodes = {
            component.id: _task_node(component)
            for component in components
        }
        selected, selection_issues = _select_task(
            nodes,
            objective=normalized_objective,
            component_id=_uuid_or_none(selected_component_id),
            fallback=fallback,
        )
        if selected.component_id is None:
            workflow = _workflow_payload(
                selected=selected,
                execution=selected if not selection_issues else None,
                now=[] if selection_issues else [selected],
                blocked=[],
                next_tasks=[],
                paused=[],
                affected=[],
                blocking_issues=selection_issues,
                modeled=False,
                relationship_count=0,
            )
            return WorkflowResolution(
                workflow=workflow,
                selected_objective=normalized_objective,
                execution_objective=normalized_objective,
                selected_component_id=None,
                execution_component_id=None,
                blocking_issues=selection_issues,
            )

        relationships = await self._trusted_dependencies(set(nodes))
        unavailable_endpoint_ids = {
            endpoint_id
            for relationship in relationships
            for endpoint_id in (
                relationship.source_component_id,
                relationship.target_component_id,
            )
            if endpoint_id not in nodes
        }
        unavailable_task_ids = await self._task_component_ids(
            unavailable_endpoint_ids
        )
        prerequisites: dict[UUID, set[UUID]] = {
            component_id: set() for component_id in nodes
        }
        dependents: dict[UUID, set[UUID]] = {
            component_id: set() for component_id in nodes
        }
        hidden_prerequisites: set[UUID] = set()
        accepted_relationship_count = 0
        for relationship in relationships:
            prerequisite_id, dependent_id = _dependency_direction(relationship)
            if (
                dependent_id in nodes
                and prerequisite_id in unavailable_task_ids
            ):
                hidden_prerequisites.add(dependent_id)
                continue
            if prerequisite_id not in nodes or dependent_id not in nodes:
                continue
            prerequisites[dependent_id].add(prerequisite_id)
            dependents[prerequisite_id].add(dependent_id)
            accepted_relationship_count += 1

        selected_id = selected.component_id
        assert selected_id is not None
        cluster_ids, graph_truncated = _workflow_cluster(
            selected_id,
            prerequisites=prerequisites,
            dependents=dependents,
        )
        resolution = _resolve_execution(
            selected_id,
            nodes=nodes,
            prerequisites=prerequisites,
            hidden_prerequisites=hidden_prerequisites,
        )
        issues = [*selection_issues, *resolution["issues"]]
        issues = [
            _with_downstream_affected_tasks(
                issue,
                nodes=nodes,
                dependents=dependents,
                selected_id=selected_id,
            )
            for issue in issues
        ]
        if graph_truncated:
            affected = _task_dicts(
                (nodes[item] for item in cluster_ids if item in nodes),
                limit=MAX_AFFECTED_TASKS,
            )
            issues.append({
                "code": "dependency_workflow_too_large",
                "message": (
                    "The dependency workflow exceeds the safe automatic traversal "
                    f"limit of {MAX_GRAPH_TASKS} tasks."
                ),
                "blocker": None,
                "blocking_tasks": [],
                "affected_tasks": affected,
            })

        execution_id = resolution["execution_id"] if not issues else None
        execution = nodes.get(execution_id) if execution_id is not None else None
        active_cluster = {
            item
            for item in cluster_ids
            if item in nodes and nodes[item].lifecycle == "active"
        }
        blocked_ids = {
            item
            for item in active_cluster
            if _unfinished_prerequisites(
                item,
                nodes=nodes,
                prerequisites=prerequisites,
                hidden_prerequisites=hidden_prerequisites,
            )
        }
        blocked = [
            {
                **nodes[item].to_dict(),
                "blocked_by": _task_dicts(
                    (
                        nodes[prerequisite]
                        for prerequisite in sorted(
                            prerequisites.get(item, set()),
                            key=str,
                        )
                        if prerequisite in nodes
                        and nodes[prerequisite].lifecycle != "completed"
                    ),
                    limit=MAX_BUCKET_ITEMS,
                ),
                "has_inaccessible_prerequisite": item in hidden_prerequisites,
            }
            for item in _sorted_task_ids(blocked_ids, nodes)[:MAX_BUCKET_ITEMS]
        ]
        next_ids = active_cluster - blocked_ids
        if execution_id is not None:
            next_ids.discard(execution_id)
        next_tasks = [
            nodes[item]
            for item in _sorted_task_ids(next_ids, nodes)[:MAX_BUCKET_ITEMS]
        ]
        paused_tasks = [
            node
            for node in sorted(nodes.values(), key=_task_sort_key)
            if node.lifecycle in {"dropped", "paused", "unknown"}
        ][:MAX_BUCKET_ITEMS]

        affected_ids = set(cluster_ids)
        if execution_id is not None:
            affected_ids.discard(execution_id)
        affected_tasks = [
            nodes[item]
            for item in _sorted_task_ids(affected_ids, nodes)[:MAX_AFFECTED_TASKS]
        ]
        workflow = _workflow_payload(
            selected=selected,
            execution=execution,
            now=[execution] if execution is not None else [],
            blocked=blocked,
            next_tasks=next_tasks,
            paused=paused_tasks,
            affected=affected_tasks,
            blocking_issues=issues,
            modeled=True,
            relationship_count=accepted_relationship_count,
        )
        execution_objective = (
            execution.objective if execution is not None else normalized_objective
        )
        return WorkflowResolution(
            workflow=workflow,
            selected_objective=normalized_objective,
            execution_objective=execution_objective,
            selected_component_id=selected.component_id,
            execution_component_id=(
                execution.component_id if execution is not None else None
            ),
            blocking_issues=issues,
        )

    async def _accessible_task_components(
        self,
        *,
        workspace_id: UUID,
        access_scope: AccessScope,
    ) -> list[Component]:
        documents = list(await self.session.scalars(
            select(SourceDocument).where(
                source_access_predicate(
                    access_scope,
                    workspace_id=workspace_id,
                )
            )
        ))
        current_documents, _ = current_source_documents(documents)
        source_ids = [document.id for document in current_documents]
        if not source_ids:
            return []
        return list(await self.session.scalars(
            select(Component)
            .where(
                Component.source_document_id.in_(source_ids),
                or_(
                    Component.workspace_id == workspace_id,
                    Component.workspace_id.is_(None),
                ),
                Component.fact_type.in_(TASK_FACT_TYPES),
            )
            .order_by(Component.created_at.desc(), Component.id.desc())
        ))

    async def _trusted_dependencies(
        self,
        component_ids: set[UUID],
    ) -> list[Relationship]:
        if not component_ids:
            return []
        return list(await self.session.scalars(
            select(Relationship).where(
                Relationship.status == "active",
                Relationship.origin.in_(TRUSTED_RELATIONSHIP_ORIGINS),
                Relationship.relationship_type.in_(
                    DEPENDENCY_RELATIONSHIP_TYPES
                ),
                or_(
                    Relationship.source_component_id.in_(component_ids),
                    Relationship.target_component_id.in_(component_ids),
                ),
            )
        ))

    async def _task_component_ids(
        self,
        component_ids: set[UUID],
    ) -> set[UUID]:
        if not component_ids:
            return set()
        return set(await self.session.scalars(
            select(Component.id).where(
                Component.id.in_(component_ids),
                Component.fact_type.in_(TASK_FACT_TYPES),
            )
        ))


async def complete_verified_execution_task(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    access_scope: AccessScope,
    workflow: dict[str, Any] | None,
) -> dict[str, Any]:
    """Advance one source-backed execution task only after a verified run.

    The runtime calls this after checks pass. The exact source revision and
    actionable lifecycle must still be current; otherwise the transition fails
    closed and leaves task truth untouched.
    """

    execution = (
        workflow.get("execution_task")
        if isinstance(workflow, dict)
        else None
    )
    if not isinstance(execution, dict):
        return {
            "status": "not_applicable",
            "reason": "No modeled execution task was attached to this run.",
        }
    component_id = _uuid_or_none(execution.get("component_id"))
    source_document_id = _uuid_or_none(execution.get("source_document_id"))
    if component_id is None or source_document_id is None:
        return {
            "status": "not_applicable",
            "reason": "The execution task is not source-backed.",
        }

    newer_revision_exists = exists(
        select(SourceDocument.id).where(
            SourceDocument.supersedes_source_document_id == source_document_id
        )
    )
    component = await session.scalar(
        select(Component)
        .join(
            SourceDocument,
            SourceDocument.id == Component.source_document_id,
        )
        .where(
            Component.id == component_id,
            Component.source_document_id == source_document_id,
            Component.fact_type.in_(TASK_FACT_TYPES),
            or_(
                Component.workspace_id == workspace_id,
                Component.workspace_id.is_(None),
            ),
            source_access_predicate(
                access_scope,
                workspace_id=workspace_id,
            ),
            ~newer_revision_exists,
        )
    )
    if component is None:
        return {
            "status": "not_advanced",
            "component_id": str(component_id),
            "reason": (
                "The execution task or its exact source revision is no longer "
                "current and accessible."
            ),
        }

    current_status = _clean_text(component.status or "active", 50).casefold()
    lifecycle = _lifecycle(current_status)
    if lifecycle == "completed":
        return {
            "status": "already_completed",
            "component_id": str(component.id),
            "title": _component_title(component),
            "previous_status": current_status,
        }
    if lifecycle != "active":
        return {
            "status": "not_advanced",
            "component_id": str(component.id),
            "title": _component_title(component),
            "previous_status": current_status,
            "reason": (
                "The execution task changed lifecycle while the agent was "
                "running."
            ),
        }

    component.status = "completed"
    await session.flush()
    return {
        "status": "completed",
        "component_id": str(component.id),
        "title": _component_title(component),
        "previous_status": current_status,
        "new_status": "completed",
    }


def _select_task(
    nodes: dict[UUID, _TaskNode],
    *,
    objective: str,
    component_id: UUID | None,
    fallback: _TaskNode,
) -> tuple[_TaskNode, list[dict[str, Any]]]:
    if component_id is not None:
        selected = nodes.get(component_id)
        if selected is not None:
            return selected, []
        return fallback, [{
            "code": "selected_task_not_accessible",
            "message": (
                "The user-selected task is not available in the caller's current "
                "source-evidence scope."
            ),
            "blocker": None,
            "blocking_tasks": [],
            "affected_tasks": [fallback.to_dict()],
        }]

    ranked = sorted(
        (
            (_objective_match_score(objective, node), node)
            for node in nodes.values()
        ),
        key=lambda item: (-item[0], *_task_sort_key(item[1])),
    )
    if not ranked or ranked[0][0] < 0.78:
        return fallback, []
    best_score = ranked[0][0]
    best = [node for score, node in ranked if abs(score - best_score) < 0.001]
    if len(best) == 1:
        return best[0], []
    affected = _task_dicts(best, limit=MAX_AFFECTED_TASKS)
    return fallback, [{
        "code": "selected_task_ambiguous",
        "message": (
            f'The selected objective "{objective}" matches multiple source-backed '
            "tasks, so automatic execution is unsafe."
        ),
        "blocker": None,
        "blocking_tasks": affected,
        "affected_tasks": affected,
    }]


def _resolve_execution(
    selected_id: UUID,
    *,
    nodes: dict[UUID, _TaskNode],
    prerequisites: dict[UUID, set[UUID]],
    hidden_prerequisites: set[UUID],
) -> dict[str, Any]:
    selected = nodes[selected_id]
    if selected.lifecycle == "completed":
        issue = _lifecycle_issue(
            selected,
            selected,
            code="selected_task_completed",
            message=(
                f'"{selected.title}" is already completed and will not be run again.'
            ),
        )
        return {"execution_id": None, "issues": [issue]}
    if selected.lifecycle != "active":
        issue = _lifecycle_issue(
            selected,
            selected,
            code="selected_task_not_actionable",
            message=(
                f'"{selected.title}" is {selected.status} and cannot be '
                "started automatically."
            ),
        )
        return {"execution_id": None, "issues": [issue]}

    leaves: set[UUID] = set()
    issues: list[dict[str, Any]] = []

    def visit(task_id: UUID, path: list[UUID]) -> None:
        task = nodes[task_id]
        if task.lifecycle == "completed":
            return
        if task.lifecycle != "active":
            affected_ids = [*path, task_id]
            affected = _task_dicts(
                (nodes[item] for item in affected_ids),
                limit=MAX_AFFECTED_TASKS,
            )
            issues.append({
                "code": "dependency_prerequisite_not_actionable",
                "message": (
                    f'"{nodes[path[0]].title}" cannot continue because prerequisite '
                    f'"{task.title}" is {task.status}.'
                ),
                "blocker": task.to_dict(),
                "blocking_tasks": [task.to_dict()],
                "affected_tasks": affected,
            })
            return
        if task_id in hidden_prerequisites:
            affected = _task_dicts(
                (nodes[item] for item in [*path, task_id]),
                limit=MAX_AFFECTED_TASKS,
            )
            issues.append({
                "code": "dependency_prerequisite_not_accessible",
                "message": (
                    f'"{task.title}" has a trusted prerequisite outside the current '
                    "source-evidence scope, so automatic execution is unsafe."
                ),
                "blocker": None,
                "blocking_tasks": [],
                "affected_tasks": affected,
            })
            return
        unfinished = [
            prerequisite
            for prerequisite in prerequisites.get(task_id, set())
            if prerequisite in nodes
            and nodes[prerequisite].lifecycle != "completed"
        ]
        if not unfinished:
            leaves.add(task_id)
            return
        for prerequisite in _sorted_task_ids(set(unfinished), nodes):
            if prerequisite in path or prerequisite == task_id:
                cycle_start = (
                    path.index(prerequisite)
                    if prerequisite in path
                    else len(path)
                )
                cycle_ids = [*path[cycle_start:], task_id, prerequisite]
                cycle_titles = [nodes[item].title for item in cycle_ids]
                affected = _task_dicts(
                    (nodes[item] for item in dict.fromkeys(cycle_ids)),
                    limit=MAX_AFFECTED_TASKS,
                )
                issues.append({
                    "code": "dependency_cycle",
                    "message": (
                        "Dependency cycle prevents safe continuation: "
                        f'{" -> ".join(cycle_titles)}.'
                    ),
                    "blocker": nodes[prerequisite].to_dict(),
                    "blocking_tasks": affected,
                    "affected_tasks": affected,
                })
                continue
            visit(prerequisite, [*path, task_id])

    visit(selected_id, [])
    issues = _dedupe_issues(issues)
    if issues:
        return {"execution_id": None, "issues": issues}
    if len(leaves) == 1:
        return {"execution_id": next(iter(leaves)), "issues": []}
    if len(leaves) > 1:
        blockers = _task_dicts(
            (nodes[item] for item in _sorted_task_ids(leaves, nodes)),
            limit=MAX_AFFECTED_TASKS,
        )
        return {
            "execution_id": None,
            "issues": [{
                "code": "dependency_execution_ambiguous",
                "message": (
                    f'"{selected.title}" has multiple unfinished actionable '
                    "prerequisites and no safe automatic execution order."
                ),
                "blocker": None,
                "blocking_tasks": blockers,
                "affected_tasks": [selected.to_dict(), *blockers][
                    :MAX_AFFECTED_TASKS
                ],
            }],
        }
    return {
        "execution_id": None,
        "issues": [{
            "code": "dependency_execution_unavailable",
            "message": (
                f'No safe executable task could be selected for "{selected.title}".'
            ),
            "blocker": None,
            "blocking_tasks": [],
            "affected_tasks": [selected.to_dict()],
        }],
    }


def _workflow_cluster(
    selected_id: UUID,
    *,
    prerequisites: dict[UUID, set[UUID]],
    dependents: dict[UUID, set[UUID]],
) -> tuple[set[UUID], bool]:
    ancestors: set[UUID] = set()
    queue = [selected_id]
    truncated = False
    while queue:
        current = queue.pop(0)
        if current in ancestors:
            continue
        ancestors.add(current)
        if len(ancestors) >= MAX_GRAPH_TASKS:
            truncated = bool(queue or prerequisites.get(current))
            break
        queue.extend(sorted(prerequisites.get(current, set()), key=str))

    cluster = set(ancestors)
    queue = sorted(ancestors, key=str)
    while queue:
        current = queue.pop(0)
        for dependent in sorted(dependents.get(current, set()), key=str):
            if dependent in cluster:
                continue
            cluster.add(dependent)
            if len(cluster) >= MAX_GRAPH_TASKS:
                return cluster, True
            queue.append(dependent)
    return cluster, truncated


def _with_downstream_affected_tasks(
    issue: dict[str, Any],
    *,
    nodes: dict[UUID, _TaskNode],
    dependents: dict[UUID, set[UUID]],
    selected_id: UUID,
) -> dict[str, Any]:
    blocker = issue.get("blocker")
    blocker_id = _uuid_or_none(
        blocker.get("component_id")
        if isinstance(blocker, dict)
        else None
    )
    if blocker_id is None or blocker_id not in nodes:
        return issue
    affected_ids: set[UUID] = set()
    queue = [blocker_id]
    while queue and len(affected_ids) < MAX_GRAPH_TASKS:
        current = queue.pop(0)
        for dependent in sorted(dependents.get(current, set()), key=str):
            if dependent == blocker_id or dependent in affected_ids:
                continue
            affected_ids.add(dependent)
            queue.append(dependent)
    if not affected_ids and blocker_id == selected_id:
        affected_ids.add(selected_id)
    return {
        **issue,
        "affected_tasks": _task_dicts(
            (
                nodes[item]
                for item in _sorted_task_ids(affected_ids, nodes)
            ),
            limit=MAX_AFFECTED_TASKS,
        ),
    }


def _unfinished_prerequisites(
    task_id: UUID,
    *,
    nodes: dict[UUID, _TaskNode],
    prerequisites: dict[UUID, set[UUID]],
    hidden_prerequisites: set[UUID],
) -> bool:
    if task_id in hidden_prerequisites:
        return True
    return any(
        prerequisite in nodes
        and nodes[prerequisite].lifecycle != "completed"
        for prerequisite in prerequisites.get(task_id, set())
    )


def _dependency_direction(relationship: Relationship) -> tuple[UUID, UUID]:
    if relationship.relationship_type == "blocks":
        return (
            relationship.source_component_id,
            relationship.target_component_id,
        )
    return (
        relationship.target_component_id,
        relationship.source_component_id,
    )


def _task_node(component: Component) -> _TaskNode:
    raw_status = _clean_text(component.status or "active", 50).casefold()
    return _TaskNode(
        component_id=component.id,
        title=_component_title(component),
        objective=_component_objective(component),
        status=raw_status,
        lifecycle=_lifecycle(raw_status),
        fact_type=_clean_text(component.fact_type or "task", 50).casefold(),
        source_document_id=component.source_document_id,
    )


def _component_title(component: Component) -> str:
    name = _clean_text(component.name, 180)
    if _normalized_text(name) not in {
        "",
        "action item",
        "feature",
        "issue",
        "requirement",
        "task",
    }:
        return name
    return _clean_text(component.value or component.name, 180)


def _component_objective(component: Component) -> str:
    return normalize_request_for_matching(
        str(component.value or component.name or "")
    )


def _lifecycle(status: str) -> str:
    if status in COMPLETED_STATUSES:
        return "completed"
    if status in PAUSED_STATUSES:
        return "paused"
    if status in DROPPED_STATUSES:
        return "dropped"
    if status in ACTIONABLE_STATUSES:
        return "active"
    return "unknown"


def _objective_match_score(objective: str, node: _TaskNode) -> float:
    objective_key = _normalized_text(objective)
    candidates = {
        _normalized_text(node.title),
        _normalized_text(node.objective),
    }
    if objective_key in candidates:
        return 1.0
    if any(
        min(len(objective_key), len(candidate)) >= 12
        and (objective_key in candidate or candidate in objective_key)
        for candidate in candidates
        if candidate
    ):
        return 0.9
    objective_tokens = _tokens(objective_key)
    if not objective_tokens:
        return 0.0
    best = 0.0
    for candidate in candidates:
        candidate_tokens = _tokens(candidate)
        if not candidate_tokens:
            continue
        overlap = objective_tokens & candidate_tokens
        coverage = len(overlap) / min(
            len(objective_tokens),
            len(candidate_tokens),
        )
        jaccard = len(overlap) / len(objective_tokens | candidate_tokens)
        best = max(best, 0.65 * coverage + 0.35 * jaccard)
    return best


def _lifecycle_issue(
    selected: _TaskNode,
    blocker: _TaskNode,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "blocker": blocker.to_dict(),
        "blocking_tasks": [blocker.to_dict()],
        "affected_tasks": [selected.to_dict()],
    }


def _workflow_payload(
    *,
    selected: _TaskNode,
    execution: _TaskNode | None,
    now: list[_TaskNode],
    blocked: list[dict[str, Any]],
    next_tasks: list[_TaskNode],
    paused: list[_TaskNode],
    affected: list[_TaskNode],
    blocking_issues: list[dict[str, Any]],
    modeled: bool,
    relationship_count: int,
) -> dict[str, Any]:
    execution_reason = "selected_task"
    if (
        execution is not None
        and selected.component_id != execution.component_id
    ):
        execution_reason = "unfinished_prerequisite"
    elif execution is None:
        execution_reason = "blocked"
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "modeled": modeled,
        "selected_intent": selected.to_dict(),
        "execution_task": execution.to_dict() if execution is not None else None,
        "execution_reason": execution_reason,
        "now": _task_dicts(now, limit=MAX_BUCKET_ITEMS),
        "blocked": blocked[:MAX_BUCKET_ITEMS],
        "next": _task_dicts(next_tasks, limit=MAX_BUCKET_ITEMS),
        "paused": _task_dicts(paused, limit=MAX_BUCKET_ITEMS),
        "affected_tasks": _task_dicts(
            affected,
            limit=MAX_AFFECTED_TASKS,
        ),
        "blocking_issues": blocking_issues,
        "relationship_count": relationship_count,
        "bounds": {
            "bucket_items": MAX_BUCKET_ITEMS,
            "affected_tasks": MAX_AFFECTED_TASKS,
            "graph_tasks": MAX_GRAPH_TASKS,
        },
    }


def _task_dicts(
    nodes: Any,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        result.append(node.to_dict())
        if len(result) >= limit:
            break
    return result


def _sorted_task_ids(
    values: set[UUID],
    nodes: dict[UUID, _TaskNode],
) -> list[UUID]:
    return sorted(values, key=lambda item: _task_sort_key(nodes[item]))


def _task_sort_key(node: _TaskNode) -> tuple[str, str]:
    return node.title.casefold(), node.id


def _dedupe_issues(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (
            str(value.get("code") or ""),
            str(value.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").replace("`", "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in value.split()
        if (len(token) > 1 or token.isdigit())
        and token
        not in {
            "a",
            "an",
            "and",
            "for",
            "in",
            "of",
            "on",
            "the",
            "to",
        }
    }


def _uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None
