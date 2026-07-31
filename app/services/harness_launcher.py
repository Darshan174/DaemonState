from __future__ import annotations

import json
import platform
import plistlib
import re
import selectors
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from app.services.harness_adapters import (
    ProviderModelOption,
    codex_cached_model_catalog,
    codex_executable,
    codex_models_from_app_server_payload,
    minimal_process_environment,
    provider_environment,
)
from app.telemetry import traced


HARNESS_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "opencode": "OpenCode",
}
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
# Claude Desktop currently bounds prompt-bearing deep links more tightly than
# the other supported apps. Keep one conservative cross-provider limit and
# fall back to the clipboard instead of silently truncating context.
DESKTOP_DEEP_LINK_PROMPT_MAX_CHARS = 12_000
# Keep clipboard and Launch Services dispatch inside one short total deadline,
# well below the API timeout, so a timed-out worker cannot continue into a
# later app-open attempt.
DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS = 3.0
CODEX_DESKTOP_ACCOUNT_PROBE_TIMEOUT_SECONDS = 2.25
CODEX_DESKTOP_ACCOUNT_PROBE_MAX_LINE_BYTES = 2_000_000
CODEX_DESKTOP_ACCOUNT_PROBE_MAX_MESSAGES = 256


@dataclass(frozen=True)
class DesktopAppSpec:
    bundle_ids: tuple[str, ...]
    app_names: tuple[str, ...]
    install_product: str
    url_scheme: str


@dataclass(frozen=True)
class MacOSDesktopApp:
    bundle_path: Path
    bundle_id: str
    url_schemes: frozenset[str]


@dataclass(frozen=True)
class HarnessVisibility:
    """Whether a continuation can be shown in the provider's own UI."""

    provider: str
    ready: bool
    desktop_available: bool
    exact_session_supported: bool
    code: str
    message: str
    action: str


@dataclass(frozen=True)
class HarnessComposerReadiness:
    """Whether a visible composer is installed and its account is usable."""

    provider: str
    ready: bool
    desktop_available: bool
    url_scheme_registered: bool
    required_url_scheme: str
    code: str
    message: str
    action: str
    models: tuple[ProviderModelOption, ...] = field(default_factory=tuple)
    account_access_state: str = "not_checked"
    account_access_verified: bool = False
    model_catalog_source: str | None = None


@dataclass(frozen=True)
class CodexDesktopAccountProbe:
    """Account-scoped evidence returned by the local Codex app-server."""

    signed_in: bool | None = None
    models: tuple[ProviderModelOption, ...] = field(default_factory=tuple)
    rate_limit_reached: bool | None = None
    rate_limit_code: str | None = None


MACOS_DESKTOP_APPS = {
    "codex": DesktopAppSpec(
        bundle_ids=("com.openai.codex",),
        app_names=("ChatGPT", "Codex"),
        install_product="the Codex desktop app",
        url_scheme="codex",
    ),
    "claude": DesktopAppSpec(
        bundle_ids=("com.anthropic.claudefordesktop", "com.anthropic.Claude"),
        app_names=("Claude", "Claude Desktop", "Claude for Desktop"),
        install_product="Claude Desktop",
        url_scheme="claude",
    ),
    "opencode": DesktopAppSpec(
        bundle_ids=("ai.opencode.desktop",),
        app_names=("OpenCode",),
        install_product="OpenCode Desktop",
        url_scheme="opencode",
    ),
}


class HarnessLaunchError(Exception):
    """Raised when a local harness desktop session cannot be opened safely."""

    def __init__(self, message: str, *, code: str = "launch_failed") -> None:
        super().__init__(message)
        self.code = code


def probe_harness_visibility(connector_type: str) -> HarnessVisibility:
    """Fail closed unless the exact running session can be shown locally."""

    connector_type = connector_type.strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    if connector_type not in MACOS_DESKTOP_APPS:
        raise HarnessLaunchError(f"Unsupported AI harness: {connector_type}")

    label = HARNESS_LABELS[connector_type]
    spec = MACOS_DESKTOP_APPS[connector_type]
    if platform.system() != "Darwin":
        return HarnessVisibility(
            provider=connector_type,
            ready=False,
            desktop_available=False,
            exact_session_supported=False,
            code="desktop_app_unsupported",
            message=f"{label} visible continuation is not supported on this system.",
            action=f"Run DaemonState on macOS with {spec.install_product}.",
        )

    desktop_available = _macos_desktop_app_installed(spec)
    exact_session_supported = connector_type == "codex"
    if not desktop_available:
        return HarnessVisibility(
            provider=connector_type,
            ready=False,
            desktop_available=False,
            exact_session_supported=exact_session_supported,
            code="desktop_app_missing",
            message=(
                f"{label} cannot show this continuation because its desktop "
                "app is not installed."
            ),
            action=f"Install {spec.install_product}, then check again.",
        )
    if not exact_session_supported:
        return HarnessVisibility(
            provider=connector_type,
            ready=False,
            desktop_available=True,
            exact_session_supported=False,
            code="visible_session_unsupported",
            message=(
                f"{label} is installed, but it cannot open the exact local "
                "automation session yet."
            ),
            action=(
                "Use a provider that can show the exact running continuation "
                "in its own harness."
            ),
        )
    return HarnessVisibility(
        provider=connector_type,
        ready=True,
        desktop_available=True,
        exact_session_supported=True,
        code="visible_harness_ready",
        message=f"{label} can show the exact running continuation.",
        action=f"Continue in {label}.",
    )


def probe_harness_composer_readiness(
    connector_type: str,
) -> HarnessComposerReadiness:
    """Report whether Continue can open a visible, non-submitting desktop draft.

    Desktop dispatch is the only hard gate. Codex account and model status is
    probed automatically when its local app-server supports the required
    read-only methods. Inconclusive account evidence never blocks opening the
    app because Codex remains the authority when the user eventually submits.
    """

    dispatch = _probe_harness_composer_dispatch(connector_type)
    if not dispatch.ready:
        return dispatch

    provider = dispatch.provider
    label = HARNESS_LABELS[provider]
    if provider == "codex":
        probe = probe_codex_desktop_account()
        cached_models = codex_cached_model_catalog()
        models = probe.models or cached_models
        model_catalog_source = (
            "codex_app_server"
            if probe.models
            else "codex_desktop_cache"
            if cached_models
            else None
        )
        if probe.signed_in is False:
            return replace(
                dispatch,
                code="desktop_account_sign_in_required",
                message=(
                    "Codex Desktop is ready to receive the draft, but its "
                    "local account status reports that sign-in is required."
                ),
                action=(
                    "Open Codex Desktop and sign in. The prepared draft will "
                    "remain reviewable and nothing is submitted automatically."
                ),
                models=models,
                account_access_state="signed_out",
                account_access_verified=False,
                model_catalog_source=model_catalog_source,
            )
        if probe.rate_limit_reached is True:
            return replace(
                dispatch,
                code="desktop_account_rate_limited",
                message=(
                    "Codex Desktop is signed in, but its account currently "
                    "reports that a usage limit has been reached."
                ),
                action=(
                    "Open Codex Desktop to review the limit or reset time. "
                    "Continue can still load the draft without submitting it."
                ),
                models=models,
                account_access_state="rate_limited",
                account_access_verified=False,
                model_catalog_source=model_catalog_source,
            )
        if probe.signed_in is True and probe.models:
            return replace(
                dispatch,
                code="desktop_account_access_verified",
                message=(
                    f"Codex Desktop is signed in and reports {len(probe.models)} "
                    f"available model{'' if len(probe.models) == 1 else 's'}."
                ),
                action="Open the prepared draft in Codex Desktop.",
                models=probe.models,
                account_access_state="verified",
                account_access_verified=True,
                model_catalog_source="codex_app_server",
            )
        return replace(
            dispatch,
            code="desktop_dispatch_ready",
            message=(
                f"{label} Desktop is ready to receive the draft. Its account "
                "or live model status could not be confirmed automatically, "
                "so Codex will verify access when the user sends."
            ),
            action=(
                "Open the prepared draft in Codex Desktop. Sign in or choose "
                "another model there if Codex requests it."
            ),
            models=models,
            account_access_state="unverified",
            account_access_verified=False,
            model_catalog_source=model_catalog_source,
        )
    return replace(
        dispatch,
        code="desktop_dispatch_ready",
        message=(
            f"{label} Desktop is ready to receive the draft. {label} will "
            "verify account and model access when the user sends."
        ),
        action=(
            f"Open the prepared draft in {label} Desktop. Nothing is submitted "
            "automatically."
        ),
        account_access_state="unverified",
        account_access_verified=False,
    )


def probe_codex_desktop_account(
    *,
    timeout_seconds: float = CODEX_DESKTOP_ACCOUNT_PROBE_TIMEOUT_SECONDS,
) -> CodexDesktopAccountProbe:
    """Read account, model, and explicit limit status without starting a turn."""

    executable = codex_executable()
    if (
        not executable
        or "\x00" in executable
        or timeout_seconds <= 0
    ):
        return CodexDesktopAccountProbe()

    try:
        process = subprocess.Popen(
            (executable, "app-server", "--stdio"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_codex_desktop_probe_environment(),
            bufsize=0,
        )
    except OSError:
        return CodexDesktopAccountProbe()

    deadline = time.monotonic() + timeout_seconds
    try:
        _send_codex_probe_message(process, {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "daemonstate",
                    "title": "DaemonState",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            },
        })
        initialize = _codex_probe_response_for(
            process,
            request_id=1,
            deadline=deadline,
        )
        if isinstance(initialize.get("error"), Mapping):
            return CodexDesktopAccountProbe()
        _send_codex_probe_message(
            process,
            {"method": "initialized", "params": {}},
        )

        _send_codex_probe_message(process, {
            "method": "account/read",
            "id": 2,
            "params": {"refreshToken": False},
        })
        account_response = _codex_probe_response_for(
            process,
            request_id=2,
            deadline=deadline,
        )
        signed_in = _codex_probe_signed_in(account_response)
        if signed_in is not True:
            return CodexDesktopAccountProbe(signed_in=signed_in)

        _send_codex_probe_message(process, {
            "method": "model/list",
            "id": 3,
            "params": {"includeHidden": False},
        })
        model_response = _codex_probe_response_for(
            process,
            request_id=3,
            deadline=deadline,
        )
        models = codex_models_from_app_server_payload(
            _codex_probe_result(model_response)
        )

        rate_limit_reached: bool | None = None
        rate_limit_code: str | None = None
        try:
            _send_codex_probe_message(process, {
                "method": "account/rateLimits/read",
                "id": 4,
            })
            rate_limit_response = _codex_probe_response_for(
                process,
                request_id=4,
                deadline=deadline,
            )
            rate_limit_reached, rate_limit_code = (
                _codex_probe_rate_limit_state(rate_limit_response)
            )
        except _CodexDesktopProbeUnavailable:
            # Account and account-scoped model evidence remains useful when an
            # older app-server lacks the optional rate-limit method.
            pass

        return CodexDesktopAccountProbe(
            signed_in=True,
            models=models,
            rate_limit_reached=rate_limit_reached,
            rate_limit_code=rate_limit_code,
        )
    except _CodexDesktopProbeUnavailable:
        return CodexDesktopAccountProbe()
    finally:
        _stop_codex_probe_process(process)


class _CodexDesktopProbeUnavailable(RuntimeError):
    pass


def _codex_desktop_probe_environment() -> dict[str, str]:
    """Use shared Codex state without letting API-key env override desktop auth."""

    environment = minimal_process_environment()
    codex_home = provider_environment("codex").get("CODEX_HOME")
    if codex_home:
        environment["CODEX_HOME"] = codex_home
    return environment


def _send_codex_probe_message(
    process: subprocess.Popen[bytes],
    payload: Mapping[str, Any],
) -> None:
    if process.stdin is None:
        raise _CodexDesktopProbeUnavailable
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    try:
        process.stdin.write(encoded)
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise _CodexDesktopProbeUnavailable from exc


def _codex_probe_response_for(
    process: subprocess.Popen[bytes],
    *,
    request_id: int,
    deadline: float,
) -> Mapping[str, Any]:
    if process.stdout is None:
        raise _CodexDesktopProbeUnavailable

    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        for _ in range(CODEX_DESKTOP_ACCOUNT_PROBE_MAX_MESSAGES):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise _CodexDesktopProbeUnavailable
            raw_line = process.stdout.readline(
                CODEX_DESKTOP_ACCOUNT_PROBE_MAX_LINE_BYTES + 1
            )
            if (
                not raw_line
                or len(raw_line) > CODEX_DESKTOP_ACCOUNT_PROBE_MAX_LINE_BYTES
            ):
                raise _CodexDesktopProbeUnavailable
            try:
                message = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (TypeError, ValueError):
                continue
            if not isinstance(message, Mapping):
                continue
            if message.get("id") == request_id:
                return message
            if message.get("id") is not None and str(
                message.get("method") or ""
            ).strip():
                _send_codex_probe_message(process, {
                    "id": message["id"],
                    "error": {
                        "code": -32000,
                        "message": (
                            "Interactive requests are unavailable during the "
                            "DaemonState readiness probe."
                        ),
                    },
                })
    raise _CodexDesktopProbeUnavailable


def _codex_probe_result(
    response: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if isinstance(response.get("error"), Mapping):
        return None
    result = response.get("result")
    return result if isinstance(result, Mapping) else None


def _codex_probe_signed_in(response: Mapping[str, Any]) -> bool | None:
    result = _codex_probe_result(response)
    if result is None or "account" not in result:
        return None
    account = result.get("account")
    if account is None:
        return False
    return True if isinstance(account, Mapping) else None


def _codex_probe_rate_limit_state(
    response: Mapping[str, Any],
) -> tuple[bool | None, str | None]:
    result = _codex_probe_result(response)
    if result is None:
        return None, None
    raw_snapshots: list[object] = [result.get("rateLimits")]
    by_limit_id = result.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, Mapping):
        raw_snapshots.extend(by_limit_id.values())
    snapshots = [
        snapshot for snapshot in raw_snapshots if isinstance(snapshot, Mapping)
    ]
    if not snapshots:
        return None, None
    for snapshot in snapshots:
        code = str(snapshot.get("rateLimitReachedType") or "").strip()
        if code:
            return True, code
    return False, None


def _stop_codex_probe_process(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass


def _probe_harness_composer_dispatch(
    connector_type: str,
) -> HarnessComposerReadiness:
    """Report only installation and URL-dispatch capability."""

    connector_type = connector_type.strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    if connector_type not in MACOS_DESKTOP_APPS:
        raise HarnessLaunchError(f"Unsupported AI harness: {connector_type}")

    label = HARNESS_LABELS[connector_type]
    spec = MACOS_DESKTOP_APPS[connector_type]
    if platform.system() != "Darwin":
        return HarnessComposerReadiness(
            provider=connector_type,
            ready=False,
            desktop_available=False,
            url_scheme_registered=False,
            required_url_scheme=spec.url_scheme,
            code="desktop_app_unsupported",
            message=(
                f"{label} visible desktop composer handoff is not supported "
                "on this system."
            ),
            action=f"Run DaemonState on macOS with {spec.install_product}.",
        )

    installations = _macos_desktop_app_installations(spec)
    if not installations:
        return HarnessComposerReadiness(
            provider=connector_type,
            ready=False,
            desktop_available=False,
            url_scheme_registered=False,
            required_url_scheme=spec.url_scheme,
            code="desktop_app_missing",
            message=(
                f"{label} cannot receive this continuation because its "
                "desktop app is not installed."
            ),
            action=f"Install {spec.install_product}, then check again.",
        )

    required_scheme = spec.url_scheme.lower()
    if not any(
        required_scheme in installation.url_schemes
        for installation in installations
    ):
        return HarnessComposerReadiness(
            provider=connector_type,
            ready=False,
            desktop_available=True,
            url_scheme_registered=False,
            required_url_scheme=required_scheme,
            code="desktop_url_scheme_missing",
            message=(
                f"{label} desktop app is installed, but it does not register "
                f"the required {required_scheme}:// URL scheme."
            ),
            action=(
                f"Update or reinstall {spec.install_product}, then check again."
            ),
        )

    return HarnessComposerReadiness(
        provider=connector_type,
        ready=True,
        desktop_available=True,
        url_scheme_registered=True,
        required_url_scheme=required_scheme,
        code="desktop_dispatch_available",
        message=(
            f"{label} desktop app and its {required_scheme}:// handler are "
            "installed. This proves only dispatch capability; account access, "
            "model access, and route rendering are not verified."
        ),
        action=f"Verify account access in {label}.",
    )


@traced(
    "daemonstate.harness.launch",
    attributes=lambda args, kwargs: {
        "daemonstate.phase": "harness_launch",
        "daemonstate.provider": (
            args[0] if args else kwargs.get("connector_type")
        ),
        "daemonstate.session.id": (
            args[1] if len(args) > 1 else kwargs.get("session_id")
        ),
    },
    result_attributes=lambda result: {
        "daemonstate.provider": result.get("connector_type"),
        "daemonstate.session.id": result.get("session_id"),
        "daemonstate.harness.launched": False,
        "daemonstate.harness.navigation_requested": result.get(
            "navigation_requested"
        ),
        "daemonstate.harness.navigation_verified": result.get(
            "navigation_verified"
        ),
        "daemonstate.status": (
            "open_requested"
            if result.get("open_requested") is True
            else "not_requested"
        ),
    },
)
def launch_harness_session(
    connector_type: str,
    session_id: str,
    *,
    cwd: str | None = None,
) -> dict[str, Any]:
    connector_type = connector_type.strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    if connector_type not in MACOS_DESKTOP_APPS:
        raise HarnessLaunchError(f"Unsupported AI harness: {connector_type}")

    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HarnessLaunchError("The local session ID is not safe to launch.")

    system = platform.system()
    if system != "Darwin":
        raise HarnessLaunchError(
            f"{HARNESS_LABELS[connector_type]} desktop launching is not available on {system} yet.",
            code="desktop_app_unsupported",
        )

    deadline = time.monotonic() + DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS
    target, navigation = _macos_launch_target(connector_type, session_id, cwd)
    app = _resolve_macos_desktop_app(
        connector_type,
        MACOS_DESKTOP_APPS[connector_type],
        require_url_scheme=target is not None,
    )
    _request_registered_macos_app_open(
        connector_type,
        app,
        target,
        deadline=deadline,
    )

    return {
        # A zero exit status from /usr/bin/open confirms only that Launch
        # Services accepted the request. It does not prove the app opened or
        # navigated, so all verified/opened fields stay false.
        "launched": False,
        "open_requested": True,
        "open_verified": False,
        "navigation_requested": target is not None,
        "navigation_verified": False,
        "connector_type": connector_type,
        "harness": HARNESS_LABELS[connector_type],
        "session_id": session_id,
        "mode": "desktop_app",
        "navigation": navigation,
        "exact_session_supported": navigation == "session",
        "topic_anchor_supported": False,
    }


@traced(
    "daemonstate.harness.launch",
    attributes=lambda args, kwargs: {
        "daemonstate.phase": "desktop_composer_handoff",
        "daemonstate.provider": (
            args[0] if args else kwargs.get("connector_type")
        ),
    },
    result_attributes=lambda result: {
        "daemonstate.provider": result.get("connector_type"),
        "daemonstate.harness.launched": False,
        "daemonstate.harness.navigation_requested": result.get(
            "navigation_requested"
        ),
        "daemonstate.harness.navigation_verified": result.get(
            "navigation_verified"
        ),
        "daemonstate.status": (
            "open_requested"
            if result.get("open_requested") is True
            else "not_requested"
        ),
    },
)
def launch_harness_composer(
    connector_type: str,
    *,
    cwd: str,
    prompt: str,
) -> dict[str, Any]:
    """Request a visible desktop composer without invoking a provider CLI.

    The full prompt is copied before the open request is sent. When it fits
    the provider-neutral deep-link budget it is also sent to the app's native
    new-session route. No deep link used here submits the prompt.
    """

    connector_type = connector_type.strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    if connector_type not in MACOS_DESKTOP_APPS:
        raise HarnessLaunchError(f"Unsupported AI harness: {connector_type}")
    if platform.system() != "Darwin":
        raise HarnessLaunchError(
            (
                f"{HARNESS_LABELS[connector_type]} desktop launching is not "
                f"available on {platform.system()} yet."
            ),
            code="desktop_app_unsupported",
        )

    deadline = time.monotonic() + DESKTOP_HANDOFF_TOTAL_TIMEOUT_SECONDS
    working_directory = _existing_directory(cwd)
    if working_directory is None:
        raise HarnessLaunchError(
            "A readable local project directory is required for the desktop handoff.",
            code="desktop_project_unavailable",
        )

    spec = MACOS_DESKTOP_APPS[connector_type]
    app = _resolve_macos_desktop_app(
        connector_type,
        spec,
        require_url_scheme=True,
    )

    context = str(prompt)
    if not context.strip():
        raise HarnessLaunchError(
            "The desktop handoff prompt is empty.",
            code="desktop_prompt_empty",
        )
    _copy_macos_clipboard(context, deadline=deadline)

    prefill_requested = len(context) <= DESKTOP_DEEP_LINK_PROMPT_MAX_CHARS
    target = _macos_composer_target(
        connector_type,
        working_directory,
        context if prefill_requested else None,
    )
    _request_registered_macos_app_open(
        connector_type,
        app,
        target,
        deadline=deadline,
    )

    return {
        "launched": False,
        "open_requested": True,
        "open_verified": False,
        "navigation_requested": True,
        "navigation_verified": False,
        "connector_type": connector_type,
        "harness": HARNESS_LABELS[connector_type],
        "mode": "desktop_composer",
        "navigation": "new_session",
        "exact_session_supported": False,
        "topic_anchor_supported": False,
        "prefill_requested": prefill_requested,
        "context_copied": True,
        "context_loaded": False,
        "execution_started": False,
        "context_delivery": (
            "desktop_composer_prefill_and_clipboard"
            if prefill_requested
            else "clipboard"
        ),
    }


def _macos_desktop_app_installed(spec: DesktopAppSpec) -> bool:
    return bool(_macos_desktop_app_installations(spec))


def _macos_application_roots() -> tuple[Path, ...]:
    return (
        Path("/Applications"),
        Path("/System/Applications"),
        Path.home() / "Applications",
    )


def _macos_desktop_app_installations(
    spec: DesktopAppSpec,
) -> tuple[MacOSDesktopApp, ...]:
    installations: list[MacOSDesktopApp] = []
    seen: set[Path] = set()
    for root in _macos_application_roots():
        for app_name in spec.app_names:
            bundle = root / f"{app_name}.app"
            if bundle in seen or not bundle.is_dir():
                continue
            seen.add(bundle)
            metadata = _macos_bundle_metadata(bundle)
            if metadata is None or metadata.bundle_id not in spec.bundle_ids:
                continue
            installations.append(metadata)
    return tuple(installations)


def _macos_bundle_identifier(bundle: Path) -> str | None:
    metadata = _macos_bundle_metadata(bundle)
    return None if metadata is None else metadata.bundle_id


def _macos_bundle_metadata(bundle: Path) -> MacOSDesktopApp | None:
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as plist_file:
            info = plistlib.load(plist_file)
    except (OSError, plistlib.InvalidFileException):
        return None
    if not isinstance(info, dict):
        return None
    raw_identifier = info.get("CFBundleIdentifier")
    if not isinstance(raw_identifier, str) or not raw_identifier.strip():
        return None

    schemes: set[str] = set()
    raw_url_types = info.get("CFBundleURLTypes")
    if isinstance(raw_url_types, list):
        for url_type in raw_url_types:
            if not isinstance(url_type, dict):
                continue
            raw_schemes = url_type.get("CFBundleURLSchemes")
            if not isinstance(raw_schemes, list):
                continue
            schemes.update(
                value.strip().lower()
                for value in raw_schemes
                if isinstance(value, str) and value.strip()
            )
    return MacOSDesktopApp(
        bundle_path=bundle,
        bundle_id=raw_identifier.strip(),
        url_schemes=frozenset(schemes),
    )


def _resolve_macos_desktop_app(
    connector_type: str,
    spec: DesktopAppSpec,
    *,
    require_url_scheme: bool,
) -> MacOSDesktopApp:
    installations = _macos_desktop_app_installations(spec)
    if not installations:
        raise HarnessLaunchError(
            f"{HARNESS_LABELS[connector_type]} desktop app is missing. "
            f"Install {spec.install_product} to open sessions here.",
            code="desktop_app_missing",
        )
    if not require_url_scheme:
        return installations[0]

    required_scheme = spec.url_scheme.lower()
    for app in installations:
        if required_scheme in app.url_schemes:
            return app
    raise HarnessLaunchError(
        (
            f"{HARNESS_LABELS[connector_type]} desktop app does not register "
            f"the required {required_scheme}:// URL scheme."
        ),
        code="desktop_url_scheme_missing",
    )


def _remaining_handoff_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HarnessLaunchError(
            "The desktop handoff timed out before the open request was sent.",
            code="desktop_handoff_timeout",
        )
    return remaining


def _copy_macos_clipboard(value: str, *, deadline: float) -> None:
    try:
        completed = subprocess.run(
            ["/usr/bin/pbcopy"],
            check=False,
            timeout=_remaining_handoff_timeout(deadline),
            input=value,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessLaunchError(
            "The desktop handoff timed out while copying its context.",
            code="desktop_handoff_timeout",
        ) from exc
    except OSError as exc:
        raise HarnessLaunchError(
            "Could not copy the continuation context to the macOS clipboard.",
            code="desktop_clipboard_failed",
        ) from exc
    if completed.returncode != 0:
        raise HarnessLaunchError(
            "Could not copy the continuation context to the macOS clipboard.",
            code="desktop_clipboard_failed",
        )


def _request_registered_macos_app_open(
    connector_type: str,
    app: MacOSDesktopApp,
    target: str | None,
    *,
    deadline: float,
) -> None:
    command = ["/usr/bin/open", "-b", app.bundle_id]
    if target is not None:
        command.append(target)
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=_remaining_handoff_timeout(deadline),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessLaunchError(
            (
                f"The {HARNESS_LABELS[connector_type]} desktop open request "
                "timed out."
            ),
            code="desktop_handoff_timeout",
        ) from exc
    except OSError as exc:
        raise HarnessLaunchError(
            f"Could not request the {HARNESS_LABELS[connector_type]} desktop app."
        ) from exc
    if completed.returncode == 0:
        return

    error = (completed.stderr or completed.stdout or "").strip()
    if _is_missing_application_error(error):
        raise HarnessLaunchError(
            f"{HARNESS_LABELS[connector_type]} desktop app is no longer available.",
            code="desktop_app_missing",
        )
    raise HarnessLaunchError(
        f"Could not request the {HARNESS_LABELS[connector_type]} desktop app."
        + (f" macOS reported: {error}" if error else "")
    )


def _is_missing_application_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "unable to find application" in lowered
        or "application not found" in lowered
    )


def _macos_launch_target(
    connector_type: str,
    session_id: str,
    cwd: str | None,
) -> tuple[str | None, str]:
    if connector_type == "codex":
        return f"codex://threads/{quote(session_id, safe='')}", "session"
    if connector_type == "opencode":
        working_directory = _existing_directory(cwd)
        if working_directory is not None:
            query = urlencode({"directory": str(working_directory)})
            return f"opencode://open-project?{query}", "project"
    return None, "app"


def _macos_composer_target(
    connector_type: str,
    working_directory: Path,
    prompt: str | None,
) -> str:
    path = str(working_directory)
    if connector_type == "codex":
        values = {"path": path}
        if prompt is not None:
            values["prompt"] = prompt
        return f"codex://threads/new?{urlencode(values)}"
    if connector_type == "claude":
        values = {"folder": path}
        if prompt is not None:
            values["q"] = prompt
        return f"claude://code/new?{urlencode(values)}"
    values = {"directory": path}
    if prompt is not None:
        values["prompt"] = prompt
    return f"opencode://new-session?{urlencode(values)}"


def _existing_directory(value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_dir():
        return None
    return candidate.resolve()
