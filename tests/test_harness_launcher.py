from __future__ import annotations

import json
import os
import plistlib
import time
from pathlib import Path
from subprocess import CompletedProcess
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import harness_launcher as harness_launcher_module
from app.services.harness_adapters import ProviderModelOption, minimal_process_environment
from app.services.harness_launcher import (
    CodexDesktopAccountProbe,
    DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS,
    HarnessLaunchError,
    MACOS_DESKTOP_APPS,
    launch_harness_composer,
    launch_harness_session,
    probe_codex_desktop_account,
    probe_harness_composer_dispatch_readiness,
    probe_harness_composer_readiness,
    probe_harness_visibility,
)


def _successful_native_paste(
    *,
    verified: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": "daemonstate.composer_paste.v1",
        "code": (
            "desktop_context_inserted"
            if verified
            else "desktop_paste_command_dispatched"
        ),
        "message": "Context delivery requested.",
        "action": "Review the draft.",
        "open_verified": True,
        "paste_requested": True,
        "paste_verified": verified,
        "context_loaded": verified,
        "paste_method": "accessibility_insert" if verified else "command_v",
        "execution_started": False,
    }


def _successful_opencode_native_paste() -> dict[str, object]:
    return {
        **_successful_native_paste(),
        "paste_method": "accessibility_verified_input_sync",
        "target_policy": "opencode-focused-chat-composer-v1",
        "target_kind": "chat_composer",
        "target_identity_verified": True,
        "marker_replaced": False,
    }


def _with_native_identity(stdout: str, argv: list[str]) -> str:
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return stdout
    if not isinstance(payload, dict):
        return stdout
    expected_identifier = argv[argv.index("--expected-bundle-id") + 1]
    expected_path = argv[argv.index("--expected-bundle-path") + 1]
    payload.setdefault("expected_bundle_identifiers", [expected_identifier])
    payload.setdefault("expected_bundle_path", expected_path)
    payload.setdefault("observed_bundle_identifier", expected_identifier)
    payload.setdefault("observed_bundle_path", expected_path)
    return json.dumps(payload)


_REAL_NATIVE_HELPER_AVAILABLE = (
    harness_launcher_module._native_paste_helper_available
)


@pytest.fixture(autouse=True)
def _native_helper_is_prebuilt_for_readiness_tests(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher._native_paste_helper_available",
        lambda: True,
    )


def _install_fake_desktop_app(
    tmp_path: Path,
    monkeypatch,
    provider: str,
    *,
    schemes: tuple[str, ...] | None = None,
    version: str = "1.18.18",
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
    if provider == "opencode":
        info["CFBundleShortVersionString"] = version
        info["CFBundleVersion"] = version
    with (contents / "Info.plist").open("wb") as plist_file:
        plistlib.dump(info, plist_file)
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_application_roots",
        lambda: (tmp_path,),
    )
    return bundle


