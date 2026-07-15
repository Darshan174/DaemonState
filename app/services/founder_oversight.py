from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AgentRun,
    Component,
    ContextPack,
    ContextPackItem,
    RunObservation,
    SourceDocument,
)


VISIBLE_EVENT_TYPES = frozenset(
    {"verification", "blocker", "blocker_resolution", "patch_summary", "outcome", "decision"}
)
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked"})
SUCCESS_OUTCOMES = frozenset({"completed", "complete", "success", "succeeded", "passed"})


class FounderOversightNotFoundError(LookupError):
    """Raised without revealing whether a focus exists in another workspace."""


def _json_object(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_time(observation: RunObservation) -> datetime:
    return observation.observed_at or observation.created_at


def _event_sort_key(observation: RunObservation) -> tuple[datetime, str]:
    return (_event_time(observation), str(observation.id))


def _normalize_command(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, UUID))]


def _payload(observation: RunObservation) -> dict[str, Any]:
    payload = _json_object(observation.payload_json)
    # Legacy columns remain factual fallbacks; structured fields always win.
    payload.setdefault("event_type", observation.event_type)
    payload.setdefault("content", observation.content)
    payload.setdefault("command", observation.command)
    payload.setdefault("exit_code", observation.exit_code)
    if "files" not in payload:
        try:
            files = json.loads(observation.files_json or "[]")
        except (TypeError, ValueError):
            files = []
        payload["files"] = files if isinstance(files, list) else []
    return payload


