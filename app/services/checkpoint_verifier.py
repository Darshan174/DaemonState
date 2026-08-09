from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CheckpointVerification, WorkCheckpoint
from app.services.checkpoints import CHECKPOINT_CATEGORIES, checkpoint_to_dict, get_checkpoint
from app.services.local_harness import capture_repository_snapshot
from app.telemetry import traced
from app.time import utc_now


VERIFIER_POLICY_VERSION = "checkpoint_verifier.v5"
MAX_REPLAY_COMMANDS = 8
_SHELL_CONTROL_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "<<"}
AUTOMATIC_REPLAY_DISABLED_REASON = (
    "automatic replay is disabled because imported session commands are "
    "untrusted evidence; run an explicitly reviewed command instead"
)


def _checkpoint_verification_trace_result(
    verification: CheckpointVerification,
) -> dict[str, Any]:
    try:
        payload = json.loads(verification.results_json)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    checks = payload.get("checks") if isinstance(payload, dict) else None
    checks = checks if isinstance(checks, list) else []
    statuses = [
        str(item.get("status") or "")
        for item in checks
        if isinstance(item, dict)
    ]
    passed = sum(status == "passed" for status in statuses)
    failed = sum(status == "failed" for status in statuses)
    return {
        "daemonstate.checkpoint.id": verification.checkpoint_id,
        "daemonstate.checkpoint.fingerprint": (
            verification.worktree_fingerprint
        ),
        "daemonstate.status": verification.status,
        "daemonstate.verification.total": len(statuses),
        "daemonstate.verification.passed": passed,
        "daemonstate.verification.failed": failed,
        "daemonstate.verification.unproven": len(statuses) - passed - failed,
    }


async def compare_checkpoint_repository(
    checkpoint: WorkCheckpoint,
    *,
    fallback_repo_paths: Iterable[str] = (),
    selected_repo_path: str | None = None,
    recorded_session_path: str | None = None,
) -> dict[str, Any]:
    """Resolve and compare repository evidence without making Git mandatory.

    The checkpoint-bound repository remains authoritative when it is readable.
    If its recorded directory is not a Git repository, a single currently
    readable workspace repository is a deterministic fallback. Multiple
    readable workspace repositories require an explicit selection; no Git
    repository is reported as unavailable evidence rather than fabricated
    state.
    """

    base = {
        "checkpoint_id": str(checkpoint.id),
        "checked_at": utc_now(),
        "captured": {
            "branch": checkpoint.branch,
            "head_commit": checkpoint.head_commit,
            "status_fingerprint": checkpoint.worktree_fingerprint,
        },
    }
    recorded_root = _normalized_repository_path(
        checkpoint.repo_root or recorded_session_path
    )
    selected_root = _normalized_repository_path(selected_repo_path)
    workspace_candidates = tuple(dict.fromkeys(
        normalized
        for raw in fallback_repo_paths
        if (normalized := _normalized_repository_path(raw)) is not None
    ))
    if selected_root is not None:
        candidate_paths = (selected_root,)
        resolution_source = "explicit_workspace_selection"
    else:
        candidate_paths = tuple(
            path for path in workspace_candidates if path != recorded_root
        )
        resolution_source = "workspace_fallback"

    recorded_error: str | None = None
    if selected_root is None and recorded_root is not None:
        try:
            current = await capture_repository_snapshot(recorded_root)
        except (OSError, ValueError) as exc:
            recorded_error = str(exc)
        else:
            return _repository_comparison_result(
                base,
                checkpoint=checkpoint,
                current=current,
                resolution_source="checkpoint",
                recorded_root=recorded_root,
                candidates=workspace_candidates,
            )

    readable: list[tuple[str, Any]] = []
    errors: list[str] = []
    for path in candidate_paths:
        try:
            readable.append((path, await capture_repository_snapshot(path)))
        except (OSError, ValueError) as exc:
            errors.append(str(exc))

    if len(readable) > 1:
        candidates = [path for path, _snapshot in readable]
        return {
            **base,
            "status": "ambiguous",
            "reason": (
                "Multiple verified workspace repositories are available. "
                "Choose the repository for this session before continuing."
            ),
            "current": None,
            "resolution": {
                "status": "selection_required",
                "source": "workspace",
                "recorded_session_directory": recorded_root,
                "selected_repository": None,
                "candidate_repositories": candidates,
            },
        }
    if len(readable) == 1:
        resolved_path, current = readable[0]
        return _repository_comparison_result(
            base,
            checkpoint=checkpoint,
            current=current,
            resolution_source=resolution_source,
            recorded_root=recorded_root,
            candidates=workspace_candidates,
            resolved_path=resolved_path,
        )

    reason = (
        "Repository snapshot unavailable: recorded session directory is not a Git repository."
        if recorded_root or candidate_paths
        else "Repository snapshot unavailable: this workspace has no verified Git repository."
    )
    return {
        **base,
        "status": "unavailable",
        "reason": reason,
        "current": None,
        "resolution": {
            "status": "unavailable",
            "source": "none",
            "recorded_session_directory": recorded_root,
            "selected_repository": selected_root,
            "candidate_repositories": list(workspace_candidates),
            "diagnostic": recorded_error or (errors[0] if errors else None),
        },
    }


