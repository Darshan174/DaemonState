"""Load snapshot-bound verification evidence for Workspace Foundation.

This module is deliberately read-only.  It never executes a repository command
and it promotes only the individual verification observations attached to a
local-harness outcome whose complete repository-after snapshot exactly matches
the supplied :class:`~app.services.repo_indexer.RepoFrame`.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, RunObservation
from app.services.repo_indexer import RepoFrame


MAX_WORKSPACE_VERIFICATION_OBSERVATIONS = 32
MAX_WORKSPACE_VERIFICATION_SCAN = 256
MAX_WORKSPACE_VERIFICATION_OUTCOMES = 32
MAX_WORKSPACE_VERIFICATION_CHANGED_ENTRIES = 500
MAX_WORKSPACE_VERIFICATION_PAYLOAD_BYTES = 2_500_000
MAX_WORKSPACE_VERIFICATION_COMMAND_CHARS = 4_000
MAX_WORKSPACE_VERIFICATION_CWD_CHARS = 4_096
MAX_WORKSPACE_VERIFICATION_HASH_BRIDGE_BYTES = 1_048_576
WORKSPACE_VERIFICATION_EVIDENCE_RULE = "local_harness_verification_observation.v1"


@dataclass(frozen=True, slots=True)
class WorkspaceVerificationObservation:
    """One executed check bound to an exact current repository snapshot."""

    command: str
    cwd: str
    exit_code: int
    observed_at: datetime
    timed_out: bool
    payload_sha256: str
    output_sha256: str
    evidence_rule: str
    evidence_id: str
    agent_run_id: str
    run_observation_id: str
    outcome_observation_id: str


@dataclass(frozen=True, slots=True)
class _MatchedOutcome:
    run: AgentRun
    observation: RunObservation
    observed_at: datetime
    verification_keys: frozenset[tuple[str, str, str, int, bool]]


async def load_workspace_verification_observations(
    session: AsyncSession | None,
    workspace_id: UUID | None,
    frame: RepoFrame,
) -> tuple[WorkspaceVerificationObservation, ...]:
    """Return bounded verification observations for an exact repository state.

    Only ``AgentRun`` and ``RunObservation`` rows are read.  Stale, truncated,
    internally inconsistent, or malformed local-harness outcomes are ignored.
    The function does not execute commands or read verification output sources.
    """

    if session is None or workspace_id is None:
        return ()

    outcomes = await _matching_outcomes(session, workspace_id, frame)
    if not outcomes:
        return ()

    outcomes_by_run_id = {outcome.run.id: outcome for outcome in outcomes}

    rows = list(
        await session.scalars(
            select(RunObservation)
            .where(
                RunObservation.agent_run_id.in_(tuple(outcomes_by_run_id)),
                RunObservation.event_type == "verification",
                RunObservation.event_key.like("harness:verification:%"),
            )
            .order_by(
                RunObservation.observed_at.desc(),
                RunObservation.created_at.desc(),
                RunObservation.id.desc(),
            )
            .limit(MAX_WORKSPACE_VERIFICATION_SCAN + 1)
        )
    )
    if len(rows) > MAX_WORKSPACE_VERIFICATION_SCAN:
        return ()

    root = _normalized_repo_root(frame.repo_path)
    if root is None:
        return ()

    observations: list[WorkspaceVerificationObservation] = []
    seen: set[tuple[str, str, int, bool, str]] = set()
    for row in rows:
        outcome = outcomes_by_run_id.get(row.agent_run_id)
        if outcome is None:
            continue
        parsed = _verification_observation(
            row,
            root=root,
            outcome_observation_id=str(outcome.observation.id),
        )
        if parsed is None or parsed.observed_at > outcome.observed_at:
            continue
        outcome_key = (
            str(row.event_key or ""),
            parsed.command,
            parsed.cwd,
            parsed.exit_code,
            parsed.timed_out,
        )
        if outcome_key not in outcome.verification_keys:
            continue
        dedupe_key = (*outcome_key[1:], parsed.output_sha256)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        observations.append(parsed)
        if len(observations) > MAX_WORKSPACE_VERIFICATION_OBSERVATIONS:
            return ()
    return tuple(observations)


async def _matching_outcomes(
    session: AsyncSession,
    workspace_id: UUID,
    frame: RepoFrame,
) -> tuple[_MatchedOutcome, ...]:
    rows = list(
        (
            await session.execute(
                select(RunObservation, AgentRun)
                .join(AgentRun, AgentRun.id == RunObservation.agent_run_id)
                .where(
                    AgentRun.workspace_id == workspace_id,
                    RunObservation.event_type == "outcome",
                    RunObservation.event_key == "harness:outcome",
                )
                .order_by(
                    RunObservation.observed_at.desc(),
                    RunObservation.created_at.desc(),
                    RunObservation.id.desc(),
                )
                .limit(MAX_WORKSPACE_VERIFICATION_OUTCOMES + 1)
            )
        ).all()
    )
    if len(rows) > MAX_WORKSPACE_VERIFICATION_OUTCOMES:
        return ()
    matches: list[_MatchedOutcome] = []
    for observation, run in rows:
        payload = _json_object(observation.payload_json)
        if payload is None or not _local_harness_outcome(payload, observation, run):
            continue
        repository_after = payload.get("repository_after")
        if not isinstance(repository_after, Mapping):
            continue
        if not _repository_after_matches_frame(repository_after, frame):
            continue
        root = _normalized_repo_root(frame.repo_path)
        if root is None:
            return ()
        verification_keys = _outcome_verification_keys(payload, root=root)
        # A later harness run with no checks does not invalidate an earlier
        # check against the exact same immutable repository state. Skip empty
        # outcomes instead of allowing them to eclipse useful persisted proof.
        if not verification_keys:
            continue
        observed_at = _utc_datetime(observation.observed_at or observation.created_at)
        if observed_at is None:
            continue
        matches.append(
            _MatchedOutcome(
                run=run,
                observation=observation,
                observed_at=observed_at,
                verification_keys=verification_keys,
            )
        )
    return tuple(matches)


def _local_harness_outcome(
    payload: Mapping[str, Any],
    observation: RunObservation,
    run: AgentRun,
) -> bool:
    repository_after = payload.get("repository_after")
    repository_before = payload.get("repository_before")
    if not isinstance(repository_after, Mapping) or not isinstance(
        repository_before,
        Mapping,
    ):
        return False
    status = _bounded_text(payload.get("status"), 80)
    top_level_head = _normalized_head(payload.get("head_commit"))
    repository_after_head = _normalized_head(repository_after.get("head_commit"))
    run_head = _normalized_head(run.head_commit)
    return bool(
        observation.event_key == "harness:outcome"
        and observation.command is None
        and observation.exit_code is None
        # The CLI uses the exact ``local-harness`` label; desktop continuation
        # runs use a namespaced daemonstate provider label. Neither label alone
        # is provenance: the production-only outcome shape below is required too.
        and (run.tool == "local-harness" or str(run.tool or "").startswith("daemonstate:"))
        and run.status in {"completed", "failed"}
        and payload.get("schema_version") == "run_observation.v1"
        and payload.get("event_type") == "outcome"
        and _present_text(payload.get("content"))
        and isinstance(payload.get("files"), list)
        and payload.get("command") is None
        and payload.get("exit_code") is None
        and status in {"completed", "failed"}
        and status == run.status
        and isinstance(payload.get("runtime_bundle_integrity_passed"), bool)
        and isinstance(payload.get("preservation_passed"), bool)
        and isinstance(payload.get("completed_context_item_ids"), list)
        and isinstance(payload.get("addresses_context_item_ids"), list)
        and top_level_head is not None
        and top_level_head == repository_after_head
        and run_head == repository_after_head
    )


def _repository_after_matches_frame(
    repository_after: Mapping[str, Any],
    frame: RepoFrame,
) -> bool:
    if repository_after.get("status_truncated") is not False:
        return False
    root = _normalized_repo_root(repository_after.get("root"))
    frame_root = _normalized_repo_root(frame.repo_path)
    if root is None or frame_root is None or root != frame_root:
        return False
    if not _valid_branch(repository_after.get("branch")) or not _valid_branch(frame.branch):
        return False
    if _normalized_branch(repository_after.get("branch")) != _normalized_branch(frame.branch):
        return False
    observed_head = _normalized_head(repository_after.get("head_commit"))
    frame_head = _normalized_head(frame.head_commit)
    if observed_head is None or frame_head is None or observed_head != frame_head:
        return False
    dirty = repository_after.get("dirty")
    if not isinstance(dirty, bool) or dirty != bool(frame.dirty):
        return False

    observed_entries = _repository_entries(repository_after.get("changed_file_entries"))
    frame_entries = _repository_entries(frame.changed_files)
    if observed_entries is None or frame_entries is None:
        return False
    if observed_entries != frame_entries and not _entry_digests_match_current_files(
        observed_entries,
        frame_entries,
        frame_root,
    ):
        return False
    if dirty != bool(observed_entries):
        return False

    changed_paths = _changed_paths(repository_after.get("changed_files"))
    if changed_paths is None:
        return False
    return changed_paths == tuple(sorted(entry[1] for entry in observed_entries))


def _entry_digests_match_current_files(
    observed: tuple[tuple[str, str, str | None], ...],
    frame: tuple[tuple[str, str, str | None], ...],
    root: str,
) -> bool:
    """Bridge the two current producers without weakening byte identity.

    ``RepoIndexer`` records a raw file SHA-256, while the local harness records
    a size-prefixed, bounded preservation hash. When those digests differ, this
    function accepts only small regular files whose bytes still reproduce both
    hashes. Status, path, branch, HEAD, dirty state, and completeness are checked
    separately before this function is called. Large files and symlinks fail
    closed rather than receiving a partial-content equivalence claim.
    """

    if len(observed) != len(frame):
        return False
    for observed_entry, frame_entry in zip(observed, frame, strict=True):
        observed_status, observed_path, observed_digest = observed_entry
        frame_status, frame_path, frame_digest = frame_entry
        if (observed_status, observed_path) != (frame_status, frame_path):
            return False
        if observed_digest == frame_digest:
            continue
        if observed_digest is None or frame_digest is None:
            return False
        digests = _current_regular_file_digests(Path(root) / observed_path)
        if digests != (frame_digest, observed_digest):
            return False
    return True


def _current_regular_file_digests(path: Path) -> tuple[str, str] | None:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > MAX_WORKSPACE_VERIFICATION_HASH_BRIDGE_BYTES
        ):
            return None
        content = path.read_bytes()
        after = path.lstat()
    except OSError:
        return None
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(content) != before.st_size:
        return None
    raw_digest = hashlib.sha256(content).hexdigest()
    preservation_digest = hashlib.sha256(
        str(before.st_size).encode("utf-8") + content + b":complete"
    ).hexdigest()
    return raw_digest, preservation_digest


def _repository_entries(
    value: Any,
) -> tuple[tuple[str, str, str | None], ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) > MAX_WORKSPACE_VERIFICATION_CHANGED_ENTRIES:
        return None
    result: list[tuple[str, str, str | None]] = []
    seen_paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            return None
        status = raw.get("status")
        if not _valid_status(status):
            return None
        if raw.get("xy") is not None and raw.get("xy") != status:
            return None
        path = _normalized_repository_path(raw.get("path"))
        if path is None or path in seen_paths:
            return None
        seen_paths.add(path)
        deleted = "D" in status
        raw_digest = raw.get("sha256")
        if raw_digest is None:
            if not deleted:
                return None
            digest = None
        else:
            digest = _normalized_digest(raw_digest)
            if digest is None:
                return None
        result.append((status, path, digest))
    return tuple(sorted(result, key=lambda item: (item[1], item[0], item[2] or "")))


def _changed_paths(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    paths: list[str] = []
    for raw in value:
        path = _normalized_repository_path(raw)
        if path is None:
            return None
        paths.append(path)
    if len(paths) != len(set(paths)):
        return None
    return tuple(sorted(paths))


def _outcome_verification_keys(
    payload: Mapping[str, Any],
    *,
    root: str,
) -> frozenset[tuple[str, str, str, int, bool]] | None:
    raw_results = payload.get("verification_results")
    if not isinstance(raw_results, list) or len(raw_results) > MAX_WORKSPACE_VERIFICATION_SCAN:
        return None
    keys: set[tuple[str, str, str, int, bool]] = set()
    for index, raw in enumerate(raw_results, start=1):
        if not isinstance(raw, Mapping):
            return None
        command = _bounded_text(raw.get("command"), MAX_WORKSPACE_VERIFICATION_COMMAND_CHARS)
        cwd = _normalized_cwd(raw.get("cwd"), root=root)
        exit_code = raw.get("exit_code")
        timed_out = raw.get("timed_out")
        if (
            command is None
            or cwd is None
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or not isinstance(timed_out, bool)
        ):
            return None
        keys.add(
            (
                f"harness:verification:{index}",
                command,
                cwd,
                exit_code,
                timed_out,
            )
        )
    return frozenset(keys)


def _verification_observation(
    observation: RunObservation,
    *,
    root: str,
    outcome_observation_id: str,
) -> WorkspaceVerificationObservation | None:
    payload = _json_object(observation.payload_json)
    if payload is None:
        return None
    if (
        payload.get("schema_version") != "run_observation.v1"
        or payload.get("event_type") != "verification"
        or not _present_text(payload.get("content"))
        or not isinstance(payload.get("files"), list)
    ):
        return None
    command = _bounded_text(payload.get("command"), MAX_WORKSPACE_VERIFICATION_COMMAND_CHARS)
    row_command = _bounded_text(observation.command, MAX_WORKSPACE_VERIFICATION_COMMAND_CHARS)
    cwd = _normalized_cwd(payload.get("cwd"), root=root)
    exit_code = payload.get("exit_code")
    timed_out = payload.get("timed_out")
    if (
        command is None
        or row_command != command
        or cwd is None
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or observation.exit_code != exit_code
        or not isinstance(timed_out, bool)
    ):
        return None

    stdout = payload.get("stdout")
    stderr = payload.get("stderr")
    stdout_truncated = payload.get("stdout_truncated")
    stderr_truncated = payload.get("stderr_truncated")
    argv = payload.get("argv")
    duration_ms = payload.get("duration_ms")
    if (
        not isinstance(stdout, str)
        or not isinstance(stderr, str)
        or not isinstance(stdout_truncated, bool)
        or not isinstance(stderr_truncated, bool)
        or not isinstance(argv, list)
        or not argv
        or any(_bounded_text(item, 4_000) is None for item in argv)
        or not isinstance(duration_ms, int)
        or isinstance(duration_ms, bool)
        or duration_ms < 0
    ):
        return None

    observed_at = _utc_datetime(observation.observed_at or observation.created_at)
    if observed_at is None:
        return None
    # Bind provenance to the exact persisted payload bytes, not merely an
    # equivalent decoded JSON object. The local harness writes canonical JSON,
    # while this remains fail-safe if storage ever preserves other formatting.
    payload_sha256 = hashlib.sha256(observation.payload_json.encode("utf-8")).hexdigest()
    output_sha256 = _sha256_json(
        {
            "stderr": stderr,
            "stderr_truncated": stderr_truncated,
            "stdout": stdout,
            "stdout_truncated": stdout_truncated,
            "timed_out": timed_out,
        }
    )
    return WorkspaceVerificationObservation(
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        observed_at=observed_at,
        timed_out=timed_out,
        payload_sha256=payload_sha256,
        output_sha256=output_sha256,
        evidence_rule=WORKSPACE_VERIFICATION_EVIDENCE_RULE,
        evidence_id=f"run-observation:{observation.id}",
        agent_run_id=str(observation.agent_run_id),
        run_observation_id=str(observation.id),
        outcome_observation_id=outcome_observation_id,
    )


def _json_object(value: str | None) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    if len(value.encode("utf-8")) > MAX_WORKSPACE_VERIFICATION_PAYLOAD_BYTES:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _normalized_repo_root(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    try:
        resolved = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    return os.path.normcase(os.path.normpath(str(resolved)))


def _normalized_repository_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    candidate = value.replace("\\", "/")
    if candidate.startswith("/"):
        return None
    if ".." in candidate.split("/"):
        return None
    normalized = posixpath.normpath(candidate)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def _normalized_cwd(value: Any, *, root: str) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    if len(value) > MAX_WORKSPACE_VERIFICATION_CWD_CHARS:
        return None
    candidate = value.strip()
    if os.path.isabs(candidate):
        normalized = _normalized_repo_root(candidate)
        if normalized is None:
            return None
        try:
            relative = Path(normalized).relative_to(Path(root))
        except ValueError:
            return None
        rendered = relative.as_posix()
        return rendered if rendered else "."
    normalized = _normalized_repository_path(candidate)
    return "." if candidate in {".", "./"} else normalized


def _normalized_branch(value: Any) -> str | None:
    if value in (None, "", "HEAD"):
        return None
    return _bounded_text(value, 500)


def _valid_branch(value: Any) -> bool:
    return value in (None, "", "HEAD") or _bounded_text(value, 500) is not None


def _valid_status(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 2 or "\x00" in value:
        return False
    allowed = frozenset(" MADRCUT?!")
    return value != "  " and value != "!!" and all(char in allowed for char in value)


def _normalized_head(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if len(normalized) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        return None
    return normalized


def _normalized_digest(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        return None
    return normalized


def _bounded_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    normalized = value.strip()
    return normalized if len(normalized) <= limit else None


def _present_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "MAX_WORKSPACE_VERIFICATION_OBSERVATIONS",
    "MAX_WORKSPACE_VERIFICATION_HASH_BRIDGE_BYTES",
    "WORKSPACE_VERIFICATION_EVIDENCE_RULE",
    "WorkspaceVerificationObservation",
    "load_workspace_verification_observations",
]
