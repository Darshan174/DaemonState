from __future__ import annotations

import base64
import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.dependencies import get_access_scope
from app.config import settings
from app.main import app
from app.models import (
    AgentRun,
    CheckpointEvidence,
    CheckpointItem,
    CodeFile,
    ContextPack,
    RunObservation,
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
    Workspace,
    WorkspaceGoal,
)
from app.services.access import AccessScope
from app.services import continuation as continuation_module
from app.services.checkpoints import capture_checkpoint
from app.services.continuation import _checkpoint_repo_compatible
from app.services.continuation_quality_gate import (
    ContinuationQualityIssue,
    ContinuationQualityReport,
)
from app.services.harness_adapters import ProviderReadiness
from app.services.harness_launcher import HarnessVisibility
from app.services.local_harness import RepositoryStateChangedError
from app.services.provider_capabilities import provider_capabilities
from app.services.session_library import sync_local_session_library
from app.services.session_events import NormalizedSessionEvent, persist_session_events
from app.services.source_revisions import ingest_source_document_revision
from app.sync.session_resolvers import ResolvedSession, SessionDiscoveryResult
from app.time import utc_now


@pytest.fixture(autouse=True)
def _continuation_tests_have_an_exact_visible_harness(monkeypatch) -> None:
    """Keep runtime tests independent from apps installed on the test machine."""

    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_harness_visibility",
        lambda provider: HarnessVisibility(
            provider=provider,
            ready=True,
            desktop_available=True,
            exact_session_supported=True,
            code="visible_harness_ready",
            message=f"{provider} can show the exact continuation.",
            action=f"Continue in {provider}.",
        ),
    )


async def test_prepare_continuation_infers_task_and_captures_session_tip(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Implement zero-curation continuation for the active coding task.",
        session_id="zero-curation",
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_model": "general-coder",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "continuation.v1"
    assert body["objective"] == (
        "Implement zero-curation continuation for the active coding task."
    )
    assert body["task"]["origin"] == "session"
    assert body["source_session"]["provider"] == "codex"
    assert body["source_session"]["session_id"] == "zero-curation"
    assert body["checkpoint"]["id"]
    assert body["context_pack_id"]
    assert body["manifest"]["continuation"]["checkpoint_id"] == body["checkpoint"]["id"]
    assert "Restored Session Checkpoint" in body["markdown"]
    assert body["project_context"]["schema_version"] == (
        "continuation_staging_context.v1"
    )
    assert body["project_context"]["scope"] == "project"
    assert body["project_context"]["copy_ready"] is True
    assert body["quality_report"]["launchable"] is False
    assert body["quality_report"]["automatic_execution_ready"] is False
    verification_issue = next(
        item
        for item in body["project_context"]["quality_issues"]
        if item["code"]
        == "mandatory_requirement_verification_unexecutable"
    )
    assert verification_issue["blocks_current_execution"] is True
    assert verification_issue["blocks_copy"] is False
    assert body["project_context"]["estimated_tokens"] > 0
    assert body["project_context"]["sha256"] == hashlib.sha256(
        body["project_context"]["content"].encode("utf-8")
    ).hexdigest()
    assert "### Authoritative current lead" in (
        body["project_context"]["content"]
    )
    assert body["objective"] in body["project_context"]["content"]
    assert "### Reconciliation and unresolved state" in (
        body["project_context"]["content"]
    )
    assert body["project_context"]["content"] != body["markdown"]
    assert body["project_context"]["content"] != body["execution_prompt"]
    assert any(
        item["code"] == "agent_progress_is_reported"
        for item in body["attention"]
    )


@pytest.mark.parametrize(
    "mutation_point",
    ("context_scan_then_revert", "after_contract_compile"),
)
async def test_prepare_never_marks_mixed_time_repository_context_copy_ready(
    client,
    db_session,
    tmp_path,
    monkeypatch,
    mutation_point,
) -> None:
    goal = (
        "Update app/continuation.py for the requested behavior and verify the "
        "focused continuation tests."
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id=f"prepare-repository-race-{mutation_point}",
    )
    _initialize_git_repository(tmp_path)
    tracked = tmp_path / "app" / "continuation.py"
    original_content = tracked.read_text(encoding="utf-8")
    changed_content = (
        "def prepare_continuation():\n"
        f"    return {mutation_point!r}\n"
    )

    if mutation_point == "context_scan_then_revert":
        original_compile = (
            continuation_module.ContextCompiler.compile_context_pack
        )

        async def scan_transient_repository_state(compiler, *args, **kwargs):
            tracked.write_text(changed_content, encoding="utf-8")
            compiled = await original_compile(compiler, *args, **kwargs)
            tracked.write_text(original_content, encoding="utf-8")
            return compiled

        monkeypatch.setattr(
            continuation_module.ContextCompiler,
            "compile_context_pack",
            scan_transient_repository_state,
        )
    else:
        original_execution_compile = (
            continuation_module.compile_and_persist_continuation_execution
        )

        async def mutate_after_contract_compile(*args, **kwargs):
            compiled = await original_execution_compile(*args, **kwargs)
            tracked.write_text(changed_content, encoding="utf-8")
            return compiled

        monkeypatch.setattr(
            continuation_module,
            "compile_and_persist_continuation_execution",
            mutate_after_contract_compile,
        )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": goal,
            "target_model": "general-coder",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    race_issue = next(
        (
            issue
            for issue in body["project_context"]["quality_issues"]
            if issue["code"]
            == "project_context_repository_changed_during_prepare"
        ),
        None,
    )
    assert race_issue is not None, body["project_context"]
    assert race_issue["severity"] == "blocking"
    assert race_issue["blocks_copy"] is True
    assert body["project_context"]["copy_ready"] is False


async def test_prepare_binds_pack_and_contract_to_one_repository_snapshot(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Update app/continuation.py and verify the focused continuation tests."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="prepare-authoritative-repository-snapshot",
    )
    _initialize_git_repository(tmp_path)
    tracked = tmp_path / "app" / "continuation.py"
    tracked.write_text(
        "def prepare_continuation():\n    return 'dirty user work'\n",
        encoding="utf-8",
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": goal,
            "target_model": "general-coder",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    current = body["repository"]["current"]
    repo_state = body["manifest"]["repo_state"]
    authoritative = repo_state["authoritative_snapshot"]
    contract_repository = body["execution_contract"]["repository"]
    assert authoritative["status_fingerprint"] == current["status_fingerprint"]
    assert repo_state["status_fingerprint"] == current["status_fingerprint"]
    assert (
        contract_repository["status_fingerprint"]
        == current["status_fingerprint"]
    )
    assert authoritative["head_commit"] == current["head_commit"]
    assert repo_state["head_commit"] == current["head_commit"]
    assert contract_repository["head_commit"] == current["head_commit"]
    manifest_change = next(
        item
        for item in repo_state["changed_files"]
        if item["path"] == "app/continuation.py"
    )
    contract_change = next(
        item
        for item in contract_repository["preexisting_changes"]
        if item["path"] == "app/continuation.py"
    )
    assert manifest_change["sha256"] == contract_change["content_sha256"]
    assert body["project_context"]["copy_ready"] is True, body[
        "project_context"
    ]["quality_issues"]
    assert not any(
        issue["code"]
        == "project_context_repository_changed_during_prepare"
        for issue in body["project_context"]["quality_issues"]
    )


async def test_prepare_blocks_project_context_copy_for_contract_blocker(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Implement the requested visual change.",
        session_id="project-copy-blocker",
    )
    original = continuation_module.evaluate_continuation_quality

    def blocked_quality(*args, **kwargs):
        report = original(*args, **kwargs)
        return ContinuationQualityReport(
            launchable=False,
            issues=(
                *report.issues,
                ContinuationQualityIssue(
                    code="required_artifact_unresolved",
                    severity="blocking",
                    message="A required screenshot is unavailable.",
                    artifact_id="A1",
                ),
            ),
            contract_sha256=report.contract_sha256,
            prompt_sha256=report.prompt_sha256,
        )

    monkeypatch.setattr(
        continuation_module,
        "evaluate_continuation_quality",
        blocked_quality,
    )
    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": "Implement the requested visual change.",
        },
    )

    assert response.status_code == 200
    project_context = response.json()["project_context"]
    assert project_context["copy_ready"] is False
    issues = {
        issue["code"]: issue
        for issue in project_context["quality_issues"]
    }
    assert issues["required_artifact_unresolved"] == {
        "code": "required_artifact_unresolved",
        "severity": "blocking",
        "message": "A required screenshot is unavailable.",
        "artifact_id": "A1",
        "blocks_current_execution": True,
        "blocks_copy": True,
    }
    assert issues[
        "mandatory_requirement_verification_unexecutable"
    ]["blocks_copy"] is False


async def test_checkpoint_project_context_recovers_lossless_request_and_images(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    image_paths: list[Path] = []
    image_inputs: list[dict[str, object]] = []
    image_contents: list[bytes] = []
    for index, content in enumerate(
        (
            _test_png((255, 0, 0)),
            _test_png((0, 255, 0)),
            _test_png((0, 0, 255)),
        ),
        start=1,
    ):
        path = tmp_path / f"reference-{index}.png"
        path.write_bytes(content)
        image_paths.append(path)
        image_contents.append(content)
        image_inputs.append({
            "mime_type": "image/png",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        })
    task_text = (
        "Use the historical prompt report as context. "
        "WORK ON THIS AND GET THIS DONE. Implement the Session Context and "
        "Project Context split and verify the visible workflow.\n"
        + "\n".join(
            f'<image path="{path}"></image>' for path in image_paths
        )
        + "\n"
    )
    padding_length = 687 - len(task_text)
    assert padding_length > 0
    request = (
        task_text
        + ("Keep every user-authored requirement intact. " * 30)[
            :padding_length
        ]
    )
    assert len(request) == 687

    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=request,
        session_id="lossless-visual-checkpoint",
    )
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "27"
    sessions_dir.mkdir(parents=True)
    rollout = sessions_dir / "rollout.jsonl"
    rollout.write_text("\n".join([
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": request},
                    *[
                        {
                            "type": "input_image",
                            "image_url": (
                                "data:image/png;base64,"
                                + base64.b64encode(content).decode("ascii")
                            ),
                        }
                        for content in image_contents
                    ],
                ],
            },
        }),
        json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": request,
                "local_images": [str(path) for path in image_paths],
            },
        }),
    ]), encoding="utf-8")
    monkeypatch.setattr(settings, "codex_home", str(codex_home))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    source_document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id
            == "codex:session:lossless-visual-checkpoint",
        )
    )
    assert source_document is not None
    source_metadata = json.loads(source_document.metadata_json)
    source_metadata["source_path"] = str(rollout)
    source_document.metadata_json = json.dumps(source_metadata)
    goal_event = await db_session.scalar(
        select(SessionEvent).where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.provider_event_id
            == "codex:lossless-visual-checkpoint:user",
        )
    )
    assert goal_event is not None
    goal_event.payload_json = json.dumps({
        "cwd": str(tmp_path),
        "local_images": [str(path) for path in image_paths],
        "input_images": image_inputs,
    })
    _initialize_git_repository(tmp_path)
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="lossless-visual-checkpoint",
        trigger="continuation",
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "checkpoint_id": str(checkpoint.id),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    contract = body["execution_contract"]
    assert contract["task"]["request_verbatim"] == request
    assert contract["task"]["request_sha256"] == hashlib.sha256(
        request.encode("utf-8")
    ).hexdigest()
    assert contract["task_mode"] == "change"
    assert body["project_context"]["copy_ready"] is True, body["project_context"]
    assert len(contract["artifacts"]) == 3
    requirements = {
        requirement["id"]: requirement
        for requirement in contract["requirements"]
    }
    for index, artifact in enumerate(contract["artifacts"]):
        assert artifact["id"] == f"A{index + 1}"
        assert artifact["available"] is True
        assert artifact["path"] != str(image_paths[index])
        assert Path(artifact["path"]).is_absolute()
        assert Path(artifact["path"]).is_file()
        assert (tmp_path / "data") in Path(artifact["path"]).parents
        assert artifact["source_path"] == str(image_paths[index])
        assert artifact["sha256"] == image_inputs[index]["sha256"]
        assert len(artifact["requirement_ids"]) == 1
        linked = requirements[artifact["requirement_ids"][0]]
        assert linked["source_span_ids"] == []
        assert linked["source_artifact_ids"] == [artifact["id"]]
    assert all(
        "<image" not in span["text"]
        and "</image>" not in span["text"]
        for span in contract["source_spans"]
    )
    assert all(
        "<image" not in requirement["text"]
        for requirement in contract["requirements"]
    )
    for artifact in contract["artifacts"]:
        assert artifact["id"] in body["project_context"]["content"]
        assert artifact["path"] in body["project_context"]["content"]
        assert artifact["sha256"] in body["project_context"]["content"]
        assert artifact["mime_type"] in body["project_context"]["content"]
    assert (
        "Portable bundle-relative locator (not yet materialized):"
        in body["project_context"]["content"]
    )
    assert (
        "DAEMONSTATE_EXECUTION_BUNDLE_PATH"
        not in body["project_context"]["content"]
    )
    assert "Runtime bundle delivery:" in body["execution_prompt"]
    assert "Requirement linkage:" in body["project_context"]["content"]
    assert "Verification guidance:" in body["project_context"]["content"]
    assert (
        "inline `<image path=...>` tag"
        not in body["project_context"]["content"]
    )
    assert (
        "Never reopen its original provider/source path"
        not in body["project_context"]["content"]
    )


