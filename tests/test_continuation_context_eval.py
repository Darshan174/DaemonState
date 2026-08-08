from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas.continuation_execution import (
    AtomicRequirement,
    ContinuationExecutionContract,
    ExecutionAuthority,
    FilesystemMode,
    HandoffReconciliation,
    ProjectContextItem,
    ProjectContextKind,
    ProjectContextProvenance,
    ProjectEvidenceLevel,
    ProjectFoundationSection,
    ProjectFoundationSnapshot,
    ReadPlanItem,
    RepositoryContract,
    RepositoryEvidenceItem,
    RepositoryReconciliationState,
    RequirementPriority,
    StructuredHandoff,
    StructuredHandoffItem,
    TaskMode,
    VerificationSpec,
    VerifierType,
    build_authoritative_request,
    compile_request_requirements,
    infer_task_mode,
)
from app.services.continuation_execution import _read_plan
from app.services.execution_prompt_renderer import (
    PROJECT_FOUNDATION_REQUIRED_HEADINGS,
    render_continuation_staging_context,
)
from app.services.repo_indexer import RepoIndexer


LICENSE_SELF_HOST_LEAD = (
    "I want u to update the license of this project, where users can use the "
    "project, self host it, but cannot copy and make product out of it and "
    "make them selfs money. idk anything about license of a project, research "
    "and work on this. also make this project self hostable"
)

# Compact frozen slice of the broken artifact reported by the user. It keeps
# only the features scored below, rather than duplicating the whole prompt.
LEGACY_VISIBLE_SLICE = """\
## Project foundation

> Foundation readiness: **NOT READY** — no durable workspace fact was compiled.

### What the project is, who it serves, what problem it solves, and why it exists
- No current evidence-backed durable fact was compiled.
### Primary workflows and expected behaviour
- No current evidence-backed durable fact was compiled.
### Architecture, boundaries, data flow, storage, APIs, integrations, and authentication
- No current evidence-backed durable fact was compiled.
### Repository map, modules, entry points, and responsibilities
- No current evidence-backed durable fact was compiled.

### First action
Inspect `scripts/self-host-smoke.sh`, `scripts/self-host.sh`, and `tests/test_continuation_execution_contract.py`, then complete and verify R1–R5.

### Task-relevant project context
No current evidence-backed durable workspace facts were compiled. Project Context is not ready.

### Definition of done
- R1 [remaining] — proof: model rubric
- R2 [remaining] — proof: model rubric
- R3 [remaining] — proof: model rubric
- R4 [remaining] — proof: model rubric
- R5 [remaining] — proof: model rubric
"""

LEGACY_REQUIREMENT_TEXTS = (
    "I want u to update the license of this project, where users can use the "
    "project, self host it, but cannot copy",
    "make product out of it",
    "make them selfs money.",
    "idk anything about license of a project, research and work on this.",
    "also make this project self hostable",
)

# Six visible repository-evidence entries were unrelated, followed by a five
# item read plan with three task-relevant paths and two continuation internals.
LEGACY_VISIBLE_PATH_ENTRIES = (
    "tests/test_agents.py",
    "tests/test_agents.py",
    "tests/test_agents.py",
    "tests/test_checkpoints.py",
    "tests/test_checkpoints.py",
    "tests/test_checkpoints.py",
    "scripts/self-host-smoke.sh",
    "scripts/self-host.sh",
    "tests/test_continuation_execution_contract.py",
    "tests/test_project_memory.py",
    "docs/self-hosting.md",
)

EXPECTED_LICENSE_PATHS = {
    "LICENSE",
    "docker-compose.yml",
    "docs/self-hosting.md",
    "scripts/self-host-smoke.sh",
    "scripts/self-host.sh",
}

