from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import os
import shlex
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _record_observation, _stored_manifest
from app.models import AgentRun, ContextPack, ContinuationExecution
from app.schemas.continuation_execution import ContinuationExecutionContract
from app.services.harness_adapters import (
    is_daemonstate_secret_key,
    minimal_process_environment,
)
from app.services.redaction import REDACTED_VALUE, is_sensitive_key, redact_sensitive_text
from app.services.repo_paths import validated_repository_path
from app.services.runtime_bundle import (
    RuntimeBundle,
    RuntimeBundleIntegrityError,
    materialize_runtime_bundle,
)
from app.telemetry import traced
from app.time import utc_now


DEFAULT_OUTPUT_LIMIT_BYTES = 32_768
DEFAULT_COMMAND_TIMEOUT_SECONDS = 3_600.0
DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 900.0
MAX_OUTPUT_LIMIT_BYTES = 1_048_576
MAX_CONTEXT_STDIN_BYTES = 1_048_576
MAX_STRUCTURED_EVENT_LINE_BYTES = 1_048_576
MAX_STATUS_BYTES = 131_072
MAX_STATUS_PATHS = 500
MAX_HASHED_FILE_BYTES = 1_048_576
MAX_PRESERVATION_FILE_BYTES = 4_194_304
MAX_PRESERVATION_TOTAL_BYTES = 16_777_216
CONTEXT_FILE_PLACEHOLDER = "{context_file}"
TRUNCATED_OUTPUT = "[output truncated by local harness; middle content omitted]"
StdoutChunkObserver = Callable[[bytes], Awaitable[None]]


logger = logging.getLogger(__name__)


class RepositoryStateChangedError(RuntimeError):
    """Raised before worker launch when a compiled pack no longer matches the repo."""

    def __init__(self, expected: str, observed: str) -> None:
        self.expected = expected
        self.observed = observed
        super().__init__(
            "Repository state changed after context preparation and before agent launch."
        )


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
    structured_terminal_error: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # This is an internal streaming classification used when the bounded
        # diagnostic text cannot retain a complete provider event.
        payload.pop("structured_terminal_error", None)
        return {**payload, "argv": list(self.argv)}


@dataclass(frozen=True)
class _BaselineFile:
    path: str
    status: str
    base_content: bytes | None
    baseline_content: bytes | None
    baseline_mode: int | None
    exact_content_required: bool
    baseline_sha256: str | None = None


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
    _preservation_files: tuple[_BaselineFile, ...] = ()
    _preservation_complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "branch": self.branch,
            "head_commit": self.head_commit,
            "dirty": self.dirty,
            "changed_files": list(self.changed_files),
            "changed_file_entries": [
                {
                    "status": status,
                    "xy": status,
                    "change_kind": _git_change_kind(status),
                    "path": path,
                    "sha256": digest,
                }
                for status, path, digest in self._entries
            ],
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
    verifier_id: str | None = None
    requirement_ids: tuple[str, ...] = ()
    verifier_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "verifier_id": self.verifier_id or self.requirement_id,
            "requirement_ids": list(self.requirement_ids),
            "verifier_type": self.verifier_type,
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
    verifier_id: str | None = None
    requirement_ids: tuple[str, ...] = ()
    verifier_type: str | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class _MaterializedContext:
    path: Path
    runtime_environment: Mapping[str, str]
    bundle: RuntimeBundle | None = None


@dataclass(frozen=True)
class _BoundedStreamCapture:
    head: bytes
    tail: bytes
    truncated: bool
    tail_starts_at_line_boundary: bool
    structured_terminal_error: bool | None


@dataclass(frozen=True)
class LocalHarnessResult:
    context_pack_id: str
    run_id: str
    status: str
    command: CommandResult
    repository_before: RepositorySnapshot
    repository_after: RepositorySnapshot
    agent_changed_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    verification_results: tuple[VerificationResult, ...]
    continuation_execution_id: str | None = None
    runtime_bundle_integrity_passed: bool = True
    preservation_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_pack_id": self.context_pack_id,
            "run_id": self.run_id,
            "status": self.status,
            "command": self.command.to_dict(),
            "repository_before": self.repository_before.to_dict(),
            "repository_after": self.repository_after.to_dict(),
            "agent_changed_files": list(self.agent_changed_files),
            "changed_files": list(self.changed_files),
            "verification_results": [item.to_dict() for item in self.verification_results],
            "continuation_execution_id": self.continuation_execution_id,
            "runtime_bundle_integrity_passed": self.runtime_bundle_integrity_passed,
            "preservation_passed": self.preservation_passed,
        }


def _local_harness_trace_result(
    result: LocalHarnessResult,
) -> dict[str, Any]:
    total = len(result.verification_results)
    passed = sum(
        item.result.exit_code == 0
        for item in result.verification_results
    )
    return {
        "daemonstate.context_pack.id": result.context_pack_id,
        "daemonstate.continuation.execution.id": (
            result.continuation_execution_id
        ),
        "daemonstate.run.id": result.run_id,
        "daemonstate.status": result.status,
        "daemonstate.runtime.worker_succeeded": result.status == "completed",
        "daemonstate.runtime.bundle_integrity_passed": (
            result.runtime_bundle_integrity_passed
        ),
        "daemonstate.runtime.preservation_passed": result.preservation_passed,
        "daemonstate.runtime.changed_file_count": len(result.changed_files),
        "daemonstate.repository.fingerprint": (
            result.repository_after.status_fingerprint
        ),
        "daemonstate.verification.total": total,
        "daemonstate.verification.passed": passed,
        "daemonstate.verification.failed": total - passed,
    }


