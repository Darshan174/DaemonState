from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CheckpointVerification, WorkCheckpoint
from app.services.checkpoints import CHECKPOINT_CATEGORIES, checkpoint_to_dict, get_checkpoint
from app.services.local_harness import capture_repository_snapshot, run_repository_command
from app.time import utc_now


VERIFIER_POLICY_VERSION = "checkpoint_verifier.v1"
MAX_REPLAY_COMMANDS = 8
_SHELL_CONTROL_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "<<"}


async def compare_checkpoint_repository(checkpoint: WorkCheckpoint) -> dict[str, Any]:
    """Compare one saved checkpoint with the current repository without mutating state."""

    base = {
        "checkpoint_id": str(checkpoint.id),
        "checked_at": utc_now(),
        "captured": {
            "branch": checkpoint.branch,
            "head_commit": checkpoint.head_commit,
            "status_fingerprint": checkpoint.worktree_fingerprint,
        },
    }
    if not checkpoint.repo_root or not checkpoint.worktree_fingerprint:
        return {
            **base,
            "status": "unavailable",
            "reason": "This saved version is not linked to a repository snapshot.",
            "current": None,
        }

    try:
        current = await capture_repository_snapshot(checkpoint.repo_root)
    except (OSError, ValueError) as exc:
        return {
            **base,
            "status": "unavailable",
            "reason": str(exc),
            "current": None,
        }

    matches = current.status_fingerprint == checkpoint.worktree_fingerprint
    return {
        **base,
        "status": "matched" if matches else "changed",
        "reason": (
            "The current repository matches this saved version."
            if matches
            else "The current repository differs from this saved version."
        ),
        "current": current.to_dict(),
    }


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
    data = checkpoint_to_dict(checkpoint)
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
    checks.append({
        "name": "checkpoint_structure",
        "status": "passed" if not structural_errors else "failed",
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
            seen: set[tuple[str, str]] = set()
            for item in evidence_results:
                payload = item.get("payload", {})
                command = str(payload.get("command") or "").strip()
                cwd = str(payload.get("cwd") or checkpoint.repo_root)
                key = (cwd, command)
                if not command or key in seen:
                    continue
                seen.add(key)
                if len(replay_results) + len(replay_rejections) >= MAX_REPLAY_COMMANDS:
                    break
                try:
                    argv = _safe_replay_argv(command)
                    result = await run_repository_command(
                        checkpoint.repo_root,
                        argv,
                        cwd=cwd,
                    )
                except (OSError, ValueError, TypeError) as exc:
                    replay_rejections.append({"command": command, "reason": str(exc)})
                    continue
                replay_results.append({
                    "command": command,
                    "cwd": cwd,
                    "result": result.to_dict(),
                    "passed": result.exit_code == 0 and not result.timed_out,
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
    hard_failure = bool(structural_errors or missing_files or replay_failed)
    verification_evidence = replay_passed if execute_commands else bool(observed_passes)
    verification_failure = bool(observed_failures) and not replay_passed
    if hard_failure or verification_failure:
        status = "failed"
    elif stale:
        status = "stale"
    elif (
        not snapshot_error
        and not has_blockers
        and verification_evidence
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


def _safe_replay_argv(command: str) -> tuple[str, ...]:
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
    return argv


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
