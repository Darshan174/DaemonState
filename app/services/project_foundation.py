from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, SourceDocument
from app.schemas.continuation_execution import (
    MAX_PROJECT_CONTEXT_ITEMS,
    ProjectContextItem,
    ProjectContextKind,
    ProjectContextProvenance,
    ProjectEvidenceLevel,
    ProjectFoundationSection,
    ProjectFoundationSnapshot,
)
from app.services.memory_trust import (
    assess_memory_trust,
    is_agent_source_type,
    load_component_evidence,
)
from app.services.project_foundation_sections import (
    PROJECT_FOUNDATION_SECTIONS,
    classify_project_foundation_section,
    looks_like_generic_inventory,
)


_DURABLE_FACT_TYPES = frozenset({
    "ai_decision",
    "assumption",
    "constraint",
    "decision",
    "fact",
    "feature",
    "meeting_note",
    "metric",
    "milestone",
    "owner",
    "requirement",
    "risk",
})
_TRANSIENT_FACT_TYPES = frozenset({
    "ai_blocker",
    "ai_step",
    "ai_task",
    "blocker",
    "changed_file",
    "commit_reference",
    "failed_attempt",
    "lesson",
    "open_question",
    "outcome",
    "release",
    "task",
    "test",
    "verification",
})
_PERSISTENT_RISK_RE = re.compile(
    r"\b(?:long[- ]term|persistent|invariant|technical debt|security|"
    r"constraint|must (?:always|never)|unsupported|does not support)\b",
    re.IGNORECASE,
)
_CONVERSATION_DUMP_RE = re.compile(
    r"(?:chatgpt-conversation://|\"role\"\s*:\s*\"(?:user|assistant|system)\"|"
    r"^\s*(?:user|assistant|system)\s*:)",
    re.IGNORECASE | re.MULTILINE,
)
_EVIDENCE_PRIORITY = {
    ProjectEvidenceLevel.MECHANICALLY_VERIFIED: 3,
    ProjectEvidenceLevel.HUMAN_CONFIRMED: 2,
    ProjectEvidenceLevel.CORROBORATED: 1,
}
_MAX_FACTS_PER_SECTION = 4


@dataclass(frozen=True)
class CompiledProjectFoundation:
    snapshot: ProjectFoundationSnapshot
    items: tuple[ProjectContextItem, ...]


@dataclass(frozen=True)
class _Candidate:
    component: Component
    kind: ProjectContextKind
    section: ProjectFoundationSection
    title: str
    statement: str
    identity_key: str
    value_key: str
    evidence_level: ProjectEvidenceLevel
    provenance: tuple[ProjectContextProvenance, ...]
    source_identity: str
    confidence: float