_EMPTY_FOUNDATION_MARKERS = (
    "No current evidence-backed durable fact was compiled.",
    "No current evidence-backed durable workspace facts were compiled.",
)
_SENSITIVE_PROHIBITED_ACTION_RE = re.compile(
    r"\b(?:copy|commercial(?:ize|ise|ization|isation)?|"
    r"make (?:a )?product|make (?:them\s+selfs|themselves|money)|"
    r"moneti[sz]e|profit)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(?:cannot|can['’]?t|do not|don['’]?t|must not|never|without)\b",
    re.IGNORECASE,
)


def _contract(
    request_text: str,
    *,
    task_mode: TaskMode | None = None,
    project_context: tuple[ProjectContextItem, ...] = (),
    project_foundation: ProjectFoundationSnapshot | None = None,
    repository_evidence: tuple[RepositoryEvidenceItem, ...] = (),
    read_plan: tuple[ReadPlanItem, ...] = (),
    handoff: StructuredHandoff | None = None,
) -> ContinuationExecutionContract:
    mode = task_mode or infer_task_mode(request_text)
    task = build_authoritative_request(request_text)
    source_spans, raw_requirements = compile_request_requirements(
        task,
        task_mode=mode,
    )
    requirements: list[AtomicRequirement] = []
    verification: list[VerificationSpec] = []
    for requirement in raw_requirements:
        if requirement.priority is RequirementPriority.MUST:
            verifier_id = f"VR-{requirement.id}"
            requirement = requirement.model_copy(update={
                "verification_ids": (verifier_id,),
            })
            verification.append(VerificationSpec(
                id=verifier_id,
                verifier_type=VerifierType.MODEL_RUBRIC,
                requirement_ids=(requirement.id,),
                rubric=(
                    "Observe repository or runtime evidence that this exact "
                    f"requirement is satisfied: {requirement.text}"
                ),
            ))
        requirements.append(requirement)

    fingerprint = "b" * 64
    if project_foundation is None:
        project_foundation = ProjectFoundationSnapshot(
            workspace_id=uuid4(),
            repository_fingerprint=fingerprint,
            included_fact_count=len(project_context),
            provisional_fact_count=24 if not project_context else 0,
            superseded_conflicting_fact_count=517 if not project_context else 0,
            source_document_count=len(project_context),
        )
    return ContinuationExecutionContract(
        id=f"eval-{uuid4().hex}",
        context_pack_id=f"pack-{uuid4().hex}",
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
        task_mode=mode,
        task=task,
        execution_focus=request_text,
        source_spans=source_spans,
        requirements=tuple(requirements),
        definition_of_done=tuple(
            item.id
            for item in requirements
            if item.priority is RequirementPriority.MUST
        ),
        repository=RepositoryContract(
            root="/workspace/context-engine",
            branch="main",
            head_commit="a" * 40,
            status_fingerprint=fingerprint,
        ),
        handoff=handoff or StructuredHandoff(),
        project_foundation=project_foundation,
        project_context=project_context,
        repository_evidence=repository_evidence,
        read_plan=read_plan,
        verification=tuple(verification),
        authority=ExecutionAuthority.for_mode(mode),
    )


def _complete_foundation() -> tuple[ProjectContextItem, ...]:
    facts = (
        (
            ProjectFoundationSection.IDENTITY,
            "Product purpose and target users",
            "The product preserves coding-project context across agent sessions.",
        ),
        (
            ProjectFoundationSection.WORKFLOWS,
            "Primary workspace workflow",
            "The workflow compiles workspace evidence before continuation.",
        ),
        (
            ProjectFoundationSection.ARCHITECTURE,
            "Workspace architecture",
            "The architecture uses an API, compiler pipeline, and durable storage.",
        ),
        (
            ProjectFoundationSection.REPOSITORY,
            "Repository module responsibilities",
            "Backend services live in app/services and UI modules in frontend/src.",
        ),
    )
    result: list[ProjectContextItem] = []
    for index, (section, title, statement) in enumerate(facts, start=1):
        result.append(ProjectContextItem(
            id=f"P{index}",
            kind=ProjectContextKind.CONTEXT,
            section=section,
            title=title,
            statement=statement,
            identity_key=f"eval:{section.value}",
            evidence_level=ProjectEvidenceLevel.MECHANICALLY_VERIFIED,
            provenance_refs=(ProjectContextProvenance(
                source_document_id=f"source-{index}",
                evidence_span_id=f"evidence-{index}",
                source_type="local_repository",
                source_content_sha256=f"{index}" * 64,
                evidence_text_sha256=f"{index}" * 64,
            ),),
        ))
    return tuple(result)