async def test_prepare_continuation_recovers_legacy_command_failure_checkpoint(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Finish the interrupted continuation workflow."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="legacy-command-blocker",
    )
    _initialize_git_repository(tmp_path)
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="legacy-command-blocker",
        trigger="continuation",
    )
    checkpoint.continuation_status = "blocked"
    exact_next = await db_session.scalar(
        select(CheckpointItem).where(
            CheckpointItem.checkpoint_id == checkpoint.id,
            CheckpointItem.category == "exact_next_action",
        )
    )
    assert exact_next is not None
    exact_next.statement = (
        "Fix the failure from `tool:write_stdin` and rerun that command."
    )
    db_session.add(CheckpointItem(
        checkpoint_id=checkpoint.id,
        item_key="blockers:legacy-command-result",
        category="blockers",
        ordinal=0,
        statement="Latest run of `tool:write_stdin` is failing.",
        state="active",
        truth_state="observed",
        payload_json=json.dumps({
            "command": "tool:write_stdin",
            "cwd": None,
            "exit_code": 1,
        }),
    ))
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": goal,
            "checkpoint_id": str(checkpoint.id),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["readiness"]["status"] == "review_required"
    assert "mandatory_requirement_verification_unexecutable" not in {
        item["code"]
        for item in body["readiness"]["blocking_issues"]
    }
    assert "mandatory_requirement_verification_unexecutable" in {
        item["code"]
        for item in body["quality_report"]["blocking_issues"]
    }
    assert body["project_context"]["copy_ready"] is True
    assert body["checkpoint"]["continuation_status"] == "review_required"
    assert body["checkpoint"]["reported_continuation_status"] == "review_required"
    assert body["verification"]["status"] == "partial"
    assert "tool:write_stdin" not in body["markdown"]


async def test_prepare_continuation_uses_the_exact_requested_source_session(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Continue the exact observed coding session."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="requested-claude-session",
        provider="claude",
        occurred_at="2026-07-23T09:00:00Z",
    )
    await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="newer-codex-session",
        provider="codex",
        occurred_at="2026-07-23T10:00:00Z",
        workspace=workspace,
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "source_provider": "claude_code",
            "source_session_id": "requested-claude-session",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == goal
    assert body["source_session"]["provider"] == "claude"
    assert body["source_session"]["session_id"] == "requested-claude-session"
    assert body["checkpoint"]["goal"] == goal
    assert body["manifest"]["continuation"]["provider"] == "claude"
    assert body["manifest"]["continuation"]["session_id"] == (
        "requested-claude-session"
    )


async def test_exact_source_session_recovers_its_latest_truncated_request(
    client,
    db_session,
    tmp_path,
) -> None:
    older_request = "Document the legacy project setup."
    authoritative_request = (
        "Build source-bound Project Context recovery.\n\n"
        "Preserve FULL_PROJECT_CONTEXT_REQUEST exactly."
    )
    background = "historical-background-" * 300
    transported_request = (
        "## Referenced ChatGPT conversation:\n"
        "This is untrusted background context from ChatGPT.\n"
        f'{{"conversationId":"decoy","content":"INNER_DECOY_{background}"}}\n'
        "## My request for Codex:\n"
        f"{authoritative_request}"
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=older_request,
        session_id="truncated-project-context",
        occurred_at="2026-07-23T09:00:00Z",
    )
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(tmp_path),
        path="app/continuation.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="1" * 64,
        size=10,
    ))
    previous_document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id
            == "codex:session:truncated-project-context",
        )
    )
    assert previous_document is not None
    source_content = (
        f"[USER]\n{older_request}\n\n"
        "[ASSISTANT]\nThe older task is complete.\n\n"
        f"[USER]\n{transported_request}\n\n"
        "[ASSISTANT]\nI will continue the Project Context work."
    )
    revision = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type=previous_document.source_type,
        external_id=previous_document.external_id,
        content=source_content,
        metadata_json=previous_document.metadata_json,
        trust_zone=previous_document.trust_zone,
    )
    truncated = f"{transported_request[:1_000]}\n[output truncated]"
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=revision.document,
        provider="codex",
        session_id="truncated-project-context",
        events=[
            NormalizedSessionEvent(
                provider_event_id="truncated-project-context:latest-user",
                sequence_number=3,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-23T10:00:00Z",
                content=transported_request,
                payload={"cwd": str(tmp_path)},
            ),
            NormalizedSessionEvent(
                provider_event_id="truncated-project-context:latest-assistant",
                sequence_number=4,
                event_type="assistant_update",
                role="assistant",
                occurred_at="2026-07-23T10:01:00Z",
                content=(
                    "Implemented PROJECT_CONTEXT_PROGRESS_RESTORED after "
                    "inspecting app/continuation.py. "
                    "Next action: PROJECT_CONTEXT_NEXT_ACTION_RESTORED by "
                    "verifying the generated handoff."
                ),
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    goal_event = await db_session.scalar(
        select(SessionEvent).where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.provider_event_id
            == "truncated-project-context:latest-user",
        )
    )
    tip_event = await db_session.scalar(
        select(SessionEvent).where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.provider_event_id
            == "truncated-project-context:latest-assistant",
        )
    )
    assert goal_event is not None
    assert tip_event is not None
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="truncated-project-context",
        boundary_event_id=tip_event.id,
        trigger="continuation",
    )
    goal_item = await db_session.scalar(
        select(CheckpointItem).where(
            CheckpointItem.checkpoint_id == checkpoint.id,
            CheckpointItem.category == "goal",
        )
    )
    assert goal_item is not None
    goal_item.statement = "[output truncated]"
    goal_item.payload_json = json.dumps({
        "request_verbatim": truncated,
        "request_sha256": hashlib.sha256(
            truncated.encode("utf-8")
        ).hexdigest(),
    })
    goal_event.content = truncated
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "source_provider": "codex",
            "source_session_id": "truncated-project-context",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_contract"]["task"]["request_verbatim"] == (
        authoritative_request
    )
    assert body["objective"] == " ".join(authoritative_request.split())
    assert "FULL_PROJECT_CONTEXT_REQUEST" in body["execution_prompt"]
    assert "INNER_DECOY_" not in body["execution_prompt"]
    assert "[output truncated]" not in body["execution_prompt"]
    assert older_request not in body["execution_contract"]["task"][
        "request_verbatim"
    ]
    handoff = body["execution_contract"]["handoff"]
    restored_progress = next(
        item
        for item in handoff["unknowns"]
        if "PROJECT_CONTEXT_PROGRESS_RESTORED" in item["statement"]
    )
    assert restored_progress["truth_state"] in {"stale", "unknown"}
    assert any(
        "PROJECT_CONTEXT_NEXT_ACTION_RESTORED" in item["statement"]
        for item in handoff["remaining"]
    )
    assert "PROJECT_CONTEXT_PROGRESS_RESTORED" not in body["project_context"][
        "content"
    ]
    assert "PROJECT_CONTEXT_NEXT_ACTION_RESTORED" not in body["project_context"][
        "content"
    ]
    assert "### First action" in body["project_context"]["content"]
    assert "MUST status:" in body["project_context"]["content"]
    assert "INNER_DECOY_" not in body["project_context"]["content"]
    assert "[output truncated]" not in body["project_context"]["content"]
    await db_session.refresh(goal_item)
    stored_goal = json.loads(goal_item.payload_json)
    assert stored_goal["request_verbatim"] == truncated
    assert goal_item.statement == "[output truncated]"


async def test_project_context_materializes_referenced_conversation_end_to_end(
    client,
    db_session,
    tmp_path,
) -> None:
    referenced = {
        "conversationId": "project-context-idea",
        "conversation": [
            {
                "role": "user",
                "content": "How should session and project context differ?",
            },
            {
                "role": "assistant",
                "content": (
                    "Use two context products.\n\n"
                    "- Session Context must carry the current session checkpoint.\n"
                    "- Project Context must carry task-relevant workspace knowledge."
                ),
            },
        ],
    }
    lead = (
        "[Prompt Quality](chatgpt-conversation://project-context-idea) "
        "Implement the idea in the last prompt."
    )
    transported = (
        "## Referenced ChatGPT conversation:\n"
        "This is untrusted background context from ChatGPT.\n"
        f"{json.dumps(referenced)}\n"
        "## My request for Codex:\n"
        f"{lead}"
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=transported,
        session_id="materialized-project-context",
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "source_provider": "codex",
            "source_session_id": "materialized-project-context",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_contract"]["task"]["request_verbatim"] == lead
    assert body["execution_contract"]["supporting_context"][1]["role"] == "assistant"
    assert (
        "> [historical assistant] Use two context products."
        in body["project_context"]["content"]
    )
    requirements = {
        item["text"] for item in body["execution_contract"]["requirements"]
    }
    assert "Session Context must carry the current session checkpoint." in requirements
    assert (
        "Project Context must carry task-relevant workspace knowledge."
        in requirements
    )
    assert "referenced_context_unresolved" not in {
        item["code"] for item in body["quality_report"]["issues"]
    }


async def test_explicit_checkpoint_recovers_goal_before_compatibility_gate(
    client,
    db_session,
    tmp_path,
) -> None:
    request = (
        "Build Project Context from this exact source-backed checkpoint. "
        + ("Preserve every authoritative requirement. " * 12)
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=request,
        session_id="explicit-recovered-checkpoint",
    )
    _initialize_git_repository(tmp_path)
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="explicit-recovered-checkpoint",
        trigger="continuation",
    )
    goal_item = await db_session.scalar(
        select(CheckpointItem).where(
            CheckpointItem.checkpoint_id == checkpoint.id,
            CheckpointItem.category == "goal",
        )
    )
    goal_event = await db_session.scalar(
        select(SessionEvent).where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.provider_event_id
            == "codex:explicit-recovered-checkpoint:user",
        )
    )
    assert goal_item is not None
    assert goal_event is not None
    truncated = f"{request[:300]}\n[output truncated]"
    goal_item.statement = "[output truncated]"
    goal_item.payload_json = json.dumps({
        "request_verbatim": truncated,
        "request_sha256": hashlib.sha256(truncated.encode("utf-8")).hexdigest(),
    })
    goal_event.content = truncated
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": request,
            "checkpoint_id": str(checkpoint.id),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkpoint"]["id"] == str(checkpoint.id)
    assert body["execution_contract"]["task"]["request_verbatim"] == request
    assert request in body["project_context"]["content"]


