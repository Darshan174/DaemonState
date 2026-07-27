from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
from subprocess import CompletedProcess
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_access_scope
from app.api.desktop_overlay import _local_api_url
from app.main import app
from app.models import Workspace
from app.services.access import AccessScope
from app.services.desktop_overlay import (
    CONTROL_FILENAME,
    CONTROL_SCHEMA,
    STATE_FILENAME,
    STATE_SCHEMA,
    DesktopOverlayError,
    DesktopOverlayManager,
    DesktopOverlayStatus,
)


def _manager(tmp_path: Path, monkeypatch) -> DesktopOverlayManager:
    repository_root = tmp_path / "repository"
    launcher = repository_root / "scripts" / "overlay.sh"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o700)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    monkeypatch.setattr(
        "app.services.desktop_overlay.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "app.services.desktop_overlay.shutil.which",
        lambda *_args, **_kwargs: "/usr/bin/swift",
    )
    return DesktopOverlayManager(
        repository_root=repository_root,
        runtime_dir=runtime_dir,
    )


def _write_state(
    manager: DesktopOverlayManager,
    *,
    pid: int = 4242,
    token: str = "test-control-token-1234567890",
    visible: bool = True,
    workspace_id: UUID | None = None,
) -> None:
    manager.state_path.write_text(
        json.dumps(
            {
                "schema_version": STATE_SCHEMA,
                "pid": pid,
                "control_token": token,
                "visible": visible,
                "workspace_id": str(workspace_id) if workspace_id else None,
            }
        ),
        encoding="utf-8",
    )
    manager.state_path.chmod(0o600)


def _verified_command(token: str = "test-control-token-1234567890") -> str:
    return (
        "/tmp/DaemonStateOverlay "
        f"--control-token {token} --workspace-id ignored"
    )


def test_status_reports_platform_unavailable(tmp_path: Path, monkeypatch) -> None:
    manager = DesktopOverlayManager(
        repository_root=tmp_path,
        runtime_dir=tmp_path,
    )
    monkeypatch.setattr(
        "app.services.desktop_overlay.platform.system",
        lambda: "Linux",
    )

    status = manager.status()

    assert status.supported is False
    assert status.available is False
    assert status.running is False
    assert status.code == "overlay_unsupported"


def test_local_api_url_uses_server_socket_instead_of_host_header() -> None:
    request = SimpleNamespace(
        scope={
            "scheme": "http",
            "server": ("0.0.0.0", 9123),
            "headers": [(b"host", b"attacker.example:4444")],
        },
    )

    assert _local_api_url(request) == "http://127.0.0.1:9123/api"


def test_status_accepts_only_token_bound_overlay_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    workspace_id = uuid4()
    _write_state(manager, workspace_id=workspace_id)
    monkeypatch.setattr(manager, "_pid_command", lambda _pid: _verified_command())

    status = manager.status()

    assert status.running is True
    assert status.visible is True
    assert status.workspace_id == str(workspace_id)
    assert status.code == "overlay_visible"
    assert "control_token" not in status.to_dict()


def test_status_reports_missing_swift_toolchain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.services.desktop_overlay.shutil.which",
        lambda *_args, **_kwargs: None,
    )

    status = manager.status()

    assert status.supported is True
    assert status.available is False
    assert status.code == "overlay_swift_unavailable"


def test_group_accessible_runtime_directory_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    manager.state_path.parent.chmod(0o770)

    status = manager.status()

    assert status.available is False
    assert status.code == "overlay_runtime_unverified"


def test_nonprivate_state_permissions_are_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    _write_state(manager)
    manager.state_path.chmod(0o644)
    monkeypatch.setattr(manager, "_pid_command", lambda _pid: _verified_command())

    with pytest.raises(DesktopOverlayError) as error:
        manager.status()

    assert error.value.code == "overlay_state_unverified"


