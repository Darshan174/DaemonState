from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


ProviderName = Literal["codex", "claude", "opencode"]
TargetProvider = Literal["codex", "claude", "opencode", "auto"]
ContextDelivery = Literal["stdin", "file"]
InvocationMode = Literal["fresh", "session"]

CONTEXT_FILE_PLACEHOLDER = "{context_file}"
OPENCODE_CONTINUATION_MESSAGE = (
    "Execute the attached canonical DaemonState continuation prompt. "
    "Do not merely summarize it. Use the supplied runtime bundle for its "
    "hash-bound contract and artifacts."
)
OPENCODE_MODEL_ENV = "DAEMONSTATE_OPENCODE_MODEL"
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
CODEX_EXECUTABLE_OVERRIDE_ENV = "DAEMONSTATE_CODEX_EXECUTABLE"
CODEX_APP_EXECUTABLES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
)
PROVIDER_READINESS_TIMEOUT_SECONDS = 5.0
PROVIDER_READINESS_OUTPUT_LIMIT = 8_192
CODEX_MODEL_CATALOG_TIMEOUT_SECONDS = 5.0
CODEX_MODEL_CATALOG_OUTPUT_LIMIT = 2_000_000
CODEX_DESKTOP_MODEL_CACHE_MAX_AGE_SECONDS = 15 * 60
CODEX_DESKTOP_MODEL_CACHE_MAX_BYTES = 2_000_000
CODEX_REASONING_EFFORTS = frozenset({
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
})
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
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
DAEMONSTATE_SECRET_KEYS = frozenset({
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
class ProviderModelOption:
    id: str
    label: str
    default: bool
    reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "default": self.default,
            "reasoning_efforts": list(self.reasoning_efforts),
            "default_reasoning_effort": self.default_reasoning_effort,
        }


@dataclass(frozen=True)
class ProviderReadiness:
    provider: ProviderName
    ready: bool
    status: str
    code: str
    message: str
    action: str
    models: tuple[ProviderModelOption, ...] = field(default_factory=tuple)
    desktop_available: bool | None = None
    exact_session_supported: bool | None = None
    context_staging_supported: bool = False
    desktop_handoff_supported: bool = False
    readiness_scope: str = "provider_cli_and_authentication"
    account_access_state: str | None = None
    account_access_verified: bool | None = None
    model_catalog_source: str | None = None
    capabilities: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "ready": self.ready,
            "readiness_scope": self.readiness_scope,
            "task_contract_checked": False,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "models": [model.to_dict() for model in self.models],
            "desktop_available": self.desktop_available,
            "exact_session_supported": self.exact_session_supported,
            "context_staging_supported": self.context_staging_supported,
            "desktop_handoff_supported": self.desktop_handoff_supported,
            "account_access_state": self.account_access_state,
            "account_access_verified": self.account_access_verified,
            "model_catalog_source": self.model_catalog_source,
        }
        if self.capabilities is not None:
            payload["capabilities"] = self.capabilities
        return payload


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
    effort: str | None = None
    filesystem_mode: str = "workspace_write"