def _fake_codex_account_server(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "\n"
        "def receive():\n"
        "    return json.loads(sys.stdin.readline())\n"
        "\n"
        "def send(message):\n"
        "    print(json.dumps(message, separators=(',', ':')), flush=True)\n"
        "\n"
        "initialize = receive()\n"
        "send({'id': initialize['id'], 'result': {'userAgent': 'fake'}})\n"
        "receive()\n"
        "account = receive()\n"
        "send({'id': account['id'], 'result': {\n"
        "    'account': {'type': 'chatgpt', 'planType': 'plus', 'email': None},\n"
        "    'requiresOpenaiAuth': True,\n"
        "}})\n"
        "models = receive()\n"
        "send({'id': models['id'], 'result': {'data': [{\n"
        "    'id': 'catalog-gpt-5.6-sol',\n"
        "    'model': 'gpt-5.6-sol',\n"
        "    'displayName': 'GPT-5.6 Sol',\n"
        "    'description': 'Fast coding model',\n"
        "    'hidden': False,\n"
        "    'isDefault': True,\n"
        "    'defaultReasoningEffort': 'medium',\n"
        "    'supportedReasoningEfforts': [\n"
        "        {'reasoningEffort': 'low', 'description': 'Low'},\n"
        "        {'reasoningEffort': 'medium', 'description': 'Medium'},\n"
        "    ],\n"
        "}]}})\n"
        "limits = receive()\n"
        "send({'id': limits['id'], 'result': {\n"
        "    'rateLimits': {'rateLimitReachedType': None},\n"
        "}})\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_codex_account_probe_uses_read_only_app_server_status_methods(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = _fake_codex_account_server(tmp_path)
    monkeypatch.setattr(
        "app.services.harness_launcher.codex_executable",
        lambda: str(executable),
    )

    probe = probe_codex_desktop_account(timeout_seconds=1.5)

    assert probe.signed_in is True
    assert probe.rate_limit_reached is False
    assert probe.rate_limit_code is None
    assert [model.to_dict() for model in probe.models] == [{
        "id": "gpt-5.6-sol",
        "label": "GPT-5.6 Sol",
        "default": True,
        "reasoning_efforts": ["low", "medium"],
        "default_reasoning_effort": "medium",
    }]


def test_codex_account_probe_deadline_handles_a_partial_app_server_line(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "partial-line-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "import time\n"
        "sys.stdin.readline()\n"
        "sys.stdout.write('{')\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setattr(
        "app.services.harness_launcher.codex_executable",
        lambda: str(executable),
    )
    real_popen = harness_launcher_module.subprocess.Popen
    processes = []

    def tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(
        harness_launcher_module.subprocess,
        "Popen",
        tracked_popen,
    )

    started = time.monotonic()
    probe = probe_codex_desktop_account(timeout_seconds=0.05)
    elapsed = time.monotonic() - started

    assert probe == CodexDesktopAccountProbe()
    assert elapsed < 1.0
    assert len(processes) == 1
    assert processes[0].poll() is not None


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
        "-a",
        str((tmp_path / "ChatGPT.app").resolve()),
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
    assert calls[0][0][:3] == [
        "/usr/bin/open",
        "-a",
        str((tmp_path / "OpenCode.app").resolve()),
    ]
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
        "-a",
        str((tmp_path / "Claude.app").resolve()),
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
def test_installed_desktop_and_registered_scheme_enable_draft_handoff(
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
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: CodexDesktopAccountProbe(),
    )

    readiness = probe_harness_composer_readiness(provider)

    assert readiness.ready is True
    assert readiness.desktop_available is True
    assert readiness.url_scheme_registered is True
    assert readiness.required_url_scheme == MACOS_DESKTOP_APPS[provider].url_scheme
    assert readiness.code == "desktop_dispatch_ready"
    assert readiness.account_access_state == "unverified"
    assert readiness.account_access_verified is False
    assert "ready to receive the draft" in readiness.message
    assert "open" in readiness.action.lower()


def test_codex_dispatch_readiness_does_not_wait_for_account_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: pytest.fail("hard dispatch readiness must not probe the account"),
    )

    readiness = probe_harness_composer_dispatch_readiness("codex")

    assert readiness.ready is True
    assert readiness.code == "desktop_dispatch_ready"
    assert readiness.account_access_state == "unverified"
    assert readiness.account_access_verified is False


def test_codex_cached_models_restore_controls_when_live_probe_is_unavailable(
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
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: CodexDesktopAccountProbe(),
    )

    readiness = probe_harness_composer_readiness("codex")

    assert readiness.ready is True
    assert readiness.models == (model,)
    assert readiness.model_catalog_source == "codex_desktop_cache"
    assert readiness.account_access_verified is False
    assert "could not be confirmed automatically" in readiness.message


def test_codex_app_server_account_and_models_are_verified_automatically(
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
        default_reasoning_effort="medium",
    )
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: CodexDesktopAccountProbe(
            signed_in=True,
            models=(model,),
            rate_limit_reached=False,
        ),
    )

    readiness = probe_harness_composer_readiness("codex")

    assert readiness.ready is True
    assert readiness.code == "desktop_account_access_verified"
    assert readiness.models == (model,)
    assert readiness.account_access_state == "verified"
    assert readiness.account_access_verified is True
    assert readiness.model_catalog_source == "codex_app_server"