async def test_exact_source_session_does_not_fall_back_when_recovery_is_ambiguous(
    client,
    db_session,
    tmp_path,
) -> None:
    older_request = "Implement the obsolete Project Context task."
    shared_prefix = "Build the exact Project Context task. " + (
        "shared-source-prefix-" * 20
    )
    first_request = f"{shared_prefix}FIRST_ENDING"
    second_request = f"{shared_prefix}SECOND_ENDING"
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=older_request,
        session_id="ambiguous-project-context",
        occurred_at="2026-07-23T09:00:00Z",
    )
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(tmp_path),
        path="app/continuation.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="1" * 64,
        size=10,
    ))
    previous_document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id
            == "codex:session:ambiguous-project-context",
        )
    )
    assert previous_document is not None
    revision = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type=previous_document.source_type,
        external_id=previous_document.external_id,
        content=(
            f"[USER]\n{older_request}\n\n"
            "[ASSISTANT]\nDone.\n\n"
            f"[USER]\n{first_request}\n\n"
            "[ASSISTANT]\nWorking.\n\n"
            f"[USER]\n{second_request}"
        ),
        metadata_json=previous_document.metadata_json,
        trust_zone=previous_document.trust_zone,
    )
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=revision.document,
        provider="codex",
        session_id="ambiguous-project-context",
        events=[
            NormalizedSessionEvent(
                provider_event_id="ambiguous-project-context:latest-user",
                sequence_number=3,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-23T10:00:00Z",
                content=f"{shared_prefix}[output truncated]",
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "source_provider": "codex",
            "source_session_id": "ambiguous-project-context",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == (
        "continuation_source_session_not_found"
    )
    assert older_request not in response.text
    assert "FIRST_ENDING" not in response.text
    assert "SECOND_ENDING" not in response.text


async def test_exact_source_session_overrides_an_unrelated_workspace_goal(
    client,
    db_session,
    tmp_path,
) -> None:
    session_goal = "Continue the exact source session task."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=session_goal,
        session_id="exact-source-over-current-goal",
    )
    db_session.add(WorkspaceGoal(
        workspace_id=workspace.id,
        title="Work on an unrelated selected workspace goal.",
        status="active",
    ))
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "source_provider": "codex",
            "source_session_id": "exact-source-over-current-goal",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == session_goal
    assert body["task"]["origin"] == "session"
    assert body["source_session"]["provider"] == "codex"
    assert body["source_session"]["session_id"] == (
        "exact-source-over-current-goal"
    )


async def test_reported_checkpoint_blocker_is_advisory_not_launch_authority(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Finish the continuation workflow despite reported intermediate issues."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="reported-blocker",
    )
    document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id == "codex:session:reported-blocker",
        )
    )
    assert document is not None
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="reported-blocker",
        events=[
            NormalizedSessionEvent(
                provider_event_id="reported-blocker:latest",
                sequence_number=3,
                event_type="assistant_update",
                role="assistant",
                content=(
                    "Blocker: the agent is waiting for a continuation policy fix."
                ),
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "source_provider": "codex",
            "source_session_id": "reported-blocker",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["readiness"]["status"] == "review_required"
    assert "mandatory_requirement_verification_unexecutable" not in {
        item["code"]
        for item in body["readiness"]["blocking_issues"]
    }
    assert "mandatory_requirement_verification_unexecutable" in {
        item["code"]
        for item in body["quality_report"]["blocking_issues"]
        if item["blocks_current_execution"]
    }
    issue = next(
        item
        for item in body["readiness"]["blocking_issues"]
        if item["code"] == "checkpoint_blocker"
    )
    assert issue["blocks_current_execution"] is False
    assert body["checkpoint"]["continuation_status"] == "review_required"
    assert body["checkpoint"]["reported_continuation_status"] == "blocked"


async def test_exact_source_session_can_resume_an_earlier_compatible_request(
    client,
    db_session,
    tmp_path,
) -> None:
    earlier_goal = "Plan Alpha billing for launch."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=earlier_goal,
        session_id="multi-topic-source",
    )
    document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id == "codex:session:multi-topic-source",
        )
    )
    assert document is not None
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="multi-topic-source",
        events=[
            NormalizedSessionEvent(
                provider_event_id="multi-topic-source:newer-goal",
                sequence_number=3,
                event_type="user_request",
                role="user",
                content="Redesign the unrelated onboarding flow.",
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": "Alpha billing",
            "objective_is_user_edited": True,
            "source_provider": "codex",
            "source_session_id": "multi-topic-source",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == "Alpha billing"
    assert body["source_session"]["provider"] == "codex"
    assert body["source_session"]["session_id"] == "multi-topic-source"
    assert body["manifest"]["continuation"]["session_id"] == "multi-topic-source"


async def test_continuation_source_session_requires_a_complete_pair(
    client,
    db_session,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Source session pair",
        slug=f"source-session-pair-{uuid4().hex[:8]}",
    )
    db_session.add(workspace)
    await db_session.commit()

    for partial in (
        {"source_provider": "codex"},
        {"source_session_id": "session-only"},
    ):
        response = await client.post(
            "/api/continuations/prepare",
            json={
                "workspace_id": str(workspace.id),
                "objective": "Continue the selected task.",
                **partial,
            },
        )
        assert response.status_code == 422, response.text
        assert (
            "source_provider and source_session_id must be provided together"
            in response.text
        )


async def test_exact_source_session_fails_explicitly_when_missing_or_mismatched(
    client,
    db_session,
    tmp_path,
) -> None:
    source_goal = "Implement exact source-session continuation."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=source_goal,
        session_id="exact-source",
    )
    await db_session.commit()
    workspace_id = str(workspace.id)

    mismatch = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": workspace_id,
            "repo_path": str(tmp_path),
            "objective": "Implement an unrelated billing workflow.",
            "source_provider": "codex",
            "source_session_id": "exact-source",
        },
    )
    missing = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": workspace_id,
            "repo_path": str(tmp_path),
            "objective": source_goal,
            "source_provider": "codex",
            "source_session_id": "missing-source",
        },
    )

    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["detail"]["code"] == (
        "continuation_source_session_objective_mismatch"
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"]["code"] == (
        "continuation_source_session_not_found"
    )


async def test_prepare_continuation_rejects_transport_metadata_as_a_goal(
    client,
    db_session,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Invalid continuation goal",
        slug=f"invalid-continuation-goal-{uuid4().hex[:8]}",
    )
    db_session.add(workspace)
    await db_session.commit()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "objective": "conversationId",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "continuation_invalid_goal",
        "message": (
            "The continuation goal is transport metadata or a control "
            "instruction, not an executable user task."
        ),
    }


async def test_explicit_objective_excludes_an_unrelated_checkpoint(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Repair authentication token refresh failures.",
        session_id="authentication",
    )
    tip = await db_session.scalar(
        select(SessionEvent)
        .where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.session_id == "authentication",
        )
        .order_by(SessionEvent.sequence_number.desc())
        .limit(1)
    )
    assert tip is not None
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="authentication",
        boundary_event_id=tip.id,
        trigger="manual",
    )
    await db_session.flush()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": "Build monthly billing export reports.",
            "target_model": "general-coder",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == "Build monthly billing export reports."
    assert body["task"]["origin"] == "explicit"
    assert body["checkpoint"] is None
    assert body["source_session"] is None
    assert body["manifest"]["continuation"]["checkpoint_id"] is None
    assert all(
        item.get("id") != f"session_checkpoint:{checkpoint.id}"
        for item in body["manifest"]["selected_context"]
    )
    assert any(
        item["code"] == "no_compatible_checkpoint"
        for item in body["attention"]
    )


async def test_explicit_repo_excludes_a_repo_less_checkpoint_from_another_session(
    client,
    db_session,
    tmp_path,
) -> None:
    source_repo = tmp_path / "source-repo"
    target_repo = tmp_path / "target-repo"
    source_repo.mkdir()
    target_repo.mkdir()
    goal = "Implement repository-scoped continuation safely."
    workspace = await _seed_session(
        db_session,
        source_repo,
        goal=goal,
        session_id="legacy-repo-less",
    )
    tip = await db_session.scalar(
        select(SessionEvent)
        .where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.session_id == "legacy-repo-less",
        )
        .order_by(SessionEvent.sequence_number.desc())
        .limit(1)
    )
    assert tip is not None
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="legacy-repo-less",
        boundary_event_id=tip.id,
        trigger="manual",
    )
    assert checkpoint.repo_root is None
    (target_repo / "README.md").write_text("# Target repository\n", encoding="utf-8")
    await db_session.flush()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(target_repo),
            "objective": goal,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkpoint"] is None
    assert body["source_session"] is None
    assert body["manifest"]["continuation"]["checkpoint_id"] is None
    assert any(
        item["code"] == "no_compatible_checkpoint"
        for item in body["attention"]
    )


def test_checkpoint_without_branch_fails_closed_against_a_known_current_branch() -> None:
    checkpoint = SimpleNamespace(repo_root="/workspace/project", branch=None)

    assert _checkpoint_repo_compatible(
        checkpoint,
        requested_repo="/workspace/project",
        current_repository={"branch": "main"},
        allow_missing_repo=False,
        allow_missing_branch=False,
    ) is False
    assert _checkpoint_repo_compatible(
        checkpoint,
        requested_repo="/workspace/project",
        current_repository={"branch": "main"},
        allow_missing_repo=False,
        allow_missing_branch=True,
    ) is True


async def test_task_identity_is_stable_across_provider_checkpoints(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = "Carry the same coding task between agent harnesses."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="codex-handoff",
        provider="codex",
        occurred_at="2026-07-23T09:00:00Z",
    )

    codex_response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
        },
    )
    assert codex_response.status_code == 200, codex_response.text
    codex_body = codex_response.json()
    assert codex_body["source_session"]["provider"] == "codex"

    await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="claude-handoff",
        provider="claude",
        occurred_at="2026-07-23T10:00:00Z",
        workspace=workspace,
    )
    claude_response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
        },
    )

    assert claude_response.status_code == 200, claude_response.text
    claude_body = claude_response.json()
    assert claude_body["source_session"]["provider"] == "claude"
    assert claude_body["task"]["id"] == codex_body["task"]["id"]
    assert claude_body["task"]["id"].startswith("task:")

    async def no_recent_checkpoints(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        "app.services.continuation.list_checkpoints",
        no_recent_checkpoints,
    )
    exact_response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "checkpoint_id": codex_body["checkpoint"]["id"],
        },
    )
    assert exact_response.status_code == 200, exact_response.text
    exact_body = exact_response.json()
    assert exact_body["checkpoint"]["id"] == codex_body["checkpoint"]["id"]
    assert exact_body["source_session"]["provider"] == "codex"
    assert exact_body["task"]["origin"] == "checkpoint"


async def test_legacy_provider_checkpoint_is_resolved_from_its_exact_source(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Restore the exact pre-compaction coding context."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="legacy-provider-checkpoint",
    )
    document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id
            == "codex:session:legacy-provider-checkpoint",
        )
    )
    assert document is not None
    metadata = json.loads(document.metadata_json)
    metadata["compaction_checkpoints"] = [{
        "id": "checkpoint-a1b2c3d4e5f6",
        "kind": "provider_compaction",
        "provider": "codex",
        "occurred_at": "2026-07-23T10:00:00Z",
        "turn_count": 2,
        "user_turn_count": 1,
        "assistant_turn_count": 1,
        "window_id": 1,
    }]
    document.metadata_json = json.dumps(metadata)
    await db_session.flush()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": goal,
            "checkpoint_id": "checkpoint-a1b2c3d4e5f6",
            "checkpoint_source_id": str(document.id),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkpoint"]["id"] == "checkpoint-a1b2c3d4e5f6"
    assert body["checkpoint"]["schema_version"] == "provider_compaction.v1"
    assert body["source_session"]["session_id"] == "legacy-provider-checkpoint"
    assert body["readiness"]["status"] == "review_required"
    assert body["project_context"]["copy_ready"] is True
    assert body["quality_report"]["automatic_execution_ready"] is False
    assert body["manifest"]["continuation"]["checkpoint_id"] == (
        "checkpoint-a1b2c3d4e5f6"
    )
    assert "Restored Session Checkpoint" in body["markdown"]


