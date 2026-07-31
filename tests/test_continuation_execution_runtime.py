from __future__ import annotations

import hashlib
import json
import stat
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

import app.services.local_harness as local_harness
import app.services.runtime_bundle as runtime_bundle
from app.services import continuation_execution
from app.models import (
    AgentRun,
    ContextPack,
    ContinuationExecution,
    ContinuationOutcome,
    ContinuationRequirement,
    Workspace,
)
from app.schemas.continuation_execution import (
    AtomicRequirement,
    ArtifactReference,
    ContinuationExecutionContract,
    ExecutionAuthority,
    HandoffTruthState,
    PreexistingChange,
    ProjectContextItem,
    ProjectContextKind,
    ProjectContextProvenance,
    ProjectEvidenceLevel,
    ProjectFoundationSection,
    ProjectFoundationSnapshot,
    ReadPlanItem,
    RepositoryContract,
    RepositoryEvidenceItem,
    RepositoryEvidenceKind,
    RequestSourceSpan,
    RequiredCapability,
    RequirementPriority,
    SourceSpanKind,
    StructuredHandoff,
    StructuredHandoffItem,
    TaskMode,
    VerificationSpec,
    VerifierType,
    build_authoritative_request,
    sha256_text,
)
from app.services.continuation_quality_gate import evaluate_continuation_quality
from app.services.checkpoints import SESSION_HANDOFF_SCHEMA_VERSION
from app.services.continuation_runtime import (
    ContinuationRunError,
    _contract_outcome,
    _repairable,
    _staging_context_for_preparation,
)
from app.services.execution_prompt_renderer import (
    STAGING_CONTEXT_SCHEMA_VERSION,
    canonical_contract_json,
    execution_prompt_sha256,
    render_continuation_execution_prompt,
    render_continuation_staging_context,
    render_targeted_repair_prompt,
)
from app.services.local_harness import (
    CommandResult,
    LocalHarnessRunner,
    VerificationResult,
    _preservation_passed,
    capture_repository_snapshot,
)
from app.services.requirement_verifier import (
    build_requirement_matrix,
    persist_final_outcome,
    persist_requirement_matrix,
)
from app.services.runtime_bundle import (
    RuntimeBundleIntegrityError,
    materialize_runtime_bundle,
)
from app.time import utc_now


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_worker_projection_version_invalidates_pre_normalization_prompts() -> None:
    assert (
        continuation_execution.WORKER_CONTEXT_PROJECTION_VERSION
        == "worker_context_projection.v7"
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "runtime@example.test")
    _git(root, "config", "user.name", "Runtime Test")
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "initial")
    return root


async def _contract(
    root: Path,
    *,
    verifier_type: VerifierType = VerifierType.UNIT_TEST,
    command_argv: tuple[str, ...] | None = None,
) -> ContinuationExecutionContract:
    request_text = (
        "Update the continuation worker and prove it with the exact runtime test."
    )
    request = build_authoritative_request(request_text)
    verifier_id = "V1"
    requirement = AtomicRequirement(
        id="R1",
        text=request_text,
        priority=RequirementPriority.MUST,
        source_span_ids=("S1",),
        verification_ids=(verifier_id,),
    )
    verifier = VerificationSpec(
        id=verifier_id,
        verifier_type=verifier_type,
        requirement_ids=("R1",),
        command_argv=(
            command_argv
            if command_argv is not None
            else (sys.executable, "-c", "print('verified')")
        ),
        expected_exit_code=0,
        rubric=(
            "Judge independent runtime evidence."
            if verifier_type is VerifierType.MODEL_RUBRIC
            else None
        ),
    )
    snapshot = await capture_repository_snapshot(root)
    return ContinuationExecutionContract(
        id=str(uuid4()),
        context_pack_id=str(uuid4()),
        created_at=utc_now(),
        task_mode=TaskMode.CHANGE,
        task=request,
        source_spans=(
            RequestSourceSpan(
                id="S1",
                start_char=0,
                end_char=len(request_text),
                text=request_text,
                text_sha256=sha256_text(request_text),
                kind=SourceSpanKind.REQUIREMENT,
            ),
        ),
        requirements=(requirement,),
        definition_of_done=("R1",),
        repository=RepositoryContract(
            root=str(root),
            branch=snapshot.branch,
            head_commit=snapshot.head_commit,
            status_fingerprint=snapshot.status_fingerprint,
            status_truncated=False,
        ),
        project_foundation=ProjectFoundationSnapshot(
            workspace_id=uuid4(),
            repository_fingerprint=snapshot.status_fingerprint,
            included_fact_count=4,
            source_document_count=4,
        ),
        project_context=_complete_project_foundation(),
        verification=(verifier,),
        required_capabilities=(
            RequiredCapability.COMMAND_EXECUTION,
            RequiredCapability.FILE_CONTEXT,
            RequiredCapability.FILESYSTEM_WRITE,
        ),
        authority=ExecutionAuthority.for_mode(TaskMode.CHANGE),
    )


def _complete_project_foundation() -> tuple[ProjectContextItem, ...]:
    values = (
        (
            ProjectFoundationSection.IDENTITY,
            "Product purpose and target users",
            "The product purpose is to preserve coding context for software teams.",
        ),
        (
            ProjectFoundationSection.WORKFLOWS,
            "Primary workflow",
            "The primary workflow compiles evidence before continuing agent work.",
        ),
        (
            ProjectFoundationSection.ARCHITECTURE,
            "Runtime architecture",
            "The architecture uses an API, compiler pipeline, and durable storage.",
        ),
        (
            ProjectFoundationSection.REPOSITORY,
            "Repository responsibilities",
            "The repository map places runtime services in app/services.",
        ),
    )
    result = []
    for index, (section, title, statement) in enumerate(values, start=1):
        result.append(ProjectContextItem(
            id=f"P{index}",
            kind=ProjectContextKind.CONTEXT,
            section=section,
            title=title,
            statement=statement,
            identity_key=f"runtime-fixture:{section.value}",
            evidence_level=ProjectEvidenceLevel.MECHANICALLY_VERIFIED,
            provenance_refs=(ProjectContextProvenance(
                source_document_id=f"source-{index}",
                evidence_span_id=f"evidence-{index}",
                source_type="local_repository",
                source_revision_number=1,
                source_content_sha256=f"{index}" * 64,
                evidence_text_sha256=f"{index}" * 64,
            ),),
        ))
    return tuple(result)


