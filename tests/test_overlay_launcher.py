from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = REPOSITORY_ROOT / "scripts" / "overlay.sh"


def _launcher_repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    launcher = repository / "scripts" / "overlay.sh"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        LAUNCHER_SOURCE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    package = repository / "desktop" / "macos" / "DaemonStateOverlay"
    sources = package / "Sources" / "DaemonStateOverlay"
    sources.mkdir(parents=True)
    (package / "Package.swift").write_text("// package\n", encoding="utf-8")
    (sources / "Application.swift").write_text("// source\n", encoding="utf-8")
    return launcher, package


def _recording_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "{ printf '%s\\n' \"$0\"; printf '%s\\n' \"$@\"; }"
        " > \"${OVERLAY_TEST_OUTPUT}\"\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def test_launcher_uses_newest_fresh_binary_and_forwards_arguments(
    tmp_path: Path,
) -> None:
    launcher, package = _launcher_repository(tmp_path)
    release = package / ".build" / "release" / "DaemonStateOverlay"
    debug = package / ".build" / "debug" / "DaemonStateOverlay"
    _recording_executable(release)
    _recording_executable(debug)
    source_time = time.time() - 20
    os.utime(package / "Package.swift", (source_time, source_time))
    os.utime(
        package / "Sources" / "DaemonStateOverlay" / "Application.swift",
        (source_time, source_time),
    )
    os.utime(release, (source_time - 5, source_time - 5))
    os.utime(debug, (source_time + 5, source_time + 5))
    output = tmp_path / "launch.txt"
    environment = {
        **os.environ,
        "OVERLAY_TEST_OUTPUT": str(output),
        "DAEMONSTATE_OVERLAY_SWIFT_CACHE_ROOT": str(tmp_path / "cache"),
    }

    subprocess.run(
        [
            str(launcher),
            "--control-token",
            "provided-control-token-123456",
            "--workspace-id",
            "e87439d7-f8a0-4641-accb-6bb324073b3c",
        ],
        check=True,
        env=environment,
    )

    lines = output.read_text(encoding="utf-8").splitlines()
    assert Path(lines[0]) == debug
    assert lines[1:] == [
        "--control-token",
        "provided-control-token-123456",
        "--workspace-id",
        "e87439d7-f8a0-4641-accb-6bb324073b3c",
    ]


def test_launcher_fallback_uses_private_package_cache_and_generated_token(
    tmp_path: Path,
) -> None:
    launcher, _package = _launcher_repository(tmp_path)
    fake_bin = tmp_path / "bin"
    swift = fake_bin / "swift"
    _recording_executable(swift)
    output = tmp_path / "swift.txt"
    cache_root = tmp_path / "launcher-cache"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "OVERLAY_TEST_OUTPUT": str(output),
        "DAEMONSTATE_OVERLAY_CONTROL_TOKEN": (
            "generated-control-token-123456"
        ),
        "DAEMONSTATE_OVERLAY_SWIFT_CACHE_ROOT": str(cache_root),
    }

    subprocess.run(
        [
            str(launcher),
            "--workspace-id",
            "e87439d7-f8a0-4641-accb-6bb324073b3c",
        ],
        check=True,
        env=environment,
    )

    lines = output.read_text(encoding="utf-8").splitlines()
    assert Path(lines[0]) == swift
    arguments = lines[1:]
    assert "--disable-sandbox" in arguments
    assert "--manifest-cache" in arguments
    executable_index = arguments.index("DaemonStateOverlay")
    assert arguments[executable_index + 1 :] == [
        "--workspace-id",
        "e87439d7-f8a0-4641-accb-6bb324073b3c",
        "--control-token",
        "generated-control-token-123456",
    ]
    assert cache_root.stat().st_mode & 0o077 == 0