def test_unverified_state_never_signals_its_pid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    _write_state(manager)
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: "/usr/bin/python unrelated.py",
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.desktop_overlay.os.kill",
        lambda pid, sig: signals.append((pid, sig)),
    )

    with pytest.raises(DesktopOverlayError) as error:
        manager.set_visible(False, workspace_id=None)

    assert error.value.code == "overlay_process_unverified"
    assert signals == []


def test_symlinked_state_is_rejected_without_following_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    outside_state = tmp_path / "outside-state.json"
    outside_state.write_text("{}", encoding="utf-8")
    manager.state_path.symlink_to(outside_state)

    with pytest.raises(DesktopOverlayError) as error:
        manager.status()

    assert error.value.code == "overlay_state_unverified"


def test_hiding_running_overlay_writes_token_bound_control_then_signals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    workspace_id = uuid4()
    token = "test-control-token-1234567890"
    _write_state(
        manager,
        token=token,
        visible=True,
        workspace_id=workspace_id,
    )
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: _verified_command(token),
    )
    signals: list[tuple[int, int]] = []

    def apply_control(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        _write_state(
            manager,
            pid=pid,
            token=token,
            visible=False,
            workspace_id=workspace_id,
        )

    monkeypatch.setattr("app.services.desktop_overlay.os.kill", apply_control)

    status = manager.set_visible(False, workspace_id=None)

    control = json.loads((manager.control_path).read_text(encoding="utf-8"))
    assert control == {
        "schema_version": CONTROL_SCHEMA,
        "target_token": token,
        "visible": False,
        "workspace_id": None,
    }
    assert manager.control_path.name == CONTROL_FILENAME
    assert manager.state_path.name == STATE_FILENAME
    assert signals == [(4242, signal.SIGUSR1)]
    assert status.running is True
    assert status.visible is False
    assert status.code == "overlay_hidden"


def test_show_launches_only_fixed_repository_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    workspace_id = uuid4()
    calls: list[tuple[list[str], dict]] = []

    class FakeProcess:
        pid = 6789

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        token = argv[2]
        _write_state(
            manager,
            pid=FakeProcess.pid,
            token=token,
            visible=True,
            workspace_id=workspace_id,
        )
        return FakeProcess()

    monkeypatch.setattr("app.services.desktop_overlay.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: _verified_command(calls[0][0][2]),
    )

    status = manager.set_visible(
        True,
        workspace_id=workspace_id,
        api_url="http://127.0.0.1:9123/api",
    )

    assert status.visible is True
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [
        str(manager.launcher_path),
        "--control-token",
        argv[2],
        "--workspace-id",
        str(workspace_id),
        "--api-url",
        "http://127.0.0.1:9123/api",
    ]
    assert options["cwd"] == str(manager.launcher_path.parents[1])
    assert options["start_new_session"] is True
    assert options["env"]["DAEMONSTATE_OVERLAY_RUNTIME_DIR"] == str(
        manager.state_path.parent
    )


def test_show_rejects_nonloopback_api_before_launch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    launches: list[list[str]] = []
    monkeypatch.setattr(
        "app.services.desktop_overlay.subprocess.Popen",
        lambda argv, **_kwargs: launches.append(argv),
    )

    with pytest.raises(DesktopOverlayError) as error:
        manager.set_visible(
            True,
            workspace_id=uuid4(),
            api_url="https://daemonstate.example/api",
        )

    assert error.value.code == "overlay_api_url_invalid"
    assert launches == []


def test_dead_state_is_removed_without_signalling_old_pid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    _write_state(manager)
    monkeypatch.setattr(manager, "_pid_command", lambda _pid: None)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.desktop_overlay.os.kill",
        lambda pid, sig: signals.append((pid, sig)),
    )

    status = manager.set_visible(False, workspace_id=None)

    assert status.running is False
    assert not manager.state_path.exists()
    assert signals == []