async def capture_repository_snapshot(repo_path: str | Path) -> RepositorySnapshot:
    """Return a bounded, content-aware snapshot for checkpoint freshness checks."""

    root = await _resolve_git_root(repo_path)
    return await _stable_repository_snapshot(root)


async def _stable_repository_snapshot(root: Path) -> RepositorySnapshot:
    snapshot = await _repository_snapshot(root)
    if not snapshot.status_truncated:
        return snapshot
    # A dirty file can be replaced atomically, or the status set can change,
    # while the snapshot is being read. Retry once so a transient race does not
    # become a stale blocking contract.
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

    @traced(
        "daemonstate.harness.execute",
        attributes=lambda _args, kwargs: {
            "daemonstate.phase": "harness_execute",
            "daemonstate.context_pack.id": kwargs.get("context_pack_id"),
            "daemonstate.continuation.execution.id": kwargs.get(
                "continuation_execution_id"
            ),
            "daemonstate.run.id": kwargs.get("run_id"),
            "daemonstate.verification.enabled": kwargs.get("verify", False),
        },
        result_attributes=lambda result: _local_harness_trace_result(result),
    )
    async def run(
        self,
        *,
        context_pack_id: UUID | str,
        run_id: UUID | str,
        repo_path: str | Path,
        command: Sequence[str],
        verify: bool = False,
        context_stdin: bool = False,
        extra_env: Mapping[str, str] | None = None,
        expected_status_fingerprint: str | None = None,
        command_timeout_seconds: float | None = None,
        stdout_chunk_observer: StdoutChunkObserver | None = None,
        continuation_execution_id: UUID | str | None = None,
        execution_prompt_override: str | None = None,
        preservation_baseline: RepositorySnapshot | None = None,
    ) -> LocalHarnessResult:
        effective_command_timeout = (
            self.command_timeout_seconds
            if command_timeout_seconds is None
            else command_timeout_seconds
        )
        if effective_command_timeout <= 0:
            raise ValueError("command_timeout_seconds must be positive")
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
        execution: ContinuationExecution | None = None
        contract: ContinuationExecutionContract | None = None
        if continuation_execution_id is not None:
            execution_uuid = _uuid(
                continuation_execution_id,
                "continuation_execution_id",
            )
            execution = await self.session.get(ContinuationExecution, execution_uuid)
            if execution is None:
                raise ValueError(
                    f"ContinuationExecution not found: {execution_uuid}"
                )
            if execution.context_pack_id != pack.id:
                raise ValueError(
                    "ContinuationExecution is not linked to the supplied ContextPack"
                )
            if run.continuation_execution_id != execution.id:
                raise ValueError(
                    "AgentRun is not linked to the supplied ContinuationExecution"
                )
            contract = ContinuationExecutionContract.model_validate_json(
                execution.contract_json
            )
            if str(contract.id) != str(execution.id):
                raise ValueError("ContinuationExecution contract identity does not match")
            if execution_prompt_override is not None:
                if not execution_prompt_override.startswith(
                    execution.prompt_markdown
                ):
                    raise ValueError(
                        "repair prompt must preserve the canonical execution prompt"
                    )
                context_text = execution_prompt_override
            else:
                context_text = execution.prompt_markdown
        else:
            if execution_prompt_override is not None:
                raise ValueError(
                    "execution_prompt_override requires ContinuationExecution"
                )
            if preservation_baseline is not None:
                raise ValueError(
                    "preservation_baseline requires ContinuationExecution"
                )
            if run.continuation_execution_id is not None:
                raise ValueError(
                    "ContinuationExecution is required for a continuation AgentRun"
                )
            if str(run.run_key or "").startswith("continuation:"):
                raise ValueError(
                    "continuation AgentRun requires the canonical "
                    "ContinuationExecution prompt"
                )
            context_text = pack.markdown
        if run.status != "running":
            raise ValueError("AgentRun must have status 'running' before harness execution")
        context_input = _context_stdin_payload(context_text) if context_stdin else None

        manifest = _stored_manifest(pack)
        repo_root = await _resolve_git_root(repo_path)
        verification_commands = (
            (
                _contract_verification_commands(contract, repo_root)
                if contract is not None
                else _required_verification_commands(manifest, repo_root)
            )
            if verify
            else []
        )
        before = await _stable_repository_snapshot(repo_root)
        if (
            preservation_baseline is not None
            and Path(preservation_baseline.root).resolve() != repo_root
        ):
            raise ValueError(
                "preservation_baseline belongs to a different repository"
            )
        compiled_fingerprint = (
            contract.repository.status_fingerprint
            if contract is not None and preservation_baseline is None
            else None
        )
        expected_fingerprints = {
            value
            for value in (expected_status_fingerprint, compiled_fingerprint)
            if value
        }
        if len(expected_fingerprints) > 1:
            run.status = "failed"
            run.ended_at = utc_now()
            await self.session.commit()
            raise RepositoryStateChangedError(
                compiled_fingerprint or "",
                expected_status_fingerprint or "",
            )
        expected_fingerprint = next(iter(expected_fingerprints), None)
        if expected_fingerprint and before.status_fingerprint != expected_fingerprint:
            run.status = "failed"
            run.ended_at = utc_now()
            await self.session.commit()
            raise RepositoryStateChangedError(
                expected_fingerprint,
                before.status_fingerprint,
            )
        run.branch = before.branch
        run.base_commit = before.head_commit
        run.started_at = run.started_at or utc_now()
        await self.session.commit()

        bundle_integrity_passed = True
        preservation_passed = True
        with _materialized_context(
            execution=execution,
            contract=contract,
            context_text=context_text,
        ) as materialized:
            context_path = str(materialized.path)
            child_argv = tuple(context_path if arg == CONTEXT_FILE_PLACEHOLDER else arg for arg in argv)
            child_env = _child_environment(
                extra_env,
                context_path=context_path,
                context_pack_id=pack.id,
                run_id=run.id,
                model_profile=pack.model_profile,
                continuation_execution_id=(
                    execution.id if execution is not None else None
                ),
                runtime_environment=materialized.runtime_environment,
            )
            child_result = await _run_command(
                child_argv,
                cwd=repo_root,
                env=child_env,
                output_limit_bytes=self.output_limit_bytes,
                timeout_seconds=effective_command_timeout,
                stdin_data=context_input,
                stdout_chunk_observer=stdout_chunk_observer,
            )
            if materialized.bundle is not None:
                try:
                    materialized.bundle.verify_integrity()
                except RuntimeBundleIntegrityError:
                    bundle_integrity_passed = False
            after_command = await _stable_repository_snapshot(repo_root)
            agent_changed_files = await _observed_changed_files(
                repo_root,
                before,
                after_command,
            )
            await self._record_command(
                run=run,
                result=child_result,
                changed_files=agent_changed_files,
                before=before,
                after=after_command,
            )

            verification_results: list[VerificationResult] = []
            if (
                verify
                and child_result.exit_code == 0
                and not _command_has_structured_terminal_error(child_result)
                and bundle_integrity_passed
            ):
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
                        timeout_seconds=(
                            item.timeout_seconds
                            or (
                                contract.execution_policy.verification_timeout_seconds
                                if contract is not None
                                else self.verification_timeout_seconds
                            )
                        ),
                    )
                    verification = VerificationResult(
                        requirement_id=item.requirement_id,
                        verifier_id=item.verifier_id,
                        requirement_ids=item.requirement_ids,
                        verifier_type=item.verifier_type,
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
                    if contract is None and result.exit_code != 0:
                        break

            if materialized.bundle is not None and bundle_integrity_passed:
                try:
                    materialized.bundle.verify_integrity()
                except RuntimeBundleIntegrityError:
                    bundle_integrity_passed = False
            after = await _stable_repository_snapshot(repo_root)
            changed_files = await _observed_changed_files(repo_root, before, after)
            if contract is not None:
                preservation_passed = await _preservation_passed(
                    contract,
                    before=preservation_baseline or before,
                    after=after,
                )
            await self._record_patch_summary(
                run=run,
                changed_files=changed_files,
                before=before,
                after=after,
                verification_results=verification_results,
            )

        terminal_status = (
            _worker_status(child_result)
            if contract is not None
            else _terminal_status(child_result, verification_results)
        )
        await self._record_outcome(
            run=run,
            status=terminal_status,
            child_result=child_result,
            changed_files=changed_files,
            before=before,
            after=after,
            verification_results=verification_results,
            runtime_bundle_integrity_passed=bundle_integrity_passed,
            preservation_passed=preservation_passed,
        )
        return LocalHarnessResult(
            context_pack_id=str(pack.id),
            run_id=str(run.id),
            status=terminal_status,
            command=child_result,
            repository_before=before,
            repository_after=after,
            agent_changed_files=tuple(agent_changed_files),
            changed_files=tuple(changed_files),
            verification_results=tuple(verification_results),
            continuation_execution_id=(
                str(execution.id) if execution is not None else None
            ),
            runtime_bundle_integrity_passed=bundle_integrity_passed,
            preservation_passed=preservation_passed,
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
                "verifier_id": verification.verifier_id,
                "requirement_ids": list(verification.requirement_ids),
                "verifier_type": verification.verifier_type,
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
        runtime_bundle_integrity_passed: bool = True,
        preservation_passed: bool = True,
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
        if not runtime_bundle_integrity_passed:
            summary += " Runtime bundle integrity was not preserved."
        if not preservation_passed:
            summary += " Repository preservation policy was not satisfied."
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
                "runtime_bundle_integrity_passed": runtime_bundle_integrity_passed,
                "preservation_passed": preservation_passed,
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


@contextmanager
def _materialized_context(
    *,
    execution: ContinuationExecution | None,
    contract: ContinuationExecutionContract | None,
    context_text: str,
) -> Iterator[_MaterializedContext]:
    if execution is not None and contract is not None:
        with materialize_runtime_bundle(
            contract,
            prompt_markdown=context_text,
        ) as bundle:
            yield _MaterializedContext(
                path=bundle.execution_path,
                runtime_environment=bundle.environment(),
                bundle=bundle,
            )
        return

    with tempfile.TemporaryDirectory(
        prefix="daemonstate-harness-"
    ) as temp_dir:
        context_file = Path(temp_dir) / "context-pack.md"
        context_file.write_text(context_text, encoding="utf-8")
        context_file.chmod(stat.S_IRUSR)
        yield _MaterializedContext(
            path=context_file,
            runtime_environment={},
        )


def _child_environment(
    extra_env: Mapping[str, str] | None,
    *,
    context_path: str,
    context_pack_id: UUID,
    run_id: UUID,
    model_profile: str | None,
    continuation_execution_id: UUID | None = None,
    runtime_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = minimal_process_environment()
    if extra_env:
        for key, value in extra_env.items():
            key_text = str(key)
            value_text = str(value)
            if not key_text or "\x00" in key_text or "=" in key_text or "\x00" in value_text:
                raise ValueError("extra_env contains an invalid environment entry")
            if is_daemonstate_secret_key(key_text):
                continue
            env[key_text] = value_text
    env.update(
        {
            "DAEMONSTATE_PACK_PATH": context_path,
            "DAEMONSTATE_PACK_ID": str(context_pack_id),
            "DAEMONSTATE_RUN_ID": str(run_id),
            "DAEMONSTATE_MODEL_PROFILE": model_profile or "",
            "DAEMONSTATE_EXECUTION_ID": (
                str(continuation_execution_id)
                if continuation_execution_id is not None
                else ""
            ),
        }
    )
    if runtime_environment:
        for key, value in runtime_environment.items():
            key_text = str(key)
            value_text = str(value)
            if (
                not key_text
                or "\x00" in key_text
                or "=" in key_text
                or "\x00" in value_text
            ):
                raise ValueError(
                    "runtime_environment contains an invalid environment entry"
                )
            env[key_text] = value_text
    return env


async def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    output_limit_bytes: int,
    timeout_seconds: float,
    stdin_data: bytes | None = None,
    stdout_chunk_observer: StdoutChunkObserver | None = None,
) -> CommandResult:
    if stdin_data is not None:
        if not isinstance(stdin_data, bytes):
            raise TypeError("stdin_data must be bytes")
        if len(stdin_data) > MAX_CONTEXT_STDIN_BYTES:
            raise ValueError(
                f"stdin_data exceeds the {MAX_CONTEXT_STDIN_BYTES}-byte limit"
            )
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=dict(env),
            stdin=(
                asyncio.subprocess.PIPE
                if stdin_data is not None
                else asyncio.subprocess.DEVNULL
            ),
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
    stdout_task = asyncio.create_task(
        _read_bounded(
            process.stdout,
            output_limit_bytes,
            chunk_observer=stdout_chunk_observer,
            track_structured_events=True,
        )
    )
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, output_limit_bytes))
    stdin_task = (
        asyncio.create_task(_write_stdin(process, stdin_data))
        if stdin_data is not None
        else None
    )
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        if stdin_task is not None:
            stdin_task.cancel()
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(
            *(
                [stdout_task, stderr_task]
                + ([stdin_task] if stdin_task is not None else [])
            ),
            return_exceptions=True,
        )
        raise
    if stdin_task is not None:
        try:
            await asyncio.wait_for(stdin_task, timeout=5.0)
        except TimeoutError:
            stdin_task.cancel()
            await asyncio.gather(stdin_task, return_exceptions=True)
    try:
        stdout_capture, stderr_capture = await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task),
            timeout=5.0,
        )
    except TimeoutError:
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        stdout_capture = _BoundedStreamCapture(
            b"",
            b"",
            True,
            True,
            None,
        )
        stderr_capture = _BoundedStreamCapture(
            b"",
            b"",
            True,
            True,
            None,
        )

    exit_code = 124 if timed_out else int(process.returncode or 0)
    return CommandResult(
        argv=_redacted_argv(argv),
        exit_code=exit_code,
        stdout=_captured_output_text(stdout_capture, output_limit_bytes),
        stderr=_captured_output_text(stderr_capture, output_limit_bytes),
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        timed_out=timed_out,
        duration_ms=_duration_ms(started),
        structured_terminal_error=stdout_capture.structured_terminal_error,
    )