async def test_exact_checkpoint_rejects_hidden_evidence_sources(
    client,
    db_session,
    tmp_path,
) -> None:
    goal = "Keep exact continuation evidence inside its access scope."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="restricted-exact-checkpoint",
    )
    tip = await db_session.scalar(
        select(SessionEvent)
        .where(
            SessionEvent.workspace_id == workspace.id,
            SessionEvent.session_id == "restricted-exact-checkpoint",
        )
        .order_by(SessionEvent.sequence_number.desc())
        .limit(1)
    )
    assert tip is not None
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="restricted-exact-checkpoint",
        boundary_event_id=tip.id,
        trigger="manual",
    )
    checkpoint_item_id = await db_session.scalar(
        select(CheckpointItem.id)
        .where(CheckpointItem.checkpoint_id == checkpoint.id)
        .limit(1)
    )
    assert checkpoint_item_id is not None
    hidden_content = "Restricted evidence must not cross an exact checkpoint lookup."
    hidden_source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:hidden-revision",
        content=hidden_content,
        content_sha256=hashlib.sha256(hidden_content.encode("utf-8")).hexdigest(),
        source_identity_sha256=hashlib.sha256(
            f"{workspace.id}:hidden-revision".encode("utf-8")
        ).hexdigest(),
        revision_number=1,
        visibility_scope="restricted",
        permission_snapshot_sha256="restricted-snapshot",
        metadata_json="{}",
    )
    db_session.add(hidden_source)
    await db_session.flush()
    db_session.add(CheckpointEvidence(
        checkpoint_item_id=checkpoint_item_id,
        evidence_type="source_document",
        source_document_id=hidden_source.id,
        supports=True,
        locator_json="{}",
        evidence_sha256=hashlib.sha256(hidden_content.encode("utf-8")).hexdigest(),
    ))
    await db_session.flush()

    async def workspace_only_scope() -> AccessScope:
        return AccessScope(
            principal_id="workspace-member",
            workspace_ids=frozenset({workspace.id}),
        )

    app.dependency_overrides[get_access_scope] = workspace_only_scope
    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": goal,
            "checkpoint_id": str(checkpoint.id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkpoint_not_found"
    app.dependency_overrides.pop(get_access_scope, None)


async def test_legacy_checkpoint_does_not_match_an_observed_secondary_repository(
    client,
    db_session,
    tmp_path,
) -> None:
    source_repo = tmp_path / "source-repo"
    secondary_repo = tmp_path / "secondary-repo"
    source_repo.mkdir()
    secondary_repo.mkdir()
    goal = "Restore a provider checkpoint only inside its original repository."
    workspace = await _seed_session(
        db_session,
        source_repo,
        goal=goal,
        session_id="multi-repo-legacy",
    )
    document = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id == "codex:session:multi-repo-legacy",
        )
    )
    assert document is not None
    metadata = json.loads(document.metadata_json)
    metadata["observed_cwds"] = [str(source_repo), str(secondary_repo)]
    metadata["compaction_checkpoints"] = [{
        "id": "checkpoint-secondary-repo",
        "kind": "provider_compaction",
        "provider": "codex",
        "turn_count": 2,
        "user_turn_count": 1,
        "assistant_turn_count": 1,
        "window_id": 1,
    }]
    document.metadata_json = json.dumps(metadata)
    await db_session.flush()

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(secondary_repo),
            "objective": goal,
            "checkpoint_id": "checkpoint-secondary-repo",
            "checkpoint_source_id": str(document.id),
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]["code"]
        == "checkpoint_repository_mismatch"
    )


async def test_partial_checkpoint_is_returned_as_review_required(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Finish the repository-backed continuation service.",
        session_id="partial-checkpoint",
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification"]["status"] == "partial"
    assert body["repository"]["freshness"]["status"] == "unavailable"
    assert body["readiness"]["status"] == "review_required"
    assert body["project_context"]["copy_ready"] is True
    assert body["quality_report"]["automatic_execution_ready"] is False
    assert any(
        item["code"] == "checkpoint_partial"
        for item in body["attention"]
    )


async def test_continuation_enforces_workspace_access_and_local_only_controls(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Keep continuation side effects local.",
        session_id="local-controls",
    )

    async def remote_scope() -> AccessScope:
        return AccessScope(
            principal_id="remote-user",
            workspace_ids=frozenset({workspace.id}),
        )

    app.dependency_overrides[get_access_scope] = remote_scope
    sync_response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": "Keep continuation side effects local.",
            "sync_sessions": True,
        },
    )
    command_response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "objective": "Keep continuation side effects local.",
            "execute_commands": True,
        },
    )

    assert sync_response.status_code == 403
    assert sync_response.json()["detail"]["code"] == "local_action_required"
    assert command_response.status_code == 422
    assert (
        command_response.json()["detail"]["code"]
        == "checkpoint_command_replay_disabled"
    )

    async def inaccessible_scope() -> AccessScope:
        return AccessScope(
            principal_id="remote-user",
            workspace_ids=frozenset(),
        )

    app.dependency_overrides[get_access_scope] = inaccessible_scope
    inaccessible = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "objective": "Keep continuation side effects local.",
        },
    )
    assert inaccessible.status_code == 404
    app.dependency_overrides.pop(get_access_scope, None)


async def test_failed_prepare_rolls_back_sessions_synchronized_in_the_same_request(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    repo = tmp_path / "indexed-repo"
    repo.mkdir()
    workspace = Workspace(
        id=uuid4(),
        name="Atomic continuation",
        slug=f"atomic-continuation-{uuid4().hex[:8]}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(repo),
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="1" * 64,
        size=10,
    ))
    workspace_id = workspace.id
    await db_session.commit()

    discovered = ResolvedSession(
        connector_type="codex",
        session_id="must-roll-back",
        content="[USER]\nImplement atomic continuation preparation.",
        metadata={
            "tool": "codex",
            "cwd": str(repo),
            "source_path": str(tmp_path / "must-roll-back.jsonl"),
        },
    )
    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        lambda _types: [
            SessionDiscoveryResult(connector_type="codex", sessions=[discovered]),
        ],
    )
    sync_observation = {}

    async def tracked_sync(session, requested_workspace_id, **kwargs):
        result = await sync_local_session_library(
            session,
            requested_workspace_id,
            **kwargs,
        )
        sync_observation["imported"] = result["imported"]
        sync_observation["visible_before_failure"] = await session.scalar(
            select(SourceDocument.id).where(
                SourceDocument.workspace_id == workspace_id,
                SourceDocument.external_id == "codex:session:must-roll-back",
            )
        )
        return result

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        tracked_sync,
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace_id),
            "repo_path": str(tmp_path / "missing-repo"),
            "objective": "Implement atomic continuation preparation.",
            "sync_sessions": True,
        },
    )

    assert response.status_code == 422
    assert sync_observation["imported"] == 1
    assert sync_observation["visible_before_failure"] is not None
    persisted = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.external_id == "codex:session:must-roll-back",
        )
    )
    assert persisted is None


async def test_automatic_continue_resolves_the_latest_task_after_session_sync(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    old_goal = "Repair the earlier continuation implementation."
    latest_goal = "Ship the newly observed continuation workflow."
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=old_goal,
        session_id="previously-imported-session",
        occurred_at="2026-07-25T09:00:00Z",
    )
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(tmp_path),
        path="app/continuation.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="1" * 64,
        size=10,
    ))
    await db_session.flush()
    discovered = ResolvedSession(
        connector_type="codex",
        session_id="newly-synchronized-session",
        content=(
            f"[USER]\n{latest_goal}\n\n"
            "[ASSISTANT]\nProgress: the newest task is ready to continue."
        ),
        metadata={
            "tool": "codex",
            "cwd": str(tmp_path),
            "source_path": str(tmp_path / "newly-synchronized-session.jsonl"),
            "updated_at": "2026-07-25T10:00:00Z",
        },
        events=[
            NormalizedSessionEvent(
                provider_event_id="newly-synchronized-session:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T10:00:00Z",
                content=latest_goal,
                payload={"cwd": str(tmp_path)},
            ),
            NormalizedSessionEvent(
                provider_event_id="newly-synchronized-session:assistant",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                occurred_at="2026-07-25T10:00:01Z",
                content="Progress: the newest task is ready to continue.",
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        lambda _types: [
            SessionDiscoveryResult(
                connector_type="codex",
                sessions=[discovered],
            ),
        ],
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "sync_sessions": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == latest_goal, body.get("sync")
    assert body["task"]["origin"] == "session"
    assert body["source_session"]["provider"] == "codex"
    assert body["source_session"]["session_id"] == (
        "newly-synchronized-session"
    )
    assert body["checkpoint"]["goal"] == latest_goal


async def test_automatic_continue_ignores_subagents_and_attachment_reactions(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = "Build a working workflow where a user can continue in another agent."
    root_session_id = "user-owned-root-session"
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id=root_session_id,
        occurred_at="2026-07-25T09:00:00Z",
    )
    root_source = await db_session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.external_id == f"codex:session:{root_session_id}",
        )
    )
    assert root_source is not None
    root_metadata = json.loads(root_source.metadata_json)
    root_metadata.update({
        "thread_source": "user",
        "title": "Continue AI Infra strategy",
    })
    root_source.metadata_json = json.dumps(root_metadata)
    reaction = (
        "# Files mentioned by the user:\n\n"
        "## Screenshot 2026-07-25 at 19.57.03.png: "
        "/Users/example/Screenshot 2026-07-25 at 19.57.03.png\n\n"
        "## My request for Codex:\n"
        "ARE U FUCKING KIDDING ME U FUCKING PICEC OF SHITE\n"
        "<image name=[Image #1] "
        'path="/Users/example/Screenshot 2026-07-25 at 19.57.03.png"></image>'
    )
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=root_source,
        provider="codex",
        session_id=root_session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{root_session_id}:reaction",
                sequence_number=3,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T10:00:00Z",
                content=reaction,
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    subagent_session_id = "internal-failure-ui-audit"
    discovered_subagent = ResolvedSession(
        connector_type="codex",
        session_id=subagent_session_id,
        content=(
            f"[USER]\n{goal}\n\n"
            f"[USER]\n{reaction}\n\n"
            "[ASSISTANT]\nInspecting the failure card."
        ),
        metadata={
            "tool": "codex",
            "cwd": str(tmp_path),
            "source_path": str(tmp_path / f"{subagent_session_id}.jsonl"),
            "updated_at": "2026-07-25T11:00:00Z",
            "thread_source": "subagent",
            "parent_thread_id": root_session_id,
            "title": "Continuing from AI Infra Components",
        },
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{subagent_session_id}:goal",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T11:00:00Z",
                content=goal,
                payload={"cwd": str(tmp_path)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{subagent_session_id}:reaction",
                sequence_number=2,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T11:00:01Z",
                content=reaction,
                payload={"cwd": str(tmp_path)},
            ),
        ],
    )
    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        lambda _types: [
            SessionDiscoveryResult(
                connector_type="codex",
                sessions=[discovered_subagent],
            ),
        ],
    )

    response = await client.post(
        "/api/continuations/prepare",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "sync_sessions": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["objective"] == goal
    assert body["source_session"]["session_id"] == root_session_id
    assert body["checkpoint"]["goal"] == goal
    assert "Screenshot 2026" not in body["markdown"]
    assert "PICEC OF SHITE" not in body["markdown"]


async def test_run_continuation_switches_provider_and_verifies_automatically(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Continue the real task in a different local agent",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="one-click-source",
        provider="codex",
    )
    workspace_id = workspace.id
    _initialize_git_repository(tmp_path)
    fake_claude = _fake_executable(tmp_path, "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-provider-auth")
    monkeypatch.setenv("DATABASE_URL", "postgresql://server-secret")
    monkeypatch.setenv("SERVER_API_KEY", "server-secret")
    sync_calls = []
    runner_calls = {}

    async def fake_sync(_session, workspace_id, *, commit):
        sync_calls.append((workspace_id, commit))
        return {"failed": 0, "imported": 0, "updated": 0}

    def fake_which(executable):
        return str(fake_claude) if executable == "claude" else None

    class FakeRunner:
        def __init__(self, session):
            self.session = session

        async def run(self, **kwargs):
            runner_calls.update(kwargs)
            run = await self.session.get(AgentRun, UUID(str(kwargs["run_id"])))
            assert run is not None
            run.status = "completed"
            run.ended_at = utc_now()
            await self.session.commit()
            return _fake_harness_result(
                run_id=str(run.id),
                status="completed",
                changed_files=("app/continuation.py",),
                check_exit_code=0,
                cwd=tmp_path,
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace_id),
            "repo_path": str(tmp_path),
            "idempotency_key": "continue-switch-provider",
            "target_provider": "claude",
            "provider_model": "claude-test-model",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "continuation.run.v1"
    assert body["status"] == "verified_complete"
    assert body["preparation"]["source_session"]["provider"] == "codex"
    assert body["delivery"] == {
        "status": "delivered",
        "provider": "claude",
        "source_provider": "codex",
        "provider_switched": True,
        "mode": "fresh",
        "context_delivery": "stdin",
        "run_id": body["run"]["run_id"],
        "provider_model": "claude-test-model",
        "provider_effort": None,
        "task_mode": "change",
        "filesystem_mode": "workspace_write",
        "command_timeout_seconds": settings.continuation_command_timeout_seconds,
        "root_run_id": body["run"]["run_id"],
        "attempts": [{
            "attempt_index": 1,
            "run_id": body["run"]["run_id"],
            "status": "verified_complete",
        }],
    }
    assert runner_calls["verify"] is True
    assert runner_calls["context_stdin"] is True
    assert runner_calls["command_timeout_seconds"] == (
        settings.continuation_command_timeout_seconds
    )
    assert runner_calls["extra_env"]["ANTHROPIC_API_KEY"] == (
        "claude-provider-auth"
    )
    assert "DATABASE_URL" not in runner_calls["extra_env"]
    assert "SERVER_API_KEY" not in runner_calls["extra_env"]
    assert runner_calls["expected_status_fingerprint"] == (
        body["preparation"]["repository"]["current"]["status_fingerprint"]
    )
    assert runner_calls["command"][0] == str(fake_claude)
    assert ("--model", "claude-test-model") == tuple(
        runner_calls["command"][-2:]
    )
    assert "--resume" not in runner_calls["command"]
    assert sync_calls == [(workspace_id, False)]
    assert body["outcome"]["verified"] is True
    assert body["outcome"]["changed_files"] == ["app/continuation.py"]
    assert body["outcome"]["task_transition"]["status"] == "not_applicable"
    assert body["outcome"]["mandatory"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "unproven": 0,
    }
    checks = body["outcome"]["checks"]
    assert checks["passed"] == 1
    assert checks["failed"] == 0
    required_check = next(
        item for item in checks["items"] if item["required"]
    )
    assert required_check["verifier_id"] == "V1"
    assert required_check["status"] == "passed"
    assert required_check["command_argv"][-1] == (
        "tests/test_continuation_provider_fixture.py"
    )
    assert "browser_fallback" not in response.text.lower()
    assert "copy_fallback" not in response.text.lower()

    duplicate = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace_id),
            "repo_path": str(tmp_path),
            "idempotency_key": "continue-switch-provider",
            "target_provider": "claude",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "continuation_duplicate"
    assert sync_calls == [(workspace_id, False)]
    runs = list(await db_session.scalars(
        select(AgentRun).where(AgentRun.workspace_id == workspace_id)
    ))
    assert len(runs) == 1