async def compile_workspace_project_foundation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    repository_fingerprint: str | None,
) -> CompiledProjectFoundation:
    """Compile the durable parent from all current workspace evidence.

    This query intentionally has no objective, prompt, file-overlap, focus, or
    selected-session input. Task retrieval remains a separate concern.
    """

    components = list(
        await session.scalars(
            select(Component)
            .options(
                selectinload(Component.source_document),
                selectinload(Component.claim),
            )
            .where(Component.workspace_id == workspace_id)
            .order_by(Component.created_at.desc(), Component.id.desc())
        )
    )
    evidence_by_component = await load_component_evidence(session, components)
    superseded_document_ids = {
        document_id
        for document_id in await session.scalars(
            select(SourceDocument.supersedes_source_document_id)
            .where(SourceDocument.workspace_id == workspace_id)
            .where(SourceDocument.supersedes_source_document_id.is_not(None))
        )
        if document_id is not None
    }

    admitted: list[_Candidate] = []
    corroboration_pool: list[_Candidate] = []
    provisional_count = 0
    superseded_conflicting_count = 0
    for component in components:
        source = component.source_document
        evidence = evidence_by_component.get(component.id)
        source_is_current = bool(
            source is not None and source.id not in superseded_document_ids
        )
        assessment = assess_memory_trust(
            component,
            evidence,
            source=source,
            source_is_current=source_is_current,
            conflict=bool(
                getattr(component.claim, "status", "") == "contested"
            ),
        )
        if (
            not source_is_current
            or assessment.truth_state
            in {
                "contested",
                "stale",
                "superseded",
                "rejected",
                "historical",
            }
            or component.superseded_by_id is not None
        ):
            superseded_conflicting_count += 1
            continue

        candidate = _candidate(
            component,
            source=source,
            evidence=evidence,
            assessment=assessment,
        )
        if candidate is None:
            if _could_be_durable(component):
                provisional_count += 1
            continue
        if candidate.evidence_level in {
            ProjectEvidenceLevel.MECHANICALLY_VERIFIED,
            ProjectEvidenceLevel.HUMAN_CONFIRMED,
        }:
            admitted.append(candidate)
        else:
            corroboration_pool.append(candidate)

    repo_values_by_identity: dict[str, set[str]] = defaultdict(set)
    for candidate in admitted:
        if candidate.evidence_level is ProjectEvidenceLevel.MECHANICALLY_VERIFIED:
            repo_values_by_identity[candidate.identity_key].add(
                candidate.value_key
            )

    grouped_agent: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in corroboration_pool:
        grouped_agent[candidate.identity_key].append(candidate)
    for identity_key, values in grouped_agent.items():
        value_groups: dict[str, list[_Candidate]] = defaultdict(list)
        for candidate in values:
            value_groups[candidate.value_key].append(candidate)
        if len(value_groups) != 1:
            superseded_conflicting_count += len(values)
            continue
        value_key, matches = next(iter(value_groups.items()))
        distinct_sources = {
            candidate.source_identity for candidate in matches
        }
        repo_values = repo_values_by_identity.get(identity_key, set())
        if repo_values and value_key not in repo_values:
            superseded_conflicting_count += len(matches)
            continue
        if len(distinct_sources) < 2:
            provisional_count += len(matches)
            continue
        first = max(matches, key=lambda item: item.confidence)
        provenance = _dedupe_provenance(
            reference
            for candidate in matches
            for reference in candidate.provenance
        )
        admitted.append(_Candidate(
            component=first.component,
            kind=first.kind,
            section=first.section,
            title=first.title,
            statement=first.statement,
            identity_key=first.identity_key,
            value_key=first.value_key,
            evidence_level=ProjectEvidenceLevel.CORROBORATED,
            provenance=provenance,
            source_identity=first.source_identity,
            confidence=first.confidence,
        ))

    selected = _select_balanced(admitted)
    items: list[ProjectContextItem] = []
    for candidate, provenance, corroboration_count in selected:
        items.append(ProjectContextItem(
            id=f"P{len(items) + 1}",
            kind=candidate.kind,
            section=candidate.section,
            title=candidate.title,
            statement=candidate.statement,
            identity_key=candidate.identity_key,
            evidence_level=candidate.evidence_level,
            provenance_refs=provenance,
            corroboration_count=corroboration_count,
        ))

    source_ids = {
        reference.source_document_id
        for item in items
        for reference in item.provenance_refs
    }
    snapshot = ProjectFoundationSnapshot(
        workspace_id=workspace_id,
        repository_fingerprint=repository_fingerprint,
        included_fact_count=len(items),
        provisional_fact_count=provisional_count,
        superseded_conflicting_fact_count=superseded_conflicting_count,
        source_document_count=len(source_ids),
    )
    return CompiledProjectFoundation(snapshot=snapshot, items=tuple(items))


def _candidate(
    component: Component,
    *,
    source: SourceDocument | None,
    evidence: object | None,
    assessment: object,
) -> _Candidate | None:
    if (
        source is None
        or evidence is None
        or not _could_be_durable(component)
        or float(getattr(evidence, "prompt_injection_risk_score", 0.0) or 0.0)
        >= 0.70
    ):
        return None
    title = _single_line(component.name, 240)
    statement = str(component.value or "").strip()[:1_200]
    if (
        not title
        or not statement
        or looks_like_generic_inventory(title, statement)
        or _CONVERSATION_DUMP_RE.search(f"{title}\n{statement}")
    ):
        return None
    kind = _kind_for_component(component)
    section = classify_project_foundation_section(
        kind=kind,
        title=title,
        statement=statement,
    )
    if section is None:
        return None
    if (
        str(component.fact_type or "").casefold() == "risk"
        and not _PERSISTENT_RISK_RE.search(f"{title} {statement}")
    ):
        return None

    evidence_level: ProjectEvidenceLevel
    trust_zone = str(getattr(assessment, "trust_zone", "") or "")
    if (
        getattr(assessment, "current_truth", False)
        and trust_zone in {"trusted_repo", "trusted_system"}
    ):
        evidence_level = ProjectEvidenceLevel.MECHANICALLY_VERIFIED
    elif (
        getattr(assessment, "current_truth", False)
        and trust_zone == "trusted_human"
    ):
        evidence_level = ProjectEvidenceLevel.HUMAN_CONFIRMED
    elif (
        is_agent_source_type(source.source_type)
        and getattr(assessment, "evidence_exact", False)
        and str(component.status or "").casefold() in {"active", "verified"}
    ):
        evidence_level = ProjectEvidenceLevel.PROVISIONAL
    else:
        return None

    identity_key = _identity_key(component, title=title, statement=statement)
    source_identity = (
        f"{source.source_type}:{source.external_id}"
        if source.external_id
        else str(source.id)
    )
    return _Candidate(
        component=component,
        kind=kind,
        section=section,
        title=title,
        statement=statement,
        identity_key=identity_key,
        value_key=_normalized_fact(statement),
        evidence_level=evidence_level,
        provenance=(_provenance(source, evidence),),
        source_identity=source_identity,
        confidence=float(component.confidence or 0.0),
    )