def test_codex_reported_limit_blocks_the_ready_card(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: CodexDesktopAccountProbe(
            signed_in=True,
            rate_limit_reached=True,
            rate_limit_code="rate_limit_reached",
        ),
    )

    readiness = probe_harness_composer_readiness("codex")

    assert readiness.ready is False
    assert readiness.code == "desktop_account_rate_limited"
    assert readiness.account_access_state == "rate_limited"
    assert readiness.account_access_verified is False
    assert "review the limit" in readiness.action


def test_codex_signed_out_status_blocks_the_ready_card(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(
        "app.services.harness_launcher.probe_codex_desktop_account",
        lambda: CodexDesktopAccountProbe(signed_in=False),
    )

    readiness = probe_harness_composer_readiness("codex")

    assert readiness.ready is False
    assert readiness.code == "desktop_account_sign_in_required"
    assert readiness.account_access_state == "signed_out"
    assert readiness.account_access_verified is False
    assert "sign in" in readiness.action.lower()


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


def test_opencode_readiness_rejects_an_unaudited_desktop_version(
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
        "opencode",
        version="1.18.17",
    )

    readiness = probe_harness_composer_readiness("opencode")

    assert readiness.ready is False
    assert readiness.desktop_available is True
    assert readiness.url_scheme_registered is True
    assert readiness.code == "desktop_app_version_unsupported"
    assert "safe focused-composer insertion" in readiness.message


def test_opencode_focused_composer_readiness_does_not_require_a_url_scheme(
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
        "opencode",
        schemes=(),
    )

    readiness = probe_harness_composer_readiness("opencode")

    assert readiness.ready is True
    assert readiness.desktop_available is True
    assert readiness.url_scheme_registered is False
    assert readiness.code == "desktop_dispatch_ready"
    assert "ready to receive the draft" in readiness.message


def test_composer_readiness_requires_a_prebuilt_native_paste_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    monkeypatch.setattr(
        "app.services.harness_launcher._native_paste_helper_available",
        lambda: False,
    )

    readiness = probe_harness_composer_readiness("opencode")

    assert readiness.ready is False
    assert readiness.code == "desktop_paste_helper_missing"
    assert "native paste helper" in readiness.message


def test_native_paste_helper_requires_a_fresh_executable_binary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "repository"
    launcher = repository / "scripts" / "overlay.sh"
    package = repository / "desktop" / "macos" / "DaemonStateOverlay"
    source = package / "Sources" / "DaemonStateOverlay" / "Helper.swift"
    binary = package / ".build" / "release" / "DaemonStateOverlay"
    launcher.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o700)
    (package / "Package.swift").write_text("// package\n", encoding="utf-8")
    source.write_text("// source\n", encoding="utf-8")
    binary.write_text("binary\n", encoding="utf-8")
    binary.chmod(0o700)
    monkeypatch.setattr(
        harness_launcher_module,
        "_native_paste_helper_available",
        _REAL_NATIVE_HELPER_AVAILABLE,
    )
    monkeypatch.setattr(
        harness_launcher_module,
        "_native_overlay_launcher",
        lambda: launcher,
    )

    os.utime(source, (100.0, 100.0))
    os.utime(package / "Package.swift", (100.0, 100.0))
    os.utime(binary, (200.0, 200.0))
    assert harness_launcher_module._native_paste_helper_available() is True

    os.utime(source, (300.0, 300.0))
    assert harness_launcher_module._native_paste_helper_available() is False


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

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "--paste-stdin" in argv:
            payload = (
                _successful_opencode_native_paste()
                if provider == "opencode"
                else _successful_native_paste()
            )
            return CompletedProcess(
                argv,
                0,
                stdout=_with_native_identity(
                    json.dumps(payload),
                    argv,
                ),
                stderr="",
            )
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.harness_launcher.subprocess.run", run)

    result = launch_harness_composer(
        provider,
        cwd=str(tmp_path),
        prompt="Inspect the current task; do not submit automatically.",
    )

    assert result["launched"] is True
    assert result["open_requested"] is True
    assert result["open_verified"] is True
    assert result["navigation_requested"] is (provider != "opencode")
    assert result["navigation_verified"] is False
    assert result["mode"] == "desktop_composer"
    assert result["navigation"] == (
        "app" if provider == "opencode" else "new_session"
    )
    assert result["prefill_requested"] is False
    assert result["context_copied"] is True
    assert result["context_loaded"] is True
    assert result["paste_requested"] is True
    assert result["paste_verified"] is True
    assert result["paste_method"] == (
        "accessibility_verified_input_sync"
        if provider == "opencode"
        else "accessibility_insert"
    )
    assert result["context_delivery"] == (
        "desktop_composer_verified_input_sync"
        if provider == "opencode"
        else "desktop_composer_accessibility_insert"
    )
    assert result["execution_started"] is False
    assert calls[0][0] == ["/usr/bin/pbcopy"]
    assert calls[0][1]["input"].startswith("Inspect the current task")
    assert calls[1][0][0:2] == ["/usr/bin/open", "-a"]
    assert len(calls) == 3
    assert {argv[0] for argv, _kwargs in calls} == {
        "/usr/bin/open",
        "/usr/bin/pbcopy",
        str(Path(__file__).resolve().parents[1] / "scripts" / "overlay.sh"),
    }
    if provider == "opencode":
        assert calls[1][0] == [
            "/usr/bin/open",
            "-a",
            str(
                (
                    tmp_path / f"{MACOS_DESKTOP_APPS[provider].app_names[0]}.app"
                ).resolve()
            ),
        ]
        assert calls[2][0][calls[2][0].index("--target-policy") + 1] == (
            "opencode-focused-chat-composer-v1"
        )
        assert "--target-marker" not in calls[2][0]
        assert "--expected-project-directory" not in calls[2][0]
    else:
        target = urlparse(calls[1][0][-1])
        assert target.scheme == scheme
        assert target.hostname == host
        query = parse_qs(target.query)
        assert query[path_key] == [str(tmp_path.resolve())]
        assert prompt_key not in query
        assert "--target-policy" not in calls[2][0]
        assert "--target-marker" not in calls[2][0]
        assert "--expected-project-directory" not in calls[2][0]
    assert calls[2][1]["input"] == (
        "Inspect the current task; do not submit automatically."
    )
    assert calls[2][0][calls[2][0].index("--expected-bundle-id") + 1] == (
        MACOS_DESKTOP_APPS[provider].bundle_ids[0]
    )
    assert calls[2][0][calls[2][0].index("--expected-bundle-path") + 1] == (
        str((tmp_path / f"{MACOS_DESKTOP_APPS[provider].app_names[0]}.app").resolve())
    )