class _FakeOverlayManager:
    def __init__(self) -> None:
        self.updates: list[tuple[bool, UUID | None, str]] = []
        self.status_calls = 0

    def status(self) -> DesktopOverlayStatus:
        self.status_calls += 1
        return DesktopOverlayStatus(
            supported=True,
            available=True,
            running=False,
            visible=False,
            workspace_id=None,
            code="overlay_stopped",
            message="The floating context control is off.",
        )

    def set_visible(
        self,
        visible: bool,
        *,
        workspace_id: UUID | None,
        api_url: str,
    ) -> DesktopOverlayStatus:
        self.updates.append((visible, workspace_id, api_url))
        return DesktopOverlayStatus(
            supported=True,
            available=True,
            running=True,
            visible=visible,
            workspace_id=str(workspace_id) if workspace_id else None,
            code="overlay_visible" if visible else "overlay_hidden",
            message="updated",
        )


async def test_local_status_endpoint_returns_sanitized_state(
    client,
    monkeypatch,
) -> None:
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )

    response = await client.get(
        f"/api/desktop/overlay?workspace_id={uuid4()}",
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "desktop_overlay.v1",
        "supported": True,
        "available": True,
        "running": False,
        "visible": False,
        "workspace_id": None,
        "code": "overlay_stopped",
        "message": "The floating context control is off.",
    }
    assert manager.status_calls == 1


async def test_update_requires_workspace_when_showing(client) -> None:
    response = await client.put(
        "/api/desktop/overlay",
        json={"visible": True},
    )

    assert response.status_code == 422


async def test_update_validates_workspace_before_touching_native_process(
    client,
    monkeypatch,
) -> None:
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )

    response = await client.put(
        "/api/desktop/overlay",
        json={"visible": True, "workspace_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert manager.updates == []


async def test_local_update_passes_only_validated_workspace(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Overlay project",
        slug=f"overlay-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )

    response = await client.put(
        "/api/desktop/overlay",
        json={"visible": True, "workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200
    assert response.json()["visible"] is True
    assert response.json()["workspace_id"] == str(workspace.id)
    assert manager.updates == [
        (True, workspace.id, "http://127.0.0.1:80/api"),
    ]


async def test_hiding_ignores_workspace_input_and_does_not_require_lookup(
    client,
    monkeypatch,
) -> None:
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )

    response = await client.put(
        "/api/desktop/overlay",
        json={"visible": False, "workspace_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert manager.updates == [
        (False, None, "http://127.0.0.1:80/api"),
    ]


async def test_remote_clients_are_rejected_before_status_even_with_forwarding(
    monkeypatch,
) -> None:
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )
    transport = ASGITransport(
        app=app,
        client=("203.0.113.42", 43123),
    )
    async with AsyncClient(
        transport=transport,
        base_url="http://daemonstate.test",
    ) as remote:
        response = await remote.get(
            "/api/desktop/overlay",
            headers={
                "Forwarded": "for=127.0.0.1",
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "local_action_required"
    assert manager.status_calls == 0


async def test_nonlocal_principal_is_rejected_before_status(
    client,
    monkeypatch,
) -> None:
    manager = _FakeOverlayManager()
    monkeypatch.setattr(
        "app.api.desktop_overlay.desktop_overlay_manager",
        manager,
    )

    async def remote_scope() -> AccessScope:
        return AccessScope(principal_id="remote-user")

    app.dependency_overrides[get_access_scope] = remote_scope
    try:
        response = await client.get("/api/desktop/overlay")
    finally:
        app.dependency_overrides.pop(get_access_scope, None)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "local_action_required"
    assert manager.status_calls == 0


def test_pid_probe_uses_fixed_ps_argv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(
            argv,
            0,
            stdout="/tmp/DaemonStateOverlay --control-token safe-token-123456\n",
        )

    monkeypatch.setattr("app.services.desktop_overlay.subprocess.run", fake_run)

    command = manager._pid_command(4242)

    assert command is not None
    assert calls[0][0] == [
        "/bin/ps",
        "-ww",
        "-p",
        "4242",
        "-o",
        "command=",
    ]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
