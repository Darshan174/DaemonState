from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import secrets
import signal
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.services.harness_adapters import minimal_process_environment


STATE_SCHEMA = "context_overlay_state.v1"
CONTROL_SCHEMA = "context_overlay_control.v1"
STATUS_SCHEMA = "desktop_overlay.v1"
STATE_FILENAME = "daemonstate-overlay-state.json"
CONTROL_FILENAME = "daemonstate-overlay-control.json"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_STATE_BYTES = 8_192
LAUNCH_TIMEOUT_SECONDS = 45.0
CONTROL_TIMEOUT_SECONDS = 3.0
POLL_INTERVAL_SECONDS = 0.05
DEFAULT_API_URL = "http://127.0.0.1:8000/api"


class DesktopOverlayError(RuntimeError):
    """Raised when the native overlay cannot be controlled safely."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DesktopOverlayStatus:
    supported: bool
    available: bool
    running: bool
    visible: bool
    workspace_id: str | None
    code: str
    message: str
    schema_version: str = STATUS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _NativeOverlayState:
    pid: int
    control_token: str
    visible: bool
    workspace_id: str | None


class DesktopOverlayManager:
    """Own the local dashboard-to-overlay control boundary.

    The native process publishes a token-bound state file. We signal only a
    PID whose command line proves that it is the overlay carrying that exact
    token. Caller-provided PIDs, executable paths, and launch arguments are
    never accepted.
    """

    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        runtime_dir: Path | None = None,
    ) -> None:
        self._repository_root = (
            repository_root or Path(__file__).resolve().parents[2]
        ).resolve()
        configured_runtime_dir = os.environ.get(
            "DAEMONSTATE_OVERLAY_RUNTIME_DIR",
            "",
        ).strip()
        self._runtime_dir = (
            runtime_dir
            or (Path(configured_runtime_dir) if configured_runtime_dir else None)
            or Path(tempfile.gettempdir())
        ).resolve()
        self._lock = threading.Lock()
        self._owned_process: subprocess.Popen[bytes] | None = None

    @property
    def state_path(self) -> Path:
        return self._runtime_dir / STATE_FILENAME

    @property
    def control_path(self) -> Path:
        return self._runtime_dir / CONTROL_FILENAME

    @property
    def launcher_path(self) -> Path:
        return self._repository_root / "scripts" / "overlay.sh"

    def status(self) -> DesktopOverlayStatus:
        with self._lock:
            return self._status_locked()

    def set_visible(
        self,
        visible: bool,
        *,
        workspace_id: UUID | None,
        api_url: str = DEFAULT_API_URL,
    ) -> DesktopOverlayStatus:
        with self._lock:
            capability = self._capability_status()
            if not capability.supported or not capability.available:
                if visible:
                    raise DesktopOverlayError(
                        capability.message,
                        code=capability.code,
                    )
                return capability

            state = self._verified_state()
            if state is None:
                if not visible:
                    return self._stopped_status()
                if workspace_id is None:
                    raise DesktopOverlayError(
                        "Choose a workspace before showing the floating context control.",
                        code="overlay_workspace_required",
                    )
                state = self._launch(
                    workspace_id,
                    api_url=self._validated_api_url(api_url),
                )

            requested_workspace = str(workspace_id) if workspace_id is not None else None
            workspace_matches = (
                requested_workspace is None
                or state.workspace_id == requested_workspace
            )
            if state.visible == visible and workspace_matches:
                return self._running_status(state)

            self._write_control(
                state,
                visible=visible,
                workspace_id=requested_workspace,
            )
            self._signal_verified_process(state)
            updated = self._wait_for_control(
                state,
                visible=visible,
                workspace_id=requested_workspace,
            )
            return self._running_status(updated)

    def _status_locked(self) -> DesktopOverlayStatus:
        capability = self._capability_status()
        if not capability.supported or not capability.available:
            return capability
        state = self._verified_state()
        if state is None:
            return self._stopped_status()
        return self._running_status(state)

    def _capability_status(self) -> DesktopOverlayStatus:
        if platform.system() != "Darwin":
            return DesktopOverlayStatus(
                supported=False,
                available=False,
                running=False,
                visible=False,
                workspace_id=None,
                code="overlay_unsupported",
                message="The floating context control is available only on macOS.",
            )
        launcher = self.launcher_path
        try:
            launcher_stat = launcher.stat()
        except OSError:
            launcher_stat = None
        if (
            launcher_stat is None
            or not stat.S_ISREG(launcher_stat.st_mode)
            or not os.access(launcher, os.X_OK)
        ):
            return DesktopOverlayStatus(
                supported=True,
                available=False,
                running=False,
                visible=False,
                workspace_id=None,
                code="overlay_launcher_missing",
                message="The native floating-control launcher is unavailable.",
            )
        process_environment = minimal_process_environment()
        if shutil.which("swift", path=process_environment.get("PATH")) is None:
            return DesktopOverlayStatus(
                supported=True,
                available=False,
                running=False,
                visible=False,
                workspace_id=None,
                code="overlay_swift_unavailable",
                message="The Swift toolchain required by the native control is unavailable.",
            )
        runtime_error = self._runtime_directory_error()
        if runtime_error is not None:
            return DesktopOverlayStatus(
                supported=True,
                available=False,
                running=False,
                visible=False,
                workspace_id=None,
                code=runtime_error.code,
                message=str(runtime_error),
            )
        return DesktopOverlayStatus(
            supported=True,
            available=True,
            running=False,
            visible=False,
            workspace_id=None,
            code="overlay_stopped",
            message="The floating context control is off.",
        )

    def _stopped_status(self) -> DesktopOverlayStatus:
        return DesktopOverlayStatus(
            supported=True,
            available=True,
            running=False,
            visible=False,
            workspace_id=None,
            code="overlay_stopped",
            message="The floating context control is off.",
        )

    def _running_status(self, state: _NativeOverlayState) -> DesktopOverlayStatus:
        return DesktopOverlayStatus(
            supported=True,
            available=True,
            running=True,
            visible=state.visible,
            workspace_id=state.workspace_id,
            code="overlay_visible" if state.visible else "overlay_hidden",
            message=(
                "The floating context control is on."
                if state.visible
                else "The floating context control is hidden."
            ),
        )

    def _verified_state(
        self,
        *,
        expected_token: str | None = None,
    ) -> _NativeOverlayState | None:
        self._reap_owned_process()
        state = self._read_state()
        if state is None:
            return None
        if expected_token is not None and state.control_token != expected_token:
            raise DesktopOverlayError(
                "Another floating context control started at the same time.",
                code="overlay_instance_conflict",
            )

        command = self._pid_command(state.pid)
        if command is None:
            self._remove_stale_state()
            return None
        command_parts = command.split()
        if (
            "DaemonStateOverlay" not in command
            or state.control_token not in command_parts
        ):
            raise DesktopOverlayError(
                "The native overlay state could not be matched to its process.",
                code="overlay_process_unverified",
            )
        return state

    def _read_state(self) -> _NativeOverlayState | None:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.state_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            file_stat = os.fstat(descriptor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DesktopOverlayError(
                "The native overlay state file is not safe to use.",
                code="overlay_state_unverified",
            ) from exc

        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.getuid()
            or file_stat.st_size > MAX_STATE_BYTES
            or stat.S_IMODE(file_stat.st_mode) != 0o600
        ):
            os.close(descriptor)
            raise DesktopOverlayError(
                "The native overlay state file is not safe to use.",
                code="overlay_state_unverified",
            )
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                raw = handle.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError("state file is too large")
            payload = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DesktopOverlayError(
                "The native overlay state is invalid.",
                code="overlay_state_invalid",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA:
            raise DesktopOverlayError(
                "The native overlay state uses an unsupported schema.",
                code="overlay_state_invalid",
            )

        pid = payload.get("pid")
        token = payload.get("control_token")
        visible = payload.get("visible")
        workspace_value = payload.get("workspace_id")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 1
            or not isinstance(token, str)
            or not TOKEN_PATTERN.fullmatch(token)
            or not isinstance(visible, bool)
        ):
            raise DesktopOverlayError(
                "The native overlay state has invalid process data.",
                code="overlay_state_invalid",
            )
        workspace_id: str | None = None
        if workspace_value is not None:
            try:
                workspace_id = str(UUID(str(workspace_value)))
            except (TypeError, ValueError, AttributeError) as exc:
                raise DesktopOverlayError(
                    "The native overlay state has an invalid workspace.",
                    code="overlay_state_invalid",
                ) from exc
        return _NativeOverlayState(
            pid=pid,
            control_token=token,
            visible=visible,
            workspace_id=workspace_id,
        )

    def _pid_command(self, pid: int) -> str | None:
        try:
            result = subprocess.run(
                ["/bin/ps", "-ww", "-p", str(pid), "-o", "command="],
                check=False,
                timeout=2,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=minimal_process_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DesktopOverlayError(
                "The native overlay process could not be verified.",
                code="overlay_process_unverified",
            ) from exc
        command = str(result.stdout or "").strip()
        return command if result.returncode == 0 and command else None

    def _launch(
        self,
        workspace_id: UUID,
        *,
        api_url: str,
    ) -> _NativeOverlayState:
        self._ensure_runtime_dir()
        token = secrets.token_urlsafe(32)
        argv = [
            str(self.launcher_path),
            "--control-token",
            token,
            "--workspace-id",
            str(workspace_id),
            "--api-url",
            api_url,
        ]
        environment = minimal_process_environment()
        environment["DAEMONSTATE_OVERLAY_RUNTIME_DIR"] = str(self._runtime_dir)
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(self._repository_root),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise DesktopOverlayError(
                "The native floating context control could not be launched.",
                code="overlay_launch_failed",
            ) from exc
        self._owned_process = process

        deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._owned_process = None
                raise DesktopOverlayError(
                    "The native floating context control exited during launch.",
                    code="overlay_launch_failed",
                )
            try:
                state = self._verified_state(expected_token=token)
            except DesktopOverlayError as exc:
                if exc.code not in {
                    "overlay_state_invalid",
                    "overlay_state_unavailable",
                    "overlay_state_unverified",
                }:
                    self._stop_owned_process(process)
                    raise
                state = None
            if state is not None:
                return state
            time.sleep(POLL_INTERVAL_SECONDS)

        self._stop_owned_process(process)
        raise DesktopOverlayError(
            "The native floating context control did not report ready in time.",
            code="overlay_launch_timeout",
        )

    def _validated_api_url(self, value: str) -> str:
        try:
            parsed = urlsplit(str(value).strip())
            port = parsed.port
            address = ipaddress.ip_address(parsed.hostname or "")
        except (ValueError, TypeError) as exc:
            raise DesktopOverlayError(
                "The local DaemonState API address is invalid.",
                code="overlay_api_url_invalid",
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not address.is_loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/api"
        ):
            raise DesktopOverlayError(
                "The native control can connect only to this local DaemonState API.",
                code="overlay_api_url_invalid",
            )
        resolved_port = port or (443 if parsed.scheme == "https" else 80)
        host = "[::1]" if isinstance(address, ipaddress.IPv6Address) else "127.0.0.1"
        return f"{parsed.scheme}://{host}:{resolved_port}/api"

    def _write_control(
        self,
        state: _NativeOverlayState,
        *,
        visible: bool,
        workspace_id: str | None,
    ) -> None:
        self._ensure_runtime_dir()
        payload: dict[str, Any] = {
            "schema_version": CONTROL_SCHEMA,
            "target_token": state.control_token,
            "visible": visible,
            "workspace_id": workspace_id,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{CONTROL_FILENAME}.",
                dir=str(self._runtime_dir),
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.control_path)
        except OSError as exc:
            raise DesktopOverlayError(
                "The native overlay command could not be written.",
                code="overlay_control_failed",
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def _signal_verified_process(self, state: _NativeOverlayState) -> None:
        verified = self._verified_state(expected_token=state.control_token)
        if verified is None or verified.pid != state.pid:
            raise DesktopOverlayError(
                "The native overlay exited before it could be updated.",
                code="overlay_process_exited",
            )
        try:
            os.kill(verified.pid, signal.SIGUSR1)
        except (PermissionError, ProcessLookupError) as exc:
            raise DesktopOverlayError(
                "The native overlay could not be updated.",
                code="overlay_control_failed",
            ) from exc

    def _wait_for_control(
        self,
        previous: _NativeOverlayState,
        *,
        visible: bool,
        workspace_id: str | None,
    ) -> _NativeOverlayState:
        deadline = time.monotonic() + CONTROL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            state = self._verified_state(expected_token=previous.control_token)
            if state is None:
                raise DesktopOverlayError(
                    "The native overlay exited before confirming the update.",
                    code="overlay_process_exited",
                )
            workspace_matches = workspace_id is None or state.workspace_id == workspace_id
            if state.visible == visible and workspace_matches:
                return state
            time.sleep(POLL_INTERVAL_SECONDS)
        raise DesktopOverlayError(
            "The native overlay did not confirm the visibility update.",
            code="overlay_control_timeout",
        )

    def _ensure_runtime_dir(self) -> None:
        try:
            self._runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            directory_stat = self._runtime_dir.lstat()
        except OSError as exc:
            raise DesktopOverlayError(
                "The native overlay runtime directory is unavailable.",
                code="overlay_runtime_unavailable",
            ) from exc
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
            or stat.S_IMODE(directory_stat.st_mode) & 0o700 != 0o700
        ):
            raise DesktopOverlayError(
                "The native overlay runtime directory is not safe to use.",
                code="overlay_runtime_unverified",
            )

    def _runtime_directory_error(self) -> DesktopOverlayError | None:
        try:
            directory_stat = self._runtime_dir.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            return DesktopOverlayError(
                "The native overlay runtime directory is unavailable.",
                code="overlay_runtime_unavailable",
            )
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
            or stat.S_IMODE(directory_stat.st_mode) & 0o700 != 0o700
        ):
            return DesktopOverlayError(
                "The native overlay runtime directory is not safe to use.",
                code="overlay_runtime_unverified",
            )
        return None

    def _remove_stale_state(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise DesktopOverlayError(
                "The stale native overlay state could not be cleared.",
                code="overlay_state_unavailable",
            ) from exc

    def _reap_owned_process(self) -> None:
        process = self._owned_process
        if process is not None and process.poll() is not None:
            self._owned_process = None

    def _stop_owned_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            if self._owned_process is process:
                self._owned_process = None
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (PermissionError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if self._owned_process is process:
            self._owned_process = None


desktop_overlay_manager = DesktopOverlayManager()