def test_oversized_desktop_prompt_is_copied_without_truncation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    prompt = "x" * 20_000
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "claude")
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "--paste-stdin" in argv:
            return CompletedProcess(
                argv,
                0,
                stdout=_with_native_identity(
                    json.dumps(_successful_native_paste(verified=False)),
                    argv,
                ),
                stderr="",
            )
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.harness_launcher.subprocess.run", run)

    result = launch_harness_composer(
        "claude",
        cwd=str(tmp_path),
        prompt=prompt,
    )

    assert result["prefill_requested"] is False
    assert result["context_delivery"] == "desktop_composer_command_v"
    assert result["context_copied"] is True
    assert result["paste_requested"] is True
    assert result["paste_verified"] is False
    assert result["context_loaded"] is False
    assert result["launched"] is True
    assert result["open_requested"] is True
    assert calls[0][1]["input"] == prompt
    query = parse_qs(urlparse(calls[1][0][-1]).query)
    assert "q" not in query
    assert query["folder"] == [str(tmp_path.resolve())]
    assert calls[2][1]["input"] == prompt


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
        "-a",
        str((tmp_path / "ChatGPT.app").resolve()),
        "codex://threads/session-123",
    ]


def test_opens_the_canonical_inspected_bundle_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    actual_root = tmp_path / "actual"
    actual_bundle = _install_fake_desktop_app(
        actual_root,
        monkeypatch,
        "codex",
    )
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    (scan_root / "ChatGPT.app").symlink_to(
        actual_bundle,
        target_is_directory=True,
    )
    monkeypatch.setattr(
        "app.services.harness_launcher._macos_application_roots",
        lambda: (scan_root,),
    )
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or CompletedProcess(argv, 0, stdout="", stderr="")
        ),
    )

    launch_harness_session("codex", "session-123")

    assert calls[0][0][0:3] == [
        "/usr/bin/open",
        "-a",
        str(actual_bundle.resolve(strict=True)),
    ]