async def _write_stdin(
    process: asyncio.subprocess.Process,
    payload: bytes,
) -> None:
    stream = process.stdin
    if stream is None:
        raise RuntimeError("worker stdin pipe is unavailable")
    try:
        stream.write(payload)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        stream.close()
        try:
            await stream.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass


def _context_stdin_payload(markdown: str) -> bytes:
    payload = str(markdown).encode("utf-8")
    if len(payload) > MAX_CONTEXT_STDIN_BYTES:
        raise ValueError(
            "context pack is too large for stdin delivery "
            f"({len(payload)} bytes; maximum {MAX_CONTEXT_STDIN_BYTES})"
        )
    return payload


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
    *,
    chunk_observer: StdoutChunkObserver | None = None,
    track_structured_events: bool = False,
) -> _BoundedStreamCapture:
    head_limit = limit_bytes // 2
    tail_limit = limit_bytes - head_limit
    head = bytearray()
    tail = bytearray()
    tail_starts_at_line_boundary = head_limit == 0
    truncated = False
    observer_failed = False
    structured_buffer = bytearray()
    structured_line_overflow = False
    structured_terminal_error: bool | None = None
    while True:
        chunk = await stream.read(8_192)
        if not chunk:
            break
        if chunk_observer is not None and not observer_failed:
            try:
                await chunk_observer(chunk)
            except Exception:
                # Observability must never stop pipe draining or kill the
                # provider process. The captured command remains authoritative.
                observer_failed = True
                logger.exception("Local harness stdout observer failed")
        if track_structured_events:
            (
                structured_terminal_error,
                structured_line_overflow,
            ) = _observe_structured_chunk(
                structured_buffer,
                chunk,
                terminal_error=structured_terminal_error,
                line_overflow=structured_line_overflow,
            )
        head_remaining = head_limit - len(head)
        if head_remaining > 0:
            head.extend(chunk[:head_remaining])
            chunk = chunk[head_remaining:]
        if not chunk:
            continue
        if not tail:
            tail_starts_at_line_boundary = (
                head_limit == 0
                or head.endswith(b"\n")
            )
        if len(tail) + len(chunk) > tail_limit:
            truncated = True
        if tail_limit:
            tail.extend(chunk)
            if len(tail) > tail_limit:
                overflow = len(tail) - tail_limit
                tail_starts_at_line_boundary = tail[overflow - 1] == 0x0A
                del tail[:overflow]
    if (
        track_structured_events
        and structured_buffer
        and not structured_line_overflow
    ):
        terminal_state = _structured_terminal_state_from_line(
            bytes(structured_buffer)
        )
        if terminal_state is not None:
            structured_terminal_error = terminal_state
    return _BoundedStreamCapture(
        bytes(head),
        bytes(tail),
        truncated,
        tail_starts_at_line_boundary,
        structured_terminal_error,
    )