def _verification_result(*, exit_code: int = 0) -> VerificationResult:
    command = CommandResult(
        argv=("python", "-c", "print('verified')"),
        exit_code=exit_code,
        stdout="verified\n" if exit_code == 0 else "",
        stderr="" if exit_code == 0 else "failed",
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=False,
        duration_ms=1,
    )
    return VerificationResult(
        requirement_id="R1",
        verifier_id="V1",
        requirement_ids=("R1",),
        verifier_type=VerifierType.UNIT_TEST.value,
        command="python -c 'print(verified)'",
        cwd=".",
        result=command,
    )


@pytest.mark.asyncio
async def test_staging_context_is_a_compact_truth_capsule(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    reference = tmp_path / "reference.png"
    reference_bytes = b"\x89PNG\r\n\x1a\nruntime-reference"
    reference.write_bytes(reference_bytes)
    artifact = ArtifactReference(
        id="A1",
        kind="screenshot",
        path=str(reference),
        sha256=hashlib.sha256(reference_bytes).hexdigest(),
        available=True,
        required=True,
        requirement_ids=("R1",),
    )
    requirement = contract.requirements[0].model_copy(
        update={"source_artifact_ids": ("A1",)}
    )
    contract = contract.model_copy(
        update={
            "requirements": (requirement,),
            "artifacts": (artifact,),
        }
    )

    staged = render_continuation_staging_context(contract)

    assert "## Context" in staged
    assert "## Direction" in staged
    assert "## Execution loop" not in staged
    assert "Inspect → implement → test → fix → verify" not in staged
    assert contract.task.request_verbatim in staged
    assert "### Authoritative current lead" in staged
    assert "### First action" in staged
    assert "### Reconciliation and unresolved state" in staged
    assert staged.count("Activation boundary:") == 1
    assert "Retrieval boundary:" not in staged
    assert "R1 [remaining]" in staged
    assert "preserve regardless of authorship" in staged
    assert "user-owned" not in staged
    assert "### Current repository evidence" not in staged
    assert "Complete the immediate task" not in staged
    assert "DAEMONSTATE_EXECUTION_BUNDLE_PATH" not in staged
    assert str(reference) in staged
    assert artifact.sha256 in staged
    assert "Runtime bundle delivery" not in staged
    assert "Portable bundle-relative locator (not yet materialized)" in staged
    assert "attachments/01-A1.png" in staged

    executable = render_continuation_execution_prompt(contract)
    assert executable.startswith("Complete the immediate task")
    assert "DAEMONSTATE_EXECUTION_BUNDLE_PATH" in executable
    assert "DAEMONSTATE_EXECUTION_CONTRACT_PATH" in executable
    assert "attachments/01-A1.png" in executable
    assert executable != staged


@pytest.mark.asyncio
async def test_visible_desktop_stage_allows_only_incomplete_core_advisory(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    rendered = render_continuation_staging_context(contract)
    base_context = {
        "schema_version": STAGING_CONTEXT_SCHEMA_VERSION,
        "scope": "project",
        "copy_ready": False,
        "content": rendered,
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }
    session_content = (
        "# Session Context — task-level working memory\n\n"
        f"## Current main goal\n\n{contract.task.request_verbatim}\n"
    )
    session_context = {
        "schema_version": SESSION_HANDOFF_SCHEMA_VERSION,
        "scope": "session",
        "provider": "codex",
        "session_id": "latest-session",
        "content": session_content,
        "sha256": hashlib.sha256(session_content.encode("utf-8")).hexdigest(),
        "current_goal": {"request_sha256": contract.task.request_sha256},
        "quality_report": {
            "copy_ready": True,
            "blocking_issues": [],
        },
    }
    preparation = SimpleNamespace(
        project_context={
            **base_context,
            "quality_issues": [{
                "code": "project_context_core_sections_empty",
                "message": "Project Context core sections are incomplete.",
                "blocks_copy": True,
            }],
        },
        source_session={
            "provider": "codex",
            "session_id": "latest-session",
        },
    )

    staged_session = _staging_context_for_preparation(
        preparation,
        contract=contract,
        expected_lead=contract.task.request_verbatim,
        session_context=session_context,
    )
    assert staged_session == session_content
    assert staged_session.startswith(
        "# Session Context — task-level working memory\n"
    )

    for code in (
        "project_context_foundation_stale",
        "project_context_fact_provenance_missing",
        "project_context_unresolved_fact_conflict",
    ):
        blocked = SimpleNamespace(
            project_context={
                **base_context,
                "quality_issues": [{
                    "code": code,
                    "message": f"Blocking issue: {code}.",
                    "blocks_copy": True,
                }],
            },
            source_session=preparation.source_session,
        )
        with pytest.raises(ContinuationRunError) as exc_info:
            _staging_context_for_preparation(
                blocked,
                contract=contract,
                expected_lead=contract.task.request_verbatim,
                session_context=session_context,
            )
        assert exc_info.value.code == "project_context_staging_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handoff", "expected_status", "expected_action"),
    (
        (
            StructuredHandoff(
                completed=(
                    StructuredHandoffItem(
                        id="completed-1",
                        statement=(
                            "Updated the continuation worker and proved it with "
                            "the exact runtime test."
                        ),
                        truth_state=HandoffTruthState.AGENT_REPORTED,
                    ),
                ),
            ),
            "reported-complete",
            "Verify R1",
        ),
        (
            StructuredHandoff(
                completed=(
                    StructuredHandoffItem(
                        id="completed-unrelated",
                        statement="Implemented the billing banner.",
                        truth_state=HandoffTruthState.AGENT_REPORTED,
                    ),
                ),
            ),
            "remaining",
            "complete and verify R1",
        ),
        (
            StructuredHandoff(
                completed=(
                    StructuredHandoffItem(
                        id="completed-question",
                        statement="What works for the continuation worker?",
                        truth_state=HandoffTruthState.AGENT_REPORTED,
                    ),
                ),
            ),
            "remaining",
            "complete and verify R1",
        ),
        (
            StructuredHandoff(
                completed=(
                    StructuredHandoffItem(
                        id="completed-2",
                        statement=(
                            "Updated the continuation worker and proved it with "
                            "the exact runtime test."
                        ),
                        truth_state=HandoffTruthState.AGENT_REPORTED,
                    ),
                ),
                remaining=(
                    StructuredHandoffItem(
                        id="remaining-1",
                        statement=(
                            "The continuation worker still needs the exact "
                            "runtime test."
                        ),
                        truth_state=HandoffTruthState.AGENT_REPORTED,
                    ),
                ),
            ),
            "conflicted",
            "Reconcile R1",
        ),
    ),
)
async def test_staging_context_derives_only_scoped_requirement_status(
    tmp_path,
    handoff: StructuredHandoff,
    expected_status: str,
    expected_action: str,
) -> None:
    contract = (await _contract(_repository(tmp_path))).model_copy(
        update={"handoff": handoff}
    )

    staged = render_continuation_staging_context(contract)

    assert f"R1 [{expected_status}]" in staged
    assert expected_action in staged