def test_composer_launch_preflights_native_helper_before_clipboard_or_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_launcher.platform.system",
        lambda: "Darwin",
    )
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    monkeypatch.setattr(
        "app.services.harness_launcher._native_paste_helper_available",
        lambda: False,
    )
    calls = []
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer(
            "codex",
            cwd=str(tmp_path),
            prompt="Private continuation context",
        )

    assert raised.value.code == "desktop_paste_helper_missing"
    assert calls == []


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


def _native_helper_failure(
    *,
    code: str,
    open_verified: bool = True,
    paste_requested: bool = False,
) -> str:
    return json.dumps({
        "schema_version": "daemonstate.composer_paste.v1",
        "code": code,
        "message": "Native paste was not completed.",
        "action": "Grant the required permission, then retry Continue.",
        "open_verified": open_verified,
        "paste_requested": paste_requested,
        "paste_verified": False,
        "context_loaded": False,
        "paste_method": None,
        "execution_started": False,
    })


def _launcher_with_native_response(
    monkeypatch,
    *,
    stdout: str,
    returncode: int,
):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "--paste-stdin" in argv:
            response = _with_native_identity(stdout, argv)
            return CompletedProcess(
                argv,
                returncode,
                stdout=response,
                stderr="",
            )
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.harness_launcher.subprocess.run", run)
    return calls


