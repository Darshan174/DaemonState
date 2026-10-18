from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.models import Component
from app.schemas.continuation_execution import (
    ProjectContextItem,
    ProjectContextKind,
    ProjectContextProvenance,
    ProjectEvidenceLevel,
    ProjectFoundationSection,
    ProjectFoundationSnapshot,
)
from app.schemas.workspace_foundation import (
    RepositoryEngineeringKnowledgeFact,
    RepositoryEngineeringKnowledgeKind,
    WorkspaceFoundationArtifact,
)
from app.services.context_compiler import _workspace_repository_inventory
from app.services.project_foundation import (
    CompiledProjectFoundation,
    _Candidate,
    _normalized_fact,
    _select_balanced,
)
from app.services.project_foundation_sections import PROJECT_FOUNDATION_SECTIONS
from app.services.repo_indexer import RepoIndexer
from app.services.workspace_foundation import compile_workspace_foundation
from app.services.workspace_foundation_renderer import render_workspace_foundation_markdown


def _selection_fact(
    index: int,
    *,
    section: ProjectFoundationSection = ProjectFoundationSection.ARCHITECTURE,
    kind: ProjectContextKind = ProjectContextKind.CONTEXT,
    statement: str | None = None,
) -> _Candidate:
    text = statement or f"Architecture component {index} owns a distinct storage adapter."
    return _Candidate(
        component=Component(),
        kind=kind,
        section=section,
        title=f"Fact {index}",
        statement=text,
        identity_key=f"fact:{index}",
        value_key=_normalized_fact(text),
        evidence_level=ProjectEvidenceLevel.HUMAN_CONFIRMED,
        provenance=(ProjectContextProvenance(
            source_document_id=f"source-{index}",
            evidence_span_id=f"span-{index}",
            source_type="human_note",
            source_revision_number=1,
            source_content_sha256="a" * 64,
            evidence_text_sha256="b" * 64,
        ),),
        source_identity=f"source-{index}",
        confidence=0.95,
    )


def _foundation(candidates: list[_Candidate]) -> CompiledProjectFoundation:
    items = tuple(
        ProjectContextItem(
            id=f"P{index}", kind=fact.kind, section=fact.section,
            title=fact.title, statement=fact.statement,
            identity_key=fact.identity_key, evidence_level=fact.evidence_level,
            provenance_refs=refs, corroboration_count=count,
        )
        for index, (fact, refs, count) in enumerate(_select_balanced(candidates), start=1)
    )
    return CompiledProjectFoundation(
        snapshot=ProjectFoundationSnapshot(
            workspace_id=uuid4(), included_fact_count=len(items),
            source_document_count=len({
                ref.source_document_id for item in items for ref in item.provenance_refs
            }),
        ),
        items=items,
    )


def test_foundation_retains_late_topics_and_multiple_constraints_under_skew() -> None:
    candidates = [
        _selection_fact(index, section=section)
        for index, (section, _title) in enumerate(PROJECT_FOUNDATION_SECTIONS)
    ]
    candidates.extend(_selection_fact(index) for index in range(20, 90))
    constraints = [
        _selection_fact(
            index,
            section=ProjectFoundationSection.CONSTRAINTS,
            kind=ProjectContextKind.RISK,
            statement=f"Persistent risk {index}: offline storage can fill its volume.",
        )
        for index in range(100, 104)
    ]

    selected = _select_balanced([*candidates, *constraints])

    assert {item.section for item, _refs, _count in selected} == {
        section for section, _title in PROJECT_FOUNDATION_SECTIONS
    }
    assert {item.identity_key for item in constraints} <= {
        item.identity_key for item, _refs, _count in selected
    }
    assert len(selected) <= 48


def test_foundation_deduplication_preserves_operators_and_source_references() -> None:
    original = _selection_fact(1, statement="Reject requests when actor != owner.")
    duplicate = replace(
        original,
        provenance=_selection_fact(2).provenance,
        source_identity="source-2",
    )
    opposite_text = "Reject requests when actor = owner."
    opposite = replace(
        original,
        statement=opposite_text,
        value_key=_normalized_fact(opposite_text),
        provenance=_selection_fact(3).provenance,
    )

    selected = _select_balanced([original, duplicate, opposite])

    assert {item.statement for item, _refs, _count in selected} == {
        original.statement, opposite_text,
    }
    original_refs = next(refs for item, refs, _count in selected if item == original)
    assert {ref.source_document_id for ref in original_refs} == {"source-1", "source-2"}
    # Spaces inside a literal are data, not harmless formatting.
    assert _normalized_fact('Store the key "a  b".') != _normalized_fact('Store the key "a b".')


async def test_export_preserves_critical_fact_tail_and_topic_coverage_in_budget(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    candidates = [_selection_fact(index) for index in range(30)]
    restriction = (
        "Tenant records include source identifiers, session identifiers, local paths, "
        "document revisions, and verification evidence. " * 3
        + "Do not transmit tenant records to a remote service without user approval."
    )
    assert 420 < len(restriction) <= 600
    candidates.extend([
        _selection_fact(
            31, section=ProjectFoundationSection.DECISIONS,
            kind=ProjectContextKind.INVARIANT, statement=restriction,
        ),
        _selection_fact(
            32, section=ProjectFoundationSection.CONSTRAINTS,
            kind=ProjectContextKind.RISK,
            statement="Persistent risk: local storage may run out of space.",
        ),
        _selection_fact(
            33, section=ProjectFoundationSection.IDENTITY,
            statement="Product purpose: portable context for the user's next instruction.",
        ),
        _selection_fact(
            34, section=ProjectFoundationSection.WORKFLOWS,
            statement="Workflow: load project context, add a new instruction, continue.",
        ),
    ])
    frame = await RepoIndexer(None).inspect_repo(tmp_path)
    artifact = compile_workspace_foundation(
        frame=frame, inventory=_workspace_repository_inventory(frame),
        durable_foundation=_foundation(candidates),
    )

    rendered = render_workspace_foundation_markdown(artifact)
    durable_section = rendered.split("## Promoted durable workspace knowledge\n", 1)[1]
    durable_section = durable_section.split("\n## ", 1)[0]
    assert restriction in durable_section
    assert "Persistent risk: local storage may run out of space." in durable_section
    assert "Product purpose: portable context" in durable_section
    assert "Workflow: load project context" in durable_section
    assert "Architecture component" in durable_section
    assert "Bounded projection omits" in durable_section
    assert "human confirmed" in durable_section
    assert "Continue only from" not in rendered
    # Budget includes whole rendered fact lines, including citation labels;
    # section headers and the explicit omission notice have a small allowance.
    assert len(durable_section) / 4 < 1_450


async def test_export_keeps_distinct_facets_of_one_identity_and_their_provenance(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    storage = _selection_fact(1, statement="Database storage keeps durable records.")
    cache = replace(
        _selection_fact(2, statement="Cache storage keeps disposable lookup results."),
        identity_key=storage.identity_key,
    )
    corroborating_storage = replace(
        storage, provenance=_selection_fact(3).provenance, source_identity="source-3",
    )
    frame = await RepoIndexer(None).inspect_repo(tmp_path)
    artifact = compile_workspace_foundation(
        frame=frame, inventory=_workspace_repository_inventory(frame),
        durable_foundation=_foundation([storage, cache, corroborating_storage]),
    )

    assert {fact.statement for fact in artifact.durable_facts} == {
        storage.statement, cache.statement,
    }
    assert len({fact.id for fact in artifact.durable_facts}) == 2
    evidence = {ref.id: ref for ref in artifact.evidence_references}
    storage_fact = next(fact for fact in artifact.durable_facts if fact.statement == storage.statement)
    cache_fact = next(fact for fact in artifact.durable_facts if fact.statement == cache.statement)
    assert len(storage_fact.evidence_ref_ids) == 2
    assert len(cache_fact.evidence_ref_ids) == 1
    storage_notes = " ".join(evidence[ref_id].note for ref_id in storage_fact.evidence_ref_ids)
    assert "source_document_id=source-1;" in storage_notes
    assert "source_document_id=source-3;" in storage_notes
    assert "source_document_id=source-2;" in evidence[cache_fact.evidence_ref_ids[0]].note
    rendered = render_workspace_foundation_markdown(artifact)
    assert storage.statement in rendered
    assert cache.statement in rendered


async def test_fact_quotes_preserve_literals_without_promoting_source_headings(tmp_path) -> None:
    statement = (
        'Compute `x**2` using the exact key "a  b".\n'
        '    result = x**2\n\n'
        '## A heading from the source\n'
        'Keep `literal_backticks` and the  repeated spaces.'
    )
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    frame = await RepoIndexer(None).inspect_repo(tmp_path)
    compiled = compile_workspace_foundation(
        frame=frame, inventory=_workspace_repository_inventory(frame),
        durable_foundation=_foundation([_selection_fact(
            1, kind=ProjectContextKind.INVARIANT,
            section=ProjectFoundationSection.DECISIONS, statement=statement,
        )]),
    )
    documentation_ref = next(
        ref for ref in compiled.evidence_references if ref.path == "README.md"
    )
    payload = compiled.model_dump(mode="json")
    payload["repository_engineering_knowledge"] = [RepositoryEngineeringKnowledgeFact(
        id="engineering.literal-statement", kind=RepositoryEngineeringKnowledgeKind.CONVENTION,
        title="Exact literal convention", statement=statement,
        evidence_ref_ids=(documentation_ref.id,),
    ).model_dump(mode="json")]
    artifact = WorkspaceFoundationArtifact.from_payload(payload)

    rendered = render_workspace_foundation_markdown(artifact)

    for heading in (
        "## Promoted durable workspace knowledge",
        "## Repository engineering notes (source-scoped)",
    ):
        section = rendered.split(heading + "\n", 1)[1].split("\n## ", 1)[0]
        quoted_lines = [line[4:] for line in section.splitlines() if line.startswith("  > ")]
        assert quoted_lines == [line for line in statement.splitlines() if line]
        assert "  >\n" in section  # Preserve the source's blank line inside the quote.
        assert "\n## A heading from the source" not in section
        assert "x2" not in section
        assert any(line.startswith("- **") and "[" in line for line in section.splitlines())


async def test_malformed_single_source_corroboration_fails_closed(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    provenance = ProjectContextProvenance(
        source_document_id="source-1",
        evidence_span_id="span-1",
        source_type="agent_session",
        source_revision_number=1,
        source_content_sha256="a" * 64,
        evidence_text_sha256="b" * 64,
    )
    malformed = CompiledProjectFoundation(
        snapshot=ProjectFoundationSnapshot(
            workspace_id=uuid4(),
            repository_fingerprint="f" * 64,
            included_fact_count=1,
            source_document_count=1,
        ),
        items=(
            ProjectContextItem(
                id="P1",
                kind=ProjectContextKind.LEARNING,
                section=ProjectFoundationSection.ARCHITECTURE,
                title="Claimed corroboration",
                statement="A single source must not become corroborated knowledge.",
                identity_key="learning:single-source",
                evidence_level=ProjectEvidenceLevel.CORROBORATED,
                provenance_refs=(provenance,),
                corroboration_count=2,
            ),
        ),
    )
    frame = await RepoIndexer(None).inspect_repo(tmp_path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=malformed,
    )

    assert artifact.durable_knowledge == ()
