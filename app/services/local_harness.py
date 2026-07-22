from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import signal
import stat
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _record_observation, _stored_manifest
from app.models import AgentRun, ContextPack
from app.services.redaction import REDACTED_VALUE, is_sensitive_key, redact_sensitive_text
from app.time import utc_now


DEFAULT_OUTPUT_LIMIT_BYTES = 32_768
DEFAULT_COMMAND_TIMEOUT_SECONDS = 3_600.0
DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 900.0
MAX_OUTPUT_LIMIT_BYTES = 1_048_576
MAX_STATUS_BYTES = 131_072
MAX_STATUS_PATHS = 500
MAX_HASHED_FILE_BYTES = 1_048_576
CONTEXT_FILE_PLACEHOLDER = "{context_file}"
TRUNCATED_OUTPUT = "[output truncated by local harness; captured content omitted]"


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "argv": list(self.argv)}


@dataclass(frozen=True)
class RepositorySnapshot:
    root: str
    branch: str | None
    head_commit: str
    dirty: bool
    changed_files: tuple[str, ...]
    status_fingerprint: str
    diff_summary: str
    status_truncated: bool
    _entries: tuple[tuple[str, str, str | None], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "branch": self.branch,
            "head_commit": self.head_commit,
            "dirty": self.dirty,
            "changed_files": list(self.changed_files),
            "status_fingerprint": self.status_fingerprint,
            "diff_summary": self.diff_summary,
            "status_truncated": self.status_truncated,
        }


@dataclass(frozen=True)
class VerificationResult:
    requirement_id: str | None
    command: str
    cwd: str
    result: CommandResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "command": self.command,
            "cwd": self.cwd,
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class _VerificationCommand:
    requirement_id: str | None
    command: str
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class LocalHarnessResult:
    context_pack_id: str
    run_id: str
    status: str
    command: CommandResult
    repository_before: RepositorySnapshot
    repository_after: RepositorySnapshot
    changed_files: tuple[str, ...]
    verification_results: tuple[VerificationResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_pack_id": self.context_pack_id,
            "run_id": self.run_id,
            "status": self.status,
            "command": self.command.to_dict(),
            "repository_before": self.repository_before.to_dict(),
            "repository_after": self.repository_after.to_dict(),
            "changed_files": list(self.changed_files),
            "verification_results": [item.to_dict() for item in self.verification_results],
        }


async def capture_repository_snapshot(repo_path: str | Path) -> RepositorySnapshot:
    """Return a bounded, content-aware snapshot for checkpoint freshness checks."""

    root = await _resolve_git_root(repo_path)
    return await _repository_snapshot(root)


async def run_repository_command(
    repo_path: str | Path,
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout_seconds: float = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
) -> CommandResult:
    """Run an explicit argv inside one repository for opt-in checkpoint verification."""

    root = await _resolve_git_root(repo_path)
    workdir = Path(cwd).expanduser() if cwd not in (None, "") else root
    if not workdir.is_absolute():
        workdir = root / workdir
    workdir = workdir.resolve()
    if workdir != root and root not in workdir.parents:
        raise ValueError("verification cwd must stay inside the checkpoint repository")
    if not workdir.is_dir():
        raise ValueError("verification cwd does not exist")
    return await _run_command(
        _explicit_argv(command),
        cwd=workdir,
        env=os.environ,
        output_limit_bytes=output_limit_bytes,
        timeout_seconds=timeout_seconds,
    )