def probe_provider_readiness(
    provider: str,
    *,
    provider_model: str | None = None,
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
        readiness = _codex_readiness(result.returncode, combined)
        if not readiness.ready:
            return readiness
        models = codex_model_catalog(
            executable=executable,
            timeout_seconds=timeout_seconds,
        )
        try:
            normalized_model = _model(provider_model) if provider_model else None
        except HarnessAdapterError:
            return ProviderReadiness(
                provider="codex",
                ready=False,
                status="configuration_required",
                code="provider_model_configuration_required",
                message="The selected Codex model identifier is invalid.",
                action="Choose a model reported by the current Codex CLI.",
                models=models,
            )
        if normalized_model is not None and not any(
            option.id == normalized_model for option in models
        ):
            catalog_detail = (
                "the discovered Codex model catalog does not list it"
                if models
                else "Codex model catalog discovery did not succeed"
            )
            return ProviderReadiness(
                provider="codex",
                ready=False,
                status="access_required",
                code="provider_model_access_required",
                message=(
                    f"DaemonState cannot prove that Codex model "
                    f"`{normalized_model}` is available because {catalog_detail}."
                ),
                action=(
                    "Choose a model listed by the current Codex CLI, or clear "
                    "the explicit model selection and use the CLI default."
                ),
                models=models,
            )
        message = readiness.message
        if not models:
            message = (
                f"{message} Codex model catalog discovery did not return "
                "a trustworthy catalog, so DaemonState will use the CLI "
                "default without offering model or effort overrides."
            )
        return replace(
            readiness,
            message=message,
            models=models,
        )
    return _opencode_readiness(
        result.returncode,
        combined,
        provider_model=(
            provider_model
            or continuation_provider_model("opencode", None)
        ),
    )


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


def continuation_provider_model(
    provider: str,
    requested_model: str | None,
) -> str | None:
    """Resolve the explicit model used by DaemonState continuation runs."""

    normalized_provider = _provider_name(provider)
    if requested_model is not None:
        return requested_model
    if normalized_provider != "opencode":
        return None
    return str(os.environ.get(OPENCODE_MODEL_ENV) or "").strip() or None


def codex_model_catalog(
    *,
    executable: str | None = None,
    timeout_seconds: float = CODEX_MODEL_CATALOG_TIMEOUT_SECONDS,
) -> tuple[ProviderModelOption, ...]:
    """Return only model choices proven by the current Codex CLI."""

    resolved_executable = executable or _provider_executable("codex")
    if not resolved_executable or "\x00" in resolved_executable:
        return ()
    try:
        result = subprocess.run(
            (resolved_executable, "debug", "models"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=provider_environment("codex"),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()
    payload = _json_object(
        ANSI_ESCAPE_PATTERN.sub("", str(result.stdout or ""))[
            :CODEX_MODEL_CATALOG_OUTPUT_LIMIT
        ]
    )
    return codex_models_from_payload(payload)


def codex_cached_model_catalog(
    *,
    cache_path: Path | None = None,
    now: datetime | None = None,
    max_age_seconds: float = CODEX_DESKTOP_MODEL_CACHE_MAX_AGE_SECONDS,
) -> tuple[ProviderModelOption, ...]:
    """Read a fresh, non-secret model catalog already cached by Codex.

    This never starts Codex or reads authentication material. A catalog is
    useful for rendering requested model/effort controls, but its presence is
    not proof of a current subscription, entitlement, quota, or successful
    desktop sign-in.
    """

    resolved_path = cache_path or _codex_model_cache_path()
    try:
        stat = resolved_path.stat()
        if (
            not resolved_path.is_file()
            or stat.st_size <= 0
            or stat.st_size > CODEX_DESKTOP_MODEL_CACHE_MAX_BYTES
        ):
            return ()
        payload = json.loads(
            resolved_path.read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    fetched_at = _utc_datetime(payload.get("fetched_at"))
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    else:
        checked_at = checked_at.astimezone(timezone.utc)
    if fetched_at is None:
        return ()
    age_seconds = (checked_at - fetched_at).total_seconds()
    if age_seconds < -60 or age_seconds > max(0.0, max_age_seconds):
        return ()
    if not str(payload.get("client_version") or "").strip():
        return ()
    return codex_models_from_payload(payload)


def _codex_model_cache_path() -> Path:
    configured_home = str(os.environ.get("CODEX_HOME") or "").strip()
    root = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
    return root / "models_cache.json"


def _utc_datetime(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_daemonstate_secret_key(key: str) -> bool:
    normalized = str(key or "").strip().upper()
    return (
        normalized in DAEMONSTATE_SECRET_KEYS
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
            or is_daemonstate_secret_key(normalized_key)
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
    effort: str | None = None,
    visible: bool = False,
    filesystem_mode: str = "workspace_write",
) -> HarnessInvocation:
    """Build a non-interactive provider argv without executing it."""

    normalized_provider = _provider_name(provider)
    normalized_repo = _repository_path(repo_path)
    normalized_session_id = _session_id(session_id)
    normalized_model = _model(model)
    normalized_effort = _reasoning_effort(effort)
    normalized_filesystem_mode = _filesystem_mode(filesystem_mode)
    executable_name = PROVIDER_EXECUTABLES[normalized_provider]
    executable = _provider_executable(normalized_provider)
    if not executable:
        raise HarnessExecutableNotFound(
            f"{executable_name} CLI is not available on PATH"
        )
    if "\x00" in executable:
        raise HarnessAdapterError("provider executable path is invalid")
    if normalized_effort is not None and normalized_provider != "codex":
        raise HarnessAdapterError(
            "reasoning effort is only supported by the Codex provider"
        )
    if (
        normalized_filesystem_mode == "read_only"
        and normalized_provider == "opencode"
    ):
        raise HarnessAdapterError(
            f"{PROVIDER_DISPLAY_NAMES[normalized_provider]} cannot enforce "
            "the required read-only filesystem mode"
        )

    mode: InvocationMode = (
        "session" if normalized_session_id is not None else "fresh"
    )
    if normalized_provider == "codex":
        _validate_codex_model_selection(
            model=normalized_model,
            effort=normalized_effort,
            executable=executable,
        )
        argv = (
            _codex_visible_argv(
                executable,
                normalized_repo,
                normalized_session_id,
                normalized_model,
                normalized_effort,
                normalized_filesystem_mode,
            )
            if visible
            else _codex_argv(
                executable,
                normalized_repo,
                normalized_session_id,
                normalized_model,
                normalized_effort,
                normalized_filesystem_mode,
            )
        )
        delivery: ContextDelivery = "stdin"
    elif normalized_provider == "claude":
        argv = _claude_argv(
            executable,
            normalized_repo,
            normalized_session_id,
            normalized_model,
            normalized_filesystem_mode,
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
        effort=normalized_effort,
        filesystem_mode=normalized_filesystem_mode,
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
        auth_method = str(payload.get("authMethod") or "").strip().casefold()
        if (
            return_code == 0
            and payload.get("loggedIn") is True
            and auth_method
            and auth_method != "none"
        ):
            return ProviderReadiness(
                provider="claude",
                ready=True,
                status="configured",
                code="provider_configured",
                message=(
                    "Claude Code CLI has authentication configured. "
                    "Live Claude Code plan or API access is not verified until "
                    "a run starts."
                ),
                action="Continue in Claude Code.",
            )
        if (
            payload.get("loggedIn") is False
            or auth_method == "none"
        ):
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


def _opencode_readiness(
    return_code: int,
    combined: str,
    *,
    provider_model: str | None,
) -> ProviderReadiness:
    auth_failure = _authentication_readiness("opencode", combined)
    if auth_failure is not None:
        return auth_failure
    if return_code != 0:
        return _probe_failed("opencode")
    normalized = combined.casefold()
    credential_match = re.search(r"\b(\d+)\s+credentials?\b", normalized)
    model_provider = (
        _opencode_model_provider(provider_model)
        if provider_model
        else None
    )
    if (
        (credential_match and int(credential_match.group(1)) == 0)
        or "no credentials" in normalized
    ):
        if model_provider != "opencode":
            return _authentication_required("opencode")
        credential_providers: set[str] = set()
    else:
        credential_providers = _opencode_credential_providers(combined)
    if not credential_providers:
        return ProviderReadiness(
            provider="opencode",
            ready=False,
            status="unavailable",
            code="provider_readiness_invalid",
            message=(
                "OpenCode listed credentials, but their providers could not "
                "be identified."
            ),
            action="Update OpenCode, then check provider access again.",
        )
    if not provider_model:
        return ProviderReadiness(
            provider="opencode",
            ready=False,
            status="configuration_required",
            code="provider_model_configuration_required",
            message=(
                "OpenCode CLI has connected providers, but DaemonState has "
                "no execution model selected. Installed credentials do not "
                "prove an active OpenCode Go or Zen subscription."
            ),
            action=(
                f"Set `{OPENCODE_MODEL_ENV}` to a `provider/model` available "
                "from one of the connected providers, then check again."
            ),
        )
    if (
        model_provider not in credential_providers
    ):
        provider_label = _opencode_provider_label(model_provider)
        return ProviderReadiness(
            provider="opencode",
            ready=False,
            status="access_required",
            code="provider_model_access_required",
            message=(
                "OpenCode CLI is installed, but "
                f"`{provider_model}` has no matching {provider_label} credential."
            ),
            action=(
                f"Connect {provider_label} in OpenCode, or configure a model "
                "from one of the connected providers."
            ),
        )
    return ProviderReadiness(
        provider="opencode",
        ready=True,
        status="configured",
        code="provider_configured",
        message=(
            f"OpenCode CLI is configured to try `{provider_model}`. "
            "Live model access, service availability, and balance are not "
            "verified until a run starts."
        ),
        action="Continue in OpenCode.",
    )


def _opencode_credential_providers(output: str) -> set[str]:
    providers: set[str] = set()
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip().lstrip("●○│└┌─ ").strip()
        match = re.fullmatch(r"(.+?)\s+(?:api|oauth|wellknown)", line, re.IGNORECASE)
        if match is None:
            continue
        provider = _normalized_provider_id(match.group(1))
        if provider:
            providers.add(provider)
    return providers


def _opencode_model_provider(model: str) -> str:
    provider = str(model or "").split("/", 1)[0]
    return _normalized_provider_id(provider)


def _normalized_provider_id(value: str) -> str:
    normalized = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").strip().casefold(),
    ).strip("-")
    return {
        "opencode-zen": "opencode",
    }.get(normalized, normalized)


def _opencode_provider_label(provider: str) -> str:
    return {
        "opencode": "OpenCode Zen",
        "opencode-go": "OpenCode Go",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
    }.get(provider, provider)


def _ready(provider: ProviderName) -> ProviderReadiness:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    cli_name = "Claude Code CLI" if provider == "claude" else f"{display_name} CLI"
    return ProviderReadiness(
        provider=provider,
        ready=True,
        status="ready",
        code="provider_ready",
        message=f"{cli_name} is installed and signed in.",
        action=f"Continue in {display_name}.",
    )


def _authentication_required(provider: ProviderName) -> ProviderReadiness:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    cli_name = "Claude Code CLI" if provider == "claude" else f"{display_name} CLI"
    return ProviderReadiness(
        provider=provider,
        ready=False,
        status="authentication_required",
        code="provider_authentication_required",
        message=f"{cli_name} is installed, but it is not signed in.",
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
        or not MODEL_ID_PATTERN.fullmatch(normalized)
    ):
        raise HarnessAdapterError("model is not safe to pass to a provider CLI")
    return normalized


def _reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized not in CODEX_REASONING_EFFORTS:
        raise HarnessAdapterError(
            "reasoning effort is not supported by the Codex CLI"
        )
    return normalized


def _filesystem_mode(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized not in {"read_only", "workspace_write"}:
        raise HarnessAdapterError(
            "filesystem_mode must be read_only or workspace_write"
        )
    return normalized


def _validate_codex_model_selection(
    *,
    model: str | None,
    effort: str | None,
    executable: str,
) -> None:
    if model is None and effort is None:
        return
    catalog = codex_model_catalog(executable=executable)
    if not catalog:
        requested = (
            f"model `{model}`"
            if model is not None
            else f"reasoning effort `{effort}`"
        )
        raise HarnessAdapterError(
            f"cannot use Codex {requested}: the current CLI did not return "
            "a trustworthy model catalog"
        )
    selected = next(
        (
            option
            for option in catalog
            if option.id == model or (model is None and option.default)
        ),
        None,
    )
    if selected is None:
        raise HarnessAdapterError(
            f"Codex model `{model}` is not present in the current CLI model catalog"
        )
    if effort is not None and effort not in selected.reasoning_efforts:
        raise HarnessAdapterError(
            f"reasoning effort `{effort}` is not supported by model "
            f"`{selected.id}`"
        )


def codex_models_from_payload(
    payload: dict[str, Any] | None,
) -> tuple[ProviderModelOption, ...]:
    raw_models = payload.get("models") if payload is not None else None
    if not isinstance(raw_models, list):
        return ()
    parsed: list[tuple[int, int, str, str, tuple[str, ...], str]] = []
    seen: set[str] = set()
    for index, raw_model in enumerate(raw_models):
        if not isinstance(raw_model, dict):
            continue
        model_id = str(raw_model.get("slug") or "").strip()
        if (
            str(raw_model.get("visibility") or "").strip().casefold() != "list"
            or not model_id.startswith("gpt-")
            or not MODEL_ID_PATTERN.fullmatch(model_id)
            or model_id in seen
        ):
            continue
        raw_levels = raw_model.get("supported_reasoning_levels")
        if not isinstance(raw_levels, list):
            continue
        efforts: list[str] = []
        for raw_level in raw_levels:
            raw_effort = (
                raw_level.get("effort")
                if isinstance(raw_level, dict)
                else raw_level
            )
            normalized_effort = str(raw_effort or "").strip().casefold()
            if (
                normalized_effort in CODEX_REASONING_EFFORTS
                and normalized_effort not in efforts
            ):
                efforts.append(normalized_effort)
        if not efforts:
            continue
        default_effort = str(
            raw_model.get("default_reasoning_level") or ""
        ).strip().casefold()
        if default_effort not in efforts:
            default_effort = "medium" if "medium" in efforts else efforts[0]
        raw_label = str(raw_model.get("display_name") or model_id).strip()
        label = re.sub(r"[\x00-\x1f\x7f]", "", raw_label)[:128] or model_id
        raw_priority = raw_model.get("priority")
        priority = (
            raw_priority
            if isinstance(raw_priority, int) and not isinstance(raw_priority, bool)
            else 10_000
        )
        seen.add(model_id)
        parsed.append(
            (
                priority,
                index,
                model_id,
                label,
                tuple(efforts),
                default_effort,
            )
        )
    parsed.sort(key=lambda item: (item[0], item[1]))
    return tuple(
        ProviderModelOption(
            id=model_id,
            label=label,
            default=index == 0,
            reasoning_efforts=efforts,
            default_reasoning_effort=default_effort,
        )
        for index, (
            _priority,
            _source_index,
            model_id,
            label,
            efforts,
            default_effort,
        ) in enumerate(parsed)
    )


def _codex_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
    effort: str | None,
    filesystem_mode: str,
) -> tuple[str, ...]:
    prefix = (
        executable,
        "-C",
        repo_path,
        "--sandbox",
        filesystem_mode.replace("_", "-"),
        *((("-m", model)) if model is not None else ()),
        *(
            (("-c", f"model_reasoning_effort={effort}"))
            if effort is not None
            else ()
        ),
        "exec",
    )
    if session_id is None:
        return (*prefix, "--json", "-")
    return (*prefix, "resume", "--json", session_id, "-")


def _codex_visible_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
    effort: str | None,
    filesystem_mode: str,
) -> tuple[str, ...]:
    if session_id is not None:
        raise HarnessAdapterError(
            "visible Codex continuation currently requires a fresh Codex thread"
        )
    # `codex exec` owns its tool runtime and persists the rollout that the
    # desktop app renders. A raw app-server client would also need to implement
    # every server-initiated dynamic tool call; rejecting those requests
    # interrupts the turn at its first tool use.
    return _codex_argv(
        executable,
        repo_path,
        session_id,
        model,
        effort,
        filesystem_mode,
    )


def _claude_argv(
    executable: str,
    repo_path: str,
    session_id: str | None,
    model: str | None,
    filesystem_mode: str,
) -> tuple[str, ...]:
    permission_mode = (
        "plan"
        if filesystem_mode == "read_only"
        else "acceptEdits"
    )
    argv = (
        executable,
        "--print",
        "--verbose",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--permission-mode",
        permission_mode,
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
        # OpenCode's --file option is an array. Every following positional
        # token is otherwise consumed as another attachment, so the message
        # must appear before -f.
        OPENCODE_CONTINUATION_MESSAGE,
        "-f",
        CONTEXT_FILE_PLACEHOLDER,
    )
