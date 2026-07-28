from __future__ import annotations

import plistlib
from pathlib import Path
from subprocess import CompletedProcess
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.harness_adapters import ProviderModelOption
from app.services.harness_launcher import (
    DESKTOP_DEEP_LINK_PROMPT_MAX_CHARS,
    DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS,
    HarnessLaunchError,
    MACOS_DESKTOP_APPS,
    launch_harness_composer,
    launch_harness_session,
    probe_harness_composer_readiness,
    probe_harness_visibility,
)


def _install_fake_desktop_app(
    tmp_path: Path,
    monkeypatch,
    provider: str,
    *,
    schemes: tuple[str, ...] | None = None,
) -> Path:
    spec = MACOS_DESKTOP_APPS[provider]
    bundle = tmp_path / f"{spec.app_names[0]}.app"
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    info: dict[str, object] = {
        "CFBundleIdentifier": spec.bundle_ids[0],
        "CFBundleURLTypes": [
            {
                "CFBundleURLSchemes": list(
                    (spec.url_scheme,) if schemes is None else schemes
                )
            }
        ],
    }
    with (contents / "Info.plist").open("wb") as plist_file:
        plistlib.dump(info, plist_file)
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_application_roots",
        lambda: (tmp_path,),
    )
    return bundle


def test_requests_codex_session_in_the_desktop_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session(
        "codex",
        "6f5cb153-dbaa-4a5b-9cd4-2cc3fd24ef24",
    )

    assert result["launched"] is False
    assert result["open_requested"] is True
    assert result["open_verified"] is False
    assert result["navigation_requested"] is True
    assert result["navigation_verified"] is False
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


def test_requests_opencode_project_in_the_desktop_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session("opencode", "session-123", cwd=str(tmp_path))

    assert result["navigation"] == "project"
    assert result["exact_session_supported"] is False
    assert calls[0][0][:3] == ["/usr/bin/open", "-b", "ai.opencode.desktop"]
    assert calls[0][0][3].startswith("opencode://open-project?directory=")


def test_uses_registered_claude_desktop_bundle_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "claude")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or CompletedProcess(argv, 0),
    )

    result = launch_harness_session("claude", "session-123")

    assert result["launched"] is False
    assert result["open_requested"] is True
    assert result["navigation_requested"] is False
    assert calls[0][0] == [
        "/usr/bin/open",
        "-b",
        "com.anthropic.claudefordesktop",
    ]


def test_visible_harness_readiness_fails_closed_when_desktop_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_desktop_app_installed",
        lambda _spec: False,
    )

    visibility = probe_harness_visibility("codex")

    assert visibility.ready is False
    assert visibility.desktop_available is False
    assert visibility.exact_session_supported is True
    assert visibility.code == "desktop_app_missing"


@pytest.mark.parametrize("provider", ("claude", "opencode"))
def test_visible_harness_readiness_fails_closed_without_exact_session_navigation(
    provider: str,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_desktop_app_installed",
        lambda _spec: True,
    )

    visibility = probe_harness_visibility(provider)

    assert visibility.ready is False
    assert visibility.desktop_available is True
    assert visibility.exact_session_supported is False
    assert visibility.code == "visible_session_unsupported"


@pytest.mark.parametrize("provider", ("codex", "claude", "opencode"))
def test_installed_desktop_and_registered_scheme_do_not_prove_account_access(
    provider: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, provider)
    monkeypatch.setattr(
        "app.services.harness_launcher.codex_cached_model_catalog",
        lambda: (),
    )

    readiness = probe_harness_composer_readiness(provider)

    assert readiness.ready is False
    assert readiness.desktop_available is True
    assert readiness.url_scheme_registered is True
    assert readiness.required_url_scheme == MACOS_DESKTOP_APPS[provider].url_scheme
    assert readiness.code == "desktop_account_access_unverified"
    assert readiness.account_access_state == "unverified"
    assert readiness.account_access_verified is False
    assert "installed" in readiness.message
    assert "verify" in readiness.action.lower()


def test_codex_cached_models_restore_controls_without_proving_subscription(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    model = ProviderModelOption(
        id="gpt-5.6-sol",
        label="GPT-5.6 Sol",
        default=True,
        reasoning_efforts=("low", "medium", "high"),
        default_reasoning_effort="low",
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.codex_cached_model_catalog",
        lambda: (model,),
    )

    readiness = probe_harness_composer_readiness("codex")

    assert readiness.ready is False
    assert readiness.models == (model,)
    assert readiness.model_catalog_source == "codex_desktop_cache"
    assert readiness.account_access_verified is False
    assert "does not prove" in readiness.message


def test_composer_readiness_distinguishes_missing_scheme_from_missing_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(
        tmp_path,
        monkeypatch,
        "claude",
        schemes=("some-other-app",),
    )

    readiness = probe_harness_composer_readiness("claude")

    assert readiness.ready is False
    assert readiness.desktop_available is True
    assert readiness.url_scheme_registered is False
    assert readiness.required_url_scheme == "claude"
    assert readiness.code == "desktop_url_scheme_missing"
    assert "required claude:// URL scheme" in readiness.message
    assert "Update or reinstall Claude Desktop" in readiness.action


def test_composer_readiness_reports_desktop_missing_separately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_application_roots",
        lambda: (tmp_path,),
    )

    readiness = probe_harness_composer_readiness("opencode")

    assert readiness.ready is False
    assert readiness.desktop_available is False
    assert readiness.url_scheme_registered is False
    assert readiness.required_url_scheme == "opencode"
    assert readiness.code == "desktop_app_missing"