def _first_action(markdown: str) -> str:
    marker = "### First action\n"
    if marker not in markdown:
        return ""
    remainder = markdown.split(marker, 1)[1].lstrip()
    boundary = re.search(r"\n#{2,3} ", remainder)
    return remainder[:boundary.start()].strip() if boundary else remainder.strip()


def _blank_placeholder_count(markdown: str) -> int:
    return sum(markdown.count(marker) for marker in _EMPTY_FOUNDATION_MARKERS)


def _opaque_proof_count(markdown: str) -> int:
    return markdown.casefold().count("proof: model rubric")


def _first_action_specificity(markdown: str) -> int:
    action = _first_action(markdown)
    return int(bool(re.search(r"\bR[1-9][0-9]*\s+—\s+\S.{8,}", action)))


def _polarity_inversion_count(
    request_text: str,
    requirement_texts: tuple[str, ...],
) -> int:
    if not _NEGATION_RE.search(request_text):
        return 0
    return sum(
        1
        for text in requirement_texts
        if _SENSITIVE_PROHIBITED_ACTION_RE.search(text)
        and not _NEGATION_RE.search(text)
    )


def _irrelevant_path_rate(
    paths: tuple[str, ...],
    expected_paths: set[str],
) -> float:
    if not paths:
        return 0.0
    return sum(path not in expected_paths for path in paths) / len(paths)


def _metrics(
    markdown: str,
    *,
    request_text: str,
    requirement_texts: tuple[str, ...],
    paths: tuple[str, ...] = (),
    expected_paths: set[str] | None = None,
) -> dict[str, int | float]:
    return {
        "blank_placeholder_count": _blank_placeholder_count(markdown),
        "opaque_proof_count": _opaque_proof_count(markdown),
        "requirement_polarity_inversions": _polarity_inversion_count(
            request_text,
            requirement_texts,
        ),
        "irrelevant_path_rate": round(
            _irrelevant_path_rate(paths, expected_paths or set()),
            3,
        ),
        "first_action_specificity": _first_action_specificity(markdown),
        "output_chars": len(markdown),
    }


def _write_license_fixture_repo(root: Path) -> None:
    (root / ".git").mkdir()
    (root / "scripts").mkdir()
    (root / "docs").mkdir()
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "frontend").mkdir()
    (root / "frontend" / "src").mkdir()
    (root / "LICENSE").write_text("Use and self-host; no commercial resale.\n")
    (root / "docker-compose.yml").write_text(
        "services:\n  api:\n    image: context-engine:local\n"
    )
    (root / "scripts" / "self-host.sh").write_text(
        "#!/bin/sh\ndocker compose up\n"
    )
    (root / "scripts" / "self-host-smoke.sh").write_text(
        "#!/bin/sh\ncurl http://localhost:8000/health\n"
    )
    (root / "docs" / "self-hosting.md").write_text(
        "# Self-hosting\nRun the operator setup script.\n"
    )
    (root / "app" / "clipboard.py").write_text(
        "def copy_context_to_client_host():\n    return True\n"
    )
    (root / "tests" / "test_agents.py").write_text(
        "def test_context_pack_can_scope_to_selected_component():\n"
        "    assert True\n"
    )
    (root / "tests" / "test_checkpoints.py").write_text(
        "def test_copy_ready_checkpoint_uses_client_host():\n"
        "    assert True\n"
    )
    (root / "frontend" / "src" / "CopyButton.jsx").write_text(
        "export function CopyButton() { return null; }\n"
    )