async def test_run_continuation_delivers_real_pack_and_records_lineage(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    goal = (
        "Finish app/continuation.py so prepare_continuation returns True "
        "and run the repository tests."
    )
    workspace = await _seed_session(
        db_session,
        repo,
        goal=goal,
        session_id="real-run-source",
        provider="codex",
    )
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "continuation.py").write_text(
        "def prepare_continuation():\n    return False\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_continuation.py").write_text(
        "from app.continuation import prepare_continuation\n\n"
        "def test_prepare_continuation():\n"
        "    assert prepare_continuation() is True\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    _initialize_git_repository(repo)

    received_context = tmp_path / "received-context.md"
    fake_claude = tmp_path / "fake-bin" / "claude"
    fake_claude.parent.mkdir()
    fake_claude.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n\n"
        "if sys.argv[1:4] == ['auth', 'status', '--json']:\n"
        "    print('{\"loggedIn\": true, \"authMethod\": \"claude.ai\"}')\n"
        "    raise SystemExit(0)\n\n"
        "payload = sys.stdin.read()\n"
        f"Path({str(received_context)!r}).write_text(payload, encoding='utf-8')\n"
        f"if {goal!r} not in payload or 'app/continuation.py' not in payload:\n"
        "    print('compiled continuation context was not delivered', file=sys.stderr)\n"
        "    raise SystemExit(41)\n"
        "Path('app/continuation.py').write_text(\n"
        "    'def prepare_continuation():\\n    return True\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "print('{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false}')\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0, "imported": 0, "updated": 0}

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_claude) if name == "claude" else None,
    )

    response = await client.post(
        "/api/continuations",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(repo),
            "idempotency_key": "real-pack-lineage-proof",
            "target_provider": "claude",
            "source_provider": "codex",
            "source_session_id": "real-run-source",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    preparation = body["preparation"]
    assert body["status"] == "verified_complete"
    assert preparation["objective"] == goal
    assert preparation["source_session"] == {
        "provider": "codex",
        "session_id": "real-run-source",
        "source_document_id": preparation["source_session"]["source_document_id"],
    }
    source_document_id = UUID(preparation["source_session"]["source_document_id"])
    checkpoint_id = UUID(preparation["checkpoint"]["id"])
    pack_id = UUID(preparation["context_pack_id"])
    run_id = UUID(body["run"]["run_id"])
    assert body["delivery"] == {
        "status": "delivered",
        "provider": "claude",
        "source_provider": "codex",
        "provider_switched": True,
        "mode": "fresh",
        "context_delivery": "stdin",
        "run_id": str(run_id),
        "provider_model": None,
        "provider_effort": None,
        "task_mode": "change",
        "filesystem_mode": "workspace_write",
        "command_timeout_seconds": settings.continuation_command_timeout_seconds,
        "root_run_id": str(run_id),
        "attempts": [{
            "attempt_index": 1,
            "run_id": str(run_id),
            "status": "verified_complete",
        }],
    }
    assert body["outcome"]["verified"] is True
    mandatory = body["outcome"]["mandatory"]
    assert mandatory["total"] >= 1
    assert mandatory["passed"] == mandatory["total"]
    assert mandatory["failed"] == 0
    assert mandatory["unproven"] == 0
    assert all(
        item["status"] == "passed"
        for item in body["outcome"]["requirements"]
        if item["priority"] == "must"
    )
    assert all(
        item["status"] == "passed"
        for item in body["outcome"]["evidence"]
        if item["required"]
    )
    assert body["outcome"]["changed_files"] == ["app/continuation.py"]
    assert received_context.read_text(encoding="utf-8") == (
        preparation["execution_prompt"]
    )
    assert goal in received_context.read_text(encoding="utf-8")
    assert "app/continuation.py" in received_context.read_text(encoding="utf-8")
    assert (repo / "app" / "continuation.py").read_text(encoding="utf-8") == (
        "def prepare_continuation():\n    return True\n"
    )

    checkpoint = await db_session.get(WorkCheckpoint, checkpoint_id)
    pack = await db_session.get(ContextPack, pack_id)
    run = await db_session.get(AgentRun, run_id)
    assert checkpoint is not None
    assert checkpoint.provider == "codex"
    assert checkpoint.session_id == "real-run-source"
    assert checkpoint.trigger == "continuation"
    assert checkpoint.source_document_id == source_document_id
    assert pack is not None
    manifest = json.loads(pack.manifest)
    lineage = manifest["continuation"]
    assert lineage["task_id"] == preparation["task"]["id"]
    assert lineage["checkpoint_id"] == str(checkpoint.id)
    assert lineage["source_document_id"] == str(checkpoint.source_document_id)
    assert lineage["provider"] == "codex"
    assert lineage["session_id"] == "real-run-source"
    assert run is not None
    assert run.workspace_id == workspace.id
    assert run.context_pack_id == pack.id
    assert run.tool == "daemonstate:claude"
    assert run.objective == goal
    assert run.status == "completed"
    assert run.ended_at is not None

    observations = list(await db_session.scalars(
        select(RunObservation)
        .where(RunObservation.agent_run_id == run.id)
        .order_by(RunObservation.created_at, RunObservation.id)
    ))
    assert {item.event_type for item in observations} == {
        "command",
        "patch_summary",
        "verification",
        "outcome",
        "provider_event",
    }
    assert all(item.source_document_id is not None for item in observations)
    verification = next(
        item for item in observations if item.event_type == "verification"
    )
    assert verification.exit_code == 0
    assert "pytest" in str(verification.command)
    outcome = next(item for item in observations if item.event_type == "outcome")
    outcome_payload = json.loads(outcome.payload_json)
    assert outcome_payload["status"] == "completed"
    assert outcome_payload["verification_results"]
    assert all(
        item["exit_code"] == 0
        for item in outcome_payload["verification_results"]
    )


async def test_run_continuation_uses_a_fresh_same_provider_when_needed(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Continue without asking the user to route the handoff",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="same-provider-source",
        provider="codex",
    )
    _initialize_git_repository(tmp_path)
    fake_codex = _fake_executable(tmp_path, "codex")
    fake_claude = _fake_executable(tmp_path, "claude")
    runner_calls = {}
    launched_sessions = []
    visible_before_completion = []

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    def fake_which(executable):
        if executable == "codex":
            return str(fake_codex)
        if executable == "claude":
            return str(fake_claude)
        return None

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            runner_calls.update(kwargs)
            await kwargs["stdout_chunk_observer"](
                b'{"type":"thread.started",'
                b'"thread_id":"019f9a4d-f586-79d3-b305-4844518003bd"}\n'
            )
            await kwargs["stdout_chunk_observer"](
                b'{"type":"turn.started"}\n'
                b'{"type":"item.completed","item":{'
                b'"id":"item-1","type":"agent_message",'
                b'"text":"Starting the visible continuation."}}\n'
            )
            visible_before_completion.append(bool(launched_sessions))
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="completed",
                changed_files=(),
                check_exit_code=0,
                cwd=tmp_path,
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )
    monkeypatch.setattr(
        "app.services.harness_sessions.launch_harness_session",
        lambda provider, session_id, **_kwargs: (
            launched_sessions.append((provider, session_id))
            or {
                "launched": True,
                "mode": "desktop_app",
                "navigation": "session",
                "exact_session_supported": True,
            }
        ),
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "verified_complete"
    assert body["delivery"]["provider"] == "codex"
    assert body["delivery"]["provider_switched"] is False
    assert body["delivery"]["mode"] == "fresh"
    assert body["delivery"]["harness_session"] == {
        "provider": "codex",
        "session_id": "019f9a4d-f586-79d3-b305-4844518003bd",
        "launched": True,
        "navigation_requested": True,
        "navigation_verified": False,
        "mode": "desktop_app",
        "navigation": "session",
        "exact_session_supported": True,
        "renderable_activity_observed": True,
    }
    assert launched_sessions == [
        ("codex", "019f9a4d-f586-79d3-b305-4844518003bd")
    ]
    assert visible_before_completion == [True]
    assert "resume" not in runner_calls["command"]
    assert body["outcome"]["mandatory"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "unproven": 0,
    }


async def test_repair_repository_drift_closes_the_child_run(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Repair the continuation after a failed verifier",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="repair-drift-cleanup",
    )
    _initialize_git_repository(tmp_path)
    fake_codex = _fake_executable(tmp_path, "codex")
    calls = 0

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    class DriftOnRepairRunner:
        def __init__(self, session):
            self.session = session

        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            run = await self.session.get(
                AgentRun,
                UUID(str(kwargs["run_id"])),
            )
            assert run is not None
            if calls == 2:
                raise RepositoryStateChangedError("expected", "observed")
            await kwargs["stdout_chunk_observer"](
                b'{"type":"thread.started",'
                b'"thread_id":"019f9a4d-f586-79d3-b305-4844518003bd"}\n'
            )
            run.status = "completed"
            run.ended_at = utc_now()
            await self.session.commit()
            return _fake_harness_result(
                run_id=str(run.id),
                status="completed",
                changed_files=(),
                check_exit_code=1,
                cwd=tmp_path,
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_codex) if name == "codex" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        DriftOnRepairRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "codex",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked_external"
    assert body["outcome"]["blocker"]["code"] == (
        "continuation_repository_changed"
    )
    runs = list(await db_session.scalars(
        select(AgentRun)
        .where(AgentRun.workspace_id == workspace.id)
        .order_by(AgentRun.attempt_index)
    ))
    assert len(runs) == 2
    assert runs[1].parent_agent_run_id == runs[0].id
    assert runs[1].attempt_index == 2
    assert runs[1].status == "failed"
    assert runs[1].ended_at is not None
    assert body["delivery"]["attempts"][-1] == {
        "attempt_index": 2,
        "run_id": str(runs[1].id),
        "status": "execution_failed",
    }


async def test_run_continuation_preserves_exact_source_during_drift_reprepare(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[dict] = []
    pack_ids = [uuid4(), uuid4()]

    class FakeContinuationService:
        def __init__(self, _session):
            pass

        async def prepare(self, **kwargs):
            calls.append(kwargs)
            fingerprint = (
                "compiled-before-drift"
                if len(calls) == 1
                else "repository-after-drift"
            )
            return SimpleNamespace(
                objective="Continue the exact source after repository drift.",
                task={"workflow": {}},
                source_session={
                    "provider": "claude",
                    "session_id": "pinned-source",
                },
                checkpoint=None,
                verification=None,
                repository={
                    "path": str(tmp_path),
                    "current": {"status_fingerprint": fingerprint},
                },
                readiness={
                    "status": "ready",
                    "blocking_issues": [],
                    "affected_tasks": [],
                },
                attention=[],
                context_pack_id=str(pack_ids[min(len(calls) - 1, 1)]),
            )

    async def repository_after_drift(_repo_path):
        return SimpleNamespace(status_fingerprint="repository-after-drift")

    async def stop_after_reprepare(**_kwargs):
        raise ValueError("stopped after drift reprepare")

    async def valid_prepared_execution(*_args, **_kwargs):
        return SimpleNamespace(
            prompt_markdown="execution prompt",
            contract_sha256="a" * 64,
            prompt_sha256="b" * 64,
        ), SimpleNamespace()

    monkeypatch.setattr(
        "app.services.continuation_runtime.ContinuationService",
        FakeContinuationService,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.capture_repository_snapshot",
        repository_after_drift,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime._prepared_execution",
        valid_prepared_execution,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.evaluate_continuation_quality",
        lambda *_args, **_kwargs: SimpleNamespace(
            launchable=True,
            to_dict=lambda: {"launchable": True, "issues": []},
        ),
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime._select_ready_invocation",
        stop_after_reprepare,
    )

    response = await client.post(
        "/api/continuations",
        json={
            "workspace_id": str(uuid4()),
            "repo_path": str(tmp_path),
            "source_provider": "claude_code",
            "source_session_id": "pinned-source",
            "target_provider": "claude",
        },
    )

    assert response.status_code == 422, response.text
    assert len(calls) == 2
    assert [item["sync_sessions"] for item in calls] == [True, False]
    assert all(item["source_provider"] == "claude" for item in calls)
    assert all(item["source_session_id"] == "pinned-source" for item in calls)


async def test_run_continuation_recompiles_a_transient_truncated_baseline(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[dict] = []

    class FakeContinuationService:
        def __init__(self, _session):
            pass

        async def prepare(self, **kwargs):
            calls.append(kwargs)
            truncated = len(calls) == 1
            issue = {
                "code": "repository_baseline_truncated",
                "severity": "blocking",
                "blocks_current_execution": True,
            }
            return SimpleNamespace(
                objective="Continue after a transient baseline capture race.",
                checkpoint=None,
                repository={
                    "path": str(tmp_path),
                    "current": {
                        "status_fingerprint": (
                            "truncated" if truncated else "complete"
                        ),
                    },
                },
                quality_report={
                    "launchable": not truncated,
                    "issues": [issue] if truncated else [],
                    "blocking_issues": [issue] if truncated else [],
                },
                readiness={
                    "status": "blocked" if truncated else "ready",
                    "blocking_issues": [issue] if truncated else [],
                    "affected_tasks": [],
                },
            )

    async def complete_repository(_repo_path):
        return SimpleNamespace(
            status_fingerprint="complete",
            status_truncated=False,
        )

    async def stop_after_refresh(*_args, **_kwargs):
        raise ValueError("stopped after baseline refresh")

    monkeypatch.setattr(
        "app.services.continuation_runtime.ContinuationService",
        FakeContinuationService,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.capture_repository_snapshot",
        complete_repository,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime._prepared_execution",
        stop_after_refresh,
    )

    response = await client.post(
        "/api/continuations",
        json={
            "workspace_id": str(uuid4()),
            "repo_path": str(tmp_path),
            "target_provider": "codex",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["message"] == (
        "stopped after baseline refresh"
    )
    assert len(calls) == 2
    assert [item["sync_sessions"] for item in calls] == [True, False]


async def test_run_continuation_fails_safely_when_no_agent_cli_is_installed(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Do not pretend a handoff happened without a target agent",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="no-provider",
        provider="codex",
    )
    _initialize_git_repository(tmp_path)

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _executable: None,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.CODEX_APP_EXECUTABLES",
        (),
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
        },
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]["code"]
        == "continuation_provider_unavailable"
    )
    runs = list(await db_session.scalars(
        select(AgentRun).where(AgentRun.workspace_id == workspace.id)
    ))
    assert runs == []


async def test_provider_readiness_endpoint_returns_structured_local_status(
    client,
    monkeypatch,
) -> None:
    statuses = {
        "codex": _provider_status(
            "codex",
            ready=False,
            status="unavailable",
            code="provider_cli_broken",
            message="Codex CLI wrapper is broken.",
            action="Reinstall Codex.",
        ),
        "claude": _provider_status(
            "claude",
            ready=False,
            status="authentication_required",
            code="provider_authentication_revoked",
            message="Claude Code OAuth token has been revoked (401).",
            action="Run `claude auth login` and try again.",
        ),
        "opencode": _provider_status("opencode"),
    }
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: statuses[provider],
    )

    response = await client.get(
        f"/api/continuations/providers?workspace_id={uuid4()}"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "active_run": None,
        "latest_run": None,
        "staged_handoff": None,
        "providers": [
            {
                **statuses[name].to_dict(),
                "capabilities": provider_capabilities(name).to_dict(),
            }
            for name in ("codex", "claude", "opencode")
        ],
    }


async def test_stage_requires_a_lead_or_exact_source_boundary(client) -> None:
    response = await client.post(
        "/api/continuations/stage",
        json={
            "workspace_id": str(uuid4()),
            "target_provider": "codex",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "continuation_lead_required"
    assert "unknown future instruction" in response.json()["detail"]["message"]


async def test_stage_continuation_loads_context_and_waits_without_execution(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = (
        "Make the carried Project Context clear and visually polished for the "
        "confirmed lead."
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="waiting-handoff-source",
        provider="codex",
    )
    _initialize_git_repository(tmp_path)
    fake_codex = _fake_executable(tmp_path, "codex")
    staged_calls: list[dict[str, object]] = []
    launch_calls: list[tuple[str, str, str | None]] = []
    thread_id = "019f9a4d-f586-79d3-b305-4844518003bd"

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0, "imported": 0, "updated": 0}

    async def fake_stage(**kwargs):
        staged_calls.append(kwargs)
        return SimpleNamespace(
            thread_id=thread_id,
            context_delivery="thread_history_and_developer_instructions",
            context_sha256=hashlib.sha256(
                kwargs["context_message"].encode("utf-8")
            ).hexdigest(),
            developer_instructions_sha256="d" * 64,
            execution_started=False,
            activation_boundary_verified=True,
            observed_turn_count=0,
        )

    def fake_launch(provider: str, session_id: str, *, cwd: str | None = None):
        launch_calls.append((provider, session_id, cwd))
        return {
            "launched": True,
            "navigation_requested": True,
            "navigation_verified": False,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
        }

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: _provider_status(provider),
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.CODEX_APP_EXECUTABLES",
        (),
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_codex) if name == "codex" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.stage_codex_thread",
        fake_stage,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.launch_harness_session",
        fake_launch,
    )
    baseline = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    response = await client.post(
        "/api/continuations/stage",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "idempotency_key": "stage-context-and-wait",
            "target_provider": "codex",
            "source_provider": "codex",
            "source_session_id": "waiting-handoff-source",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "continuation.stage.v1"
    assert body["status"] == "awaiting_user"
    assert body["execution_started"] is False
    assert body["delivery"]["status"] == "awaiting_user"
    assert body["delivery"]["activation"] == "next_user_turn"
    assert body["delivery"]["execution_started"] is False
    assert body["delivery"]["activation_boundary_verified"] is True
    assert body["delivery"]["observed_turn_count"] == 0
    assert body["delivery"]["run_id"] == body["run"]["run_id"]
    assert body["delivery"]["harness_session"]["session_id"] == thread_id
    assert body["delivery"]["harness_session"]["awaiting_user"] is True
    assert (
        body["delivery"]["harness_session"]["execution_started"]
        is False
    )
    assert body["preparation"]["quality_report"]["launchable"] is False
    assert body["preparation"]["project_context"]["copy_ready"] is True
    assert any(
        issue["code"] == "mandatory_requirement_verification_unexecutable"
        for issue in body["preparation"]["quality_report"]["issues"]
    )
    assert len(staged_calls) == 1
    staged_context = str(staged_calls[0]["context_message"])
    assert "## Context" in staged_context
    assert "## Direction" in staged_context
    assert "## Execution loop" not in staged_context
    assert goal in staged_context
    assert "Retrieval boundary:" not in staged_context
    assert "next user lead" not in staged_context
    assert "future instruction" not in staged_context
    assert "Inspect → implement → test → fix → verify" not in staged_context
    assert staged_context.count("Activation boundary:") == 1
    assert "### First action" in staged_context
    assert "### Definition of done" in staged_context
    assert "Complete the immediate task" not in staged_context
    assert launch_calls == [("codex", thread_id, str(tmp_path))]
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout == baseline

    run = await db_session.get(AgentRun, UUID(body["run"]["run_id"]))
    assert run is not None
    assert run.status == "awaiting_user"
    assert run.ended_at is None
    assert run.provider_session_id == thread_id
    assert run.continuation_execution_id is None
    observations = list(await db_session.scalars(
        select(RunObservation).where(RunObservation.agent_run_id == run.id)
    ))
    assert [item.event_key for item in observations] == ["harness:session"]

    providers = await client.get(
        f"/api/continuations/providers?workspace_id={workspace.id}"
    )
    assert providers.status_code == 200, providers.text
    provider_body = providers.json()
    assert provider_body["active_run"] is None
    assert provider_body["latest_run"] is None
    codex_provider = next(
        item
        for item in provider_body["providers"]
        if item["provider"] == "codex"
    )
    assert codex_provider["context_staging_supported"] is True
    staged_handoff = provider_body["staged_handoff"]
    assert staged_handoff["status"] == "awaiting_user"
    assert staged_handoff["delivery"]["status"] == "awaiting_user"
    assert staged_handoff["delivery"]["run_id"] == str(run.id)
    assert staged_handoff["delivery"]["context_delivery"] == (
        "thread_history_and_developer_instructions"
    )
    assert staged_handoff["delivery"]["harness_session"]["session_id"] == thread_id
    assert (
        staged_handoff["context_package"]["continuation_identity"][
            "selected_objective"
        ]
        == goal
    )

    source_document = await db_session.scalar(
        select(SourceDocument)
        .where(SourceDocument.workspace_id == workspace.id)
        .limit(1)
    )
    assert source_document is not None
    activated_at = utc_now()
    db_session.add(SessionEvent(
        workspace_id=workspace.id,
        source_document_id=source_document.id,
        provider="codex",
        session_id=thread_id,
        provider_event_id="waiting-thread-user-lead",
        sequence_number=1,
        event_type="user_message",
        role="user",
        occurred_at=activated_at,
        content="Finish the remaining UI work and verify it.",
        payload_json=json.dumps({"type": "user_message"}),
        content_sha256=hashlib.sha256(
            b"Finish the remaining UI work and verify it."
        ).hexdigest(),
    ))
    await db_session.commit()

    activated = await client.get(
        f"/api/continuations/providers?workspace_id={workspace.id}"
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["staged_handoff"] is None
    assert activated.json()["latest_run"] is None
    await db_session.refresh(run)
    assert run.status == "handed_off"
    assert run.ended_at == activated_at


async def test_running_continuation_is_reported_and_blocks_a_duplicate_workspace_run(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Active continuation guard",
        slug=f"active-continuation-{uuid4().hex[:8]}",
    )
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective="Finish the existing OpenCode continuation.",
        markdown="# Active continuation\n",
        manifest=json.dumps({"schema_version": "context_pack.v2"}),
        repo_state_json="{}",
        idempotency_key=f"active-pack-{uuid4()}",
    )
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key=f"continuation:{uuid4().hex}",
        tool="daemonstate:opencode",
        model="opencode/big-pickle",
        objective=pack.objective,
        started_at=utc_now(),
        status="running",
    )
    db_session.add_all([workspace, pack, run])
    await db_session.commit()
    workspace_id = workspace.id
    run_id = run.id
    run_started_at = run.started_at
    objective = pack.objective

    status = _provider_status("opencode")
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: status,
    )

    providers = await client.get(
        f"/api/continuations/providers?workspace_id={workspace_id}"
    )
    duplicate = await client.post(
        "/api/continuations",
        json={
            "workspace_id": str(workspace_id),
            "repo_path": str(tmp_path),
            "idempotency_key": "different-browser-click",
            "target_provider": "opencode",
        },
    )

    assert providers.status_code == 200, providers.text
    assert providers.json()["active_run"] == {
        "run_id": str(run_id),
        "provider": "opencode",
        "model": "opencode/big-pickle",
        "objective": objective,
        "status": "running",
        "started_at": f"{run_started_at.isoformat()}Z",
        "phase": "starting_harness",
    }
    assert duplicate.status_code == 409, duplicate.text
    detail = duplicate.json()["detail"]
    assert detail["code"] == "continuation_already_running"
    assert detail["blocker"]["title"] == "Continuation already running"
    assert detail["blocker"]["active_run"]["run_id"] == str(run_id)
    assert "No duplicate agent was started" in detail["blocker"]["message"]
    runs = list(await db_session.scalars(
        select(AgentRun).where(AgentRun.workspace_id == workspace_id)
    ))
    assert [item.id for item in runs] == [run_id]

    run.status = "failed"
    run.ended_at = utc_now()
    await db_session.commit()

    terminal = await client.get(
        f"/api/continuations/providers?workspace_id={workspace_id}"
    )

    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["active_run"] is None
    latest = terminal.json()["latest_run"]
    assert latest["run_id"] == str(run_id)
    assert latest["provider"] == "opencode"
    assert latest["status"] == "failed"
    assert latest["verified_success"] is False
    assert latest["outcome_summary"] == (
        "The run ended before a local harness outcome was recorded."
    )


