from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AgentRun, RunObservation, SourceDocument, VerifiedPlaybook
from app.services.access import AccessScope, source_access_predicate
from app.services.redaction import REDACTED_VALUE, redact_sensitive_text
from app.services.source_revisions import ingest_source_document_revision
from app.time import utc_now


SUCCESS_OUTCOMES = frozenset({"completed", "complete", "success", "succeeded", "passed"})


class PlaybookNotFoundError(LookupError):
    pass


class PlaybookActionError(ValueError):
    pass


class PlaybookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def extract_from_run(self, run_id: UUID) -> VerifiedPlaybook | None:
        run = await self.session.scalar(
            select(AgentRun)
            .options(
                selectinload(AgentRun.context_pack),
                selectinload(AgentRun.observations),
            )
            .where(AgentRun.id == run_id)
        )
        if run is None or run.workspace_id is None or run.context_pack is None:
            return None
        observations = sorted(run.observations, key=_observation_key)
        outcome = next(
            (item for item in reversed(observations) if item.event_type == "outcome"),
            None,
        )
        if outcome is None or _outcome_status(outcome) not in SUCCESS_OUTCOMES:
            return None
        manifest = _json_object(run.context_pack.manifest)
        required = _required_commands(manifest)
        if not required or not _required_verification_passed(required, observations):
            return None
        if _unresolved_blockers(observations):
            return None
        step_observations = [
            item for item in observations if item.event_type in {"patch_summary", "decision"}
        ]
        if not step_observations:
            return None
        steps = []
        for item in step_observations:
            step = _safe_step(item)
            if step:
                steps.append(step)
            if len(steps) == 8:
                break
        if not steps:
            return None
        commands = [
            _safe_text(item["command"], 500) for item in required if item.get("command")
        ]
        if not commands or any(REDACTED_VALUE in item for item in commands):
            # Redacted credentials make a procedure ambiguous and unsafe to replay.
            return None

        objective = " ".join(str(run.objective or run.context_pack.objective or "").split())
        terms = _objective_terms(objective)
        if not terms:
            return None
        objective_fingerprint = _hash(sorted(terms))
        repo_state = _json_object(run.context_pack.repo_state_json)
        repository_identity = _text_or_none(repo_state.get("repo_path"))
        repository_snapshot = _text_or_none(
            run.head_commit or repo_state.get("head_commit") or repo_state.get("snapshot_fingerprint")
        )
        identity_key = _hash([
            str(run.workspace_id), objective_fingerprint, repository_identity or "no-repository"
        ])
        existing = await self.session.scalar(
            select(VerifiedPlaybook)
            .where(VerifiedPlaybook.identity_key == identity_key)
            .with_for_update()
        )
        source_ids = [
            str(item.source_document_id) for item in observations if item.source_document_id
        ]
        verified_at = _event_time(outcome)
        if existing is None:
            playbook = VerifiedPlaybook(
                id=uuid4(),
                workspace_id=run.workspace_id,
                identity_key=identity_key,
                objective_fingerprint=objective_fingerprint,
                objective_pattern=objective,
                repository_identity=repository_identity,
                repository_snapshot=repository_snapshot,
                status="pending_review",
                ordered_steps_json=_json(steps),
                verification_commands_json=_json(commands),
                source_run_id=run.id,
                supporting_run_ids_json=_json([str(run.id)]),
                source_document_ids_json=_json(list(dict.fromkeys(source_ids))),
                successful_run_count=1,
                last_verified_at=verified_at,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(playbook)
                    await self.session.flush()
                return playbook
            except IntegrityError:
                existing = await self.session.scalar(
                    select(VerifiedPlaybook).where(
                        VerifiedPlaybook.identity_key == identity_key
                    )
                )
                if existing is None:
                    raise

        supporting = _json_list(existing.supporting_run_ids_json)
        if str(run.id) not in supporting:
            supporting.append(str(run.id))
            existing.supporting_run_ids_json = _json(supporting)
            existing.successful_run_count = len(supporting)
            existing.last_verified_at = verified_at
            existing.repository_snapshot = repository_snapshot
            existing.ordered_steps_json = _json(steps)
            existing.verification_commands_json = _json(commands)
            existing.source_document_ids_json = _json(list(dict.fromkeys([
                *_json_list(existing.source_document_ids_json),
                *source_ids,
            ])))
            if existing.status == "pending_review" and existing.successful_run_count >= 2:
                existing.status = "approved"
                existing.approved_at = verified_at
                existing.review_reason = "Approved after a second independent verified run."
        await self.session.flush()
        return existing

    async def list(self, *, workspace_id: UUID) -> list[VerifiedPlaybook]:
        return list(await self.session.scalars(
            select(VerifiedPlaybook)
            .where(VerifiedPlaybook.workspace_id == workspace_id)
            .order_by(VerifiedPlaybook.updated_at.desc(), VerifiedPlaybook.created_at.desc())
            .limit(100)
        ))

    async def compatible_playbook(
        self,
        *,
        workspace_id: UUID,
        objective: str,
        repo_state: dict[str, Any],
        access_scope: AccessScope | None = None,
    ) -> dict[str, Any] | None:
        access_scope = access_scope or AccessScope.local()
        accessible_source_ids = set(await self.session.scalars(
            select(SourceDocument.id).where(
                source_access_predicate(access_scope, workspace_id=workspace_id)
            )
        ))
        candidates = list(await self.session.scalars(
            select(VerifiedPlaybook).where(
                VerifiedPlaybook.workspace_id == workspace_id,
                VerifiedPlaybook.status == "approved",
            )
        ))
        objective_terms = _objective_terms(objective)
        repo_identity = _text_or_none(repo_state.get("repo_path"))
        repo_snapshot = _text_or_none(
            repo_state.get("head_commit") or repo_state.get("snapshot_fingerprint")
        )
        scored: list[tuple[float, VerifiedPlaybook]] = []
        for item in candidates:
            try:
                source_ids = {
                    UUID(str(value)) for value in _json_list(item.source_document_ids_json)
                }
            except (TypeError, ValueError):
                continue
            if not source_ids <= accessible_source_ids:
                continue
            overlap = _jaccard(objective_terms, _objective_terms(item.objective_pattern))
            if overlap < 0.6:
                continue
            if item.repository_identity != repo_identity:
                continue
            if item.repository_snapshot != repo_snapshot:
                continue
            scored.append((overlap, item))
        if not scored:
            return None
        scored.sort(key=lambda entry: (entry[0], entry[1].last_verified_at), reverse=True)
        return playbook_to_dict(scored[0][1], compatible=True)

    async def apply_action(
        self,
        *,
        workspace_id: UUID,
        playbook_id: UUID,
        action: str,
        reason: str,
    ) -> VerifiedPlaybook:
        normalized_action = str(action or "").strip().lower()
        normalized_reason = " ".join(str(reason or "").split())
        if normalized_action not in {"approve", "disable"}:
            raise PlaybookActionError("action must be approve or disable")
        if not normalized_reason:
            raise PlaybookActionError("reason is required")
        playbook = await self.session.scalar(select(VerifiedPlaybook).where(
            VerifiedPlaybook.id == playbook_id,
            VerifiedPlaybook.workspace_id == workspace_id,
        ))
        if playbook is None:
            raise PlaybookNotFoundError("playbook was not found")
        if normalized_action == "approve" and playbook.status not in {"pending_review", "approved"}:
            raise PlaybookActionError("only a pending playbook can be approved")
        now = utc_now()
        playbook.status = "approved" if normalized_action == "approve" else "disabled"
        playbook.approved_at = now if normalized_action == "approve" else None
        playbook.review_reason = normalized_reason
        evidence = await ingest_source_document_revision(
            self.session,
            workspace_id=workspace_id,
            source_type="human_playbook_review",
            external_id=(
                f"playbook:{playbook.id}:{normalized_action}:"
                f"{hashlib.sha256(normalized_reason.encode()).hexdigest()}"
            ),
            content=(
                f"Playbook review: {normalized_action}\n"
                f"Objective: {playbook.objective_pattern}\nReason: {normalized_reason}"
            ),
            author="human",
            metadata_json={
                "playbook_id": str(playbook.id),
                "action": normalized_action,
                "reason": normalized_reason,
            },
            source_created_at=now,
            trust_zone="trusted_human",
        )
        playbook.review_source_document_id = evidence.document.id
        await self.session.flush()
        return playbook


def playbook_to_dict(
    playbook: VerifiedPlaybook,
    *,
    compatible: bool | None = None,
) -> dict[str, Any]:
    source_ids = _json_list(playbook.source_document_ids_json)
    value = {
        "id": str(playbook.id),
        "status": playbook.status,
        "title": playbook.objective_pattern,
        "objective_pattern": playbook.objective_pattern,
        "objective_fingerprint": playbook.objective_fingerprint,
        "repository_identity": playbook.repository_identity,
        "repository_snapshot": playbook.repository_snapshot,
        "ordered_steps": _json_list(playbook.ordered_steps_json),
        "verification_commands": _json_list(playbook.verification_commands_json),
        "source_run_id": str(playbook.source_run_id),
        "supporting_run_ids": _json_list(playbook.supporting_run_ids_json),
        "successful_run_count": playbook.successful_run_count,
        "verified_run_count": playbook.successful_run_count,
        "last_verified_at": playbook.last_verified_at.isoformat(),
        "review_reason": playbook.review_reason,
        "review_source_document_id": (
            str(playbook.review_source_document_id)
            if playbook.review_source_document_id else None
        ),
        "sources": [{"source_document_id": value} for value in source_ids],
    }
    if compatible is not None:
        value["compatible"] = compatible
    return value


def _required_commands(manifest: dict[str, Any]) -> list[dict[str, str]]:
    raw = (manifest.get("verification") or {}).get("commands") or []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("required") is not True:
            continue
        command = _normalize_command(item.get("command"))
        requirement_id = _text_or_none(item.get("id"))
        if command or requirement_id:
            result.append({"command": command or "", "id": requirement_id or ""})
    return result


def _required_verification_passed(
    required: list[dict[str, str]],
    observations: list[RunObservation],
) -> bool:
    evidence: list[tuple[RunObservation, dict[str, Any]]] = []
    for observation in observations:
        payload = _payload(observation)
        if observation.event_type == "verification":
            evidence.append((observation, payload))
        if observation.event_type == "outcome":
            evidence.extend(
                (observation, item) for item in payload.get("verification_results") or []
                if isinstance(item, dict)
            )
    for requirement in required:
        matches = [
            (observation, payload) for observation, payload in evidence
            if (
                requirement["id"]
                and str(payload.get("requirement_id") or "") == requirement["id"]
            ) or (
                requirement["command"]
                and _normalize_command(payload.get("command")) == requirement["command"]
            )
        ]
        if not matches:
            return False
        latest = sorted(matches, key=lambda item: _observation_key(item[0]))[-1][1]
        if not _passed(latest):
            return False
    return True


def _unresolved_blockers(observations: list[RunObservation]) -> bool:
    blockers = {
        item.event_key: _observation_key(item)
        for item in observations if item.event_type == "blocker" and item.event_key
    }
    for item in observations:
        if item.event_type != "blocker_resolution":
            continue
        key = _payload(item).get("resolves_event_key")
        if key in blockers and _observation_key(item) > blockers[key]:
            blockers.pop(key, None)
    return bool(blockers)


def _safe_step(observation: RunObservation) -> str | None:
    payload = _payload(observation)
    value = (
        payload.get("summary") or payload.get("decision") or payload.get("content")
        or observation.content
    )
    return _safe_text(value, 600)


def _safe_text(value: Any, limit: int) -> str:
    redacted = redact_sensitive_text(" ".join(str(value or "").split())) or ""
    return redacted if len(redacted) <= limit else f"{redacted[:limit - 3].rstrip()}..."


def _payload(observation: RunObservation) -> dict[str, Any]:
    value = _json_object(observation.payload_json)
    value.setdefault("content", observation.content)
    value.setdefault("command", observation.command)
    value.setdefault("exit_code", observation.exit_code)
    return value


def _outcome_status(observation: RunObservation) -> str:
    payload = _payload(observation)
    return str(
        payload.get("status") or payload.get("terminal_status") or payload.get("outcome") or ""
    ).strip().lower()


def _passed(payload: dict[str, Any]) -> bool:
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code == 0
    return str(payload.get("status") or "").strip().lower() in {
        "passed", "pass", "success", "succeeded"
    }


def _observation_key(observation: RunObservation) -> tuple[datetime, str]:
    return (_event_time(observation), str(observation.id))


def _event_time(observation: RunObservation) -> datetime:
    return observation.observed_at or observation.created_at or utc_now()


def _normalize_command(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _objective_terms(value: str) -> set[str]:
    stop = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
    return {
        token for token in re.findall(r"[a-z0-9_]+", str(value or "").lower())
        if len(token) > 1 and token not in stop
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_object(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _text_or_none(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None