def _repository_comparison_result(
    base: dict[str, Any],
    *,
    checkpoint: WorkCheckpoint,
    current: Any,
    resolution_source: str,
    recorded_root: str | None,
    candidates: Iterable[str],
    resolved_path: str | None = None,
) -> dict[str, Any]:
    current_root = _normalized_repository_path(
        resolved_path or getattr(current, "root", None)
    )
    comparable_to_checkpoint = bool(
        checkpoint.worktree_fingerprint
        and recorded_root
        and current_root == recorded_root
    )
    matches = bool(
        comparable_to_checkpoint
        and current.status_fingerprint == checkpoint.worktree_fingerprint
    )
    status = (
        "matched" if matches else "changed" if comparable_to_checkpoint else "resolved"
    )
    return {
        **base,
        "status": status,
        "reason": (
            "The current repository matches this saved version."
            if matches
            else "The current repository differs from this saved version."
            if comparable_to_checkpoint
            else "Using the workspace's verified repository because the recorded session directory has no usable Git snapshot."
        ),
        "current": current.to_dict(),
        "resolution": {
            "status": "resolved",
            "source": resolution_source,
            "recorded_session_directory": recorded_root,
            "selected_repository": current_root,
            "candidate_repositories": list(candidates),
        },
    }


def _normalized_repository_path(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return str(Path(raw).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(Path(raw).expanduser())


@traced(
    "daemonstate.checkpoint.verify",
    attributes=lambda _args, kwargs: {
        "daemonstate.phase": "checkpoint_verify",
        "daemonstate.checkpoint.id": kwargs.get("checkpoint_id"),
        "daemonstate.verification.enabled": kwargs.get(
            "execute_commands",
            False,
        ),
    },
    result_attributes=lambda result: _checkpoint_verification_trace_result(
        result
    ),
)
async def verify_checkpoint(
    session: AsyncSession,
    *,
    checkpoint_id: UUID,
    execute_commands: bool = False,
) -> CheckpointVerification:
    """Verify structure, evidence, repository freshness, files, and observed tests."""

    checkpoint = await get_checkpoint(session, checkpoint_id)
    if checkpoint is None:
        raise ValueError("Checkpoint not found")
    data = checkpoint_to_dict(
        checkpoint,
        filter_presentation_noise=True,
    )
    current_snapshot = None
    snapshot_error = None
    if checkpoint.repo_root:
        try:
            current_snapshot = await capture_repository_snapshot(checkpoint.repo_root)
        except (OSError, ValueError) as exc:
            snapshot_error = str(exc)

    fingerprint = current_snapshot.status_fingerprint if current_snapshot else None
    mode = "execute" if execute_commands else "evidence"
    idempotency_key = _sha256(
        f"{checkpoint.id}:{VERIFIER_POLICY_VERSION}:{mode}:{fingerprint or 'no-repo'}"
    )
    existing = await session.scalar(
        select(CheckpointVerification).where(
            CheckpointVerification.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing

    checks: list[dict[str, Any]] = []
    structural_errors = _structural_errors(data)
    integrity_errors = [
        error
        for error in structural_errors
        if error not in {
            "checkpoint must contain exactly one goal",
            "checkpoint must contain exactly one exact next action",
        }
    ]
    checks.append({
        "name": "checkpoint_structure",
        "status": (
            "passed"
            if not structural_errors
            else "failed"
            if integrity_errors
            else "partial"
        ),
        "details": structural_errors,
    })

    stale = bool(
        checkpoint.worktree_fingerprint
        and fingerprint
        and checkpoint.worktree_fingerprint != fingerprint
    )
    if snapshot_error:
        repo_status = "failed"
    elif not checkpoint.repo_root:
        repo_status = "not_available"
    elif stale:
        repo_status = "stale"
    else:
        repo_status = "passed"
    checks.append({
        "name": "repository_freshness",
        "status": repo_status,
        "captured_fingerprint": checkpoint.worktree_fingerprint,
        "current_fingerprint": fingerprint,
        "error": snapshot_error,
    })

    missing_files: list[str] = []
    unchecked_files: list[str] = []
    for item in data["sections"]["relevant_files"]:
        item_payload = item.get("payload", {})
        raw_path = str(item_payload.get("path") or item["statement"])
        expected_to_exist = item_payload.get("exists_at_capture") is not False
        if not checkpoint.repo_root:
            unchecked_files.append(raw_path)
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = Path(checkpoint.repo_root) / candidate
        try:
            root = Path(checkpoint.repo_root).resolve()
            resolved = candidate.resolve()
            exists = (resolved == root or root in resolved.parents) and resolved.exists()
        except OSError:
            exists = False
        if expected_to_exist and not exists:
            missing_files.append(raw_path)
    checks.append({
        "name": "relevant_files",
        "status": "failed" if missing_files else "not_available" if unchecked_files else "passed",
        "missing": missing_files,
        "unchecked": unchecked_files,
    })

    evidence_results = data["sections"]["verification"]
    observed_passes = [
        item for item in evidence_results if item.get("payload", {}).get("passed") is True
    ]
    observed_failures = [
        item for item in evidence_results if item.get("payload", {}).get("passed") is False
    ]
    checks.append({
        "name": "observed_verification",
        "status": (
            "failed" if observed_failures else "passed" if observed_passes else "not_available"
        ),
        "passing_commands": len(observed_passes),
        "failing_commands": len(observed_failures),
    })

    replay_results: list[dict[str, Any]] = []
    replay_rejections: list[dict[str, str]] = []
    if execute_commands:
        if not checkpoint.repo_root:
            replay_rejections.append({
                "command": "",
                "reason": "checkpoint has no repository root",
            })
        else:
            for item in evidence_results:
                payload = item.get("payload", {})
                command = str(payload.get("command") or "").strip()
                if not command:
                    continue
                if len(replay_rejections) >= MAX_REPLAY_COMMANDS:
                    break
                replay_rejections.append({
                    "command": command,
                    "reason": AUTOMATIC_REPLAY_DISABLED_REASON,
                })
    replay_failed = any(not item["passed"] for item in replay_results)
    replay_passed = bool(replay_results) and not replay_failed
    if execute_commands:
        checks.append({
            "name": "fresh_command_execution",
            "status": (
                "failed"
                if replay_failed
                else "passed"
                if replay_passed and not replay_rejections
                else "partial"
                if replay_passed
                else "not_available"
            ),
            "executed": len(replay_results),
            "rejected": replay_rejections,
        })

    has_blockers = bool(data["sections"]["blockers"])
    integrity_failure = bool(integrity_errors)
    repository_drift = bool(stale or missing_files)
    fresh_execution_failure = bool(execute_commands and replay_failed)
    verification_evidence = replay_passed if execute_commands else bool(observed_passes)
    if integrity_failure or fresh_execution_failure:
        status = "failed"
    elif repository_drift:
        status = "stale"
    elif (
        not snapshot_error
        and not has_blockers
        and verification_evidence
        and not observed_failures
        and current_snapshot is not None
        and fingerprint == checkpoint.worktree_fingerprint
    ):
        status = "verified"
    else:
        status = "partial"

    results = {
        "policy_version": VERIFIER_POLICY_VERSION,
        "mode": mode,
        "status": status,
        "checks": checks,
        "has_blockers": has_blockers,
        "integrity_errors": integrity_errors,
        "historical_verification_failures": len(observed_failures),
        "replay_results": replay_results,
        "replay_rejections": replay_rejections,
        "repository": current_snapshot.to_dict() if current_snapshot else None,
    }
    verification = CheckpointVerification(
        checkpoint_id=checkpoint.id,
        status=status,
        worktree_fingerprint=fingerprint,
        policy_version=VERIFIER_POLICY_VERSION,
        results_json=json.dumps(results, sort_keys=True, separators=(",", ":")),
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(verification)
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(
            select(CheckpointVerification).where(
                CheckpointVerification.idempotency_key == idempotency_key
            )
        )
        if winner is None:
            raise
        return winner
    return verification


def _structural_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sections = data.get("sections")
    if not isinstance(sections, dict):
        return ["sections object is missing"]
    for category in CHECKPOINT_CATEGORIES:
        if category not in sections or not isinstance(sections[category], list):
            errors.append(f"section {category} is missing")
            continue
        for item in sections[category]:
            if not str(item.get("statement") or "").strip():
                errors.append(f"{category} contains an empty statement")
            if not item.get("evidence"):
                errors.append(f"{category} item has no evidence")
    if len(sections.get("goal", [])) != 1:
        errors.append("checkpoint must contain exactly one goal")
    if len(sections.get("exact_next_action", [])) != 1:
        errors.append("checkpoint must contain exactly one exact next action")
    return errors


def _safe_replay_commands(
    command: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if "\x00" in command:
        raise ValueError("commands containing NUL bytes are not replayed")
    lines = tuple(line.strip() for line in command.splitlines() if line.strip())
    if not lines:
        raise ValueError("command is empty")
    return tuple((line, _safe_replay_argv(line)) for line in lines)


def _safe_replay_argv(command: str) -> tuple[str, ...]:
    if any(separator in command for separator in ("\n", "\r", "\x00")):
        raise ValueError("command separators must be replayed as independent commands")
    try:
        argv = tuple(shlex.split(command))
    except ValueError as exc:
        raise ValueError(f"command cannot be parsed safely: {exc}") from exc
    if not argv:
        raise ValueError("command is empty")
    if any(token in _SHELL_CONTROL_TOKENS for token in argv):
        raise ValueError("shell operators are not replayed; run a direct test command")
    if argv[0] in {"bash", "sh", "zsh", "fish", "powershell", "pwsh"}:
        raise ValueError("shell-wrapped commands are not replayed")
    if not _is_allowlisted_verification_argv(argv):
        raise ValueError("command is not an allowlisted verification command")
    return argv


def _is_allowlisted_verification_argv(argv: tuple[str, ...]) -> bool:
    executable = argv[0]
    if "/" in executable or "\\" in executable or len(argv) < 2:
        return False
    if executable == "pytest":
        return True
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        return len(argv) >= 3 and argv[1:3] == ("-m", "pytest")
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        if argv[1] == "test":
            return True
        return (
            len(argv) >= 3
            and argv[1] == "run"
            and argv[2] in {"build", "check", "lint", "test", "typecheck"}
        )
    if executable == "cargo":
        return argv[1] in {"check", "clippy", "test"}
    if executable == "go":
        return argv[1] in {"test", "vet"}
    if executable == "dotnet":
        return argv[1] == "test"
    return False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
