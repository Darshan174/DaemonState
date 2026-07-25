from __future__ import annotations

from pathlib import Path

import pytest

from app.services.harness_adapters import (
    CONTEXT_FILE_PLACEHOLDER,
    OPENCODE_CONTINUATION_MESSAGE,
    HarnessAdapterError,
    HarnessExecutableNotFound,
    build_harness_invocation,
    probe_provider_readiness,
    provider_environment,
)


def _available(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: f"/tools/{name}",
    )


@pytest.mark.parametrize(
    ("provider", "expected_argv", "delivery"),
    [
        (
            "codex",
            (
                "/tools/codex",
                "-C",
                "{repo}",
                "--sandbox",
                "workspace-write",
                "exec",
                "--json",
                "-",
            ),
            "stdin",
        ),
        (
            "claude",
            (
                "/tools/claude",
                "--print",
                "--verbose",
                "--output-format",
                "stream-json",
                "--input-format",
                "text",
                "--add-dir",
                "{repo}",
            ),
            "stdin",
        ),
        (
            "opencode",
            (
                "/tools/opencode",
                "run",
                "--format",
                "json",
                "--dir",
                "{repo}",
                "-f",
                CONTEXT_FILE_PLACEHOLDER,
                OPENCODE_CONTINUATION_MESSAGE,
            ),
            "file",
        ),
    ],
)
def test_builds_safe_fresh_provider_invocations(
    provider,
    expected_argv,
    delivery,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    invocation = build_harness_invocation(provider, repo_path=tmp_path)

    repo = str(tmp_path.resolve())
    assert invocation.argv == tuple(repo if item == "{repo}" else item for item in expected_argv)
    assert invocation.context_delivery == delivery
    assert invocation.executable == f"/tools/{provider}"
    assert invocation.mode == "fresh"
    assert invocation.repo_path == repo
    assert invocation.session_id is None
    assert invocation.model is None
    assert not any("bypass" in item.lower() for item in invocation.argv)


@pytest.mark.parametrize(
    ("provider", "expected_fragment"),
    [
        ("codex", ("exec", "resume", "--json", "session-123", "-")),
        ("claude", ("--resume", "session-123")),
        ("opencode", ("--session", "session-123")),
    ],
)
def test_builds_exact_session_invocations(
    provider,
    expected_fragment,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    invocation = build_harness_invocation(
        provider,
        repo_path=tmp_path,
        session_id="session-123",
    )

    assert invocation.mode == "session"
    assert invocation.session_id == "session-123"
    joined = " ".join(invocation.argv)
    assert " ".join(expected_fragment) in joined
    assert not any("bypass" in item.lower() for item in invocation.argv)


def test_normalizes_claude_code_provider_alias(tmp_path: Path, monkeypatch) -> None:
    _available(monkeypatch)

    invocation = build_harness_invocation("claude_code", repo_path=tmp_path)

    assert invocation.provider == "claude"
    assert invocation.argv[0] == "/tools/claude"


def test_codex_grants_only_workspace_write_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    invocation = build_harness_invocation("codex", repo_path=tmp_path)

    assert ("--sandbox", "workspace-write") == invocation.argv[3:5]
    assert "danger-full-access" not in invocation.argv
    assert not any("bypass" in item.lower() for item in invocation.argv)


def test_codex_prefers_the_current_desktop_cli_over_an_npm_global_wrapper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundled_codex = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    bundled_codex.parent.mkdir(parents=True)
    bundled_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    bundled_codex.chmod(0o755)
    monkeypatch.setattr(
        "app.services.harness_adapters.CODEX_APP_EXECUTABLES",
        (bundled_codex,),
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: "/Users/tester/.npm-global/bin/codex",
    )

    invocation = build_harness_invocation("codex", repo_path=tmp_path)

    assert invocation.executable == str(bundled_codex)
    assert invocation.argv[0] == str(bundled_codex)


@pytest.mark.parametrize(
    ("provider", "model_flag"),
    [
        ("codex", ("-m", "test-model")),
        ("claude", ("--model", "test-model")),
        ("opencode", ("--model", "test-model")),
    ],
)
def test_passes_an_explicit_model_as_direct_argv(
    provider,
    model_flag,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    invocation = build_harness_invocation(
        provider,
        repo_path=tmp_path,
        model="test-model",
    )

    assert invocation.model == "test-model"
    joined = " ".join(invocation.argv)
    assert " ".join(model_flag) in joined


@pytest.mark.parametrize("model", ["", "  ", "--danger", "x" * 256, "bad\x00model"])
def test_rejects_unsafe_model_values(
    model,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    with pytest.raises(HarnessAdapterError, match="model"):
        build_harness_invocation("codex", repo_path=tmp_path, model=model)


@pytest.mark.parametrize(
    "session_id",
    ["", " session id ", "session;open-calculator", "../session", "x" * 256],
)
def test_rejects_unsafe_session_ids(
    session_id,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    with pytest.raises(HarnessAdapterError, match="session_id"):
        build_harness_invocation(
            "codex",
            repo_path=tmp_path,
            session_id=session_id,
        )


def test_rejects_unknown_provider_before_lookup(tmp_path: Path, monkeypatch) -> None:
    lookups = []
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: lookups.append(name),
    )

    with pytest.raises(HarnessAdapterError, match="unsupported"):
        build_harness_invocation("unknown", repo_path=tmp_path)

    assert lookups == []


def test_reports_missing_provider_cli(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: None,
    )

    with pytest.raises(HarnessExecutableNotFound, match="not available"):
        build_harness_invocation("opencode", repo_path=tmp_path)


def test_requires_an_existing_repository_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _available(monkeypatch)

    with pytest.raises(HarnessAdapterError, match="does not exist"):
        build_harness_invocation("codex", repo_path=tmp_path / "missing")


def test_claude_readiness_uses_structured_auth_status(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/Users/tester")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-auth")
    monkeypatch.setenv("DATABASE_URL", "postgresql://server-secret")
    monkeypatch.setenv("SERVER_API_KEY", "server-secret")
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda name: f"/tools/{name}",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {
            "returncode": 0,
            "stdout": '{"loggedIn": false, "authMethod": "none"}',
            "stderr": "",
        })()

    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        fake_run,
    )

    readiness = probe_provider_readiness("claude")

    assert readiness.ready is False
    assert readiness.status == "authentication_required"
    assert readiness.code == "provider_authentication_required"
    assert readiness.action == "Run `claude auth login` and try again."
    assert calls[0][0] == (
        "/tools/claude",
        "auth",
        "status",
        "--json",
    )
    assert calls[0][1]["timeout"] == 5.0
    assert calls[0][1]["check"] is False
    assert calls[0][1]["env"]["HOME"] == "/Users/tester"
    assert calls[0][1]["env"]["ANTHROPIC_API_KEY"] == "provider-auth"
    assert "DATABASE_URL" not in calls[0][1]["env"]
    assert "SERVER_API_KEY" not in calls[0][1]["env"]


def test_claude_readiness_accepts_logged_out_json_on_stderr(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: "/tools/claude",
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {
            "returncode": 1,
            "stdout": "",
            "stderr": (
                '{\n  "loggedIn": false,\n  "authMethod": "none",\n'
                '  "apiProvider": "firstParty"\n}\n'
            ),
        })(),
    )

    readiness = probe_provider_readiness("claude")

    assert readiness.ready is False
    assert readiness.status == "authentication_required"
    assert readiness.code == "provider_authentication_required"
    assert readiness.message == "Claude Code is not authenticated."
    assert readiness.action == "Run `claude auth login` and try again."


def test_codex_readiness_detects_a_broken_installed_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: "/tools/codex",
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {
            "returncode": 1,
            "stdout": "",
            "stderr": "Error: spawn /missing/vendor/codex ENOENT",
        })(),
    )

    readiness = probe_provider_readiness("codex")

    assert readiness.ready is False
    assert readiness.code == "provider_cli_broken"
    assert "wrapper is broken" in readiness.message