@pytest.mark.parametrize("connector_type", ["codex", "claude", "opencode"])
def test_reports_missing_before_any_open_request(
    connector_type,
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_application_roots",
        lambda: (tmp_path,),
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    with pytest.raises(HarnessLaunchError, match="desktop app is missing") as error:
        launch_harness_session(connector_type, "session-123")

    assert error.value.code == "desktop_app_missing"
    assert calls == []


def test_rejects_unsafe_session_ids_before_launch(monkeypatch) -> None:
    with pytest.raises(HarnessLaunchError, match="not safe"):
        launch_harness_session("codex", "session; open /Applications/Calculator.app")


@pytest.mark.parametrize(
    ("provider", "scheme", "host", "path_key", "prompt_key"),
    (
        ("codex", "codex", "threads", "path", "prompt"),
        ("claude", "claude", "code", "folder", "q"),
        ("opencode", "opencode", "new-session", "directory", "prompt"),
    ),
)
def test_requests_visible_desktop_composer_without_provider_cli(
    provider: str,
    scheme: str,
    host: str,
    path_key: str,
    prompt_key: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, provider)
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or CompletedProcess(argv, 0, stdout="", stderr="")
        ),
    )

    result = launch_harness_composer(
        provider,
        cwd=str(tmp_path),
        prompt="Inspect the current task; do not submit automatically.",
    )

    assert result["launched"] is False
    assert result["open_requested"] is True
    assert result["open_verified"] is False
    assert result["navigation_requested"] is True
    assert result["navigation_verified"] is False
    assert result["mode"] == "desktop_composer"
    assert result["navigation"] == "new_session"
    assert result["prefill_requested"] is True
    assert result["context_copied"] is True
    assert result["context_loaded"] is False
    assert result["execution_started"] is False
    assert calls[0][0] == ["/usr/bin/pbcopy"]
    assert calls[0][1]["input"].startswith("Inspect the current task")
    assert calls[1][0][0:2] == ["/usr/bin/open", "-b"]
    assert len(calls) == 2
    assert {argv[0] for argv, _kwargs in calls} == {
        "/usr/bin/open",
        "/usr/bin/pbcopy",
    }
    target = urlparse(calls[1][0][3])
    assert target.scheme == scheme
    assert target.hostname == host
    query = parse_qs(target.query)
    assert query[path_key] == [str(tmp_path.resolve())]
    assert query[prompt_key] == [
        "Inspect the current task; do not submit automatically."
    ]


def test_oversized_desktop_prompt_is_copied_without_truncation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    prompt = "x" * (DESKTOP_DEEP_LINK_PROMPT_MAX_CHARS + 1)
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "claude")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or CompletedProcess(argv, 0, stdout="", stderr="")
        ),
    )

    result = launch_harness_composer(
        "claude",
        cwd=str(tmp_path),
        prompt=prompt,
    )

    assert result["prefill_requested"] is False
    assert result["context_delivery"] == "clipboard"
    assert result["context_copied"] is True
    assert result["launched"] is False
    assert result["open_requested"] is True
    assert calls[0][1]["input"] == prompt
    query = parse_qs(urlparse(calls[1][0][3]).query)
    assert "q" not in query
    assert query["folder"] == [str(tmp_path.resolve())]


def test_fails_closed_before_clipboard_when_registered_scheme_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(
        tmp_path,
        monkeypatch,
        "claude",
        schemes=("some-other-app",),
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    with pytest.raises(
        HarnessLaunchError,
        match=r"required claude:// URL scheme",
    ) as error:
        launch_harness_composer(
            "claude",
            cwd=str(tmp_path),
            prompt="Keep this context private.",
        )

    assert error.value.code == "desktop_url_scheme_missing"
    assert calls == []


def test_uses_one_open_request_without_bundle_or_name_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")

    def fail_open(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="Unable to find application named Codex",
        )

    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        fail_open,
    )

    with pytest.raises(HarnessLaunchError) as error:
        launch_harness_session("codex", "session-123")

    assert error.value.code == "desktop_app_missing"
    assert len(calls) == 1
    assert calls[0][0] == [
        "/usr/bin/open",
        "-b",
        "com.openai.codex",
        "codex://threads/session-123",
    ]


def test_total_deadline_prevents_a_late_open_after_clipboard_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    ticks = iter(
        (
            100.0,
            100.1,
            100.0 + DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS + 0.01,
        )
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.time.monotonic",
        lambda: next(ticks),
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or CompletedProcess(argv, 0, stdout="", stderr="")
        ),
    )

    with pytest.raises(HarnessLaunchError) as error:
        launch_harness_composer(
            "opencode",
            cwd=str(tmp_path),
            prompt="A complete context payload.",
        )

    assert error.value.code == "desktop_handoff_timeout"
    assert len(calls) == 1
    assert calls[0][0] == ["/usr/bin/pbcopy"]
    assert 0 < calls[0][1]["timeout"] < DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS
