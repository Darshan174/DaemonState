from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode


HARNESS_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "opencode": "OpenCode",
}
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


@dataclass(frozen=True)
class DesktopAppSpec:
    bundle_ids: tuple[str, ...]
    app_names: tuple[str, ...]
    install_product: str


MACOS_DESKTOP_APPS = {
    "codex": DesktopAppSpec(
        bundle_ids=("com.openai.codex",),
        app_names=("ChatGPT", "Codex"),
        install_product="the Codex desktop app",
    ),
    "claude": DesktopAppSpec(
        bundle_ids=("com.anthropic.claudefordesktop", "com.anthropic.Claude"),
        app_names=("Claude", "Claude Desktop", "Claude for Desktop"),
        install_product="Claude Desktop",
    ),
    "opencode": DesktopAppSpec(
        bundle_ids=("ai.opencode.desktop",),
        app_names=("OpenCode",),
        install_product="OpenCode Desktop",
    ),
}


class HarnessLaunchError(Exception):
    """Raised when a local harness desktop session cannot be opened safely."""

    def __init__(self, message: str, *, code: str = "launch_failed") -> None:
        super().__init__(message)
        self.code = code


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

    target, navigation = _macos_launch_target(connector_type, session_id, cwd)
    _open_registered_macos_app(
        connector_type,
        MACOS_DESKTOP_APPS[connector_type],
        target,
    )

    return {
        "launched": True,
        "connector_type": connector_type,
        "harness": HARNESS_LABELS[connector_type],
        "session_id": session_id,
        "mode": "desktop_app",
        "navigation": navigation,
        "exact_session_supported": navigation == "session",
        "topic_anchor_supported": False,
    }


def _open_registered_macos_app(
    connector_type: str,
    spec: DesktopAppSpec,
    target: str | None,
) -> None:
    attempts = [
        ["/usr/bin/open", "-b", bundle_id]
        for bundle_id in spec.bundle_ids
    ]
    attempts.extend(
        ["/usr/bin/open", "-a", app_name]
        for app_name in spec.app_names
    )

    missing_results = 0
    last_error = ""
    for base_command in attempts:
        command = [*base_command, *([target] if target else [])]
        try:
            completed = subprocess.run(
                command,
                check=False,
                timeout=10,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HarnessLaunchError(
                f"Could not open the {HARNESS_LABELS[connector_type]} desktop app."
            ) from exc
        if completed.returncode == 0:
            return

        last_error = (completed.stderr or completed.stdout or "").strip()
        if _is_missing_application_error(last_error):
            missing_results += 1

    if missing_results == len(attempts):
        raise HarnessLaunchError(
            f"{HARNESS_LABELS[connector_type]} desktop app is missing. "
            f"Install {spec.install_product} to open sessions here.",
            code="desktop_app_missing",
        )
    raise HarnessLaunchError(
        f"Could not open the {HARNESS_LABELS[connector_type]} desktop app."
        + (f" macOS reported: {last_error}" if last_error else "")
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


def _existing_directory(value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_dir():
        return None
    return candidate.resolve()