def _observe_structured_chunk(
    buffer: bytearray,
    chunk: bytes,
    *,
    terminal_error: bool | None,
    line_overflow: bool,
) -> tuple[bool | None, bool]:
    """Track the latest complete structured terminal event with bounded memory."""

    buffer.extend(chunk)
    while True:
        newline = buffer.find(b"\n")
        if newline < 0:
            if len(buffer) > MAX_STRUCTURED_EVENT_LINE_BYTES:
                buffer.clear()
                line_overflow = True
            return terminal_error, line_overflow
        line = bytes(buffer[:newline])
        del buffer[: newline + 1]
        if line_overflow:
            line_overflow = False
            continue
        if len(line) > MAX_STRUCTURED_EVENT_LINE_BYTES:
            continue
        terminal_state = _structured_terminal_state_from_line(line)
        if terminal_state is not None:
            terminal_error = terminal_state


async def _resolve_git_root(repo_path: str | Path) -> Path:
    path = validated_repository_path(repo_path)
    inside = await _git(path, "rev-parse", "--is-inside-work-tree", limit=256)
    if inside.exit_code != 0 or inside.stdout.strip() != "true":
        raise ValueError(f"repo_path is not a Git working tree: {path}")
    root = await _git(path, "rev-parse", "--show-toplevel", limit=4_096)
    if root.exit_code != 0 or not root.stdout.strip():
        raise ValueError(f"cannot resolve Git root for: {path}")
    return validated_repository_path(root.stdout.strip())