async def _license_repo_projection(
    tmp_path: Path,
) -> tuple[
    tuple[RepositoryEvidenceItem, ...],
    tuple[ReadPlanItem, ...],
    tuple[str, ...],
]:
    _write_license_fixture_repo(tmp_path)
    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    keywords = set(re.findall(r"[a-z0-9]+", LICENSE_SELF_HOST_LEAD.casefold()))
    relevant = tuple(
        item
        for item in frame.relevant_files_for_goal(keywords, [])
        if item.get("reason") != "repo_state_fallback"
    )
    evidence_payload = frame.repository_evidence_for_goal(keywords, [])
    evidence = tuple(
        RepositoryEvidenceItem.model_validate(item)
        for item in evidence_payload["items"]
    )
    read_plan = tuple(ReadPlanItem(
        path=str(item["path"]),
        reason=str(item["why"]),
        symbol=(
            str(item["matched_symbols"][0]["name"])
            if item.get("matched_symbols")
            else None
        ),
        priority=index,
    ) for index, item in enumerate(relevant, start=1))
    evidence_paths: list[str] = []
    for item in evidence:
        for path in (
            item.path,
            item.test_path,
            item.target_path,
            item.manifest_path,
        ):
            if path:
                evidence_paths.append(path)
    return evidence, read_plan, tuple(evidence_paths)


def test_empty_foundation_is_compact_and_fail_closed() -> None:
    contract = _contract("Inspect the current implementation and report gaps.")
    rendered = render_continuation_staging_context(contract)

    assert rendered.startswith("# Project / Workspace Context — NOT READY")
    assert "DO NOT COPY, STAGE, OR USE FOR CONTINUATION" in rendered
    assert _blank_placeholder_count(rendered) == 1
    assert "### Task-relevant project context" not in rendered
    for heading in PROJECT_FOUNDATION_REQUIRED_HEADINGS[1:-1]:
        assert heading not in rendered


def test_complete_foundation_renders_only_populated_sections() -> None:
    foundation = _complete_foundation()
    contract = _contract(
        "Inspect the current implementation and report gaps.",
        project_context=foundation,
    )
    rendered = render_continuation_staging_context(contract)

    assert rendered.startswith(
        "# Project / Workspace Context — project-level foundation"
    )
    assert "Foundation readiness: **CORE COMPLETE**" in rendered
    assert _blank_placeholder_count(rendered) == 0
    for heading in PROJECT_FOUNDATION_REQUIRED_HEADINGS[1:5]:
        assert heading in rendered


async def test_license_self_host_lead_has_relevant_paths_and_specific_actions(
    tmp_path: Path,
) -> None:
    evidence, read_plan, evidence_paths = await _license_repo_projection(tmp_path)
    contract = _contract(
        LICENSE_SELF_HOST_LEAD,
        repository_evidence=evidence,
        read_plan=read_plan,
    )
    rendered = render_continuation_staging_context(contract)
    requirement_texts = tuple(item.text for item in contract.requirements)
    projected_paths = tuple(item.path for item in read_plan) + evidence_paths

    assert set(item.path for item in read_plan) == EXPECTED_LICENSE_PATHS
    assert set(evidence_paths) <= EXPECTED_LICENSE_PATHS
    assert _irrelevant_path_rate(projected_paths, EXPECTED_LICENSE_PATHS) == 0
    assert _polarity_inversion_count(
        LICENSE_SELF_HOST_LEAD,
        requirement_texts,
    ) == 0
    assert _first_action_specificity(rendered) == 1
    assert "proof: model rubric" not in rendered.casefold()
    assert "tests/test_agents.py" not in rendered
    assert "tests/test_checkpoints.py" not in rendered


