from __future__ import annotations

from types import SimpleNamespace

from app.services.continuation_runtime import (
    _failed_run_blocker,
    _outcome,
    _preparation_affected_task_titles,
)
from app.services.harness_adapters import (
    continuation_provider_model,
)


def test_passing_checks_without_agent_changes_do_not_prove_continuation() -> None:
    result = SimpleNamespace(
        status="completed",
        changed_files=(),
        verification_results=(
            SimpleNamespace(
                requirement_id="V1",
                command="pytest -q",
                cwd="/workspace",
                result=SimpleNamespace(
                    exit_code=0,
                    timed_out=False,
                ),
            ),
        ),
    )

    outcome = _outcome(
        result,
        provider="codex",
        current_task="Implement the remaining continuation work.",
    )

    assert outcome["status"] == "requirements_unproven"
    assert outcome["verified"] is False
    assert (
        outcome["completion_evidence"]
        == "checks_passed_without_repository_changes"
    )
    assert outcome["checks"]["status"] == "passed"


def test_verification_side_effects_do_not_count_as_agent_changes() -> None:
    result = SimpleNamespace(
        status="completed",
        agent_changed_files=(),
        changed_files=("verification-output.txt",),
        verification_results=(
            SimpleNamespace(
                requirement_id="V1",
                command="python check.py",
                cwd="/workspace",
                result=SimpleNamespace(
                    exit_code=0,
                    timed_out=False,
                ),
            ),
        ),
    )

    outcome = _outcome(
        result,
        provider="codex",
        current_task="Implement the remaining continuation work.",
    )

    assert outcome["status"] == "requirements_unproven"
    assert outcome["agent_changed_files"] == []
    assert outcome["changed_files"] == ["verification-output.txt"]


def test_opencode_attachment_parser_failure_is_reported_as_our_invocation_bug() -> None:
    result = SimpleNamespace(
        command=SimpleNamespace(
            exit_code=1,
            timed_out=False,
            stdout="",
            stderr=(
                "Error: File not found: Continue the task using the attached "
                "Legacy Product context pack. Verify the current repository "
                "state before editing."
            ),
        ),
    )

    blocker = _failed_run_blocker(
        result,
        provider="opencode",
        current_task="Fix the harness continuation workflow.",
        failed_check_count=0,
        affected_tasks=None,
    )

    assert blocker == {
        "code": "provider_invocation_invalid",
        "provider": "opencode",
        "message": (
            "DaemonState constructed an invalid OpenCode command: OpenCode "
            "treated the continuation message as another attachment."
        ),
        "action": (
            "Update DaemonState to the corrected OpenCode invocation and "
            "retry the continuation."
        ),
        "affected_tasks": ["Fix the harness continuation workflow."],
    }


def test_preparation_affected_tasks_prefers_executable_task_over_session_title() -> None:
    reaction = (
        "# Files mentioned by the user:\n"
        "## Screenshot 2026-07-25 at 19.57.03.png: /Users/example/failure.png\n"
        "## My request for Codex:\n"
        "ARE U FUCKING KIDDING ME U FUCKING PICEC OF SHITE"
    )
    valid = "Repair the OpenCode continuation workflow."
    preparation = SimpleNamespace(
        objective=reaction,
        source_session={"title": "Continuing from AI Infra Components"},
        task={
            "workflow": {
                "modeled": False,
                "execution_task": {"title": reaction},
                "selected_intent": {"title": valid},
                "affected_tasks": [],
            },
        },
    )

    affected = _preparation_affected_task_titles(preparation)

    assert affected == ["Repair the OpenCode continuation workflow."]


def test_opencode_requires_an_explicit_or_configured_model(monkeypatch) -> None:
    monkeypatch.delenv("DAEMONSTATE_OPENCODE_MODEL", raising=False)

    assert continuation_provider_model("opencode", None) is None
    assert continuation_provider_model("claude", None) is None
    assert continuation_provider_model("opencode", "openai/custom") == "openai/custom"

    monkeypatch.setenv("DAEMONSTATE_OPENCODE_MODEL", "opencode/team-default")
    assert continuation_provider_model("opencode", None) == "opencode/team-default"


def test_zero_exit_opencode_auth_error_is_not_reported_as_success() -> None:
    result = SimpleNamespace(
        command=SimpleNamespace(
            exit_code=0,
            timed_out=False,
            stdout=(
                '{"type":"error","error":{"name":"APIError","data":'
                '{"message":"Invalid API Key","statusCode":401}}}'
            ),
            stderr="",
        ),
    )

    blocker = _failed_run_blocker(
        result,
        provider="opencode",
        current_task="Fix the harness continuation workflow.",
        failed_check_count=0,
    )

    assert blocker["code"] == "provider_authentication_failed"
    assert blocker["message"] == "OpenCode authentication failed."