async def _repository_snapshot(root: Path) -> RepositorySnapshot:
    branch_result, head_result, status_result, diff_result = await asyncio.gather(
        _git(root, "rev-parse", "--abbrev-ref", "HEAD", limit=1_024),
        _git(root, "rev-parse", "HEAD", limit=1_024),
        _git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--no-renames",
            "--untracked-files=all",
            limit=MAX_STATUS_BYTES,
        ),
        _git(root, "diff", "--shortstat", "--no-ext-diff", "HEAD", "--", limit=4_096),
    )
    if head_result.exit_code != 0 or not head_result.stdout.strip():
        raise ValueError(f"cannot inspect Git HEAD in: {root}")
    branch = branch_result.stdout.strip() or None
    branch_failed = branch_result.exit_code != 0 or branch_result.timed_out
    status_failed = status_result.exit_code != 0 or status_result.timed_out
    entries, paths_truncated = await _status_entries(
        root,
        status_result.stdout,
        output_truncated=(
            status_result.stdout_truncated
            or status_failed
            or branch_failed
        ),
    )
    preservation_files, preservation_complete = (
        await _capture_preservation_baseline(
            root,
            head_commit=head_result.stdout.strip(),
            entries=entries,
        )
    )
    paths_truncated = paths_truncated or not preservation_complete
    if not paths_truncated and not await _repository_capture_is_current(
        root,
        branch=branch,
        head_commit=head_result.stdout.strip(),
        entries=entries,
        preservation_files=preservation_files,
    ):
        preservation_complete = False
        paths_truncated = True
    fingerprint_payload = {
        "branch": branch,
        "head_commit": head_result.stdout.strip(),
        "entries": entries,
        "preservation": [
            _preservation_proof_fingerprint(proof)
            for proof in preservation_files
        ],
        "status_truncated": paths_truncated,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RepositorySnapshot(
        root=str(root),
        branch=branch,
        head_commit=head_result.stdout.strip(),
        dirty=bool(entries) or paths_truncated,
        changed_files=tuple(sorted({item[1] for item in entries})),
        status_fingerprint=fingerprint,
        diff_summary=_redacted_text(diff_result.stdout.strip()),
        status_truncated=paths_truncated,
        _entries=tuple(entries),
        _preservation_files=preservation_files,
        _preservation_complete=preservation_complete,
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
        safe_path = _normalized_relative_path(raw_path)
        if safe_path is None:
            truncated = True
            continue
        if len(entries) >= MAX_STATUS_PATHS:
            truncated = True
            continue
        content_hash = await asyncio.to_thread(_bounded_file_hash, root, safe_path)
        entries.append((status_code, safe_path, content_hash))
    return entries, truncated


def _git_change_kind(status_code: str) -> str:
    """Translate an exact porcelain XY code without discarding that code."""

    normalized = str(status_code or "")
    if "U" in normalized or normalized in {"AA", "DD"}:
        return "conflicted"
    if "R" in normalized:
        return "renamed"
    if "C" in normalized:
        return "copied"
    if "D" in normalized:
        return "deleted"
    if "A" in normalized:
        return "added"
    if "?" in normalized:
        return "untracked"
    if "T" in normalized:
        return "type_changed"
    if "M" in normalized:
        return "modified"
    return "changed"


async def _repository_capture_is_current(
    root: Path,
    *,
    branch: str | None,
    head_commit: str,
    entries: Sequence[tuple[str, str, str | None]],
    preservation_files: Sequence[_BaselineFile],
) -> bool:
    """Confirm status and proof content did not change during capture."""

    current_branch, current_head, current_status = await asyncio.gather(
        _git(root, "rev-parse", "--abbrev-ref", "HEAD", limit=1_024),
        _git(root, "rev-parse", "HEAD", limit=1_024),
        _git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--no-renames",
            "--untracked-files=all",
            limit=MAX_STATUS_BYTES,
        ),
    )
    if (
        current_branch.exit_code != 0
        or current_branch.timed_out
        or (current_branch.stdout.strip() or None) != branch
        or current_head.exit_code != 0
        or current_head.timed_out
        or current_head.stdout.strip() != head_commit
        or current_status.exit_code != 0
        or current_status.timed_out
    ):
        return False
    observed_entries, observed_truncated = await _status_entries(
        root,
        current_status.stdout,
        output_truncated=current_status.stdout_truncated,
    )
    if observed_truncated or observed_entries != list(entries):
        return False
    proof_matches = await asyncio.gather(*(
        asyncio.to_thread(
            _baseline_file_unchanged,
            root,
            proof,
        )
        for proof in preservation_files
    ))
    return all(proof_matches)


async def _capture_preservation_baseline(
    root: Path,
    *,
    head_commit: str,
    entries: Sequence[tuple[str, str, str | None]],
) -> tuple[tuple[_BaselineFile, ...], bool]:
    proofs: list[_BaselineFile] = []
    total_bytes = 0
    complete = True
    for status_code, relative_path, _digest in entries:
        if "R" in status_code or "C" in status_code:
            complete = False
            continue
        if _is_sensitive_relative_path(relative_path):
            sensitive_path = root / relative_path
            digest_state = await asyncio.to_thread(
                _preservation_file_digest,
                sensitive_path,
            )
            if digest_state is None and await asyncio.to_thread(
                _preservation_path_is_missing,
                sensitive_path,
            ):
                if "D" not in status_code:
                    complete = False
                    continue
                proofs.append(_BaselineFile(
                    path=relative_path,
                    status=status_code,
                    base_content=None,
                    baseline_content=None,
                    baseline_mode=None,
                    exact_content_required=True,
                ))
                continue
            if digest_state is None:
                complete = False
                continue
            baseline_sha256, baseline_mode = digest_state
            proofs.append(_BaselineFile(
                path=relative_path,
                status=status_code,
                base_content=None,
                baseline_content=None,
                baseline_mode=baseline_mode,
                exact_content_required=True,
                baseline_sha256=baseline_sha256,
            ))
            continue
        baseline = await asyncio.to_thread(
            _read_preservation_file,
            root / relative_path,
        )
        if baseline is None:
            digest_state = await asyncio.to_thread(
                _preservation_file_digest,
                root / relative_path,
            )
            if digest_state is None:
                complete = False
                continue
            baseline_sha256, baseline_mode = digest_state
            proofs.append(_BaselineFile(
                path=relative_path,
                status=status_code,
                base_content=None,
                baseline_content=None,
                baseline_mode=baseline_mode,
                exact_content_required=True,
                baseline_sha256=baseline_sha256,
            ))
            continue
        baseline_content, baseline_mode, baseline_exact = baseline
        if baseline_content is None:
            if "D" not in status_code:
                complete = False
                continue
            proofs.append(_BaselineFile(
                path=relative_path,
                status=status_code,
                base_content=None,
                baseline_content=None,
                baseline_mode=baseline_mode,
                exact_content_required=True,
            ))
            continue
        base_size = await _git(
            root,
            "cat-file",
            "-s",
            f"{head_commit}:{relative_path}",
            limit=128,
        )
        if base_size.exit_code == 0:
            try:
                parsed_size = int(base_size.stdout.strip())
            except ValueError:
                parsed_size = MAX_PRESERVATION_FILE_BYTES + 1
            if parsed_size > MAX_PRESERVATION_FILE_BYTES:
                base_content = None
                baseline_exact = True
            else:
                base_content = await asyncio.to_thread(
                    _git_blob_bytes,
                    root,
                    f"{head_commit}:{relative_path}",
                )
                if base_content is None or len(base_content) != parsed_size:
                    base_content = None
                    baseline_exact = True
        else:
            base_content = None
        proof_bytes = len(base_content or b"") + len(baseline_content)
        baseline_sha256: str | None = None
        if total_bytes + proof_bytes > MAX_PRESERVATION_TOTAL_BYTES:
            digest_state = await asyncio.to_thread(
                _preservation_file_digest,
                root / relative_path,
            )
            if digest_state is None:
                complete = False
                continue
            baseline_sha256, baseline_mode = digest_state
            base_content = None
            baseline_content = None
            baseline_exact = True
        else:
            total_bytes += proof_bytes
        exact = bool(
            baseline_exact
            or b"\x00" in (base_content or b"")
            or b"\x00" in (baseline_content or b"")
        )
        proofs.append(_BaselineFile(
            path=relative_path,
            status=status_code,
            base_content=base_content,
            baseline_content=baseline_content,
            baseline_mode=baseline_mode,
            exact_content_required=exact,
            baseline_sha256=baseline_sha256,
        ))
    return tuple(proofs), complete and len(proofs) == len(entries)


def _preservation_proof_fingerprint(
    proof: _BaselineFile,
) -> tuple[str, str, str | None, int | None]:
    if proof.baseline_sha256 is not None:
        digest = proof.baseline_sha256
    elif proof.baseline_content is not None:
        digest = hashlib.sha256(
            b"retained-content\x00" + proof.baseline_content
        ).hexdigest()
    else:
        digest = None
    return proof.path, proof.status, digest, proof.baseline_mode


def _read_preservation_file(
    path: Path,
) -> tuple[bytes | None, int | None, bool] | None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return None, None, False
    except OSError:
        return None
    if stat.S_ISLNK(details.st_mode):
        target = os.readlink(path).encode("utf-8", errors="surrogateescape")
        return target, stat.S_IMODE(details.st_mode), True
    if not stat.S_ISREG(details.st_mode):
        return None
    if details.st_size > MAX_PRESERVATION_FILE_BYTES:
        return None
    try:
        return (
            path.read_bytes(),
            stat.S_IMODE(details.st_mode),
            False,
        )
    except OSError:
        return None


def _git_blob_bytes(root: Path, object_name: str) -> bytes | None:
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                f"safe.directory={root}",
                "-C",
                str(root),
                "show",
                object_name,
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _preservation_file_digest(path: Path) -> tuple[str, int] | None:
    """Hash a baseline file without retaining its potentially large content."""

    try:
        details = path.lstat()
        digest = hashlib.sha256()
        if stat.S_ISLNK(details.st_mode):
            digest.update(b"symlink\x00")
            digest.update(
                os.readlink(path).encode("utf-8", errors="surrogateescape")
            )
        elif stat.S_ISREG(details.st_mode):
            digest.update(b"file\x00")
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        else:
            return None
        return digest.hexdigest(), stat.S_IMODE(details.st_mode)
    except OSError:
        return None


def _preservation_path_is_missing(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


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
        (
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            *args,
        ),
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


def _contract_verification_commands(
    contract: ContinuationExecutionContract,
    repo_root: Path,
) -> list[_VerificationCommand]:
    results: list[_VerificationCommand] = []
    for specification in contract.verification:
        if not specification.required or not specification.command_argv:
            continue
        argv = _explicit_argv(specification.command_argv)
        cwd = _verification_cwd(
            repo_root,
            specification.cwd,
            specification.id,
        )
        results.append(
            _VerificationCommand(
                requirement_id=(
                    specification.requirement_ids[0]
                    if len(specification.requirement_ids) == 1
                    else None
                ),
                verifier_id=specification.id,
                requirement_ids=tuple(specification.requirement_ids),
                verifier_type=specification.verifier_type.value,
                command=shlex.join(_redacted_argv(argv)),
                argv=argv,
                cwd=cwd,
                timeout_seconds=specification.timeout_seconds,
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


async def _preservation_passed(
    contract: ContinuationExecutionContract,
    *,
    before: RepositorySnapshot,
    after: RepositorySnapshot,
) -> bool:
    """Prove original dirty changes survive while allowing additive work."""

    if (
        before.status_truncated
        or after.status_truncated
        or not before._preservation_complete
    ):
        return False
    if contract.repository.status_fingerprint != before.status_fingerprint:
        return False
    if before.branch != after.branch:
        return False

    if contract.authority.filesystem_mode.value == "read_only":
        unchanged = (
            before.head_commit == after.head_commit
            and before._entries == after._entries
        )
        if not unchanged:
            return False
        exact = await asyncio.gather(*(
            asyncio.to_thread(
                _baseline_file_unchanged,
                Path(before.root),
                proof,
            )
            for proof in before._preservation_files
        ))
        return all(exact)
    if before.head_commit != after.head_commit:
        return False
    preserved = await asyncio.gather(*(
        asyncio.to_thread(
            _baseline_file_preserved,
            Path(before.root),
            proof,
        )
        for proof in before._preservation_files
    ))
    return all(preserved)


def _baseline_file_unchanged(root: Path, proof: _BaselineFile) -> bool:
    if proof.baseline_sha256 is not None:
        final_digest = _preservation_file_digest(root / proof.path)
        return final_digest == (
            proof.baseline_sha256,
            proof.baseline_mode,
        )
    final = _read_preservation_file(root / proof.path)
    if final is None:
        return False
    final_content, final_mode, _final_exact = final
    return (
        final_content == proof.baseline_content
        and final_mode == proof.baseline_mode
    )


def _baseline_file_preserved(root: Path, proof: _BaselineFile) -> bool:
    if proof.baseline_sha256 is not None:
        final_digest = _preservation_file_digest(root / proof.path)
        return final_digest == (
            proof.baseline_sha256,
            proof.baseline_mode,
        )
    final = _read_preservation_file(root / proof.path)
    if final is None:
        return False
    final_content, final_mode, final_exact = final
    if proof.baseline_content is None:
        return final_content is None
    if final_content is None or final_mode != proof.baseline_mode:
        return False
    if (
        proof.exact_content_required
        or final_exact
        or b"\x00" in final_content
    ):
        return final_content == proof.baseline_content
    if final_content == proof.baseline_content:
        return True
    if proof.base_content is None:
        return _line_subsequence(proof.baseline_content, final_content)
    return _text_baseline_delta_preserved(
        proof.base_content,
        proof.baseline_content,
        final_content,
    )


def _line_subsequence(baseline: bytes, final: bytes) -> bool:
    required = baseline.splitlines(keepends=True)
    if not required:
        return True
    observed = iter(final.splitlines(keepends=True))
    return all(any(line == candidate for candidate in observed) for line in required)


def _text_baseline_delta_preserved(
    base: bytes,
    baseline: bytes,
    final: bytes,
) -> bool:
    """Require every original text hunk while allowing additive final lines.

    Inserted/replacement lines must remain in order between their nearest
    unchanged anchors. Lines deliberately removed by the user must stay absent.
    This is conservative: ambiguous duplicate-line or overlapping rewrites fail
    rather than claiming preservation without proof.
    """

    base_lines = base.splitlines(keepends=True)
    baseline_lines = baseline.splitlines(keepends=True)
    final_lines = final.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(
        None,
        base_lines,
        baseline_lines,
        autojunk=False,
    )
    for tag, base_start, base_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = base_lines[base_start:base_end]
        required = baseline_lines[new_start:new_end]
        left_anchor = (
            base_lines[base_start - 1]
            if base_start > 0
            else None
        )
        right_anchor = (
            base_lines[base_end]
            if base_end < len(base_lines)
            else None
        )
        if required and not _anchored_subsequence(
            final_lines,
            required=required,
            left_anchor=left_anchor,
            right_anchor=right_anchor,
        ):
            return False
        for removed_line in removed:
            if removed_line not in required and removed_line in final_lines:
                return False
    return True


def _anchored_subsequence(
    final_lines: Sequence[bytes],
    *,
    required: Sequence[bytes],
    left_anchor: bytes | None,
    right_anchor: bytes | None,
) -> bool:
    starts = (
        [
            index
            for index, line in enumerate(final_lines)
            if line == left_anchor
        ]
        if left_anchor is not None
        else [-1]
    )
    for start in starts:
        cursor = start + 1
        for required_line in required:
            while (
                cursor < len(final_lines)
                and final_lines[cursor] != required_line
            ):
                cursor += 1
            if cursor >= len(final_lines):
                break
            cursor += 1
        else:
            if right_anchor is None or right_anchor in final_lines[cursor:]:
                return True
    return False


def _worker_status(child_result: CommandResult) -> str:
    if (
        child_result.exit_code != 0
        or _command_has_structured_terminal_error(child_result)
    ):
        return "failed"
    return "completed"


def _terminal_status(
    child_result: CommandResult,
    verification_results: Sequence[VerificationResult],
) -> str:
    if (
        child_result.exit_code != 0
        or _command_has_structured_terminal_error(child_result)
    ):
        return "failed"
    if any(item.result.exit_code != 0 for item in verification_results):
        return "failed"
    return "completed"


def _structured_terminal_error(output: str) -> bool:
    """Detect provider streams that report failure while exiting with code zero."""

    for raw_line in reversed(output.splitlines()[-200:]):
        terminal_state = _structured_terminal_state_from_line(raw_line)
        if terminal_state is not None:
            return terminal_state
    return False


def _structured_terminal_state_from_line(
    raw_line: str | bytes,
) -> bool | None:
    line = (
        raw_line.decode("utf-8", errors="replace")
        if isinstance(raw_line, bytes)
        else raw_line
    ).strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    payload_type = str(payload.get("type") or "").casefold()
    subtype = str(payload.get("subtype") or "").casefold()
    is_error = (
        payload.get("is_error") is True
        or payload_type in {"error", "error_message"}
        or subtype.startswith("error")
        or bool(payload.get("error"))
    )
    if is_error:
        return True
    if payload_type == "step_finish":
        part = payload.get("part")
        reason = str(
            payload.get("reason")
            or (part.get("reason") if isinstance(part, Mapping) else "")
            or ""
        ).casefold()
        if reason in {"tool-calls", "tool_calls"}:
            # OpenCode can exit zero after a tool call without ever returning
            # for a final assistant turn. That is an incomplete provider run.
            return True
    if (
        payload_type in {"result", "step_finish", "turn.completed"}
        or subtype in {"success", "completed"}
    ):
        return False
    return None


def _command_has_structured_terminal_error(result: CommandResult) -> bool:
    if result.structured_terminal_error is not None:
        return result.structured_terminal_error
    return _structured_terminal_error(result.stdout)


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


def _captured_output_text(
    capture: _BoundedStreamCapture,
    limit_bytes: int,
) -> str:
    if not capture.truncated:
        return _bounded_redacted_text(
            capture.head + capture.tail,
            limit_bytes,
        )

    marker = f"\n{TRUNCATED_OUTPUT}\n".encode("utf-8")
    if len(marker) >= limit_bytes:
        return _truncated_output_marker(limit_bytes)

    head = _redacted_text(capture.head.decode("utf-8", errors="replace")).encode("utf-8")
    tail_bytes = capture.tail
    if not capture.tail_starts_at_line_boundary:
        # A rolling tail can start inside a secret value, without the key that
        # lets the redactor recognize it. Drop that partial line and retain
        # only complete diagnostic/provider-event lines.
        _partial, newline, complete_lines = tail_bytes.partition(b"\n")
        tail_bytes = complete_lines if newline else b""
    tail = _redacted_text(tail_bytes.decode("utf-8", errors="replace")).encode("utf-8")
    content_budget = limit_bytes - len(marker)
    head_budget = min(len(head), content_budget // 2)
    tail_budget = min(len(tail), content_budget - head_budget)

    # Spend any budget unused by a short window on the other window. Keeping
    # the tail intact when possible preserves terminal JSON provider events.
    remaining = content_budget - head_budget - tail_budget
    if remaining:
        extra_tail = min(len(tail) - tail_budget, remaining)
        tail_budget += extra_tail
        remaining -= extra_tail
    if remaining:
        head_budget += min(len(head) - head_budget, remaining)

    head_text = head[:head_budget].decode("utf-8", errors="ignore")
    tail_text = tail[-tail_budget:].decode("utf-8", errors="ignore") if tail_budget else ""
    rendered = f"{head_text}\n{TRUNCATED_OUTPUT}\n{tail_text}"
    assert len(rendered.encode("utf-8")) <= limit_bytes
    return rendered


def _truncated_output_marker(limit_bytes: int) -> str:
    return TRUNCATED_OUTPUT.encode("utf-8")[:limit_bytes].decode(
        "utf-8", errors="ignore"
    )


def _safe_relative_path(value: str) -> str | None:
    normalized = _normalized_relative_path(value)
    if normalized is None or _is_sensitive_relative_path(normalized):
        return None
    return normalized


def _normalized_relative_path(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None
    return normalized


def _is_sensitive_relative_path(value: str) -> bool:
    normalized = str(value or "").replace("\\", "/").removeprefix("./")
    if not normalized:
        return True
    path = PurePosixPath(normalized)
    lowered = [part.lower() for part in path.parts]
    basename = lowered[-1]
    stem = PurePosixPath(basename).stem
    return bool(
        any(part in {".aws", ".ssh", ".gnupg"} for part in lowered)
        or basename in {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}
        or basename.startswith(".env")
        or stem in {"credential", "credentials", "private_key", "secret", "secrets"}
        or PurePosixPath(basename).suffix in {".key", ".pem", ".p12", ".pfx"}
        or redact_sensitive_text(normalized) != normalized
    )


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1_000))