@pytest.mark.asyncio
async def test_staging_context_ignores_generic_carried_next_action_per_requirement(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    removal = contract.requirements[0].model_copy(update={
        "text": (
            "Remove Session Evidence and Compilation at Load from Continue."
        ),
    })
    telemetry = AtomicRequirement(
        id="R2",
        text="Explain how OpenTelemetry can help this project.",
        priority=RequirementPriority.MUST,
        source_span_ids=("S1",),
        verification_ids=("V1",),
    )
    handoff = StructuredHandoff(
        completed=(
            StructuredHandoffItem(
                id="completed-removal",
                statement=(
                    "Removed Session Evidence, Session Trace, Truth Summary, "
                    "and Compilation at Load from Continue."
                ),
                truth_state=HandoffTruthState.AGENT_REPORTED,
            ),
        ),
        remaining=(
            StructuredHandoffItem(
                id="generic-next-action",
                statement=(
                    "Continue the current request: Remove Session Evidence and "
                    "Compilation at Load from Continue. Explain how "
                    "OpenTelemetry can help this project."
                ),
                truth_state=HandoffTruthState.AGENT_REPORTED,
            ),
        ),
    )
    contract = contract.model_copy(update={
        "requirements": (removal, telemetry),
        "definition_of_done": ("R1", "R2"),
        "handoff": handoff,
    })

    staged = render_continuation_staging_context(contract)

    assert "R1 [reported-complete]" in staged
    assert "R2 [remaining]" in staged
    assert "R1 [conflicted]" not in staged
    assert "Verify R1" in staged
    assert "complete and verify R2" in staged
    assert "### Prior-agent scope interpretation" in staged
    assert (
        "R1 [unverified historical data]: Removed Session Evidence, Session "
        "Trace, Truth Summary, and Compilation at Load from Continue."
    ) in staged


@pytest.mark.asyncio
async def test_staging_context_separates_current_facts_and_repository_evidence(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    repository = contract.repository.model_copy(update={
        "preexisting_changes": (
            PreexistingChange(status="modified", path="README.md", xy=" M"),
            PreexistingChange(status="untracked", path="notes.txt", xy="??"),
        ),
    })
    contract = contract.model_copy(update={
        "repository": repository,
        "project_context": (
                ProjectContextItem(
                    id="P1",
                    kind=ProjectContextKind.INVARIANT,
                    section=ProjectFoundationSection.DECISIONS,
                    title="Runtime boundary",
                    statement="Workers consume the hash-bound execution contract.",
                    identity_key="runtime:hash-bound-contract",
                    evidence_level=(
                        ProjectEvidenceLevel.MECHANICALLY_VERIFIED
                    ),
                    provenance_refs=(ProjectContextProvenance(
                        source_document_id="source-runtime-boundary",
                        evidence_span_id="evidence-runtime-boundary",
                        source_type="local_repository",
                        source_revision_number=1,
                        source_content_sha256="a" * 64,
                        evidence_text_sha256="b" * 64,
                    ),),
                ),
        ),
        "repository_evidence": (
            RepositoryEvidenceItem(
                id="RE1",
                kind=RepositoryEvidenceKind.SYMBOL_DECLARATION,
                path="app/services/worker.py",
                file_sha256="a" * 64,
                symbol_type="function",
                symbol_name="run_worker",
                start_line=10,
                end_line=20,
            ),
        ),
        "read_plan": tuple(
            ReadPlanItem(
                path=f"app/path_{index}.py",
                reason=f"Inspect item {index}.",
            )
            for index in range(1, 11)
        ),
    })

    staged = render_continuation_staging_context(contract)
    executable = render_continuation_execution_prompt(contract)

    assert "2 pre-existing changes; preserve regardless of authorship" in staged
    assert (
        "> [invariant; mechanically-verified; current] Runtime boundary — "
        "Workers consume the hash-bound execution contract."
    ) in staged
    assert "### Current repository evidence" in staged
    assert "## Current repository evidence" in executable
    assert (
        "Symbol: `app/services/worker.py`:10-20 — function `run_worker`."
        in staged
    )
    assert (
        "Symbol: `app/services/worker.py`:10-20 — function `run_worker`."
        in executable
    )
    assert "source sha256" in staged
    assert "evidence sha256" in staged
    assert "source-runtime-boundary" not in staged
    assert "evidence-runtime-boundary" not in staged
    assert "source sha256" in executable
    assert "5. `app/path_5.py`" in staged
    assert "6. `app/path_6.py`" not in staged
    assert "5 additional read-plan items remain in the contract." in staged


@pytest.mark.asyncio
async def test_execution_prompt_omits_absent_read_plan_symbols(tmp_path) -> None:
    contract = await _contract(_repository(tmp_path))
    contract = contract.model_copy(update={
        "read_plan": (
            ReadPlanItem(
                path="README.md",
                symbol=None,
                reason="Inspect the repository overview.",
            ),
        ),
    })

    prompt = render_continuation_execution_prompt(contract)

    assert (
        "1. `README.md` — Inspect the repository overview."
        in prompt
    )
    assert "`README.md` — None —" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verifier_type",
    (VerifierType.MODEL_RUBRIC, VerifierType.HUMAN_REVIEW),
)
async def test_quality_gate_blocks_automatic_run_without_executable_proof(
    tmp_path,
    verifier_type: VerifierType,
) -> None:
    root = _repository(tmp_path)
    runnable = await _contract(root)
    prompt = render_continuation_execution_prompt(runnable)

    report = evaluate_continuation_quality(
        runnable,
        prompt_markdown=prompt,
        provider="codex",
        expected_contract_sha256=sha256_text(
            canonical_contract_json(runnable)
        ),
        expected_prompt_sha256=execution_prompt_sha256(prompt),
    )

    assert report.launchable is True
    assert report.issues == ()

    unverifiable = await _contract(
        root,
        verifier_type=verifier_type,
        command_argv=(),
    )
    blocked = evaluate_continuation_quality(
        unverifiable,
        prompt_markdown=render_continuation_execution_prompt(unverifiable),
        provider="codex",
    )

    assert blocked.launchable is False
    assert blocked.automatic_execution_ready is False
    assert blocked.to_dict()["automatic_execution_ready"] is False
    issues = {issue.code: issue for issue in blocked.issues}
    assert issues.keys() >= {
        "mandatory_requirement_verification_unexecutable",
        "verifier_executor_unavailable",
        "verifier_command_missing",
    }
    assert (
        issues["mandatory_requirement_verification_unexecutable"].severity
        == "blocking"
    )
    assert issues["verifier_executor_unavailable"].severity == "warning"
    assert issues["verifier_command_missing"].severity == "warning"


@pytest.mark.asyncio
async def test_quality_gate_allows_required_executable_proof_alongside_rubric(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    rubric = VerificationSpec(
        id="V2",
        verifier_type=VerifierType.MODEL_RUBRIC,
        requirement_ids=("R1",),
        command_argv=(),
        rubric="Judge the resulting user-visible behavior.",
    )
    mixed = contract.model_copy(update={
        "requirements": (
            contract.requirements[0].model_copy(
                update={"verification_ids": ("V1", "V2")},
            ),
        ),
        "verification": (*contract.verification, rubric),
    })

    report = evaluate_continuation_quality(
        mixed,
        prompt_markdown=render_continuation_execution_prompt(mixed),
        provider="codex",
    )

    assert report.launchable is True
    assert "mandatory_requirement_verification_unexecutable" not in {
        issue.code for issue in report.issues
    }
    assert {
        issue.code for issue in report.issues
    } >= {"verifier_executor_unavailable", "verifier_command_missing"}


@pytest.mark.asyncio
async def test_requirement_matrix_never_treats_missing_or_failed_proof_as_verified(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))

    missing = build_requirement_matrix(
        contract,
        (),
        worker_succeeded=True,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )
    failed = build_requirement_matrix(
        contract,
        (_verification_result(exit_code=1),),
        worker_succeeded=True,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )
    passed = build_requirement_matrix(
        contract,
        (_verification_result(),),
        worker_succeeded=True,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )

    assert missing.status == "requirements_unproven"
    assert missing.mandatory_unproven == 1
    assert failed.status == "requirements_unproven"
    assert failed.mandatory_failed == 1
    assert passed.status == "verified_complete"
    assert passed.verified is True


@pytest.mark.asyncio
async def test_command_backed_browser_verifier_can_produce_observed_proof(
    tmp_path,
) -> None:
    contract = await _contract(
        _repository(tmp_path),
        verifier_type=VerifierType.BROWSER_ASSERTION,
        command_argv=(sys.executable, "-c", "print('browser assertion passed')"),
    )
    report = evaluate_continuation_quality(
        contract,
        prompt_markdown=render_continuation_execution_prompt(contract),
        provider="codex",
    )
    result = _verification_result(exit_code=0)
    result = VerificationResult(
        requirement_id=result.requirement_id,
        verifier_id=result.verifier_id,
        requirement_ids=result.requirement_ids,
        verifier_type=VerifierType.BROWSER_ASSERTION.value,
        command=result.command,
        cwd=result.cwd,
        result=result.result,
    )
    matrix = build_requirement_matrix(
        contract,
        [result],
        worker_succeeded=True,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )

    assert report.launchable is True
    assert report.issues == ()
    assert matrix.status == "verified_complete"
    assert matrix.verified is True


@pytest.mark.asyncio
async def test_repair_prompt_targets_observed_failure_and_requires_safe_resume(
    tmp_path,
) -> None:
    contract = await _contract(_repository(tmp_path))
    failed = build_requirement_matrix(
        contract,
        (_verification_result(exit_code=1),),
        worker_succeeded=True,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )
    canonical = render_continuation_execution_prompt(contract)
    repair = render_targeted_repair_prompt(
        contract,
        canonical_prompt=canonical,
        verification_matrix=failed,
        attempt_index=2,
        current_status_fingerprint="f" * 64,
    )

    assert repair.startswith(canonical)
    assert "repair attempt 1 of 2" in repair
    assert "- R1: failed" in repair
    assert "V1: failed, exit 1" in repair
    assert f"Current repository fingerprint: `{'f' * 64}`" in repair
    assert _repairable(
        contract,
        matrix=failed,
        result=SimpleNamespace(status="completed"),
        session_id=str(uuid4()),
    )
    assert not _repairable(
        contract,
        matrix=failed,
        result=SimpleNamespace(status="completed"),
        session_id="",
    )


@pytest.mark.asyncio
async def test_preservation_allows_additive_work_but_rejects_baseline_reversion(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text(
        "initial\nuser-owned baseline edit\n",
        encoding="utf-8",
    )
    baseline = await capture_repository_snapshot(root)
    contract = await _contract(root)

    tracked.write_text(
        "initial\nuser-owned baseline edit\nagent additive edit\n",
        encoding="utf-8",
    )
    additive = await capture_repository_snapshot(root)

    assert await _preservation_passed(
        contract,
        before=baseline,
        after=additive,
    )

    tracked.write_text(
        "initial\nagent additive edit\n",
        encoding="utf-8",
    )
    reverted = await capture_repository_snapshot(root)

    assert not await _preservation_passed(
        contract,
        before=baseline,
        after=reverted,
    )


@pytest.mark.asyncio
async def test_large_dirty_file_uses_complete_digest_baseline(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text(
        "initial\n" + ("user-owned baseline edit\n" * 16),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_harness,
        "MAX_PRESERVATION_FILE_BYTES",
        64,
    )

    baseline = await capture_repository_snapshot(root)
    contract = await _contract(root)
    prompt = render_continuation_execution_prompt(contract)

    assert baseline.status_truncated is False
    assert baseline._preservation_complete is True
    assert baseline._preservation_files[0].baseline_sha256 is not None
    assert evaluate_continuation_quality(
        contract,
        prompt_markdown=prompt,
    ).launchable is True

    unchanged = await capture_repository_snapshot(root)
    assert await _preservation_passed(
        contract,
        before=baseline,
        after=unchanged,
    )

    tracked.write_text(
        tracked.read_text(encoding="utf-8") + "agent edit\n",
        encoding="utf-8",
    )
    changed = await capture_repository_snapshot(root)
    assert not await _preservation_passed(
        contract,
        before=baseline,
        after=changed,
    )


@pytest.mark.asyncio
async def test_total_baseline_budget_falls_back_to_complete_digest_proof(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text(
        "initial\nuser-owned baseline edit\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_harness,
        "MAX_PRESERVATION_TOTAL_BYTES",
        1,
    )

    snapshot = await capture_repository_snapshot(root)

    assert snapshot.status_truncated is False
    assert snapshot._preservation_complete is True
    assert snapshot._preservation_files[0].baseline_sha256 is not None


@pytest.mark.asyncio
async def test_status_fingerprint_covers_tail_beyond_bounded_status_hash(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text("A" * 64, encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "add larger tracked file")
    monkeypatch.setattr(local_harness, "MAX_HASHED_FILE_BYTES", 8)

    tracked.write_text(("A" * 56) + "USEREDIT", encoding="utf-8")
    before = await capture_repository_snapshot(root)
    tracked.write_text(("A" * 56) + "USEREDIX", encoding="utf-8")
    after = await capture_repository_snapshot(root)

    assert before.changed_files == after.changed_files
    assert before.status_fingerprint != after.status_fingerprint


@pytest.mark.asyncio
async def test_sensitive_named_change_uses_hash_only_preservation_proof(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    example = root / ".env.example"
    example.write_text("EXAMPLE_TOKEN=placeholder\n", encoding="utf-8")
    _git(root, "add", ".env.example")
    _git(root, "commit", "-q", "-m", "add environment template")
    example.write_text(
        "EXAMPLE_TOKEN=placeholder\nFEATURE_FLAG=true\n",
        encoding="utf-8",
    )

    baseline = await capture_repository_snapshot(root)
    contract = await _contract(root)

    assert baseline.status_truncated is False
    assert baseline.changed_files == (".env.example",)
    proof = baseline._preservation_files[0]
    assert proof.baseline_content is None
    assert proof.baseline_sha256 is not None

    unchanged = await capture_repository_snapshot(root)
    assert await _preservation_passed(
        contract,
        before=baseline,
        after=unchanged,
    )

    example.write_text(
        "EXAMPLE_TOKEN=placeholder\nFEATURE_FLAG=false\n",
        encoding="utf-8",
    )
    changed = await capture_repository_snapshot(root)
    assert not await _preservation_passed(
        contract,
        before=baseline,
        after=changed,
    )


@pytest.mark.asyncio
async def test_sensitive_staged_deletion_with_worktree_copy_is_preserved(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    sensitive = root / ".env"
    sensitive.write_text("TOKEN=user-owned\n", encoding="utf-8")
    _git(root, "add", ".env")
    _git(root, "commit", "-q", "-m", "add sensitive file")
    _git(root, "rm", "--cached", ".env")

    baseline = await capture_repository_snapshot(root)
    contract = await _contract(root)
    unchanged = await capture_repository_snapshot(root)

    assert baseline.status_truncated is False
    assert baseline._preservation_complete is True
    sensitive_proofs = [
        proof
        for proof in baseline._preservation_files
        if proof.path == ".env"
    ]
    assert sensitive_proofs
    assert all(proof.baseline_sha256 is not None for proof in sensitive_proofs)
    assert await _preservation_passed(
        contract,
        before=baseline,
        after=unchanged,
    )


@pytest.mark.asyncio
async def test_renamed_dirty_file_has_a_complete_preservation_baseline(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    _git(root, "mv", "README.md", "RENAMED.md")

    snapshot = await capture_repository_snapshot(root)
    contract = await _contract(root)

    assert snapshot.status_truncated is False
    assert snapshot._preservation_complete is True
    assert set(snapshot.changed_files) == {"README.md", "RENAMED.md"}
    assert evaluate_continuation_quality(
        contract,
        prompt_markdown=render_continuation_execution_prompt(contract),
    ).launchable is True


@pytest.mark.asyncio
async def test_repository_snapshot_preserves_deleted_porcelain_status(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    (root / "README.md").unlink()

    snapshot = await capture_repository_snapshot(root)
    entry = snapshot.to_dict()["changed_file_entries"][0]

    assert entry["path"] == "README.md"
    assert entry["status"] == " D"
    assert entry["xy"] == " D"
    assert entry["change_kind"] == "deleted"
    assert entry["sha256"] is None


@pytest.mark.asyncio
async def test_repository_snapshot_retries_a_transient_incomplete_baseline(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    (root / "README.md").write_text(
        "initial\nuser-owned baseline edit\n",
        encoding="utf-8",
    )
    complete = await local_harness._repository_snapshot(root)
    incomplete = replace(
        complete,
        status_truncated=True,
        _preservation_complete=False,
    )
    snapshots = iter((incomplete, complete))
    calls = 0

    async def flaky_snapshot(_root):
        nonlocal calls
        calls += 1
        return next(snapshots)

    monkeypatch.setattr(
        local_harness,
        "_repository_snapshot",
        flaky_snapshot,
    )

    observed = await capture_repository_snapshot(root)

    assert calls == 2
    assert observed.status_truncated is False
    assert observed._preservation_complete is True


@pytest.mark.asyncio
async def test_repository_snapshot_rechecks_status_after_proof_capture(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    real_capture = local_harness._capture_preservation_baseline
    captures = 0

    async def capture_then_mutate(*args, **kwargs):
        nonlocal captures
        captures += 1
        result = await real_capture(*args, **kwargs)
        if captures == 1:
            tracked.write_text(
                "initial\nuser edit during snapshot\n",
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(
        local_harness,
        "_capture_preservation_baseline",
        capture_then_mutate,
    )

    observed = await capture_repository_snapshot(root)

    assert captures == 2
    assert observed.status_truncated is False
    assert observed.changed_files == ("README.md",)
    assert observed._preservation_files[0].baseline_content == (
        b"initial\nuser edit during snapshot\n"
    )


@pytest.mark.asyncio
async def test_repository_snapshot_rechecks_branch_and_fingerprints_it(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    original = await capture_repository_snapshot(root)
    _git(root, "branch", "alternate")
    real_capture = local_harness._capture_preservation_baseline
    captures = 0

    async def capture_then_switch_branch(*args, **kwargs):
        nonlocal captures
        captures += 1
        result = await real_capture(*args, **kwargs)
        if captures == 1:
            _git(root, "switch", "-q", "alternate")
        return result

    monkeypatch.setattr(
        local_harness,
        "_capture_preservation_baseline",
        capture_then_switch_branch,
    )

    observed = await capture_repository_snapshot(root)

    assert captures == 2
    assert observed.status_truncated is False
    assert observed.branch == "alternate"
    assert observed.head_commit == original.head_commit
    assert observed.status_fingerprint != original.status_fingerprint


@pytest.mark.asyncio
async def test_preservation_rejects_same_commit_branch_switch(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    _git(root, "branch", "alternate")
    before = await capture_repository_snapshot(root)
    contract = await _contract(root)
    _git(root, "switch", "-q", "alternate")
    after = await capture_repository_snapshot(root)

    assert before.head_commit == after.head_commit
    assert before.branch != after.branch
    assert not await _preservation_passed(
        contract,
        before=before,
        after=after,
    )


@pytest.mark.asyncio
async def test_failed_git_status_is_never_reported_as_clean(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    real_git = local_harness._git
    status_calls = 0

    async def failed_status(snapshot_root, *args, limit):
        nonlocal status_calls
        if args and args[0] == "status":
            status_calls += 1
            return CommandResult(
                argv=("git", "status"),
                exit_code=128,
                stdout="",
                stderr="fatal: cannot read index",
                stdout_truncated=False,
                stderr_truncated=False,
                timed_out=False,
                duration_ms=1,
            )
        return await real_git(snapshot_root, *args, limit=limit)

    monkeypatch.setattr(local_harness, "_git", failed_status)

    observed = await capture_repository_snapshot(root)

    assert status_calls == 2
    assert observed.status_truncated is True
    assert observed.dirty is True


@pytest.mark.asyncio
async def test_modified_file_disappearing_mid_capture_is_retried_not_deleted(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text(
        "initial\nuser-owned baseline edit\n",
        encoding="utf-8",
    )
    real_read = local_harness._read_preservation_file
    reads = 0

    def transient_missing(path):
        nonlocal reads
        if path.name == "README.md":
            reads += 1
            if reads == 1:
                return None, None, False
        return real_read(path)

    monkeypatch.setattr(
        local_harness,
        "_read_preservation_file",
        transient_missing,
    )

    observed = await capture_repository_snapshot(root)

    assert reads >= 3
    assert observed.status_truncated is False
    assert observed._preservation_complete is True
    assert observed._preservation_files[0].baseline_content is not None


@pytest.mark.asyncio
async def test_modified_file_missing_in_both_captures_stays_fail_closed(
    monkeypatch,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    (root / "README.md").write_text(
        "initial\nuser-owned baseline edit\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_harness,
        "_read_preservation_file",
        lambda _path: (None, None, False),
    )

    observed = await capture_repository_snapshot(root)

    assert observed.status_truncated is True
    assert observed._preservation_complete is False
    assert observed._preservation_files == ()


@pytest.mark.asyncio
async def test_runtime_bundle_detects_prompt_tampering(tmp_path) -> None:
    contract = await _contract(_repository(tmp_path))
    prompt = render_continuation_execution_prompt(contract)

    with materialize_runtime_bundle(
        contract,
        prompt_markdown=prompt,
    ) as bundle:
        assert bundle.execution_path.stat().st_mode & 0o222 == 0
        bundle.execution_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        bundle.execution_path.write_text("tampered", encoding="utf-8")

        with pytest.raises(RuntimeBundleIntegrityError, match="runtime bundle"):
            bundle.verify_integrity()


@pytest.mark.asyncio
async def test_runtime_bundle_paths_do_not_collide_after_id_sanitization(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_path.write_bytes(b"first-image")
    second_path.write_bytes(b"second-image")
    contract = (await _contract(root)).model_copy(update={
        "artifacts": (
            ArtifactReference(
                id="screen:a",
                kind="screenshot",
                path=str(first_path),
                sha256=hashlib.sha256(b"first-image").hexdigest(),
                mime_type="image/png",
                required=True,
                available=True,
                requirement_ids=("R1",),
            ),
            ArtifactReference(
                id="screen-a",
                kind="screenshot",
                path=str(second_path),
                sha256=hashlib.sha256(b"second-image").hexdigest(),
                mime_type="image/png",
                required=True,
                available=True,
                requirement_ids=("R1",),
            ),
        ),
    })
    prompt = render_continuation_execution_prompt(contract)

    with materialize_runtime_bundle(
        contract,
        prompt_markdown=prompt,
    ) as bundle:
        artifact_manifest = json.loads(
            bundle.artifacts_path.read_text(encoding="utf-8")
        )
        entries = artifact_manifest["artifacts"]
        bundled_paths = [entry["bundle_path"] for entry in entries]

        assert artifact_manifest["schema_version"] == (
            "continuation_runtime_artifacts.v1"
        )
        assert artifact_manifest["portable"] is True
        assert artifact_manifest["path_semantics"] == {
            "bundle_path": "bundle_relative",
            "content_identity": "sha256_of_exact_bundled_bytes",
            "path": "bundle_relative",
            "source_path": "omitted",
        }
        assert bundled_paths == [
            "attachments/01-screen-a.png",
            "attachments/02-screen-a.png",
        ]
        assert [entry["path"] for entry in entries] == bundled_paths
        assert all(entry["source_path"] is None for entry in entries)
        assert str(first_path) not in bundle.artifacts_path.read_text(
            encoding="utf-8"
        )
        assert len(set(bundled_paths)) == 2
        assert (bundle.root / bundled_paths[0]).read_bytes() == b"first-image"
        assert (bundle.root / bundled_paths[1]).read_bytes() == b"second-image"
        assert all(path in prompt for path in bundled_paths)
        assert str(first_path) not in prompt
        assert hashlib.sha256(b"first-image").hexdigest() in prompt
        assert "mime=`image/png`" in prompt
        assert "requirements=R1" in prompt
        assert "DAEMONSTATE_EXECUTION_CONTRACT_PATH" in prompt
        staged = render_continuation_staging_context(contract)
        assert bundled_paths[0] in staged
        assert bundled_paths[1] in staged
        assert hashlib.sha256(b"first-image").hexdigest() in staged
        assert "DAEMONSTATE_EXECUTION_BUNDLE_PATH" not in staged
        assert "Portable bundle-relative locator (not yet materialized)" in staged
        bundle_manifest = json.loads(
            bundle.manifest_path.read_text(encoding="utf-8")
        )
        assert bundle_manifest["portability"] == {
            "bundle_root_environment_variable": (
                "DAEMONSTATE_EXECUTION_BUNDLE_PATH"
            ),
            "file_paths": "bundle_relative",
        }
        assert bundle_manifest["attachments"] == {
            "artifact_count": 2,
            "available_count": 2,
            "content_identity": "sha256",
            "directory_path": "attachments",
            "manifest_path": "artifacts.json",
            "required_count": 2,
        }
        assert bundle.environment()[
            "DAEMONSTATE_EXECUTION_ARTIFACTS_MANIFEST_PATH"
        ] == str(bundle.artifacts_path)
        assert bundle.environment()[
            "DAEMONSTATE_EXECUTION_ATTACHMENTS_PATH"
        ] == str(bundle.attachments_path)


@pytest.mark.asyncio
async def test_runtime_bundle_rejects_artifact_byte_mismatch(
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    artifact_path = tmp_path / "changed.png"
    artifact_path.write_bytes(b"contract-bound-bytes")
    contract = (await _contract(root)).model_copy(update={
        "artifacts": (
            ArtifactReference(
                id="changed-artifact",
                kind="screenshot",
                path=str(artifact_path),
                sha256=hashlib.sha256(b"contract-bound-bytes").hexdigest(),
                mime_type="image/png",
                required=True,
                available=True,
                requirement_ids=("R1",),
            ),
        ),
    })
    artifact_path.write_bytes(b"changed-after-contract")

    with pytest.raises(
        RuntimeBundleIntegrityError,
        match="copied bytes do not match contract SHA-256",
    ):
        with materialize_runtime_bundle(
            contract,
            prompt_markdown=render_continuation_execution_prompt(contract),
        ):
            pytest.fail("a digest-mismatched bundle must never be yielded")


@pytest.mark.asyncio
async def test_runtime_bundle_path_swap_cannot_change_opened_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    root = _repository(tmp_path)
    artifact_path = tmp_path / "race.png"
    original_bytes = b"contract-bound-before-path-swap"
    replacement_bytes = b"replacement-after-source-open"
    artifact_path.write_bytes(original_bytes)
    contract = (await _contract(root)).model_copy(update={
        "artifacts": (
            ArtifactReference(
                id="race-artifact",
                kind="screenshot",
                path=str(artifact_path),
                sha256=hashlib.sha256(original_bytes).hexdigest(),
                mime_type="image/png",
                required=True,
                available=True,
                requirement_ids=("R1",),
            ),
        ),
    })
    original_open = runtime_bundle.os.open
    swapped = False

    def swap_path_after_open(path, flags, *args, **kwargs):
        nonlocal swapped
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == artifact_path and not swapped:
            swapped = True
            replacement = tmp_path / "replacement.png"
            replacement.write_bytes(replacement_bytes)
            replacement.replace(artifact_path)
        return descriptor

    monkeypatch.setattr(runtime_bundle.os, "open", swap_path_after_open)

    with materialize_runtime_bundle(
        contract,
        prompt_markdown=render_continuation_execution_prompt(contract),
    ) as bundle:
        artifact_manifest = json.loads(
            bundle.artifacts_path.read_text(encoding="utf-8")
        )
        bundled_path = artifact_manifest["artifacts"][0]["bundle_path"]
        assert (bundle.root / bundled_path).read_bytes() == original_bytes
        assert artifact_path.read_bytes() == replacement_bytes
        assert swapped is True


@pytest.mark.asyncio
async def test_local_harness_delivers_execution_prompt_not_audit_pack(
    db_session,
    tmp_path,
) -> None:
    root = _repository(tmp_path)
    contract = await _contract(
        root,
        command_argv=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path('verified.txt').write_text('yes')",
        ),
    )
    workspace = Workspace(
        id=uuid4(),
        name=f"Execution runtime {uuid4()}",
        slug=f"execution-runtime-{uuid4().hex}",
    )
    pack = ContextPack(
        id=UUID(contract.context_pack_id),
        workspace_id=workspace.id,
        objective=contract.task.request_verbatim,
        markdown="# Audit pack only\nTHIS MUST NOT BE THE WORKER PROMPT\n",
        manifest=json.dumps({"schema_version": "context_pack.v2"}),
        repo_state_json="{}",
    )
    prompt = render_continuation_execution_prompt(contract)
    contract_json = canonical_contract_json(contract)
    execution = ContinuationExecution(
        id=UUID(contract.id),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        schema_version=contract.schema_version,
        task_mode=contract.task_mode.value,
        request_verbatim=contract.task.request_verbatim,
        request_normalized=contract.task.request_normalized,
        request_sha256=contract.task.request_sha256,
        display_title=contract.task.display_title,
        contract_json=contract_json,
        contract_sha256=sha256_text(contract_json),
        prompt_markdown=prompt,
        prompt_sha256=execution_prompt_sha256(prompt),
        status="launchable",
        idempotency_key=hashlib.sha256(
            f"execution:{contract.id}".encode()
        ).hexdigest(),
    )
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        continuation_execution_id=execution.id,
        run_key=f"continuation:{uuid4().hex}",
        tool="daemonstate:test",
        model="test",
        objective=contract.task.request_verbatim,
        status="running",
    )
    requirement = ContinuationRequirement(
        continuation_execution_id=execution.id,
        requirement_key="R1",
        text=contract.requirements[0].text,
        priority=RequirementPriority.MUST.value,
        source_span_ids_json='["S1"]',
        verification_ids_json='["V1"]',
    )
    db_session.add_all([workspace, pack, execution, requirement, run])
    await db_session.flush()
    child = (
        "import os, sys; from pathlib import Path; "
        "prompt = Path(sys.argv[1]).read_text(); "
        "assert 'Complete the immediate task' in prompt; "
        "assert 'THIS MUST NOT BE THE WORKER PROMPT' not in prompt; "
        "assert Path(os.environ['DAEMONSTATE_EXECUTION_CONTRACT_PATH']).is_file(); "
        "assert os.environ['DAEMONSTATE_EXECUTION_ID']; "
        "Path('worker.txt').write_text('done')"
    )

    result = await LocalHarnessRunner(db_session).run(
        context_pack_id=pack.id,
        continuation_execution_id=execution.id,
        run_id=run.id,
        repo_path=root,
        command=(sys.executable, "-c", child, "{context_file}"),
        verify=True,
    )

    assert result.status == "completed"
    assert result.continuation_execution_id == str(execution.id)
    assert result.runtime_bundle_integrity_passed is True
    assert result.preservation_passed is True
    assert result.verification_results[0].verifier_id == "V1"
    assert set(result.changed_files) == {"verified.txt", "worker.txt"}
    assert not Path(result.command.argv[-1]).exists()

    failed_matrix = build_requirement_matrix(
        contract,
        (),
        worker_succeeded=False,
        bundle_integrity_passed=True,
        preservation_passed=True,
    )
    await persist_requirement_matrix(
        db_session,
        execution=execution,
        run=run,
        matrix=failed_matrix,
    )
    failed_result = SimpleNamespace(
        status="failed",
        command=CommandResult(
            argv=("claude",),
            exit_code=1,
            stdout="",
            stderr=(
                "Claude authentication failed: OAuth token has been revoked "
                "(401 Unauthorized)"
            ),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            duration_ms=1,
        ),
        agent_changed_files=(),
        changed_files=(),
    )
    final_payload = _contract_outcome(
        failed_matrix,
        result=failed_result,
        provider="claude",
        current_task=contract.task.request_verbatim,
    )
    await persist_final_outcome(
        db_session,
        execution=execution,
        matrix=failed_matrix,
        payload=final_payload,
    )
    await db_session.commit()

    stored = await db_session.scalar(
        select(ContinuationOutcome).where(
            ContinuationOutcome.continuation_execution_id == execution.id
        )
    )
    assert final_payload["status"] == "blocked_external"
    assert final_payload["completion_evidence"] == "external_blocker_observed"
    assert stored is not None
    assert stored.status == "blocked_external"
    assert execution.status == "blocked_external"
    assert json.loads(stored.blocker_json)["code"] == (
        "provider_authentication_revoked"
    )