class LocalHarnessRunner:
    """Wrap one explicit local command and persist observed run evidence.

    The runner supplies context but does not choose a worker or generate commands.
    All child processes use direct argv execution; shell expansion is never enabled.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
        command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        verification_timeout_seconds: float = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    ) -> None:
        if not 1 <= output_limit_bytes <= MAX_OUTPUT_LIMIT_BYTES:
            raise ValueError(
                f"output_limit_bytes must be between 1 and {MAX_OUTPUT_LIMIT_BYTES}"
            )
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        if verification_timeout_seconds <= 0:
            raise ValueError("verification_timeout_seconds must be positive")
        self.session = session
        self.output_limit_bytes = output_limit_bytes
        self.command_timeout_seconds = command_timeout_seconds
        self.verification_timeout_seconds = verification_timeout_seconds

    async def run(
        self,
        *,
        context_pack_id: UUID | str,
        run_id: UUID | str,
        repo_path: str | Path,
        command: Sequence[str],
        verify: bool = False,
        extra_env: Mapping[str, str] | None = None,
    ) -> LocalHarnessResult:
        pack_uuid = _uuid(context_pack_id, "context_pack_id")
        run_uuid = _uuid(run_id, "run_id")
        argv = _explicit_argv(command)
        pack = await self.session.get(ContextPack, pack_uuid)
        if pack is None:
            raise ValueError(f"ContextPack not found: {pack_uuid}")
        run = await self.session.get(AgentRun, run_uuid)
        if run is None:
            raise ValueError(f"AgentRun not found: {run_uuid}")
        if run.context_pack_id != pack.id:
            raise ValueError("AgentRun is not linked to the supplied ContextPack")
        if run.status != "running":
            raise ValueError("AgentRun must have status 'running' before harness execution")

        manifest = _stored_manifest(pack)
        repo_root = await _resolve_git_root(repo_path)
        verification_commands = (
            _required_verification_commands(manifest, repo_root) if verify else []
        )
        before = await _repository_snapshot(repo_root)
        run.branch = before.branch
        run.base_commit = before.head_commit
        run.started_at = run.started_at or utc_now()
        await self.session.commit()

        with tempfile.TemporaryDirectory(prefix="context-engine-harness-") as temp_dir:
            context_file = Path(temp_dir) / "context-pack.md"
            context_file.write_text(pack.markdown, encoding="utf-8")
            context_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            context_path = str(context_file)
            child_argv = tuple(context_path if arg == CONTEXT_FILE_PLACEHOLDER else arg for arg in argv)
            child_env = _child_environment(
                extra_env,
                context_path=context_path,
                context_pack_id=pack.id,
                run_id=run.id,
                model_profile=pack.model_profile,
            )
            child_result = await _run_command(
                child_argv,
                cwd=repo_root,
                env=child_env,
                output_limit_bytes=self.output_limit_bytes,
                timeout_seconds=self.command_timeout_seconds,
            )
            after_command = await _repository_snapshot(repo_root)
            changed_files = await _observed_changed_files(repo_root, before, after_command)
            await self._record_command(
                run=run,
                result=child_result,
                changed_files=changed_files,
                before=before,
                after=after_command,
            )

            verification_results: list[VerificationResult] = []
            if verify and child_result.exit_code == 0:
                for index, item in enumerate(verification_commands, start=1):
                    verification_argv = tuple(
                        context_path if arg == CONTEXT_FILE_PLACEHOLDER else arg
                        for arg in item.argv
                    )
                    result = await _run_command(
                        verification_argv,
                        cwd=item.cwd,
                        env=child_env,
                        output_limit_bytes=self.output_limit_bytes,
                        timeout_seconds=self.verification_timeout_seconds,
                    )
                    verification = VerificationResult(
                        requirement_id=item.requirement_id,
                        command=item.command,
                        cwd=str(item.cwd),
                        result=result,
                    )
                    verification_results.append(verification)
                    await self._record_verification(
                        run=run,
                        verification=verification,
                        index=index,
                    )
                    if result.exit_code != 0:
                        break

            after = await _repository_snapshot(repo_root)
            changed_files = await _observed_changed_files(repo_root, before, after)
            await self._record_patch_summary(
                run=run,
                changed_files=changed_files,
                before=before,
                after=after,
                verification_results=verification_results,
            )

        terminal_status = _terminal_status(child_result, verification_results)
        await self._record_outcome(
            run=run,
            status=terminal_status,
            child_result=child_result,
            changed_files=changed_files,
            before=before,
            after=after,
            verification_results=verification_results,
        )
        return LocalHarnessResult(
            context_pack_id=str(pack.id),
            run_id=str(run.id),
            status=terminal_status,
            command=child_result,
            repository_before=before,
            repository_after=after,
            changed_files=tuple(changed_files),
            verification_results=tuple(verification_results),
        )

    async def _record_command(
        self,
        *,
        run: AgentRun,
        result: CommandResult,
        changed_files: list[str],
        before: RepositorySnapshot,
        after: RepositorySnapshot,
    ) -> None:
        await _record_observation(
            self.session,
            run=run,
            event_key="harness:command",
            event_type="command",
            content=_command_content("Wrapped command", result),
            files=changed_files,
            command=shlex.join(result.argv),
            exit_code=result.exit_code,
            extra_metadata={"observed_by": "local_harness"},
            extra_payload={
                "argv": list(result.argv),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
                "timed_out": result.timed_out,
                "duration_ms": result.duration_ms,
                "repository_before": before.to_dict(),
                "repository_after": after.to_dict(),
            },
        )

    async def _record_patch_summary(
        self,
        *,
        run: AgentRun,
        changed_files: list[str],
        before: RepositorySnapshot,
        after: RepositorySnapshot,
        verification_results: Sequence[VerificationResult],
    ) -> None:
        summary = (
            f"Observed {len(changed_files)} changed repository path(s); "
            f"HEAD {before.head_commit} -> {after.head_commit}; "
            f"working tree {'dirty' if after.dirty else 'clean'}."
        )
        await _record_observation(
            self.session,
            run=run,
            event_key="harness:patch-summary",
            event_type="patch_summary",
            content=summary,
            files=changed_files,
            extra_metadata={"observed_by": "local_harness"},
            extra_payload={
                "summary": summary,
                "tests_run": [item.command for item in verification_results],
                "repository_before": before.to_dict(),
                "repository_after": after.to_dict(),
            },
        )

    async def _record_verification(
        self,
        *,
        run: AgentRun,
        verification: VerificationResult,
        index: int,
    ) -> None:
        result = verification.result
        await _record_observation(
            self.session,
            run=run,
            event_key=f"harness:verification:{index}",
            event_type="verification",
            content=_command_content("Verification", result),
            files=[],
            command=verification.command,
            exit_code=result.exit_code,
            extra_metadata={"observed_by": "local_harness"},
            extra_payload={
                "requirement_id": verification.requirement_id,
                "cwd": verification.cwd,
                "argv": list(result.argv),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
                "timed_out": result.timed_out,
                "duration_ms": result.duration_ms,
            },
        )

    async def _record_outcome(
        self,
        *,
        run: AgentRun,
        status: str,
        child_result: CommandResult,
        changed_files: list[str],
        before: RepositorySnapshot,
        after: RepositorySnapshot,
        verification_results: list[VerificationResult],
    ) -> None:
        summary = (
            f"Harness derived status {status} from child exit {child_result.exit_code}"
            + (
                " and verification exits "
                + ", ".join(str(item.result.exit_code) for item in verification_results)
                if verification_results
                else " with no executed verification commands"
            )
            + "."
        )
        verification_payload = [
            {
                "requirement_id": item.requirement_id,
                "command": item.command,
                "cwd": item.cwd,
                "exit_code": item.result.exit_code,
                "timed_out": item.result.timed_out,
            }
            for item in verification_results
        ]
        _, observation, _, _ = await _record_observation(
            self.session,
            run=run,
            event_key="harness:outcome",
            event_type="outcome",
            content=summary,
            files=changed_files,
            extra_metadata={"observed_by": "local_harness"},
            extra_payload={
                "status": status,
                "head_commit": after.head_commit,
                "verification_results": verification_payload,
                "repository_before": before.to_dict(),
                "repository_after": after.to_dict(),
                "completed_context_item_ids": [],
                "addresses_context_item_ids": [],
            },
        )
        run.head_commit = after.head_commit
        run.ended_at = observation.observed_at or utc_now()
        run.status = status
        await self.session.commit()


def _uuid(value: UUID | str, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _explicit_argv(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise TypeError("command must be an argv sequence, not a shell string")
    argv = tuple(str(item) for item in command)
    if not argv or not argv[0].strip():
        raise ValueError("command must contain an executable")
    if len(argv) > 256 or any("\x00" in item or len(item) > 16_384 for item in argv):
        raise ValueError("command argv is invalid or too large")
    return argv


def _child_environment(
    extra_env: Mapping[str, str] | None,
    *,
    context_path: str,
    context_pack_id: UUID,
    run_id: UUID,
    model_profile: str | None,
) -> dict[str, str]:
    env = os.environ.copy()
    if extra_env:
        for key, value in extra_env.items():
            key_text = str(key)
            value_text = str(value)
            if not key_text or "\x00" in key_text or "=" in key_text or "\x00" in value_text:
                raise ValueError("extra_env contains an invalid environment entry")
            env[key_text] = value_text
    env.update(
        {
            "CONTEXT_ENGINE_PACK_PATH": context_path,
            "CONTEXT_ENGINE_PACK_ID": str(context_pack_id),
            "CONTEXT_ENGINE_RUN_ID": str(run_id),
            "CONTEXT_ENGINE_MODEL_PROFILE": model_profile or "",
        }
    )
    return env


async def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    output_limit_bytes: int,
    timeout_seconds: float,
) -> CommandResult:
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        return CommandResult(
            argv=_redacted_argv(argv),
            exit_code=127,
            stdout="",
            stderr=_bounded_redacted_text(str(exc).encode(), output_limit_bytes),
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            duration_ms=_duration_ms(started),
        )

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, output_limit_bytes))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, output_limit_bytes))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
    try:
        stdout_capture, stderr_capture = await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task),
            timeout=5.0,
        )
    except TimeoutError:
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        stdout_capture = (b"", True)
        stderr_capture = (b"", True)

    stdout_bytes, stdout_truncated = stdout_capture
    stderr_bytes, stderr_truncated = stderr_capture
    exit_code = 124 if timed_out else int(process.returncode or 0)
    return CommandResult(
        argv=_redacted_argv(argv),
        exit_code=exit_code,
        stdout=(
            _truncated_output_marker(output_limit_bytes)
            if stdout_truncated
            else _bounded_redacted_text(stdout_bytes, output_limit_bytes)
        ),
        stderr=(
            _truncated_output_marker(output_limit_bytes)
            if stderr_truncated
            else _bounded_redacted_text(stderr_bytes, output_limit_bytes)
        ),
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
        duration_ms=_duration_ms(started),
    )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def _read_bounded(
    stream: asyncio.StreamReader,
    limit_bytes: int,
) -> tuple[bytes, bool]:
    captured = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(8_192)
        if not chunk:
            break
        remaining = limit_bytes - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(captured), truncated


async def _resolve_git_root(repo_path: str | Path) -> Path:
    path = Path(repo_path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"repo_path is not a directory: {path}")
    inside = await _git(path, "rev-parse", "--is-inside-work-tree", limit=256)
    if inside.exit_code != 0 or inside.stdout.strip() != "true":
        raise ValueError(f"repo_path is not a Git working tree: {path}")
    root = await _git(path, "rev-parse", "--show-toplevel", limit=4_096)
    if root.exit_code != 0 or not root.stdout.strip():
        raise ValueError(f"cannot resolve Git root for: {path}")
    resolved = Path(root.stdout.strip()).resolve()
    if not resolved.is_dir():
        raise ValueError(f"resolved Git root is not a directory: {resolved}")
    return resolved


async def _repository_snapshot(root: Path) -> RepositorySnapshot:
    branch_result, head_result, status_result, diff_result = await asyncio.gather(
        _git(root, "rev-parse", "--abbrev-ref", "HEAD", limit=1_024),
        _git(root, "rev-parse", "HEAD", limit=1_024),
        _git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            limit=MAX_STATUS_BYTES,
        ),
        _git(root, "diff", "--shortstat", "--no-ext-diff", "HEAD", "--", limit=4_096),
    )
    if head_result.exit_code != 0 or not head_result.stdout.strip():
        raise ValueError(f"cannot inspect Git HEAD in: {root}")
    entries, paths_truncated = await _status_entries(
        root,
        status_result.stdout,
        output_truncated=status_result.stdout_truncated,
    )
    fingerprint_payload = {
        "head_commit": head_result.stdout.strip(),
        "entries": entries,
        "status_truncated": paths_truncated,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RepositorySnapshot(
        root=str(root),
        branch=branch_result.stdout.strip() or None,
        head_commit=head_result.stdout.strip(),
        dirty=bool(entries) or paths_truncated,
        changed_files=tuple(sorted({item[1] for item in entries})),
        status_fingerprint=fingerprint,
        diff_summary=_redacted_text(diff_result.stdout.strip()),
        status_truncated=paths_truncated,
        _entries=tuple(entries),
    )


async def _status_entries(
    root: Path,
    raw_status: str,
    *,
    output_truncated: bool,
) -> tuple[list[tuple[str, str, str | None]], bool]:
    tokens = raw_status.split("\x00")
    entries: list[tuple[str, str, str | None]] = []
    truncated = output_truncated
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if len(token) < 4:
            truncated = True
            continue
        status_code = token[:2]
        raw_path = token[3:]
        if status_code[0] in {"R", "C"} or status_code[1] in {"R", "C"}:
            if index < len(tokens) and tokens[index]:
                index += 1
            else:
                truncated = True
        safe_path = _safe_relative_path(raw_path)
        if safe_path is None:
            truncated = True
            continue
        if len(entries) >= MAX_STATUS_PATHS:
            truncated = True
            continue
        content_hash = await asyncio.to_thread(_bounded_file_hash, root, safe_path)
        entries.append((status_code, safe_path, content_hash))
    return entries, truncated


async def _observed_changed_files(
    root: Path,
    before: RepositorySnapshot,
    after: RepositorySnapshot,
) -> list[str]:
    before_entries = {item[1]: item for item in before._entries}
    after_entries = {item[1]: item for item in after._entries}
    changed = {
        path
        for path in set(before_entries) | set(after_entries)
        if before_entries.get(path) != after_entries.get(path)
    }
    if before.head_commit != after.head_commit:
        committed = await _git(
            root,
            "diff",
            "--name-only",
            "-z",
            before.head_commit,
            after.head_commit,
            "--",
            limit=MAX_STATUS_BYTES,
        )
        for raw_path in committed.stdout.split("\x00"):
            safe_path = _safe_relative_path(raw_path)
            if safe_path is not None:
                changed.add(safe_path)
    return sorted(changed)[:MAX_STATUS_PATHS]


def _bounded_file_hash(root: Path, relative_path: str) -> str | None:
    path = root / relative_path
    try:
        details = path.lstat()
        digest = hashlib.sha256()
        digest.update(str(details.st_size).encode())
        if stat.S_ISLNK(details.st_mode):
            digest.update(os.readlink(path).encode("utf-8", errors="replace"))
            return digest.hexdigest()
        if not stat.S_ISREG(details.st_mode):
            return None
        remaining = MAX_HASHED_FILE_BYTES
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(65_536, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
        digest.update(b":truncated" if details.st_size > MAX_HASHED_FILE_BYTES else b":complete")
        return digest.hexdigest()
    except OSError:
        return None


async def _git(root: Path, *args: str, limit: int) -> CommandResult:
    return await _run_command(
        ("git", "-C", str(root), *args),
        cwd=root,
        env=os.environ,
        output_limit_bytes=limit,
        timeout_seconds=10.0,
    )


def _required_verification_commands(
    manifest: Mapping[str, Any],
    repo_root: Path,
) -> list[_VerificationCommand]:
    verification = manifest.get("verification")
    if not isinstance(verification, Mapping):
        return []
    commands = verification.get("commands")
    if not isinstance(commands, list):
        return []
    results: list[_VerificationCommand] = []
    for item in commands:
        if not isinstance(item, Mapping) or item.get("required") is not True:
            continue
        raw_command = item.get("command")
        if isinstance(raw_command, str):
            argv = tuple(shlex.split(raw_command))
        elif isinstance(raw_command, Sequence) and not isinstance(raw_command, (str, bytes)):
            argv = _explicit_argv(raw_command)
        else:
            continue
        if not argv:
            continue
        requirement_id = str(item["id"]) if item.get("id") else None
        cwd = _verification_cwd(repo_root, item.get("cwd"), requirement_id)
        results.append(
            _VerificationCommand(
                requirement_id=requirement_id,
                command=shlex.join(_redacted_argv(argv)),
                argv=argv,
                cwd=cwd,
            )
        )
    return results


def _verification_cwd(
    repo_root: Path,
    raw_cwd: Any,
    requirement_id: str | None,
) -> Path:
    candidate = Path(str(raw_cwd)).expanduser() if raw_cwd not in (None, "") else repo_root
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve()
    if candidate != repo_root and repo_root not in candidate.parents:
        label = requirement_id or "unnamed verification"
        raise ValueError(f"verification {label} cwd is outside the repository")
    if not candidate.is_dir():
        label = requirement_id or "unnamed verification"
        raise ValueError(f"verification {label} cwd is not a directory: {candidate}")
    return candidate


def _terminal_status(
    child_result: CommandResult,
    verification_results: Sequence[VerificationResult],
) -> str:
    if child_result.exit_code != 0:
        return "failed"
    if any(item.result.exit_code != 0 for item in verification_results):
        return "failed"
    return "completed"


def _command_content(label: str, result: CommandResult) -> str:
    sections = [
        f"{label} exited with code {result.exit_code}"
        + (" after timeout." if result.timed_out else ".")
    ]
    if result.stdout:
        sections.append("Bounded stdout:\n" + result.stdout)
    if result.stderr:
        sections.append("Bounded stderr:\n" + result.stderr)
    if result.stdout_truncated or result.stderr_truncated:
        sections.append("Output was truncated by the local harness.")
    return "\n".join(sections)


def _redacted_text(value: str) -> str:
    return redact_sensitive_text(value) or ""


def _redacted_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    for raw in argv:
        value = str(raw)
        if redact_next:
            redacted.append(REDACTED_VALUE)
            redact_next = False
            continue
        if value.startswith("-"):
            option = value.lstrip("-")
            key, separator, _ = option.partition("=")
            if is_sensitive_key(key):
                prefix = value[: len(value) - len(option)]
                if separator:
                    redacted.append(f"{prefix}{key}={REDACTED_VALUE}")
                else:
                    redacted.append(value)
                    redact_next = True
                continue
        redacted.append(_redacted_text(value))
    return tuple(redacted)


def _bounded_redacted_text(value: bytes, limit_bytes: int) -> str:
    redacted = _redacted_text(value.decode("utf-8", errors="replace"))
    encoded = redacted.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return redacted
    return encoded[:limit_bytes].decode("utf-8", errors="ignore")


def _truncated_output_marker(limit_bytes: int) -> str:
    return TRUNCATED_OUTPUT.encode("utf-8")[:limit_bytes].decode(
        "utf-8", errors="ignore"
    )


def _safe_relative_path(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None
    lowered = [part.lower() for part in path.parts]
    basename = lowered[-1]
    stem = PurePosixPath(basename).stem
    if (
        any(part in {".aws", ".ssh", ".gnupg"} for part in lowered)
        or basename in {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}
        or basename.startswith(".env")
        or stem in {"credential", "credentials", "private_key", "secret", "secrets"}
        or PurePosixPath(basename).suffix in {".key", ".pem", ".p12", ".pfx"}
    ):
        return None
    if redact_sensitive_text(normalized) != normalized:
        return None
    return normalized


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1_000))