def test_negated_coordinated_actions_never_become_affirmative_requirements() -> None:
    request = (
        "Update the license so users can self-host, but cannot copy and make a "
        "product from it and make money from it."
    )
    task = build_authoritative_request(request)
    _, requirements = compile_request_requirements(
        task,
        task_mode=TaskMode.CHANGE,
    )
    texts = tuple(item.text for item in requirements)

    assert _polarity_inversion_count(request, texts) == 0
    assert len(texts) == 1
    assert "cannot copy and make a product" in texts[0]
    assert "and make money from it" in texts[0]


def test_generic_task_remains_source_grounded_without_invented_paths() -> None:
    request = "Implement the requested change."
    contract = _contract(request)
    rendered = render_continuation_staging_context(contract)
    action = _first_action(rendered)

    assert _first_action_specificity(rendered) == 1
    assert "R1 — Implement the requested change" in action
    assert "inspect the current checkout" in action.casefold()
    assert "scripts/" not in action
    assert "tests/" not in action


def test_unknown_checkpoint_cannot_override_objective_ranked_read_plan() -> None:
    handoff = StructuredHandoff(
        referenced_files=(StructuredHandoffItem(
            id="legacy-file",
            statement="tests/test_checkpoints.py",
            truth_state="agent_reported",
        ),),
        reconciliation=HandoffReconciliation(
            repository_state=RepositoryReconciliationState.UNKNOWN,
            summary="The checkpoint and current repository could not be matched.",
        ),
    )
    manifest = {
        "affected_code": {"files": [{
            "path": "scripts/self-host.sh",
            "why": "Matched the authoritative current lead.",
            "related_tests": [],
        }]},
        "repo_state": {"relevant_files": [{
            "path": "LICENSE",
            "why": "Matched the authoritative current lead.",
            "reason": "objective_match",
        }]},
        "selected_context": [],
    }

    plan = _read_plan(manifest, handoff)
    paths = tuple(item.path for item in plan)

    assert paths == ("scripts/self-host.sh", "LICENSE")
    assert "tests/test_checkpoints.py" not in paths


def test_read_only_mode_is_explicit_in_authority_and_first_action() -> None:
    request = "Review the continuation prompt only; do not edit product files."
    contract = _contract(request)
    rendered = render_continuation_staging_context(contract)
    action = _first_action(rendered)

    assert contract.task_mode is TaskMode.REVIEW
    assert contract.authority.filesystem_mode is FilesystemMode.READ_ONLY
    assert contract.authority.allow_product_edits is False
    assert "without editing files" in action
    assert _first_action_specificity(rendered) == 1


async def test_quality_delta_against_frozen_regression_baseline(
    tmp_path: Path,
) -> None:
    evidence, read_plan, evidence_paths = await _license_repo_projection(tmp_path)
    contract = _contract(
        LICENSE_SELF_HOST_LEAD,
        repository_evidence=evidence,
        read_plan=read_plan,
    )
    rendered = render_continuation_staging_context(contract)
    current_paths = tuple(item.path for item in read_plan) + evidence_paths
    before = _metrics(
        LEGACY_VISIBLE_SLICE,
        request_text=LICENSE_SELF_HOST_LEAD,
        requirement_texts=LEGACY_REQUIREMENT_TEXTS,
        paths=LEGACY_VISIBLE_PATH_ENTRIES,
        expected_paths=EXPECTED_LICENSE_PATHS,
    )
    after = _metrics(
        rendered,
        request_text=LICENSE_SELF_HOST_LEAD,
        requirement_texts=tuple(item.text for item in contract.requirements),
        paths=current_paths,
        expected_paths=EXPECTED_LICENSE_PATHS,
    )

    assert before["blank_placeholder_count"] == 5
    assert after["blank_placeholder_count"] == 1
    assert before["opaque_proof_count"] == 5
    assert after["opaque_proof_count"] == 0
    assert before["requirement_polarity_inversions"] == 2
    assert after["requirement_polarity_inversions"] == 0
    assert before["irrelevant_path_rate"] == 0.727
    assert after["irrelevant_path_rate"] == 0.0
    assert before["first_action_specificity"] == 0
    assert after["first_action_specificity"] == 1
    assert after["output_chars"] < 5_000
