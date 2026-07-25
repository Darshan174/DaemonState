from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


ProviderName = Literal["codex", "claude", "opencode"]
TargetProvider = Literal["codex", "claude", "opencode", "auto"]
ContextDelivery = Literal["stdin", "file"]
InvocationMode = Literal["fresh", "session"]

CONTEXT_FILE_PLACEHOLDER = "{context_file}"
OPENCODE_CONTINUATION_MESSAGE = (
    "Continue the task using the attached Context Engine context pack. "
    "Verify the current repository state before editing."
)
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
PROVIDER_EXECUTABLES: dict[ProviderName, str] = {
    "codex": "codex",
    "claude": "claude",
    "opencode": "opencode",
}
PROVIDER_DISPLAY_NAMES: dict[ProviderName, str] = {
    "codex": "Codex",
    "claude": "Claude Code",
    "opencode": "OpenCode",
}
PROVIDER_AUTH_ACTIONS: dict[ProviderName, str] = {
    "codex": "Run `codex login` and try again.",
    "claude": "Run `claude auth login` and try again.",
    "opencode": "Run `opencode auth login` and try again.",
}
PROVIDER_READINESS_COMMANDS: dict[ProviderName, tuple[str, ...]] = {
    "codex": ("login", "status"),
    "claude": ("auth", "status", "--json"),
    "opencode": ("auth", "list"),
}
CODEX_EXECUTABLE_OVERRIDE_ENV = "CONTEXT_ENGINE_CODEX_EXECUTABLE"
CODEX_APP_EXECUTABLES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
)
PROVIDER_READINESS_TIMEOUT_SECONDS = 5.0
PROVIDER_READINESS_OUTPUT_LIMIT = 8_192
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BASE_PROCESS_ENVIRONMENT_KEYS = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "FORCE_COLOR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
    "SSH_AUTH_SOCK",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
})
PROVIDER_ENVIRONMENT_KEYS: dict[ProviderName, frozenset[str]] = {
    "codex": frozenset({
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
    }),
    "claude": frozenset({
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "CLOUD_ML_REGION",
    }),
    "opencode": frozenset({
        "OPENCODE_CONFIG",
        "OPENCODE_CONFIG_DIR",
        "OPENCODE_CONFIG_CONTENT",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }),
}
CONTEXT_ENGINE_SECRET_KEYS = frozenset({
    "DATABASE_URL",
    "SERVER_API_KEY",
    "PRINCIPAL_API_KEYS",
    "ENCRYPTION_KEY",
    "PREVIOUS_ENCRYPTION_KEY",
    "PREVIOUS_ENCRYPTION_KEYS",
    "REDIS_URL",
    "LITELLM_API_KEY",
    "METRICS_TOKEN",
    "METRICS_BEARER_TOKEN",
    "POSTGRES_PASSWORD",
})


class HarnessAdapterError(ValueError):
    """Raised when a safe local provider invocation cannot be built."""


class HarnessExecutableNotFound(HarnessAdapterError):
    """Raised when no usable local provider CLI can be found."""


@dataclass(frozen=True)
class ProviderReadiness:
    provider: ProviderName
    ready: bool
    status: str
    code: str
    message: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "ready": self.ready,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }


@dataclass(frozen=True)
class HarnessInvocation:
    provider: ProviderName
    argv: tuple[str, ...]
    context_delivery: ContextDelivery
    executable: str
    mode: InvocationMode
    repo_path: str
    session_id: str | None
    model: str | None