def test_one_shot_overlay_stale_exit_reports_missing_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    calls = _launcher_with_native_response(
        monkeypatch,
        stdout="",
        returncode=70,
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer(
            "codex",
            cwd=str(tmp_path),
            prompt="Context that must remain fail-closed.",
        )

    assert raised.value.code == "desktop_paste_helper_missing"
    assert raised.value.action == (
        "Run bash scripts/ensure-native-context-helper.sh, then retry Continue."
    )
    assert calls[2][1]["input"] == "Context that must remain fail-closed."


def test_opencode_accepts_focused_empty_chat_composer_attestation_without_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(
        tmp_path,
        monkeypatch,
        "opencode",
        schemes=(),
    )
    calls = _launcher_with_native_response(
        monkeypatch,
        stdout=json.dumps(_successful_opencode_native_paste()),
        returncode=0,
    )

    result = launch_harness_composer(
        "opencode",
        cwd=str(tmp_path),
        prompt="Real context that must never enter the URL.",
    )

    assert result["context_loaded"] is True
    assert result["paste_verified"] is True
    assert result["navigation_requested"] is False
    assert result["navigation"] == "app"
    assert result["marker_replaced"] is False
    assert calls[1][0] == [
        "/usr/bin/open",
        "-a",
        str((tmp_path / "OpenCode.app").resolve()),
    ]
    assert calls[2][0][calls[2][0].index("--target-policy") + 1] == (
        "opencode-focused-chat-composer-v1"
    )
    assert "--target-marker" not in calls[2][0]
    assert "--expected-project-directory" not in calls[2][0]


def test_opencode_rejects_command_v_even_with_claimed_target_attestation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    _launcher_with_native_response(
        monkeypatch,
        stdout=json.dumps(
            {
                **_successful_native_paste(verified=False),
                "target_policy": "opencode-focused-chat-composer-v1",
                "target_kind": "chat_composer",
                "target_identity_verified": True,
                "marker_replaced": False,
            }
        ),
        returncode=0,
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer(
            "opencode",
            cwd=str(tmp_path),
            prompt="Context must never use OpenCode Command-V.",
        )

    assert raised.value.code == "desktop_context_insertion_unverified"


@pytest.mark.parametrize(
    ("attestation", "expected_code"),
    (
        ({}, "desktop_composer_focus_unverified"),
        (
            {
                "target_policy": "opencode-chat-composer-v0",
                "target_kind": "chat_composer",
                "target_identity_verified": True,
                "marker_replaced": False,
            },
            "desktop_composer_focus_unverified",
        ),
        (
            {
                "target_policy": "opencode-focused-chat-composer-v1",
                "target_kind": "terminal",
                "target_identity_verified": True,
                "marker_replaced": False,
            },
            "desktop_composer_focus_unverified",
        ),
        (
            {
                "target_policy": "opencode-focused-chat-composer-v1",
                "target_kind": "chat_composer",
                "target_identity_verified": False,
                "marker_replaced": False,
            },
            "desktop_composer_focus_unverified",
        ),
        (
            {
                "target_policy": "opencode-focused-chat-composer-v1",
                "target_kind": "chat_composer",
                "target_identity_verified": True,
                "marker_replaced": True,
            },
            "desktop_context_insertion_unverified",
        ),
    ),
)
def test_opencode_rejects_missing_or_inexact_chat_composer_attestation(
    attestation: dict[str, object],
    expected_code: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    _launcher_with_native_response(
        monkeypatch,
        stdout=json.dumps(
            {
                **_successful_native_paste(),
                "paste_method": "accessibility_verified_input_sync",
                **attestation,
            }
        ),
        returncode=0,
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer(
            "opencode",
            cwd=str(tmp_path),
            prompt="Context must not be reported as loaded.",
        )

    assert raised.value.code == expected_code


def test_native_accessibility_failure_propagates_dedicated_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "codex")
    calls = _launcher_with_native_response(
        monkeypatch,
        stdout=_native_helper_failure(
            code="desktop_accessibility_permission_required",
        ),
        returncode=77,
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer("codex", cwd=str(tmp_path), prompt="Full context")

    assert raised.value.code == "desktop_accessibility_permission_required"
    assert raised.value.action == (
        "Allow DaemonStateOverlay in System Settings > Privacy & Security > "
        "Accessibility, then retry Continue."
    )
    assert calls[2][1]["input"] == "Full context"
    assert calls[2][1]["env"] == minimal_process_environment()
    query = parse_qs(urlparse(calls[1][0][-1]).query)
    assert "prompt" not in query


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected_code"),
    (
        ("not-json", 0, "desktop_paste_response_invalid"),
        (
            json.dumps({
                **_successful_native_paste(),
                "schema_version": "unexpected.v1",
            }),
            0,
            "desktop_paste_response_invalid",
        ),
        (
            json.dumps({
                **_successful_native_paste(verified=False),
                "open_verified": False,
            }),
            0,
            "desktop_paste_response_invalid",
        ),
        (
            json.dumps({
                **_successful_native_paste(),
                "context_loaded": False,
            }),
            0,
            "desktop_paste_response_invalid",
        ),
        (
            _native_helper_failure(code="desktop_unknown_helper_code"),
            79,
            "desktop_paste_response_invalid",
        ),
        (
            json.dumps({
                **_successful_native_paste(),
                "message": "unsafe\u0001helper output",
            }),
            0,
            "desktop_paste_response_invalid",
        ),
        (
            json.dumps({"padding": "x" * 33_000}),
            79,
            "desktop_paste_response_invalid",
        ),
        (
            json.dumps({
                **_successful_native_paste(),
                "expected_bundle_path": "/Applications/Imposter.app",
                "observed_bundle_path": "/Applications/Imposter.app",
            }),
            0,
            "desktop_paste_response_invalid",
        ),
        (
            _native_helper_failure(code="desktop_paste_not_requested"),
            79,
            "desktop_paste_not_requested",
        ),
    ),
)
def test_rejects_unverified_or_invalid_native_paste_responses(
    stdout: str,
    returncode: int,
    expected_code: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "opencode")
    _launcher_with_native_response(
        monkeypatch,
        stdout=stdout,
        returncode=returncode,
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer("opencode", cwd=str(tmp_path), prompt="Full context")

    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("prompt", "expected_code"),
    (
        ("x" * 1_048_577, "desktop_context_too_large"),
        ("unsafe\x00context", "desktop_prompt_invalid"),
    ),
)
def test_rejects_unsafe_native_context_before_clipboard_or_open(
    prompt: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr("app.services.harness_launcher.platform.system", lambda: "Darwin")
    _install_fake_desktop_app(tmp_path, monkeypatch, "claude")
    monkeypatch.setattr(
        "app.services.harness_launcher.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    with pytest.raises(HarnessLaunchError) as raised:
        launch_harness_composer("claude", cwd=str(tmp_path), prompt=prompt)

    assert raised.value.code == expected_code
    assert calls == []
