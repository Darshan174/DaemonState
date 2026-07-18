from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.services.harness_launcher import HarnessLaunchError, launch_harness_session


def test_opens_codex_session_in_the_desktop_app(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session(
        "codex",
        "6f5cb153-dbaa-4a5b-9cd4-2cc3fd24ef24",
    )

    assert result["launched"] is True
    assert result["harness"] == "Codex"
    assert result["mode"] == "desktop_app"
    assert result["navigation"] == "session"
    assert result["exact_session_supported"] is True
    assert result["topic_anchor_supported"] is False
    argv, _ = calls[0]
    assert argv == [
        "/usr/bin/open",
        "-b",
        "com.openai.codex",
        "codex://threads/6f5cb153-dbaa-4a5b-9cd4-2cc3fd24ef24",
    ]


def test_opens_opencode_project_in_the_desktop_app(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session("opencode", "session-123", cwd=str(tmp_path))

    assert result["navigation"] == "project"
    assert result["exact_session_supported"] is False
    assert calls[0][0][:3] == ["/usr/bin/open", "-b", "ai.opencode.desktop"]
    assert calls[0][0][3].startswith("opencode://open-project?directory=")


def test_uses_registered_claude_desktop_bundle_id(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session("claude", "session-123")

    assert result["launched"] is True
    assert calls[0][0] == [
        "/usr/bin/open",
        "-b",
        "com.anthropic.claudefordesktop",
    ]


@pytest.mark.parametrize("connector_type", ["codex", "claude", "opencode"])
def test_reports_missing_only_after_all_registered_app_lookups_fail(
    connector_type,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="Unable to find application named test",
        ),
    )

    with pytest.raises(HarnessLaunchError, match="desktop app is missing") as error:
        launch_harness_session(connector_type, "session-123")

    assert error.value.code == "desktop_app_missing"


def test_rejects_unsafe_session_ids_before_launch(monkeypatch) -> None:
    with pytest.raises(HarnessLaunchError, match="not safe"):
        launch_harness_session("codex", "session; open /Applications/Calculator.app")