def probe_provider_readiness(
    provider: str,
    *,
    timeout_seconds: float = PROVIDER_READINESS_TIMEOUT_SECONDS,
) -> ProviderReadiness:
    """Fail-closed local CLI/authentication preflight with bounded output."""

    normalized_provider = _provider_name(provider)
    environment = provider_environment(normalized_provider)
    display_name = PROVIDER_DISPLAY_NAMES[normalized_provider]
    executable = _provider_executable(normalized_provider)
    if not executable:
        return ProviderReadiness(
            provider=normalized_provider,
            ready=False,
            status="unavailable",
            code="provider_cli_not_found",
            message=f"{display_name} CLI is not installed or is not on PATH.",
            action=f"Install the {display_name} CLI and try again.",
        )
    if "\x00" in executable:
        return ProviderReadiness(
            provider=normalized_provider,
            ready=False,
            status="unavailable",
            code="provider_cli_invalid",
            message=f"{display_name} CLI path is invalid.",
            action=f"Reinstall the {display_name} CLI and try again.",
        )

    command = (executable, *PROVIDER_READINESS_COMMANDS[normalized_provider])
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return ProviderReadiness(
            provider=normalized_provider,
            ready=False,
            status="unavailable",
            code="provider_readiness_timeout",
            message=f"{display_name} readiness check timed out.",
            action=f"Check the {display_name} CLI, then try again.",
        )
    except OSError:
        return ProviderReadiness(
            provider=normalized_provider,
            ready=False,
            status="unavailable",
            code="provider_cli_broken",
            message=f"{display_name} CLI could not be started.",
            action=f"Reinstall or repair the {display_name} CLI and try again.",
        )

    stdout = _bounded_probe_output(result.stdout)
    stderr = _bounded_probe_output(result.stderr)
    combined = "\n".join(part for part in (stdout, stderr) if part)
    if normalized_provider == "claude":
        return _claude_readiness(result.returncode, stdout, stderr, combined)
    if normalized_provider == "codex":
        return _codex_readiness(result.returncode, combined)
    return _opencode_readiness(result.returncode, combined)


def minimal_process_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return only non-secret OS variables needed for direct child processes."""

    environment = os.environ if source is None else source
    return _selected_environment(environment, BASE_PROCESS_ENVIRONMENT_KEYS)


def provider_environment(
    provider: str,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return one provider's minimal launch/auth environment."""

    normalized_provider = _provider_name(provider)
    allowed = (
        BASE_PROCESS_ENVIRONMENT_KEYS
        | PROVIDER_ENVIRONMENT_KEYS[normalized_provider]
    )
    environment = os.environ if source is None else source
    return _selected_environment(environment, allowed)


def is_context_engine_secret_key(key: str) -> bool:
    normalized = str(key or "").strip().upper()
    return (
        normalized in CONTEXT_ENGINE_SECRET_KEYS
        or normalized.endswith("_CLIENT_SECRET")
    )


def _selected_environment(
    source: Mapping[str, str],
    allowed: frozenset[str],
) -> dict[str, str]:
    selected: dict[str, str] = {}
    for raw_key, raw_value in source.items():
        key = str(raw_key)
        normalized_key = key.upper()
        value = str(raw_value)
        if (
            normalized_key not in allowed
            or is_context_engine_secret_key(normalized_key)
            or not key
            or "\x00" in key
            or "=" in key
            or "\x00" in value
        ):
            continue
        selected[key] = value
    return selected


def build_harness_invocation(
    provider: str,
    *,
    repo_path: str | Path,
    session_id: str | None = None,
    model: str | None = None,
) -> HarnessInvocation:
    """Build a non-interactive provider argv without executing it."""

    normalized_provider = _provider_name(provider)
    normalized_repo = _repository_path(repo_path)
    normalized_session_id = _session_id(session_id)
    normalized_model = _model(model)
    executable_name = PROVIDER_EXECUTABLES[normalized_provider]
    executable = _provider_executable(normalized_provider)
    if not executable:
        raise HarnessExecutableNotFound(
            f"{executable_name} CLI is not available on PATH"
        )
    if "\x00" in executable:
        raise HarnessAdapterError("provider executable path is invalid")

    mode: InvocationMode = (
        "session" if normalized_session_id is not None else "fresh"
    )
    if normalized_provider == "codex":
        argv = _codex_argv(
            executable,
            normalized_repo,
            normalized_session_id,
            normalized_model,
        )
        delivery: ContextDelivery = "stdin"
    elif normalized_provider == "claude":
        argv = _claude_argv(
            executable,
            normalized_repo,
            normalized_session_id,
            normalized_model,
        )
        delivery = "stdin"
    else:
        argv = _opencode_argv(
            executable,
            normalized_repo,
            normalized_session_id,
            normalized_model,
        )
        delivery = "file"

    return HarnessInvocation(
        provider=normalized_provider,
        argv=argv,
        context_delivery=delivery,
        executable=executable,
        mode=mode,
        repo_path=normalized_repo,
        session_id=normalized_session_id,
        model=normalized_model,
    )