async def test_local_action_endpoints_reject_remote_clients_even_with_forwarding(
    client,
    monkeypatch,
) -> None:
    async def must_not_probe():
        raise AssertionError("remote provider request must be rejected first")

    class MustNotRun:
        def __init__(self, _session):
            raise AssertionError("remote continuation request must be rejected first")

    monkeypatch.setattr(
        "app.api.continuations.provider_readiness",
        must_not_probe,
    )
    monkeypatch.setattr(
        "app.api.continuations.ContinuationRunService",
        MustNotRun,
    )
    monkeypatch.setattr(
        "app.api.continuations.ContinuationStageService",
        MustNotRun,
    )
    monkeypatch.setattr(
        "app.api.continuations.ContinuationService",
        MustNotRun,
    )
    transport = ASGITransport(
        app=app,
        client=("203.0.113.42", 43123),
    )
    async with AsyncClient(
        transport=transport,
        base_url="http://daemonstate.test",
    ) as remote:
        providers = await remote.get(
            "/api/continuations/providers",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
            },
        )
        run = await remote.post(
            "/api/continuations/run",
            json={"workspace_id": str(uuid4())},
            headers={
                "Forwarded": "for=127.0.0.1",
                "X-Forwarded-For": "127.0.0.1",
            },
        )
        stage = await remote.post(
            "/api/continuations/stage",
            json={"workspace_id": str(uuid4())},
            headers={
                "Forwarded": "for=127.0.0.1",
                "X-Forwarded-For": "127.0.0.1",
            },
        )
        sync_prepare = await remote.post(
            "/api/continuations/prepare",
            json={
                "workspace_id": str(uuid4()),
                "sync_sessions": True,
            },
            headers={"X-Forwarded-For": "127.0.0.1"},
        )

    for response in (providers, run, stage, sync_prepare):
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "local_action_required"
        assert "loopback" in response.json()["detail"]["message"]