def _required_commands(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        return []
    commands = verification.get("commands")
    if not isinstance(commands, list):
        return []
    required: list[dict[str, Any]] = []
    for raw in commands:
        if not isinstance(raw, dict) or raw.get("required") is not True:
            continue
        command = _normalize_command(raw.get("command"))
        requirement_id = raw.get("id")
        if command is None and not isinstance(requirement_id, str):
            continue
        required.append(
            {
                "id": requirement_id if isinstance(requirement_id, str) else None,
                "command": command,
                "raw": raw,
            }
        )
    return required


def _required_item_ids(manifest: dict[str, Any], items: Iterable[ContextPackItem]) -> list[str]:
    persisted_ids = {
        item.manifest_item_id
        for item in items
        if isinstance(item.manifest_item_id, str) and item.manifest_item_id
    }
    selected = manifest.get("selected_context")
    if not isinstance(selected, list):
        return []
    result: list[str] = []
    for raw in selected:
        if not isinstance(raw, dict) or raw.get("mandatory") is not True:
            continue
        item_id = raw.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue
        # New packs persist manifest IDs. This guard prevents a caller-authored
        # manifest from manufacturing a finding without a ledger row.
        if persisted_ids and item_id not in persisted_ids:
            continue
        result.append(item_id)
    return list(dict.fromkeys(result))


def _verification_evidence(
    observations: Iterable[RunObservation],
) -> list[tuple[RunObservation, dict[str, Any]]]:
    evidence: list[tuple[RunObservation, dict[str, Any]]] = []
    for observation in observations:
        payload = _payload(observation)
        if observation.event_type == "verification":
            evidence.append((observation, payload))
        if observation.event_type != "outcome":
            continue
        results = payload.get("verification_results")
        if not isinstance(results, list):
            continue
        evidence.extend(
            (observation, dict(result))
            for result in results
            if isinstance(result, dict)
        )
    return evidence


def _matching_verifications(
    requirement: dict[str, Any],
    evidence: Iterable[tuple[RunObservation, dict[str, Any]]],
) -> list[tuple[RunObservation, dict[str, Any]]]:
    matches: list[tuple[RunObservation, dict[str, Any]]] = []
    for observation, payload in evidence:
        explicit_id = payload.get("requirement_id")
        exact_id = (
            isinstance(explicit_id, str)
            and requirement.get("id") is not None
            and explicit_id == requirement["id"]
        )
        exact_command = (
            requirement.get("command") is not None
            and _normalize_command(payload.get("command")) == requirement["command"]
        )
        if exact_id or exact_command:
            matches.append((observation, payload))
    return sorted(matches, key=lambda match: _event_sort_key(match[0]))


def _verification_payload_result(payload: dict[str, Any]) -> str | None:
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return "passed" if exit_code == 0 else "failed"
    status = payload.get("status")
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    if normalized in {"passed", "pass", "success", "succeeded"}:
        return "passed"
    if normalized in {"failed", "fail", "error"}:
        return "failed"
    return None


def _verification_result(observation: RunObservation) -> str | None:
    return _verification_payload_result(_payload(observation))


def _outcome_status(observation: RunObservation | None) -> str | None:
    if observation is None:
        return None
    payload = _payload(observation)
    for key in ("status", "terminal_status", "outcome"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _successful_outcome(observation: RunObservation | None) -> bool:
    status = _outcome_status(observation)
    return status in SUCCESS_OUTCOMES if status is not None else False


def _terminal(run: AgentRun, observations: Iterable[RunObservation]) -> bool:
    return run.status in TERMINAL_RUN_STATUSES or any(
        observation.event_type == "outcome" for observation in observations
    )


def _unresolved_blockers(observations: list[RunObservation]) -> list[RunObservation]:
    blockers = [item for item in observations if item.event_type == "blocker" and item.event_key]
    resolutions: dict[str, list[RunObservation]] = {}
    for observation in observations:
        if observation.event_type != "blocker_resolution":
            continue
        resolved_key = _payload(observation).get("resolves_event_key")
        if isinstance(resolved_key, str):
            resolutions.setdefault(resolved_key, []).append(observation)
    unresolved: list[RunObservation] = []
    for blocker in blockers:
        later = [
            item
            for item in resolutions.get(str(blocker.event_key), [])
            if _event_sort_key(item) > _event_sort_key(blocker)
        ]
        if not later:
            unresolved.append(blocker)
    return unresolved


def _latest_outcome(observations: Iterable[RunObservation]) -> RunObservation | None:
    outcomes = [item for item in observations if item.event_type == "outcome"]
    return max(outcomes, key=_event_sort_key) if outcomes else None


def _source_entry(
    observation: RunObservation | None,
    *,
    excerpt: str,
    fallback_document: SourceDocument | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    document = observation.source_document if observation is not None else fallback_document
    return {
        "source_document_id": str(document.id) if document is not None else None,
        "source_url": document.source_url if document is not None else None,
        "excerpt": excerpt,
        "observed_at": _iso(
            _event_time(observation) if observation is not None else observed_at
        ),
    }


def _finding(
    *,
    rule_id: str,
    state: str,
    severity: str,
    title: str,
    explanation: str,
    next_action: str,
    pack: ContextPack,
    run: AgentRun | None,
    focus_component_id: UUID,
    trigger_ids: list[str],
    sources: list[dict[str, Any]],
    evaluated_at: datetime,
) -> dict[str, Any]:
    identity = "|".join(
        [rule_id, str(pack.id), str(run.id) if run else "", *sorted(trigger_ids)]
    )
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "rule_id": rule_id,
        "rule_version": 1,
        "state": state,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "next_action": next_action,
        "context_pack_id": str(pack.id),
        "run_id": str(run.id) if run is not None else None,
        "focus_component_id": str(focus_component_id),
        "trigger_ids": trigger_ids,
        "sources": sources,
        "evaluated_at": _iso(evaluated_at),
        "resolution_state": "open",
    }


class FounderOversightService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def build_timeline(
        self,
        *,
        workspace_id: UUID,
        focus_component_id: UUID,
        evaluated_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = evaluated_at or datetime.now(UTC)
        focus = await self.session.scalar(
            select(Component)
            .options(selectinload(Component.source_document))
            .where(
                Component.id == focus_component_id,
                Component.workspace_id == workspace_id,
            )
        )
        if focus is None:
            raise FounderOversightNotFoundError("focused context was not found")

        packs = list(
            (
                await self.session.scalars(
                    select(ContextPack)
                    .options(
                        selectinload(ContextPack.items).selectinload(
                            ContextPackItem.source_document
                        )
                    )
                    .where(
                        ContextPack.workspace_id == workspace_id,
                        ContextPack.focus_component_id == focus_component_id,
                    )
                    .order_by(ContextPack.created_at.desc(), ContextPack.id.desc())
                    .execution_options(populate_existing=True)
                )
            ).unique()
        )

        current_source = not bool(
            await self.session.scalar(
                select(
                    exists().where(
                        SourceDocument.supersedes_source_document_id
                        == focus.source_document_id,
                        SourceDocument.workspace_id == workspace_id,
                    )
                )
            )
        )
        focus_payload = {
            "component_id": str(focus.id),
            "title": focus.name or focus.value,
            "source_document_id": str(focus.source_document_id),
            "source_revision_number": focus.source_document.revision_number,
        }
        if not packs:
            return {
                "schema_version": "run_timeline.v1",
                "workspace_id": str(workspace_id),
                "focus": focus_payload,
                "state": "not_attempted",
                "latest_outcome": None,
                "attention": {
                    "blocked": 0,
                    "unverified": 0,
                    "stale": 0,
                },
                "findings": [],
                "runs": [],
            }

        pack_ids = [pack.id for pack in packs]
        runs = list(
            (
                await self.session.scalars(
                    select(AgentRun)
                    .options(
                        selectinload(AgentRun.observations).selectinload(
                            RunObservation.source_document
                        )
                    )
                    .where(
                        AgentRun.workspace_id == workspace_id,
                        AgentRun.context_pack_id.in_(pack_ids),
                    )
                    .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
                    .limit(10)
                    .execution_options(populate_existing=True)
                )
            ).unique()
        )
        pack_by_id = {pack.id: pack for pack in packs}
        latest_pack = packs[0]
        latest_run = next((run for run in runs if run.context_pack_id == latest_pack.id), None)
        latest_observations = (
            sorted(latest_run.observations, key=_event_sort_key) if latest_run is not None else []
        )
        findings, state = self._evaluate(
            pack=latest_pack,
            run=latest_run,
            observations=latest_observations,
            focus=focus,
            current_source=current_source,
            evaluated_at=now,
        )
        timeline_runs: list[dict[str, Any]] = []
        visible_count = 0
        for run in runs:
            pack = pack_by_id.get(run.context_pack_id)
            if pack is None:
                continue
            observations = sorted(run.observations, key=_event_sort_key)
            _, run_state = self._evaluate(
                pack=pack,
                run=run,
                observations=observations,
                focus=focus,
                current_source=current_source,
                evaluated_at=now,
            )
            visible: list[dict[str, Any]] = []
            for observation in observations:
                if observation.event_type not in VISIBLE_EVENT_TYPES or visible_count >= 100:
                    continue
                visible.append(self._timeline_event(observation))
                visible_count += 1
            timeline_runs.append(
                {
                    "run_id": str(run.id),
                    "context_pack_id": str(pack.id),
                    "status": run.status,
                    "state": run_state,
                    "tool": run.tool,
                    "model": run.model,
                    "branch": run.branch,
                    "base_commit": run.base_commit,
                    "head_commit": run.head_commit,
                    "started_at": _iso(run.started_at),
                    "ended_at": _iso(run.ended_at),
                    "events": visible,
                }
            )

        outcome = _latest_outcome(latest_observations)
        latest_outcome = None
        if latest_run is not None and outcome is not None:
            payload = _payload(outcome)
            document = outcome.source_document
            latest_outcome = {
                "run_id": str(latest_run.id),
                "summary": payload.get("summary") or payload.get("content") or outcome.content,
                "observed_at": _iso(_event_time(outcome)),
                "source_document_id": str(document.id) if document is not None else None,
            }
        attention = {
            "blocked": sum(item["state"] == "blocked" for item in findings),
            "unverified": sum(
                item["state"]
                in {
                    "verification_missing",
                    "verification_failed",
                    "no_completion_evidence",
                    "conflicting_evidence",
                }
                for item in findings
            ),
            "stale": sum(item["state"] == "stale_source" for item in findings),
        }
        timeline = {
            "schema_version": "run_timeline.v1",
            "workspace_id": str(workspace_id),
            "focus": focus_payload,
            "state": state,
            "latest_outcome": latest_outcome,
            "attention": attention,
            "findings": findings,
            "runs": timeline_runs,
        }
        affected_code = _json_object(latest_pack.manifest).get("affected_code")
        if isinstance(affected_code, dict) and affected_code.get("files"):
            timeline["affected_code"] = affected_code
        return timeline

    def _evaluate(
        self,
        *,
        pack: ContextPack,
        run: AgentRun | None,
        observations: list[RunObservation],
        focus: Component,
        current_source: bool,
        evaluated_at: datetime,
    ) -> tuple[list[dict[str, Any]], str]:
        manifest = _json_object(pack.manifest)
        required_commands = _required_commands(manifest)
        latest_outcome = _latest_outcome(observations)
        successful_outcome = _successful_outcome(latest_outcome)
        terminal = run is not None and _terminal(run, observations)
        unresolved_blockers = _unresolved_blockers(observations)
        verification_evidence = _verification_evidence(observations)
        failed: list[tuple[dict[str, Any], RunObservation, dict[str, Any]]] = []
        missing: list[dict[str, Any]] = []
        passed_count = 0
        for requirement in required_commands:
            matches = _matching_verifications(requirement, verification_evidence)
            result = _verification_payload_result(matches[-1][1]) if matches else None
            if result == "failed":
                failed.append((requirement, matches[-1][0], matches[-1][1]))
            elif result == "passed":
                passed_count += 1
            elif terminal:
                missing.append(requirement)

        findings: list[dict[str, Any]] = []
        for requirement in missing:
            command = requirement.get("command") or requirement.get("id") or "Unknown command"
            source = focus.source_document
            findings.append(
                _finding(
                    rule_id="verification.missing.v1",
                    state="verification_missing",
                    severity="warning",
                    title="Required verification has no recorded result.",
                    explanation=f"No structured result was recorded for `{command}`.",
                    next_action="Run the required command and record its structured result.",
                    pack=pack,
                    run=run,
                    focus_component_id=focus.id,
                    trigger_ids=[str(requirement.get("id") or command)],
                    sources=[
                        _source_entry(
                            None,
                            excerpt=f"Required command: {command}",
                            fallback_document=source,
                            observed_at=pack.created_at,
                        )
                    ],
                    evaluated_at=evaluated_at,
                )
            )
        for requirement, observation, payload in failed:
            command = requirement.get("command") or requirement.get("id") or "Unknown command"
            result = payload.get("exit_code")
            explanation = (
                f"{command} exited with code {result}."
                if isinstance(result, int) and not isinstance(result, bool)
                else f"{command} recorded structured status failed."
            )
            findings.append(
                _finding(
                    rule_id="verification.failed.v1",
                    state="verification_failed",
                    severity="critical",
                    title="Required verification failed.",
                    explanation=explanation,
                    next_action="Inspect the failed check and rerun the required command.",
                    pack=pack,
                    run=run,
                    focus_component_id=focus.id,
                    trigger_ids=[
                        str(observation.id),
                        str(requirement.get("id") or command),
                    ],
                    sources=[
                        _source_entry(
                            observation,
                            excerpt=(
                                f"Observed exit code: {result}"
                                if isinstance(result, int) and not isinstance(result, bool)
                                else "Observed structured status: failed"
                            ),
                        )
                    ],
                    evaluated_at=evaluated_at,
                )
            )
        for blocker in unresolved_blockers:
            payload = _payload(blocker)
            severity_value = str(payload.get("severity") or "").lower()
            severity = "critical" if severity_value in {"critical", "high"} else "warning"
            text = payload.get("blocker") or payload.get("content") or blocker.content or "Recorded blocker"
            findings.append(
                _finding(
                    rule_id="blocker.unresolved.v1",
                    state="blocked",
                    severity=severity,
                    title="A recorded blocker is unresolved.",
                    explanation=str(text),
                    next_action="Resolve the blocker explicitly or record why work cannot continue.",
                    pack=pack,
                    run=run,
                    focus_component_id=focus.id,
                    trigger_ids=[str(blocker.id)],
                    sources=[_source_entry(blocker, excerpt=str(text))],
                    evaluated_at=evaluated_at,
                )
            )

        if terminal:
            addressed: set[str] = set()
            evidence_observations: dict[str, RunObservation] = {}
            for observation in observations:
                if observation.event_type not in {
                    "patch_summary",
                    "outcome",
                    "blocker_resolution",
                    "verification",
                }:
                    continue
                payload = _payload(observation)
                references = [
                    *_string_list(payload.get("addresses_context_item_ids")),
                    *_string_list(payload.get("completed_context_item_ids")),
                ]
                requirement_id = payload.get("requirement_id")
                if isinstance(requirement_id, str):
                    references.append(requirement_id)
                for item_id in references:
                    addressed.add(item_id)
                    evidence_observations.setdefault(item_id, observation)
            item_by_manifest_id = {
                item.manifest_item_id: item
                for item in pack.items
                if isinstance(item.manifest_item_id, str)
            }
            for item_id in _required_item_ids(manifest, pack.items):
                if item_id in addressed:
                    continue
                item = item_by_manifest_id.get(item_id)
                source = item.source_document if item is not None else focus.source_document
                findings.append(
                    _finding(
                        rule_id="completion.evidence_missing.v1",
                        state="no_completion_evidence",
                        severity="warning",
                        title="This required item has no completion evidence.",
                        explanation=f"No structured runtime event cites required context item `{item_id}`.",
                        next_action="Record the patch, check, outcome, or resolution that addresses this item.",
                        pack=pack,
                        run=run,
                        focus_component_id=focus.id,
                        trigger_ids=[str(item.id) if item is not None else item_id],
                        sources=[
                            _source_entry(
                                None,
                                excerpt=f"Required context item: {item_id}",
                                fallback_document=source,
                                observed_at=item.created_at if item is not None else pack.created_at,
                            )
                        ],
                        evaluated_at=evaluated_at,
                    )
                )

        if successful_outcome and failed:
            outcome_triggers = [str(latest_outcome.id)] if latest_outcome is not None else []
            failed_triggers = [
                f"{observation.id}:{requirement.get('id') or requirement.get('command')}"
                for requirement, observation, _ in failed
            ]
            sources = []
            if latest_outcome is not None:
                sources.append(
                    _source_entry(
                        latest_outcome,
                        excerpt=f"Recorded outcome status: {_outcome_status(latest_outcome)}",
                    )
                )
            sources.extend(
                _source_entry(observation, excerpt="Required check recorded as failed")
                for _, observation, _ in failed
            )
            findings.append(
                _finding(
                    rule_id="outcome.check_conflict.v1",
                    state="conflicting_evidence",
                    severity="critical",
                    title="The claimed outcome conflicts with a recorded check.",
                    explanation="The run claims success while a required verification result is failed.",
                    next_action="Correct the completion claim or provide a later passing required result.",
                    pack=pack,
                    run=run,
                    focus_component_id=focus.id,
                    trigger_ids=[*outcome_triggers, *failed_triggers],
                    sources=sources,
                    evaluated_at=evaluated_at,
                )
            )

        if not current_source:
            findings.append(
                _finding(
                    rule_id="source.stale.v1",
                    state="stale_source",
                    severity="warning",
                    title="The prepared focus is based on an older source revision.",
                    explanation=(
                        f"Focus source revision {focus.source_document.revision_number} has been superseded."
                    ),
                    next_action="Prepare a new context pack from the current source revision.",
                    pack=pack,
                    run=run,
                    focus_component_id=focus.id,
                    trigger_ids=[str(focus.source_document_id)],
                    sources=[
                        _source_entry(
                            None,
                            excerpt=f"Prepared source revision: {focus.source_document.revision_number}",
                            fallback_document=focus.source_document,
                            observed_at=focus.source_document.ingested_at,
                        )
                    ],
                    evaluated_at=evaluated_at,
                )
            )

        if successful_outcome and failed:
            state = "conflicting_evidence"
        elif not current_source:
            state = "stale_source"
        elif unresolved_blockers:
            state = "blocked"
        elif failed:
            state = "verification_failed"
        elif missing:
            state = "verification_missing"
        elif run is None:
            state = "not_attempted"
        elif required_commands and successful_outcome and passed_count == len(required_commands):
            state = "verified"
        else:
            has_completion_evidence = any(
                item.event_type in {"outcome", "patch_summary", "verification", "blocker"}
                for item in observations
            )
            state = "completed_unverified" if has_completion_evidence else "no_completion_evidence"
        return findings, state

    @staticmethod
    def _timeline_event(observation: RunObservation) -> dict[str, Any]:
        payload = _payload(observation)
        document = observation.source_document
        raw_results = payload.get("verification_results")
        verification_results = [
            {
                "command": _normalize_command(item.get("command")),
                "requirement_id": item.get("requirement_id")
                if isinstance(item.get("requirement_id"), str)
                else None,
                "status": _verification_payload_result(item),
                "exit_code": item.get("exit_code")
                if isinstance(item.get("exit_code"), int)
                and not isinstance(item.get("exit_code"), bool)
                else None,
            }
            for item in raw_results
            if isinstance(item, dict)
        ] if isinstance(raw_results, list) else []
        summary = (
            payload.get("summary")
            or payload.get("content")
            or payload.get("blocker")
            or payload.get("decision")
            or observation.content
        )
        result = _verification_result(observation) if observation.event_type == "verification" else None
        state = {
            "passed": "verified",
            "failed": "verification_failed",
        }.get(result)
        if observation.event_type == "blocker":
            state = "blocked"
        return {
            "event_key": observation.event_key,
            "event_type": observation.event_type,
            "state": state,
            "observed_at": _iso(_event_time(observation)),
            "summary": summary,
            "files": _string_list(payload.get("files")),
            "command": _normalize_command(payload.get("command")),
            "exit_code": payload.get("exit_code")
            if isinstance(payload.get("exit_code"), int)
            and not isinstance(payload.get("exit_code"), bool)
            else None,
            "verification_results": verification_results,
            "source_document_id": str(document.id) if document is not None else None,
            "source_url": document.source_url if document is not None else None,
        }


async def build_founder_oversight_timeline(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    focus_component_id: UUID,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return await FounderOversightService(session).build_timeline(
        workspace_id=workspace_id,
        focus_component_id=focus_component_id,
        evaluated_at=evaluated_at,
    )