def _provider_executable(provider: ProviderName) -> str | None:
    """Resolve the executable that will actually receive the continuation.

    Codex Desktop ships a CLI that is kept in lock-step with the app's current
    model contract. A stale npm-global wrapper can still appear first on PATH,
    so prefer the bundled executable over that specific class of wrapper. An
    explicit override remains available for non-standard installations.
    """

    executable_name = PROVIDER_EXECUTABLES[provider]
    if provider != "codex":
        return shutil.which(executable_name)

    override = str(os.environ.get(CODEX_EXECUTABLE_OVERRIDE_ENV) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None

    path_executable = shutil.which(executable_name)
    bundled_executable = next(
        (
            str(candidate)
            for candidate in CODEX_APP_EXECUTABLES
            if candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if bundled_executable and (
        path_executable is None or _is_npm_global_codex(path_executable)
    ):
        return bundled_executable
    return path_executable


def _is_npm_global_codex(executable: str) -> bool:
    raw = str(executable or "").replace("\\", "/").casefold()
    try:
        resolved = str(Path(executable).expanduser().resolve()).replace(
            "\\", "/"
        ).casefold()
    except OSError:
        resolved = raw
    return (
        "/.npm-global/" in raw
        or "/.npm-global/" in resolved
        or "/node_modules/@openai/codex/" in resolved
    )


def _claude_readiness(
    return_code: int,
    stdout: str,
    stderr: str,
    combined: str,
) -> ProviderReadiness:
    auth_failure = _authentication_readiness("claude", combined)
    if auth_failure is not None:
        return auth_failure
    payload = (
        _json_object(stdout)
        or _json_object(stderr)
        or _json_object(combined)
    )
    if payload is not None:
        if return_code == 0 and payload.get("loggedIn") is True:
            return _ready("claude")
        if payload.get("loggedIn") is False:
            return _authentication_required("claude")
    if return_code != 0:
        return _probe_failed("claude")
    return ProviderReadiness(
        provider="claude",
        ready=False,
        status="unavailable",
        code="provider_readiness_invalid",
        message="Claude Code returned an invalid authentication status.",
        action="Repair or update the Claude Code CLI and try again.",
    )


def _codex_readiness(return_code: int, combined: str) -> ProviderReadiness:
    auth_failure = _authentication_readiness("codex", combined)
    if auth_failure is not None:
        return auth_failure
    normalized = combined.casefold()
    if return_code == 0 and "logged in" in normalized:
        return _ready("codex")
    if return_code != 0:
        if "enoent" in normalized or "spawn" in normalized:
            return ProviderReadiness(
                provider="codex",
                ready=False,
                status="unavailable",
                code="provider_cli_broken",
                message="Codex CLI is installed, but its executable wrapper is broken.",
                action="Reinstall or repair the Codex CLI and try again.",
            )
        return _probe_failed("codex")
    return ProviderReadiness(
        provider="codex",
        ready=False,
        status="unavailable",
        code="provider_readiness_invalid",
        message="Codex did not confirm a valid login.",
        action="Repair or update the Codex CLI, then run `codex login`.",
    )


def _opencode_readiness(return_code: int, combined: str) -> ProviderReadiness:
    auth_failure = _authentication_readiness("opencode", combined)
    if auth_failure is not None:
        return auth_failure
    normalized = combined.casefold()
    if return_code != 0:
        return _probe_failed("opencode")
    credential_match = re.search(r"\b(\d+)\s+credentials?\b", normalized)
    if credential_match and int(credential_match.group(1)) > 0:
        return _ready("opencode")
    if (
        (credential_match and int(credential_match.group(1)) == 0)
        or "no credentials" in normalized
    ):
        return _authentication_required("opencode")
    return ProviderReadiness(
        provider="opencode",
        ready=False,
        status="unavailable",
        code="provider_readiness_invalid",
        message="OpenCode did not report any usable provider credentials.",
        action="Run `opencode auth login` and try again.",
    )


def _ready(provider: ProviderName) -> ProviderReadiness:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    return ProviderReadiness(
        provider=provider,
        ready=True,
        status="ready",
        code="provider_ready",
        message=f"{display_name} is installed and authenticated.",
        action=f"Continue in {display_name}.",
    )


def _authentication_required(provider: ProviderName) -> ProviderReadiness:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    return ProviderReadiness(
        provider=provider,
        ready=False,
        status="authentication_required",
        code="provider_authentication_required",
        message=f"{display_name} is not authenticated.",
        action=PROVIDER_AUTH_ACTIONS[provider],
    )


def _authentication_readiness(
    provider: ProviderName,
    output: str,
) -> ProviderReadiness | None:
    normalized = output.casefold()
    if _revoked_token_failure(normalized):
        display_name = PROVIDER_DISPLAY_NAMES[provider]
        return ProviderReadiness(
            provider=provider,
            ready=False,
            status="authentication_required",
            code="provider_authentication_revoked",
            message=(
                f"{display_name} authentication failed because its OAuth token "
                "has been revoked (401)."
            ),
            action=PROVIDER_AUTH_ACTIONS[provider],
        )
    auth_markers = (
        "not logged in",
        "authentication required",
        "authentication failed",
        "unauthenticated",
        "unauthorized",
        "please log in",
        "please login",
        "invalid oauth",
        "token expired",
        "401",
    )
    if any(marker in normalized for marker in auth_markers):
        return _authentication_required(provider)
    return None


def _probe_failed(provider: ProviderName) -> ProviderReadiness:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    return ProviderReadiness(
        provider=provider,
        ready=False,
        status="unavailable",
        code="provider_readiness_failed",
        message=f"{display_name} readiness check failed.",
        action=f"Check or repair the {display_name} CLI and try again.",
    )


def _json_object(value: str) -> dict[str, Any] | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        payload = json.loads(normalized)
    except (TypeError, ValueError):
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(normalized[start : end + 1])
        except (TypeError, ValueError):
            return None
    return payload if isinstance(payload, dict) else None


def _bounded_probe_output(value: str | None) -> str:
    cleaned = ANSI_ESCAPE_PATTERN.sub("", str(value or ""))
    return cleaned[:PROVIDER_READINESS_OUTPUT_LIMIT]


def _revoked_token_failure(normalized_output: str) -> bool:
    return (
        "revoked" in normalized_output
        and ("oauth" in normalized_output or "token" in normalized_output)
    )


def _provider_name(value: str) -> ProviderName:
    normalized = str(value or "").strip().lower()
    if normalized == "claude_code":
        normalized = "claude"
    if normalized not in PROVIDER_EXECUTABLES:
        raise HarnessAdapterError(f"unsupported harness provider: {normalized or 'empty'}")
    return normalized  # type: ignore[return-value]


def _repository_path(value: str | Path) -> str:
    raw = str(value or "").strip()
    if not raw or "\x00" in raw:
        raise HarnessAdapterError("repo_path must identify a repository directory")
    candidate = Path(raw).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise HarnessAdapterError("repo_path does not exist") from exc
    if not resolved.is_dir():
        raise HarnessAdapterError("repo_path must be a directory")
    return str(resolved)


def _session_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not SESSION_ID_PATTERN.fullmatch(normalized):
        raise HarnessAdapterError("session_id is not safe to pass to a provider CLI")
    return normalized


def _model(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if (
        not normalized
        or "\x00" in normalized
        or len(normalized) > 255
        or normalized.startswith("-")
    ):
        raise HarnessAdapterError("model is not safe to pass to a provider CLI")
    return normalized


def _codex_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
) -> tuple[str, ...]:
    prefix = (
        executable,
        "-C",
        repo_path,
        "--sandbox",
        "workspace-write",
        *((("-m", model)) if model is not None else ()),
        "exec",
    )
    if session_id is None:
        return (*prefix, "--json", "-")
    return (*prefix, "resume", "--json", session_id, "-")


def _claude_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
) -> tuple[str, ...]:
    argv = (
        executable,
        "--print",
        "--verbose",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--add-dir",
        repo_path,
    )
    if model is not None:
        argv = (*argv, "--model", model)
    if session_id is None:
        return argv
    return (*argv, "--resume", session_id)


def _opencode_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
) -> tuple[str, ...]:
    argv = (
        executable,
        "run",
        "--format",
        "json",
        "--dir",
        repo_path,
    )
    if model is not None:
        argv = (*argv, "--model", model)
    if session_id is not None:
        argv = (*argv, "--session", session_id)
    return (
        *argv,
        "-f",
        CONTEXT_FILE_PLACEHOLDER,
        OPENCODE_CONTINUATION_MESSAGE,
    )