async def test_explicit_provider_selection_never_falls_back(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Continue only in the provider selected by the user",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="explicit-provider",
    )
    _initialize_git_repository(tmp_path)

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    statuses = {
        "codex": _provider_status("codex"),
        "claude": _provider_status(
            "claude",
            ready=False,
            status="authentication_required",
            code="provider_authentication_revoked",
            message=(
                "Claude Code authentication failed because its OAuth token "
                "has been revoked (401)."
            ),
            action="Run `claude auth login` and try again.",
        ),
        "opencode": _provider_status("opencode"),
    }
    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: statuses[provider],
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "claude",
        },
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "continuation_provider_not_ready"
    assert detail["readiness"] == statuses["claude"].to_dict()
    assert detail["blocker"] == {
        "code": "provider_authentication_revoked",
        "provider": "claude",
        "message": statuses["claude"].message,
        "action": statuses["claude"].action,
        "affected_tasks": [goal],
    }
    runs = list(await db_session.scalars(
        select(AgentRun).where(AgentRun.workspace_id == workspace.id)
    ))
    assert runs == []


async def test_provider_readiness_is_rechecked_immediately_before_launch(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Do not launch after provider readiness changes",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="readiness-recheck",
    )
    _initialize_git_repository(tmp_path)
    fake_codex = _fake_executable(tmp_path, "codex")
    calls = 0

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    def changing_readiness(_provider, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _provider_status("codex")
        return _provider_status(
            "codex",
            ready=False,
            status="authentication_required",
            code="provider_authentication_required",
            message="Codex is not authenticated.",
            action="Run `codex login` and try again.",
        )

    class MustNotLaunchRunner:
        def __init__(self, _session):
            raise AssertionError("readiness changed; runner must not launch")

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        changing_readiness,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_codex) if name == "codex" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        MustNotLaunchRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "codex",
        },
    )

    assert response.status_code == 409, response.text
    assert calls == 2
    assert (
        response.json()["detail"]["blocker"]["code"]
        == "provider_authentication_required"
    )
    run = await db_session.scalar(
        select(AgentRun).where(AgentRun.workspace_id == workspace.id)
    )
    assert run is not None
    assert run.status == "failed"


async def test_revoked_child_auth_failure_returns_a_blocked_outcome(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Carry the full task context into Claude Code",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="revoked-child-auth",
        provider="codex",
    )
    _initialize_git_repository(tmp_path)
    fake_claude = _fake_executable(tmp_path, "claude")

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="failed",
                changed_files=(),
                check_exit_code=None,
                cwd=tmp_path,
                command_exit_code=1,
                command_stderr=(
                    "Claude authentication failed: OAuth token has been "
                    "revoked (401 Unauthorized)"
                ),
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_claude) if name == "claude" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "claude",
        },
    )

    assert response.status_code == 200, response.text
    outcome = response.json()["outcome"]
    assert response.json()["status"] == "blocked_external"
    assert outcome["status"] == "blocked_external"
    assert outcome["verified"] is False
    assert outcome["blocker"] == {
        "code": "provider_authentication_revoked",
        "provider": "claude",
        "message": (
            "Claude Code authentication failed because its OAuth token "
            "has been revoked (401)."
        ),
        "action": "Run `claude auth login` and try again.",
        "affected_tasks": [goal],
    }


async def test_opencode_credits_error_returns_a_billing_required_blocker(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Continue the task with the configured OpenCode model",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="opencode-billing-required",
    )
    _initialize_git_repository(tmp_path)
    fake_opencode = _fake_executable(tmp_path, "opencode")

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="failed",
                changed_files=(),
                check_exit_code=None,
                cwd=tmp_path,
                command_exit_code=0,
                command_stdout=json.dumps({
                    "type": "error",
                    "error": {
                        "name": "AI_APICallError",
                        "data": {
                            "message": "Insufficient balance.",
                            "statusCode": 401,
                            "responseBody": json.dumps({
                                "type": "error",
                                "error": {
                                    "type": "CreditsError",
                                    "message": (
                                        "Insufficient balance. Manage your billing."
                                    ),
                                },
                            }),
                        },
                    },
                }),
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_opencode) if name == "opencode" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: _provider_status(provider),
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "opencode",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked_external"
    assert body["outcome"]["status"] == "blocked_external"
    assert body["outcome"]["blocker"] == {
        "code": "provider_billing_required",
        "provider": "opencode",
        "message": (
            "OpenCode cannot use the selected model because its provider "
            "account has insufficient balance or billing is not enabled."
        ),
        "action": (
            "Add credits or enable billing for that OpenCode provider, or "
            "choose another configured model."
        ),
        "affected_tasks": [goal],
    }


async def test_opencode_http_500_returns_a_service_unavailable_blocker(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Retry the task without hiding an OpenCode provider outage",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="opencode-service-unavailable",
    )
    _initialize_git_repository(tmp_path)
    fake_opencode = _fake_executable(tmp_path, "opencode")

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="failed",
                changed_files=(),
                check_exit_code=None,
                cwd=tmp_path,
                command_exit_code=0,
                command_stdout=json.dumps({
                    "type": "error",
                    "error": {
                        "name": "AI_APICallError",
                        "data": {
                            "message": "Internal server error",
                            "statusCode": 500,
                        },
                        "requestBodyValues": {
                            "messages": [{
                                "role": "user",
                                "content": "Fix the repository billing workflow.",
                            }],
                        },
                    },
                }),
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_opencode) if name == "opencode" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        lambda provider, **_kwargs: _provider_status(provider),
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "opencode",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked_external"
    assert body["outcome"]["status"] == "blocked_external"
    assert body["outcome"]["blocker"] == {
        "code": "provider_service_unavailable",
        "provider": "opencode",
        "message": (
            "OpenCode's selected model provider is temporarily unavailable "
            "(HTTP 500)."
        ),
        "action": "Retry later or choose another configured model.",
        "affected_tasks": [goal],
    }