def _could_be_durable(component: Component) -> bool:
    fact_type = str(component.fact_type or "").strip().casefold()
    if fact_type in _TRANSIENT_FACT_TYPES:
        return False
    return fact_type in _DURABLE_FACT_TYPES


def _kind_for_component(component: Component) -> ProjectContextKind:
    fact_type = str(component.fact_type or "").strip().casefold()
    if fact_type in {"decision", "ai_decision"}:
        return ProjectContextKind.DECISION
    if fact_type in {"constraint", "requirement"}:
        return ProjectContextKind.INVARIANT
    if fact_type == "risk":
        return ProjectContextKind.RISK
    return ProjectContextKind.CONTEXT


def _identity_key(
    component: Component,
    *,
    title: str,
    statement: str,
) -> str:
    claim = component.claim
    declared = str(
        getattr(claim, "identity_key", "")
        or component.identity_key
        or ""
    ).strip()
    if declared:
        return declared[:500]
    return (
        f"{component.fact_type}:"
        f"{_normalized_fact(title)}:{_normalized_fact(statement)}"
    )[:500]


def _provenance(
    source: SourceDocument,
    evidence: object,
) -> ProjectContextProvenance:
    content = str(source.content or "")
    source_sha256 = str(source.content_sha256 or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        source_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    evidence_sha256 = str(
        getattr(evidence, "text_sha256", "") or ""
    ).strip().casefold()
    return ProjectContextProvenance(
        source_document_id=str(source.id),
        evidence_span_id=str(getattr(evidence, "id")),
        source_type=str(source.source_type),
        source_revision_number=source.revision_number,
        source_content_sha256=source_sha256,
        evidence_text_sha256=evidence_sha256,
    )


def _select_balanced(
    candidates: Iterable[_Candidate],
) -> list[tuple[_Candidate, tuple[ProjectContextProvenance, ...], int]]:
    grouped_duplicates: dict[
        tuple[ProjectFoundationSection, str, str],
        list[_Candidate],
    ] = defaultdict(list)
    for candidate in candidates:
        grouped_duplicates[
            (candidate.section, candidate.identity_key, candidate.value_key)
        ].append(candidate)

    deduped: list[
        tuple[_Candidate, tuple[ProjectContextProvenance, ...], int]
    ] = []
    for values in grouped_duplicates.values():
        first = max(
            values,
            key=lambda item: (
                _EVIDENCE_PRIORITY[item.evidence_level],
                item.confidence,
            ),
        )
        provenance = _dedupe_provenance(
            reference
            for candidate in values
            for reference in candidate.provenance
        )
        corroboration_count = (
            max(2, len({candidate.source_identity for candidate in values}))
            if first.evidence_level is ProjectEvidenceLevel.CORROBORATED
            else 1
        )
        deduped.append((first, provenance, corroboration_count))

    section_order = {
        section: index
        for index, (section, _title) in enumerate(PROJECT_FOUNDATION_SECTIONS)
    }
    deduped.sort(key=lambda value: (
        section_order[value[0].section],
        -_EVIDENCE_PRIORITY[value[0].evidence_level],
        -value[0].confidence,
        value[0].title.casefold(),
    ))
    counts: dict[ProjectFoundationSection, int] = defaultdict(int)
    result: list[
        tuple[_Candidate, tuple[ProjectContextProvenance, ...], int]
    ] = []
    for value in deduped:
        section = value[0].section
        if counts[section] >= _MAX_FACTS_PER_SECTION:
            continue
        counts[section] += 1
        result.append(value)
        if len(result) >= MAX_PROJECT_CONTEXT_ITEMS:
            break
    return result


def _dedupe_provenance(
    values: Iterable[ProjectContextProvenance],
) -> tuple[ProjectContextProvenance, ...]:
    result: list[ProjectContextProvenance] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value.source_document_id, value.evidence_span_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= 8:
            break
    return tuple(result)


def _normalized_fact(value: str) -> str:
    return " ".join(
        re.sub(r"[^a-z0-9/_.:-]+", " ", value.casefold()).split()
    )[:500]


def _single_line(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]