def test_opencode_readiness_requires_at_least_one_credential(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: "/tools/opencode",
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {
            "returncode": 0,
            "stdout": "\x1b[0m\n└  4 credentials\n",
            "stderr": "",
        })(),
    )

    readiness = probe_provider_readiness("opencode")

    assert readiness.ready is True
    assert readiness.status == "ready"
    assert readiness.code == "provider_ready"


def test_readiness_preserves_revoked_oauth_401_meaning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: "/tools/claude",
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {
            "returncode": 1,
            "stdout": "",
            "stderr": "401: OAuth token has been revoked",
        })(),
    )

    readiness = probe_provider_readiness("claude")

    assert readiness.ready is False
    assert readiness.code == "provider_authentication_revoked"
    assert "OAuth token has been revoked (401)" in readiness.message


def test_readiness_reports_a_missing_cli_without_running_a_probe(
    monkeypatch,
) -> None:
    runs = []
    monkeypatch.setattr(
        "app.services.harness_adapters.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "app.services.harness_adapters.subprocess.run",
        lambda *_args, **_kwargs: runs.append(True),
    )

    readiness = probe_provider_readiness("opencode")

    assert readiness.ready is False
    assert readiness.status == "unavailable"
    assert readiness.code == "provider_cli_not_found"
    assert runs == []


def test_provider_environment_preserves_only_os_and_provider_auth() -> None:
    server_secrets = {
        "DATABASE_URL": "database-secret",
        "SERVER_API_KEY": "server-api-secret",
        "PRINCIPAL_API_KEYS": "principal-secret",
        "ENCRYPTION_KEY": "encryption-secret",
        "PREVIOUS_ENCRYPTION_KEY": "previous-secret",
        "PREVIOUS_ENCRYPTION_KEYS": "previous-secrets",
        "REDIS_URL": "redis-secret",
        "LITELLM_API_KEY": "litellm-secret",
        "GOOGLE_CLIENT_SECRET": "google-connector-secret",
        "SLACK_CLIENT_SECRET": "slack-connector-secret",
        "ZOOM_CLIENT_SECRET": "zoom-connector-secret",
        "METRICS_TOKEN": "metrics-secret",
        "METRICS_BEARER_TOKEN": "metrics-bearer-secret",
        "POSTGRES_PASSWORD": "postgres-secret",
    }
    source = {
        "PATH": "/usr/local/bin:/usr/bin",
        "HOME": "/Users/tester",
        "LANG": "en_US.UTF-8",
        "XDG_CONFIG_HOME": "/Users/tester/.config",
        "ANTHROPIC_API_KEY": "anthropic-provider-auth",
        "CLAUDE_CODE_OAUTH_TOKEN": "claude-provider-auth",
        "OPENAI_API_KEY": "unrelated-provider-auth",
        "UNRELATED_SECRET": "must-not-pass",
        **server_secrets,
    }

    environment = provider_environment("claude", source)

    assert environment == {
        "PATH": "/usr/local/bin:/usr/bin",
        "HOME": "/Users/tester",
        "LANG": "en_US.UTF-8",
        "XDG_CONFIG_HOME": "/Users/tester/.config",
        "ANTHROPIC_API_KEY": "anthropic-provider-auth",
        "CLAUDE_CODE_OAUTH_TOKEN": "claude-provider-auth",
    }
    assert not set(server_secrets).intersection(environment)