async def test_outdated_codex_cli_returns_the_exact_model_blocker(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Continue the verified harness workflow in Codex",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="outdated-codex-cli",
    )
    _initialize_git_repository(tmp_path)
    fake_codex = _fake_executable(tmp_path, "codex")

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    provider_error = json.dumps({
        "type": "error",
        "status": 400,
        "error": {
            "type": "invalid_request_error",
            "message": (
                "The 'gpt-5.6-sol' model requires a newer version of Codex. "
                "Please upgrade to the latest app or CLI and try again."
            ),
        },
    })

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="failed",
                changed_files=(),
                check_exit_code=None,
                cwd=tmp_path,
                command_exit_code=1,
                command_stdout=json.dumps({
                    "type": "error",
                    "message": provider_error,
                }),
                command_stderr=(
                    "ERROR codex_models_manager::cache: failed to load models "
                    "cache: missing field `supports_reasoning_summaries`"
                ),
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_codex) if name == "codex" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "codex",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked_external"
    assert body["outcome"]["blocker"] == {
        "code": "provider_cli_update_required",
        "provider": "codex",
        "message": (
            "Codex could not start because the installed CLI is too old for "
            "the configured `gpt-5.6-sol` model."
        ),
        "action": (
            "Upgrade Codex CLI or configure DaemonState to use a current "
            "Codex executable, then retry."
        ),
        "affected_tasks": [goal],
    }


async def test_failed_agent_stdout_mentioning_401_is_not_an_auth_blocker(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    goal = _verifiable_provider_goal(
        tmp_path,
        "Fix the task API's revoked-token regression test",
    )
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal=goal,
        session_id="task-output-mentions-auth",
    )
    _initialize_git_repository(tmp_path)
    fake_claude = _fake_executable(tmp_path, "claude")

    async def fake_sync(*_args, **_kwargs):
        return {"failed": 0}

    class FakeRunner:
        def __init__(self, _session):
            pass

        async def run(self, **kwargs):
            return _fake_harness_result(
                run_id=str(kwargs["run_id"]),
                status="failed",
                changed_files=(),
                check_exit_code=None,
                cwd=tmp_path,
                command_exit_code=1,
                command_stdout=(
                    "AssertionError: expected the task API response to say "
                    "'401 Unauthorized: OAuth token revoked'."
                ),
                command_stderr="pytest exited with one failed test.",
            )

    monkeypatch.setattr(
        "app.services.continuation.sync_local_session_library",
        fake_sync,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: str(fake_claude) if name == "claude" else None,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        FakeRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path),
            "target_provider": "claude",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["outcome"]["blocker"] == {
        "code": "provider_run_failed",
        "provider": "claude",
        "message": "Claude Code failed to complete the continuation with exit code 1.",
        "action": "Inspect the Claude Code run details and retry.",
        "affected_tasks": [goal],
    }


async def test_run_continuation_does_not_launch_a_truly_blocked_checkpoint(
    client,
    monkeypatch,
) -> None:
    class FakeContinuationService:
        def __init__(self, _session):
            pass

        async def prepare(self, **_kwargs):
            return SimpleNamespace(
                objective="Implement Feature 3.",
                task={
                    "workflow": {
                        "execution_task": {
                            "id": "feature-3",
                            "title": "Feature 3",
                        },
                        "selected_intent": {
                            "id": "feature-4",
                            "title": "Feature 4",
                        },
                        "affected_tasks": [{
                            "id": "feature-5",
                            "title": "Feature 5",
                        }],
                    },
                },
                readiness={
                    "status": "blocked",
                    "blocking_issues": [{
                        "code": "dependency_prerequisite_not_actionable",
                        "message": (
                            '"Feature 4" cannot continue because prerequisite '
                            '"Feature 3" is paused.'
                        ),
                        "blocker": {
                            "id": "feature-3",
                            "title": "Feature 3",
                        },
                        "blocking_tasks": [{
                            "id": "feature-3",
                            "title": "Feature 3",
                        }],
                        "affected_tasks": [
                            {"id": "feature-3", "title": "Feature 3"},
                            {"id": "feature-4", "title": "Feature 4"},
                            {"id": "feature-5", "title": "Feature 5"},
                        ],
                    }],
                },
                checkpoint={"continuation_status": "blocked"},
                attention=[],
            )

    class MustNotLaunchRunner:
        def __init__(self, _session):
            raise AssertionError("a blocked continuation must not create a runner")

    monkeypatch.setattr(
        "app.services.continuation_runtime.ContinuationService",
        FakeContinuationService,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.LocalHarnessRunner",
        MustNotLaunchRunner,
    )

    response = await client.post(
        "/api/continuations/run",
        json={"workspace_id": str(uuid4())},
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]["code"]
        == "continuation_preparation_blocked"
    )
    assert response.json()["detail"]["blocker"] == {
        "code": "dependency_prerequisite_not_actionable",
        "title": "Feature 3 blocks this continuation",
        "provider": None,
        "message": (
            '"Feature 4" cannot continue because prerequisite '
            '"Feature 3" is paused.'
        ),
        "action": "Make the blocking prerequisite actionable, then retry.",
        "blocking_tasks": [{"id": "feature-3", "title": "Feature 3"}],
        "affected_tasks": [
            {"id": "feature-3", "title": "Feature 3"},
            {"id": "feature-4", "title": "Feature 4"},
            {"id": "feature-5", "title": "Feature 5"},
        ],
        "applicability": None,
    }


async def test_run_continuation_is_local_only(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = await _seed_session(
        db_session,
        tmp_path,
        goal="Keep local agent execution on the local machine.",
        session_id="remote-run",
    )

    async def remote_scope() -> AccessScope:
        return AccessScope(
            principal_id="remote-user",
            workspace_ids=frozenset({workspace.id}),
        )

    app.dependency_overrides[get_access_scope] = remote_scope
    response = await client.post(
        "/api/continuations/run",
        json={"workspace_id": str(workspace.id), "repo_path": str(tmp_path)},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "local_action_required"
    app.dependency_overrides.pop(get_access_scope, None)


def _verifiable_provider_goal(repo_path: Path, statement: str) -> str:
    """Give provider-path tests one real, task-linked deterministic verifier."""

    test_path = repo_path / "tests" / "test_continuation_provider_fixture.py"
    test_path.parent.mkdir(exist_ok=True)
    test_path.write_text(
        "def test_continuation_provider_fixture():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    return (
        f"{statement.rstrip().rstrip('.')} as checked by "
        "tests/test_continuation_provider_fixture.py."
    )


def _initialize_git_repository(repo_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), "init", "-q"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "continuation@example.test"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Continuation Test"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "add", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "fixture"],
        check=True,
        capture_output=True,
        text=True,
    )


def _fake_executable(tmp_path: Path, name: str) -> Path:
    executable = tmp_path / "fake-bin" / name
    executable.parent.mkdir(exist_ok=True)
    readiness = {
        "codex": (
            'if [ "$1 $2" = "login status" ]; then\n'
            '  printf "Logged in using ChatGPT\\n"\n'
            "  exit 0\n"
            "fi\n"
        ),
        "claude": (
            'if [ "$1 $2 $3" = "auth status --json" ]; then\n'
            '  printf \'{"loggedIn": true, "authMethod": "claude.ai"}\\n\'\n'
            "  exit 0\n"
            "fi\n"
        ),
        "opencode": (
            'if [ "$1 $2" = "auth list" ]; then\n'
            '  printf "1 credential\\n"\n'
            "  exit 0\n"
            "fi\n"
        ),
    }.get(name, "")
    executable.write_text(
        f"#!/bin/sh\n{readiness}exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _fake_harness_result(
    *,
    run_id: str,
    status: str,
    changed_files: tuple[str, ...],
    check_exit_code: int | None,
    cwd: Path,
    command_exit_code: int | None = None,
    command_stdout: str = "",
    command_stderr: str = "",
    command_timed_out: bool = False,
):
    verification_results = ()
    serialized_checks = []
    if check_exit_code is not None:
        command_result = SimpleNamespace(
            exit_code=check_exit_code,
            timed_out=False,
        )
        verification_results = (SimpleNamespace(
            requirement_id="V1",
            command="python3 -m pytest -q",
            cwd=str(cwd),
            result=command_result,
        ),)
        serialized_checks = [{
            "requirement_id": "V1",
            "command": "python3 -m pytest -q",
            "cwd": str(cwd),
            "result": {"exit_code": check_exit_code, "timed_out": False},
        }]
    payload = {
        "context_pack_id": str(uuid4()),
        "run_id": run_id,
        "status": status,
        "changed_files": list(changed_files),
        "verification_results": serialized_checks,
    }
    command_result = SimpleNamespace(
        exit_code=(
            command_exit_code
            if command_exit_code is not None
            else (1 if status == "failed" else 0)
        ),
        stdout=command_stdout,
        stderr=command_stderr,
        timed_out=command_timed_out,
    )
    repository_before = SimpleNamespace(
        branch="main",
        head_commit="a" * 40,
        status_fingerprint="a" * 64,
    )
    repository_after = SimpleNamespace(
        branch="main",
        head_commit="b" * 40 if changed_files else "a" * 40,
        status_fingerprint="b" * 64 if changed_files else "a" * 64,
    )
    return SimpleNamespace(
        status=status,
        command=command_result,
        repository_before=repository_before,
        repository_after=repository_after,
        agent_changed_files=changed_files,
        changed_files=changed_files,
        verification_results=verification_results,
        runtime_bundle_integrity_passed=True,
        preservation_passed=True,
        to_dict=lambda: payload,
    )


def _provider_status(
    provider: str,
    *,
    ready: bool = True,
    status: str = "ready",
    code: str = "provider_ready",
    message: str | None = None,
    action: str | None = None,
) -> ProviderReadiness:
    return ProviderReadiness(
        provider=provider,
        ready=ready,
        status=status,
        code=code,
        message=message or f"{provider} is ready.",
        action=action or f"Continue in {provider}.",
        desktop_available=True,
        exact_session_supported=True,
    )


async def _seed_session(
    db_session,
    repo_path: Path,
    *,
    goal: str,
    session_id: str,
    provider: str = "codex",
    occurred_at: str | None = None,
    workspace: Workspace | None = None,
) -> Workspace:
    (repo_path / "app").mkdir(exist_ok=True)
    (repo_path / "app" / "continuation.py").write_text(
        "def prepare_continuation():\n    return True\n",
        encoding="utf-8",
    )
    (repo_path / "pyproject.toml").write_text(
        "[project]\nname = 'continuation-fixture'\n",
        encoding="utf-8",
    )
    if workspace is None:
        workspace = Workspace(
            id=uuid4(),
            name=f"Continuation {session_id}",
            slug=f"continuation-{session_id}-{uuid4().hex[:8]}",
        )
        db_session.add(workspace)
    content = (
        f"[USER]\n{goal}\n\n"
        "[ASSISTANT]\n"
        "Progress: the agent reports that initial discovery is complete.\n"
        "Next action: inspect app/continuation.py and implement the remaining work."
    )
    source_identity = hashlib.sha256(
        f"{workspace.id}:{provider}:{session_id}".encode("utf-8")
    ).hexdigest()
    document = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"{provider}:session:{session_id}",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_identity_sha256=source_identity,
        revision_number=1,
        trust_zone="semi_trusted_tool",
        metadata_json=json.dumps(
            {
                "workspace_id": str(workspace.id),
                "connector_type": provider,
                "tool": provider,
                "session_id": session_id,
                "cwd": str(repo_path),
                "source_path": str(repo_path / f"{session_id}.jsonl"),
            }
        ),
    )
    db_session.add(document)
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider=provider,
        session_id=session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{provider}:{session_id}:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at=occurred_at,
                content=goal,
                payload={"cwd": str(repo_path)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{provider}:{session_id}:assistant",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                occurred_at=occurred_at,
                content=(
                    "Progress: the agent reports that initial discovery is complete. "
                    "Next action: inspect app/continuation.py and implement the remaining work."
                ),
                payload={"cwd": str(repo_path)},
            ),
        ],
    )
    await db_session.flush()
    return workspace


def _test_png(rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            len(content).to_bytes(4, "big")
            + kind
            + content
            + (zlib.crc32(kind + content) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
        + chunk(b"IEND", b"")
    )
