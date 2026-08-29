from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextPack
from app.schemas.context_quality import (
    ContextClaimEnvelope,
    ContextKind,
)
from app.services.access import AccessScope
from app.services.checkpoints import (
    checkpoint_to_dict,
    get_checkpoint,
    resolve_session_handoff_attachment_descriptors,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
)
from app.services.context_compiler import ContextCompiler
from app.services.context_quality_adapters import workspace_context_claims
from app.services.context_quality_policies import evaluate_context_candidate
from app.services.session_context import build_session_context_artifact


BENCHMARK_SCHEMA_VERSION = "context_quality_post_benchmark.v1"
SUPPORTED_BASELINE_SCHEMA = "context_quality_benchmark.v1"
FROZEN_GOLD_SCHEMA_VERSION = "context_quality_frozen_gold.v2"
SESSION_RUBRIC_VERSION = "background_context_rubric.v1"
WORKSPACE_RUBRIC_VERSION = "workspace_background_rubric.v1"
SESSION_ASSESSMENT_KIND = "background_projection_safety"
SESSION_RUBRIC_WEIGHTS = {
    "goal_and_dependency_fidelity": 30,
    "useful_background_coverage": 20,
    "evidence_and_uncertainty": 15,
    "snapshot_freshness": 10,
    "non_destructive_safety": 10,
    "background_only_semantics": 10,
    "signal_density": 5,
}
WORKSPACE_RUBRIC_WEIGHTS = {
    "product_truth": 20,
    "capability_and_workflow_coverage": 20,
    "architecture_and_current_repository_usefulness": 20,
    "durable_knowledge_and_provenance": 15,
    "freshness_and_evidence_labels": 10,
    "background_and_non_destructive_safety": 10,
    "signal_density": 5,
}

_WRITE_SQL_RE = re.compile(
    r"\b(?:insert|update|delete|replace|merge|alter|create|drop|truncate|"
    r"vacuum|attach|detach|reindex)\b",
    re.IGNORECASE,
)
_READ_SQL_PREFIXES = frozenset({"select", "with", "pragma", "explain"})
_SESSION_FORBIDDEN_HEADINGS = (
    "## Start here",
    "## Exact next action",
    "## Done when",
    "## Acceptance criteria",
)
_SELF_HASH_UNSAFE_OBJECTIVE_RE = re.compile(
    r"^(?:"
    r"same issue\s*[?.!]*|"
    r"did\s+(?:u|you)\s+fix\s+(?:it|this|that)\s*[?.!]*|"
    r"you\s+have\s+[\d,]+\s+(?:weighted\s+)?tokens?\s+left\s*[.!]*|"
    r"[\[(<]?\s*(?:(?:conversation|generation|request|response|session|"
    r"task|turn)\s+)?(?:interrupted|interruption|paused|stopped)"
    r"(?:\s+by\s+(?:the\s+)?user(?:\s+for\s+[a-z0-9 _-]+)?)?"
    r"\s*[\])>]?\s*[.!?]*"
    r")$",
    re.IGNORECASE,
)
_DESTRUCTIVE_INSTRUCTION_RE = re.compile(
    r"(?im)^\s*(?:[-*]|\d+[.)])?\s*(?:run|execute|use)\s+`?"
    r"(?:rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|"
    r"git\s+push\s+--force)\b"
)
_SESSION_TARGET_NOISE = frozenset({
    "app/services/session_library.py",
    "app/services/session_summary.py",
    "frontend/src/pages/sessionContinuity.js",
})
_GOLD_OBJECTIVE_STATUSES = frozenset({"resolved", "unresolved", "not_a_task"})
_GOLD_PROVENANCE_METHODS = frozenset({
    "blinded_human_review",
    "event_log_adjudication",
    "manual_adjudication",
})


class BenchmarkInputError(RuntimeError):
    """The frozen corpus identity or persisted artifact failed validation."""


def load_frozen_baseline(path: str | Path) -> dict[str, Any]:
    baseline_path = Path(path)
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError(f"cannot read baseline: {baseline_path}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkInputError("baseline must be one JSON object")
    if payload.get("schema_version") != SUPPORTED_BASELINE_SCHEMA:
        raise BenchmarkInputError(
            "unsupported baseline schema: "
            f"{payload.get('schema_version')!r}"
        )
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict) or not workspace.get("id"):
        raise BenchmarkInputError("baseline workspace.id is required")
    try:
        UUID(str(workspace["id"]))
    except ValueError as exc:
        raise BenchmarkInputError("baseline workspace.id is not a UUID") from exc

    cases = payload.get("session_contexts")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkInputError("baseline session_contexts must be non-empty")
    checkpoint_ids: list[UUID] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise BenchmarkInputError(f"session_contexts[{index}] is not an object")
        try:
            checkpoint_id = UUID(str(case["checkpoint_id"]))
        except (KeyError, ValueError) as exc:
            raise BenchmarkInputError(
                f"session_contexts[{index}].checkpoint_id is invalid"
            ) from exc
        checkpoint_ids.append(checkpoint_id)
        for key in ("checkpoint_payload_sha256", "rendered_sha256"):
            value = str(case.get(key) or "")
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise BenchmarkInputError(
                    f"session_contexts[{index}].{key} must be lowercase SHA-256"
                )
        _validate_independent_expectations(case, index=index)
    if len(checkpoint_ids) != len(set(checkpoint_ids)):
        raise BenchmarkInputError("baseline checkpoint IDs must be unique")

    workspace_context = payload.get("workspace_context")
    if not isinstance(workspace_context, dict):
        raise BenchmarkInputError("baseline workspace_context is required")
    try:
        UUID(str(workspace_context["context_pack_id"]))
    except (KeyError, ValueError) as exc:
        raise BenchmarkInputError(
            "baseline workspace_context.context_pack_id is invalid"
        ) from exc
    return payload


def baseline_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    artifact_path = Path(path)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError(f"cannot read {label}: {artifact_path}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkInputError(f"{label} must be one JSON object")
    return payload


def _validate_unique_strings(
    values: Any,
    *,
    field: str,
    sha256: bool = False,
) -> list[str]:
    if (
        not isinstance(values, list)
        or any(not isinstance(item, str) or not item.strip() for item in values)
        or len(values) != len(set(values))
    ):
        raise BenchmarkInputError(
            f"{field} must be a unique list of non-empty strings"
        )
    if sha256 and any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in values):
        raise BenchmarkInputError(
            f"{field} must contain lowercase SHA-256 values"
        )
    return values


def _validate_uuid_strings(values: Any, *, field: str) -> list[str]:
    result = _validate_unique_strings(values, field=field)
    for item in result:
        try:
            UUID(item)
        except ValueError as exc:
            raise BenchmarkInputError(
                f"{field} must contain UUID strings"
            ) from exc
    return result


def _validate_intent_concepts(values: Any, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(values, list) or not values:
        raise BenchmarkInputError(f"{field} must be a non-empty list")
    result: list[Mapping[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(values):
        item_field = f"{field}[{index}]"
        if not isinstance(item, Mapping):
            raise BenchmarkInputError(f"{item_field} must be an object")
        name = str(item.get("name") or "").strip()
        if not name or name in names:
            raise BenchmarkInputError(
                f"{field} concept names must be unique non-empty strings"
            )
        names.add(name)
        _validate_unique_strings(
            item.get("any_of"),
            field=f"{item_field}.any_of",
        )
        result.append(item)
    return result


def validate_frozen_gold(
    payload: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate adjudicated gold that is frozen independently of candidate output.

    The manifest is bound to the canonical baseline hash and must cover the
    exact baseline case set. Runtime request/attachment resolvers are therefore
    never allowed to manufacture expectations for a candidate they also grade.
    """

    normalized = dict(payload)
    if normalized.get("schema_version") != FROZEN_GOLD_SCHEMA_VERSION:
        raise BenchmarkInputError(
            "unsupported frozen gold schema: "
            f"{normalized.get('schema_version')!r}"
        )
    expected_baseline_sha = baseline_sha256(baseline)
    if normalized.get("baseline_sha256") != expected_baseline_sha:
        raise BenchmarkInputError(
            "frozen gold baseline_sha256 does not match the frozen baseline"
        )

    provenance = normalized.get("provenance")
    if not isinstance(provenance, Mapping):
        raise BenchmarkInputError("frozen gold provenance is required")
    method = str(provenance.get("method") or "")
    if method not in _GOLD_PROVENANCE_METHODS:
        raise BenchmarkInputError(
            "frozen gold provenance.method must identify independent adjudication"
        )
    reviewer_count = provenance.get("reviewer_count")
    if (
        isinstance(reviewer_count, bool)
        or not isinstance(reviewer_count, int)
        or reviewer_count < 1
    ):
        raise BenchmarkInputError(
            "frozen gold provenance.reviewer_count must be a positive integer"
        )
    if not isinstance(provenance.get("blinded"), bool):
        raise BenchmarkInputError(
            "frozen gold provenance.blinded must be boolean"
        )
    for key in (
        "candidate_artifacts_consulted",
        "candidate_resolver_output_consulted",
    ):
        if provenance.get(key) is not False:
            raise BenchmarkInputError(
                f"frozen gold provenance.{key} must be explicitly false"
            )

    baseline_cases = {
        (str(case.get("case_id") or ""), str(case.get("checkpoint_id") or ""))
        for case in baseline.get("session_contexts") or []
        if isinstance(case, Mapping)
    }
    raw_cases = normalized.get("session_contexts")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkInputError("frozen gold session_contexts must be non-empty")

    gold_cases: set[tuple[str, str]] = set()
    for index, case in enumerate(raw_cases):
        field = f"frozen gold session_contexts[{index}]"
        if not isinstance(case, Mapping):
            raise BenchmarkInputError(f"{field} must be an object")
        identity = (
            str(case.get("case_id") or ""),
            str(case.get("checkpoint_id") or ""),
        )
        if identity not in baseline_cases:
            raise BenchmarkInputError(
                f"{field} does not identify a case in the frozen baseline"
            )
        if identity in gold_cases:
            raise BenchmarkInputError(f"{field} duplicates a frozen baseline case")
        gold_cases.add(identity)

        objective_status = str(case.get("objective_status") or "")
        if objective_status not in _GOLD_OBJECTIVE_STATUSES:
            raise BenchmarkInputError(
                f"{field}.objective_status must be resolved, unresolved, or not_a_task"
            )
        objective_sha = str(case.get("objective_sha256") or "")
        objective_text = str(case.get("objective_text") or "").strip()
        if objective_status == "resolved":
            if re.fullmatch(r"[0-9a-f]{64}", objective_sha) is None:
                raise BenchmarkInputError(
                    f"{field}.objective_sha256 is required for a resolved objective"
                )
            if not objective_text:
                raise BenchmarkInputError(
                    f"{field}.objective_text is required for a resolved objective"
                )
            canonical_text = " ".join(objective_text.split()).strip()
            canonical_sha = hashlib.sha256(
                canonical_text.encode("utf-8")
            ).hexdigest()
            if canonical_sha != objective_sha:
                raise BenchmarkInputError(
                    f"{field}.objective_sha256 does not match objective_text"
                )
            if _objective_cannot_be_validated_by_exact_self_hash(objective_text):
                raise BenchmarkInputError(
                    f"{field}.objective_text is not independently resolved"
                )

            acceptable_hashes = _validate_unique_strings(
                case.get("acceptable_objective_sha256s"),
                field=f"{field}.acceptable_objective_sha256s",
                sha256=True,
            )
            if objective_sha not in acceptable_hashes:
                raise BenchmarkInputError(
                    f"{field}.acceptable_objective_sha256s must include the "
                    "canonical objective_sha256"
                )
            _validate_intent_concepts(
                case.get("required_intent_concepts"),
                field=f"{field}.required_intent_concepts",
            )
            forbidden_hashes = _validate_unique_strings(
                case.get("forbidden_objective_sha256s", []),
                field=f"{field}.forbidden_objective_sha256s",
                sha256=True,
            )
            if set(acceptable_hashes) & set(forbidden_hashes):
                raise BenchmarkInputError(
                    f"{field} cannot accept and forbid the same objective hash"
                )

            authority = case.get("objective_authority")
            if not isinstance(authority, Mapping):
                raise BenchmarkInputError(
                    f"{field}.objective_authority must be an object"
                )
            binding_required = authority.get("binding_required")
            if not isinstance(binding_required, bool):
                raise BenchmarkInputError(
                    f"{field}.objective_authority.binding_required must be boolean"
                )
            required_source_ids = _validate_unique_strings(
                authority.get("required_provider_event_ids"),
                field=(
                    f"{field}.objective_authority.required_provider_event_ids"
                ),
            )
            allowed_source_ids = _validate_unique_strings(
                authority.get("allowed_provider_event_ids"),
                field=f"{field}.objective_authority.allowed_provider_event_ids",
            )
            raw_required_source_groups = authority.get(
                "required_provider_event_id_groups", []
            )
            if not isinstance(raw_required_source_groups, list):
                raise BenchmarkInputError(
                    f"{field}.objective_authority."
                    "required_provider_event_id_groups must be a list"
                )
            required_source_groups: list[list[str]] = []
            for group_index, raw_group in enumerate(raw_required_source_groups):
                group_field = (
                    f"{field}.objective_authority."
                    f"required_provider_event_id_groups[{group_index}]"
                )
                group = _validate_unique_strings(raw_group, field=group_field)
                if not group:
                    raise BenchmarkInputError(
                        f"{group_field} must contain at least one provider event ID"
                    )
                required_source_groups.append(group)
            if not set(required_source_ids).issubset(allowed_source_ids):
                raise BenchmarkInputError(
                    f"{field}.objective_authority.required_provider_event_ids "
                    "must be a subset of allowed_provider_event_ids"
                )
            if any(
                not set(group).issubset(allowed_source_ids)
                for group in required_source_groups
            ):
                raise BenchmarkInputError(
                    f"{field}.objective_authority."
                    "required_provider_event_id_groups must contain only "
                    "allowed_provider_event_ids"
                )
            if binding_required and not (
                required_source_ids or required_source_groups
            ):
                raise BenchmarkInputError(
                    f"{field}.objective_authority requires at least one source event"
                )
            evidence = case.get("evidence")
            if not isinstance(evidence, Mapping):
                raise BenchmarkInputError(
                    f"{field}.evidence is required for a resolved objective"
                )
            evidence_objective_ids = _validate_uuid_strings(
                evidence.get("objective_event_ids"),
                field=f"{field}.evidence.objective_event_ids",
            )
            evidence_provider_ids = _validate_unique_strings(
                evidence.get("objective_provider_event_ids"),
                field=f"{field}.evidence.objective_provider_event_ids",
            )
            if set(allowed_source_ids) != set(evidence_provider_ids):
                raise BenchmarkInputError(
                    f"{field}.objective_authority.allowed_provider_event_ids must "
                    "exactly match evidence.objective_provider_event_ids"
                )
            if len(evidence_objective_ids) != len(evidence_provider_ids):
                raise BenchmarkInputError(
                    f"{field}.evidence must provide one database SessionEvent UUID "
                    "for each objective provider event ID"
                )
        elif objective_sha or objective_text:
            raise BenchmarkInputError(
                f"{field}.objective_text and objective_sha256 must be absent when "
                f"the objective is {objective_status}"
            )

        required_count = case.get("required_attachment_count")
        if (
            isinstance(required_count, bool)
            or not isinstance(required_count, int)
            or required_count < 0
        ):
            raise BenchmarkInputError(
                f"{field}.required_attachment_count must be a non-negative integer"
            )
        attachment_hashes = _validate_unique_strings(
            case.get("required_attachment_sha256s"),
            field=f"{field}.required_attachment_sha256s",
            sha256=True,
        )
        if required_count != len(attachment_hashes):
            raise BenchmarkInputError(
                f"{field}.required_attachment_count must exactly match the "
                "number of required attachment hashes; frozen attachment gold "
                "must be complete"
            )
        for key in ("required_relevant_files", "forbidden_relevant_files"):
            _validate_unique_strings(
                case.get(key),
                field=f"{field}.{key}",
            )

    if gold_cases != baseline_cases:
        missing = sorted(baseline_cases - gold_cases)
        extra = sorted(gold_cases - baseline_cases)
        raise BenchmarkInputError(
            "frozen gold must cover the exact baseline case set; "
            f"missing={missing!r}, extra={extra!r}"
        )
    return normalized


def load_frozen_gold(
    path: str | Path,
    *,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _load_json_object(path, label="frozen gold")
    return validate_frozen_gold(payload, baseline=baseline)


def _validate_independent_expectations(
    case: Mapping[str, Any],
    *,
    index: int,
) -> None:
    raw = case.get("independent_expectations")
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise BenchmarkInputError(
            f"session_contexts[{index}].independent_expectations must be an object"
        )
    objective_sha = raw.get("objective_sha256")
    if objective_sha is not None and not re.fullmatch(
        r"[0-9a-f]{64}", str(objective_sha)
    ):
        raise BenchmarkInputError(
            "session_contexts"
            f"[{index}].independent_expectations.objective_sha256 must be "
            "lowercase SHA-256"
        )
    for key in (
        "required_attachment_sha256s",
        "required_relevant_files",
        "forbidden_relevant_files",
    ):
        values = raw.get(key)
        if values is None:
            continue
        if (
            not isinstance(values, list)
            or any(not isinstance(item, str) or not item.strip() for item in values)
            or len(values) != len(set(values))
        ):
            raise BenchmarkInputError(
                f"session_contexts[{index}].independent_expectations.{key} "
                "must be a unique list of non-empty strings"
            )
        if key == "required_attachment_sha256s" and any(
            re.fullmatch(r"[0-9a-f]{64}", item) is None for item in values
        ):
            raise BenchmarkInputError(
                f"session_contexts[{index}].independent_expectations.{key} "
                "must contain lowercase SHA-256 values"
            )


def sql_is_read_only(statement: str) -> bool:
    normalized = re.sub(r"/\*.*?\*/|--[^\n]*", " ", statement, flags=re.S)
    normalized = " ".join(normalized.split()).strip().casefold()
    if not normalized:
        return True
    prefix = normalized.split(None, 1)[0]
    return prefix in _READ_SQL_PREFIXES and _WRITE_SQL_RE.search(normalized) is None


async def install_read_only_sql_guard(session: AsyncSession):
    """Reject application-level write SQL on this benchmark connection."""

    async_connection = await session.connection()
    sync_connection = async_connection.sync_connection

    def reject_writes(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if not sql_is_read_only(statement):
            raise RuntimeError(
                "context-quality benchmark rejected non-read-only SQL: "
                f"{statement.split(None, 1)[0] if statement.strip() else 'unknown'}"
            )

    event.listen(sync_connection, "before_cursor_execute", reject_writes)

    def remove_guard() -> None:
        event.remove(sync_connection, "before_cursor_execute", reject_writes)

    return remove_guard


def _claims(artifact: Mapping[str, Any]) -> tuple[ContextClaimEnvelope, ...]:
    result: list[ContextClaimEnvelope] = []
    for raw in artifact.get("claim_manifest") or []:
        result.append(ContextClaimEnvelope.model_validate(raw))
    return tuple(result)


def _included_claims(
    claims: Sequence[ContextClaimEnvelope],
) -> tuple[ContextClaimEnvelope, ...]:
    return tuple(item for item in claims if item.selection.value == "included")


def _objective_cannot_be_validated_by_exact_self_hash(value: str) -> bool:
    """Identify text whose exact hash cannot establish objective resolution."""

    normalized = " ".join(str(value or "").split()).strip()
    return _SELF_HASH_UNSAFE_OBJECTIVE_RE.fullmatch(normalized) is not None


def _canonical_statement_sha256(value: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _intent_tokens(value: str) -> tuple[str, ...]:
    decoded = html.unescape(str(value or "")).casefold()
    return tuple(re.findall(r"[a-z0-9]+", decoded))


def _contains_intent_phrase(
    objective_tokens: Sequence[str],
    phrase: str,
) -> bool:
    phrase_tokens = _intent_tokens(phrase)
    if not phrase_tokens or len(phrase_tokens) > len(objective_tokens):
        return False
    width = len(phrase_tokens)
    if any(
        tuple(objective_tokens[index : index + width]) == phrase_tokens
        for index in range(len(objective_tokens) - width + 1)
    ):
        return True
    if len(phrase_tokens) != 2:
        return False
    modifier, shared_head = phrase_tokens
    # A coordinated shared head applies to both modifiers: “session and
    # workspace context” names both “session context” and “workspace context”.
    # Keep this deliberately narrow; arbitrary token gaps or disjunctions do
    # not establish the same all-of intent.
    return any(
        objective_tokens[index] == modifier
        and objective_tokens[index + 1] == "and"
        and objective_tokens[index + 3] == shared_head
        for index in range(len(objective_tokens) - 3)
    )


def _intent_concept_match(
    objective: str,
    concepts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    objective_tokens = _intent_tokens(objective)
    matched: list[str] = []
    missing: list[str] = []
    matched_phrases: dict[str, str] = {}
    for concept in concepts:
        name = str(concept.get("name") or "")
        alternatives = tuple(str(item) for item in concept.get("any_of") or [])
        phrase = next(
            (
                item
                for item in alternatives
                if _contains_intent_phrase(objective_tokens, item)
            ),
            None,
        )
        if phrase is None:
            missing.append(name)
        else:
            matched.append(name)
            matched_phrases[name] = phrase
    return {
        "matched": bool(concepts) and not missing,
        "matched_concepts": matched,
        "missing_concepts": missing,
        "matched_phrases": matched_phrases,
    }


def _objective_resolution_provider_event_ids(
    artifact: Mapping[str, Any],
) -> set[str]:
    resolution = artifact.get("objective_resolution")
    if not isinstance(resolution, Mapping):
        return set()
    result: set[str] = set()
    values = resolution.get("source_provider_event_ids")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        result.update(str(item).strip() for item in values if str(item).strip())
    legacy = str(resolution.get("source_provider_event_id") or "").strip()
    if legacy:
        result.add(legacy)
    return result


def _objective_claim_provider_event_ids(
    objective: ContextClaimEnvelope | None,
) -> set[str]:
    if objective is None:
        return set()
    prefix = "objective_provider_event:"
    return {
        str(item)[len(prefix) :].strip()
        for item in objective.evidence_refs
        if str(item).startswith(prefix) and str(item)[len(prefix) :].strip()
    }


def _objective_match_assessment(
    artifact: Mapping[str, Any],
    *,
    objective: ContextClaimEnvelope | None,
    expectations: Mapping[str, Any],
) -> dict[str, Any]:
    statement = objective.statement if objective is not None else ""
    status = str(expectations.get("objective_status") or "")
    objective_hash = _canonical_statement_sha256(statement) if statement else None
    acceptable_hashes = {
        str(item) for item in expectations.get("acceptable_objective_sha256s") or []
    }
    forbidden_hashes = {
        str(item) for item in expectations.get("forbidden_objective_sha256s") or []
    }
    concepts = tuple(
        item
        for item in expectations.get("required_intent_concepts") or []
        if isinstance(item, Mapping)
    )
    concept_match = _intent_concept_match(statement, concepts)
    unsafe_self_hash = bool(
        statement and _objective_cannot_be_validated_by_exact_self_hash(statement)
    )
    forbidden_hash = bool(objective_hash and objective_hash in forbidden_hashes)
    exact_hash_match = bool(
        objective_hash
        and objective_hash in acceptable_hashes
        and not unsafe_self_hash
        and not forbidden_hash
    )
    intent_match = bool(
        concept_match["matched"] and not unsafe_self_hash and not forbidden_hash
    )
    if exact_hash_match:
        text_match_method = "acceptable_hash"
    elif intent_match:
        text_match_method = "required_intent_concepts"
    else:
        text_match_method = "none"

    authority = expectations.get("objective_authority")
    authority = authority if isinstance(authority, Mapping) else {}
    binding_required = authority.get("binding_required") is True
    required_source_ids = {
        str(item) for item in authority.get("required_provider_event_ids") or []
    }
    required_source_groups = tuple(
        frozenset(str(item) for item in group)
        for group in authority.get("required_provider_event_id_groups") or []
        if isinstance(group, Sequence) and not isinstance(group, (str, bytes))
    )
    allowed_source_ids = {
        str(item) for item in authority.get("allowed_provider_event_ids") or []
    }
    resolution_source_ids = _objective_resolution_provider_event_ids(artifact)
    claim_source_ids = _objective_claim_provider_event_ids(objective)
    disallowed_resolution_ids = resolution_source_ids - allowed_source_ids
    disallowed_claim_ids = claim_source_ids - allowed_source_ids
    missing_resolution_ids = required_source_ids - resolution_source_ids
    missing_claim_ids = required_source_ids - claim_source_ids
    missing_resolution_groups = tuple(
        group for group in required_source_groups if group.isdisjoint(resolution_source_ids)
    )
    missing_claim_groups = tuple(
        group for group in required_source_groups if group.isdisjoint(claim_source_ids)
    )
    binding_complete = bool(
        (required_source_ids or required_source_groups)
        and not disallowed_resolution_ids
        and not disallowed_claim_ids
        and not missing_resolution_ids
        and not missing_claim_ids
        and not missing_resolution_groups
        and not missing_claim_groups
    )
    if disallowed_resolution_ids or disallowed_claim_ids:
        authority_status = "invalid_or_incomplete"
    elif binding_complete:
        authority_status = "verified"
    elif binding_required:
        authority_status = "invalid_or_incomplete"
    elif resolution_source_ids or claim_source_ids:
        authority_status = "legacy_partial"
    else:
        authority_status = "legacy_unavailable"

    resolution = artifact.get("objective_resolution")
    resolution_status = (
        str(resolution.get("status") or "")
        if isinstance(resolution, Mapping)
        else ""
    )
    resolution_status_valid = not resolution_status or resolution_status == "resolved"
    authority_accepted = authority_status in {
        "verified",
        "legacy_partial",
        "legacy_unavailable",
    }
    matched = bool(
        objective is not None
        and status == "resolved"
        and resolution_status_valid
        and text_match_method != "none"
        and authority_accepted
    )
    warning = (
        None
        if authority_status == "verified"
        else "OBJECTIVE_AUTHORITY_BINDING_UNAVAILABLE"
        if not binding_required
        else None
    )
    return {
        "matched": matched,
        "text_match_method": text_match_method,
        "objective_sha256": objective_hash,
        "unsafe_self_hash": unsafe_self_hash,
        "forbidden_hash": forbidden_hash,
        "matched_concepts": concept_match["matched_concepts"],
        "missing_concepts": concept_match["missing_concepts"],
        "matched_phrases": concept_match["matched_phrases"],
        "authority": {
            "status": authority_status,
            "binding_required": binding_required,
            "required_provider_event_ids": sorted(required_source_ids),
            "required_provider_event_id_groups": [
                sorted(group) for group in required_source_groups
            ],
            "resolution_provider_event_ids": sorted(resolution_source_ids),
            "claim_provider_event_ids": sorted(claim_source_ids),
            "missing_resolution_provider_event_ids": sorted(missing_resolution_ids),
            "missing_claim_provider_event_ids": sorted(missing_claim_ids),
            "missing_resolution_provider_event_id_groups": [
                sorted(group) for group in missing_resolution_groups
            ],
            "missing_claim_provider_event_id_groups": [
                sorted(group) for group in missing_claim_groups
            ],
            "disallowed_resolution_provider_event_ids": sorted(
                disallowed_resolution_ids
            ),
            "disallowed_claim_provider_event_ids": sorted(disallowed_claim_ids),
        },
        "warning": warning,
    }


def _canonical_path(value: Any) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _gold_expectations(
    gold_case: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return dict(gold_case) if isinstance(gold_case, Mapping) else {}


def _required_dependencies(
    artifact: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        item
        for item in artifact.get("attachment_dependencies") or []
        if isinstance(item, Mapping) and item.get("required") is True
    )


def _attachment_match_assessment(
    artifact: Mapping[str, Any],
    *,
    expectations: Mapping[str, Any],
) -> dict[str, Any]:
    required_dependencies = _required_dependencies(artifact)
    included = _included_claims(_claims(artifact))
    dependency_claims = [
        item for item in included if item.kind == "required_attachment"
    ]
    expected_hashes = {
        str(item)
        for item in expectations.get("required_attachment_sha256s") or []
    }
    expected_count = int(expectations.get("required_attachment_count") or 0)
    candidate_hashes = {
        str(item.get("sha256") or item.get("content_hash") or "")
        for item in required_dependencies
        if item.get("sha256") or item.get("content_hash")
    }
    missing_hashes = expected_hashes - candidate_hashes
    unexpected_hashes = candidate_hashes - expected_hashes
    missing_required_identity = bool(
        len(required_dependencies) < expected_count
        or len(dependency_claims) < expected_count
        or len(candidate_hashes) < expected_count
        or missing_hashes
    )
    unexpected_required_dependencies = bool(
        len(required_dependencies) > expected_count or unexpected_hashes
    )
    identity_complete = bool(
        not missing_required_identity
        and not unexpected_required_dependencies
        and len(required_dependencies) == expected_count
        and candidate_hashes == expected_hashes
        and all(
            bool(item.get("sha256") or item.get("content_hash"))
            for item in required_dependencies
        )
    )
    source_bytes_unavailable_ids = (
        sorted(
            str(item.get("id") or "")
            for item in required_dependencies
            if item.get("available") is not True
        )
        if expected_count and identity_complete
        else []
    )
    receiver_materialization_pending_ids = (
        sorted(
            str(item.get("id") or "")
            for item in required_dependencies
            if item.get("available") is True
            and str(item.get("receiver_availability") or "") != "available"
        )
        if expected_count and identity_complete and not source_bytes_unavailable_ids
        else []
    )
    return {
        "expected_count": expected_count,
        "expected_sha256s": sorted(expected_hashes),
        "candidate_manifest_count": len(required_dependencies),
        "candidate_claim_count": len(dependency_claims),
        "candidate_sha256s": sorted(candidate_hashes),
        "missing_required_identity": missing_required_identity,
        "missing_sha256s": sorted(missing_hashes),
        "unexpected_required_dependencies": unexpected_required_dependencies,
        "unexpected_manifest_count": max(
            0, len(required_dependencies) - expected_count
        ),
        "unexpected_sha256s": sorted(unexpected_hashes),
        "identity_complete": identity_complete,
        "source_bytes_available": bool(
            identity_complete and not source_bytes_unavailable_ids
        ),
        "source_bytes_unavailable_ids": source_bytes_unavailable_ids,
        "receiver_materialization_pending_ids": (
            receiver_materialization_pending_ids
        ),
    }


def _benchmark_session_failures(
    artifact: Mapping[str, Any],
    *,
    baseline_case: Mapping[str, Any],
    gold_case: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    content = str(artifact.get("content") or "")
    claims = _claims(artifact)
    included = _included_claims(claims)
    policy = dict(artifact.get("quality_evaluation") or {})
    failures = {str(item) for item in policy.get("hard_failures") or []}
    expected_content_hash = str(artifact.get("sha256") or "")
    actual_content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if expected_content_hash and expected_content_hash != actual_content_hash:
        failures.add("HASH_OR_LINEAGE_FAILURE")

    objective = next(
        (item for item in included if item.kind == "prior_user_objective"),
        None,
    )
    expectations = _gold_expectations(gold_case)
    if not expectations:
        failures.add("INDEPENDENT_FROZEN_GOLD_MISSING")
    if objective is None:
        failures.add("USER_OBJECTIVE_MISSING")
    objective_match = _objective_match_assessment(
        artifact,
        objective=objective,
        expectations=expectations,
    )
    if objective is not None and not objective_match["matched"]:
        failures.add("UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE")

    attachment_match = _attachment_match_assessment(
        artifact,
        expectations=expectations,
    )
    if attachment_match["missing_required_identity"]:
        failures.discard("REQUIRED_DEPENDENCY_MISSING")
        failures.add("REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED")
    if attachment_match["unexpected_required_dependencies"]:
        failures.discard("REQUIRED_DEPENDENCY_MISSING")
        failures.add("UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY")
    if attachment_match["source_bytes_unavailable_ids"]:
        failures.discard("REQUIRED_DEPENDENCY_MISSING")
        failures.add("REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE")

    included_actions = [
        item
        for item in included
        if item.kind in {"inferred_action", "future_action"}
    ]
    if included_actions or any(marker in content for marker in _SESSION_FORBIDDEN_HEADINGS):
        failures.add("INFERRED_ACTION_PRESENT")
    if any(
        marker in content
        for marker in ("## Done when", "## Acceptance criteria")
    ):
        failures.add("GENERATED_ACCEPTANCE_CRITERIA_PRESENT")

    statements = {
        _canonical_path(item.statement)
        for item in included
        if item.kind == "relevant_file"
    }
    if statements & _SESSION_TARGET_NOISE:
        failures.add("TARGET_INFERENCE_CONTAMINATED_BY_SESSION_ONLY_PUSH")
    required_targets = {
        _canonical_path(item)
        for item in expectations.get("required_relevant_files") or []
    }
    forbidden_targets = {
        _canonical_path(item)
        for item in expectations.get("forbidden_relevant_files") or []
    }
    if not required_targets.issubset(statements) or statements & forbidden_targets:
        failures.add("TARGET_INFERENCE_MISMATCH")

    if _DESTRUCTIVE_INSTRUCTION_RE.search(content):
        failures.add("DESTRUCTIVE_INSTRUCTION_PRESENT")
    return tuple(sorted(failures))


def score_session_artifact(
    artifact: Mapping[str, Any],
    *,
    baseline_case: Mapping[str, Any],
    gold_case: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    content = str(artifact.get("content") or "")
    claims = _claims(artifact)
    included = _included_claims(claims)
    failures = _benchmark_session_failures(
        artifact,
        baseline_case=baseline_case,
        gold_case=gold_case,
    )
    objective = next(
        (item for item in included if item.kind == "prior_user_objective"),
        None,
    )
    expectations = _gold_expectations(gold_case)
    objective_status = str(expectations.get("objective_status") or "")
    objective_match = _objective_match_assessment(
        artifact,
        objective=objective,
        expectations=expectations,
    )
    objective_resolved = bool(objective_match["matched"])
    attachment_match = _attachment_match_assessment(
        artifact,
        expectations=expectations,
    )
    dependency_points = 10.0
    if {
        "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED",
        "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE",
        "UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY",
    } & set(failures):
        dependency_points = 0.0

    authority_points = (
        10.0
        if objective_resolved
        and objective_match["authority"]["status"] == "verified"
        else 5.0
        if objective_resolved
        else 0.0
    )
    fidelity = (
        (10.0 if objective is not None and objective.evidence_refs else 0.0)
        + authority_points
        + dependency_points
    )
    section_groups = (
        bool(objective),
        any(item.section == "state" for item in included),
        any(
            item.kind in {"open_requirement", "blocker", "open_item", "user_constraint"}
            for item in included
        ),
        any(item.kind in {"decision", "failed_attempt"} for item in included),
        any(item.section == "relevant_surfaces" for item in included),
    )
    coverage = 4.0 * sum(section_groups)

    supported = sum(bool(item.evidence_refs) for item in included)
    evidence_ratio = supported / max(1, len(included))
    agent_claims_safely_labeled = all(
        item.truth_state in {"reported", "historical", "unknown", "contested"}
        for item in included
        if item.authority == "agent_report"
    )
    uncertainty_visible = (
        any(item.kind == "known_unknown" for item in included)
        or "[unknown]" in content
    )
    evidence = (
        round(10.0 * evidence_ratio, 2)
        + (3.0 if agent_claims_safely_labeled else 0.0)
        + (2.0 if uncertainty_visible else 0.0)
    )

    boundary = dict(artifact.get("boundary") or {})
    currentness = dict(artifact.get("currentness") or {})
    snapshot_current = not bool(
        boundary.get("has_newer_events") is True
        or currentness.get("state") == "superseded"
    )
    repository = dict(artifact.get("repository") or {})
    freshness = str((repository.get("freshness") or {}).get("status") or "unknown")
    freshness_points = (
        5.0
        if freshness in {"unchanged", "matched", "resolved"}
        else 2.0
        if "repository comparison state" in content.casefold()
        else 0.0
    )
    snapshot = (5.0 if snapshot_current else 0.0) + freshness_points

    destructive = "DESTRUCTIVE_INSTRUCTION_PRESENT" in failures
    delivery = dict(artifact.get("delivery") or {})
    quality = dict(artifact.get("quality_report") or {})
    execution_disabled = (
        delivery.get("ready_for_execution") is False
        and quality.get("automatic_execution_ready") is not True
    )
    safety = (5.0 if not destructive else 0.0) + (
        5.0 if execution_disabled else 0.0
    )

    no_forbidden_headings = not any(
        marker in content for marker in _SESSION_FORBIDDEN_HEADINGS
    )
    no_included_actions = not any(
        item.kind in {"inferred_action", "future_action"}
        for item in included
    )
    background = (
        (3.0 if artifact.get("context_role") == "background_only" else 0.0)
        + (3.0 if no_forbidden_headings else 0.0)
        + (2.0 if "awaiting user instruction" in content.casefold() else 0.0)
        + (2.0 if no_included_actions else 0.0)
    )

    estimated_tokens = int(
        artifact.get("estimated_tokens")
        or (artifact.get("token_accounting") or {}).get("estimated_tokens")
        or max(1, (len(content) + 3) // 4)
    )
    signal = 5.0 if estimated_tokens <= 1_200 else 4.0 if estimated_tokens <= 1_800 else 2.0 if estimated_tokens <= 2_500 else 0.0

    dimensions = {
        "goal_and_dependency_fidelity": round(fidelity, 2),
        "useful_background_coverage": round(coverage, 2),
        "evidence_and_uncertainty": round(min(15.0, evidence), 2),
        "snapshot_freshness": round(snapshot, 2),
        "non_destructive_safety": round(safety, 2),
        "background_only_semantics": round(background, 2),
        "signal_density": round(signal, 2),
    }
    score_before_caps = round(sum(dimensions.values()), 2)
    caps: list[int] = []
    if {
        "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE",
        "USER_OBJECTIVE_MISSING",
    } & set(failures):
        caps.append(29)
    if {
        "INFERRED_ACTION_PRESENT",
        "GENERATED_ACCEPTANCE_CRITERIA_PRESENT",
    } & set(failures):
        caps.append(49)
    if {
        "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED",
        "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE",
        "UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY",
        "REQUIRED_DEPENDENCY_MISSING",
    } & set(failures):
        caps.append(19)
    if "DESTRUCTIVE_INSTRUCTION_PRESENT" in failures:
        caps.append(0)
    if "INDEPENDENT_FROZEN_GOLD_MISSING" in failures:
        caps.append(0)
    score = min([score_before_caps, *caps]) if caps else score_before_caps
    warnings = tuple(sorted({
        *(
            str(item)
            for item in (artifact.get("quality_evaluation") or {}).get("warnings") or []
        ),
        *(
            [str(objective_match["warning"])]
            if objective_match.get("warning")
            else []
        ),
        *(
            ["REQUIRED_ATTACHMENT_RECEIVER_MATERIALIZATION_PENDING"]
            if attachment_match["receiver_materialization_pending_ids"]
            else []
        ),
    }))
    verdict = "reject" if failures else "review" if warnings or score < 85 else "promote"
    return {
        "assessment_kind": SESSION_ASSESSMENT_KIND,
        "promotion_scope": "background_projection_only",
        "frozen_gold": {
            "available": bool(expectations),
            "objective_status": objective_status or None,
            "objective_match": objective_match,
            "attachment_match": attachment_match,
            "required_attachment_count": int(
                expectations.get("required_attachment_count") or 0
            ),
        },
        "rubric_version": SESSION_RUBRIC_VERSION,
        "weights": SESSION_RUBRIC_WEIGHTS,
        "score": round(score, 2),
        "score_before_hard_caps": score_before_caps,
        "dimensions": dimensions,
        "hard_caps_applied": sorted(caps),
        "hard_failures": list(failures),
        "warnings": list(warnings),
        "verdict": verdict,
        "estimated_tokens": estimated_tokens,
        "included_claims": len(included),
        "evidence_supported_claims": supported,
    }


def _foundation(manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = manifest.get("workspace_foundation")
    return dict(value) if isinstance(value, Mapping) else {}


def _coverage_status(foundation: Mapping[str, Any], section: str) -> str:
    quality = foundation.get("quality_report") or {}
    for item in quality.get("section_coverage") or []:
        if str(item.get("section")) == section:
            return str(item.get("status") or "missing")
    return "missing"


def _status_points(status: str, maximum: float) -> float:
    return maximum if status == "complete" else maximum / 2 if status == "partial" else 0.0


def _markdown_section(markdown: str, heading: str) -> str:
    start = markdown.find(heading)
    if start < 0:
        return ""
    remainder = markdown[start + len(heading):]
    next_heading = re.search(r"(?m)^## ", remainder)
    return remainder[: next_heading.start()] if next_heading else remainder


def workspace_repository_snapshot(manifest: Mapping[str, Any]) -> dict[str, Any]:
    foundation = _foundation(manifest)
    repository = dict(foundation.get("repository_state") or {})
    lock_repo = dict((manifest.get("lockfile") or {}).get("repo") or {})
    repo_state = dict(manifest.get("repo_state") or {})
    fingerprint = str(
        repository.get("snapshot_fingerprint")
        or lock_repo.get("snapshot_fingerprint")
        or repo_state.get("snapshot_fingerprint")
        or repo_state.get("status_fingerprint")
        or ""
    )
    changed_paths = repository.get("changes") or lock_repo.get("changed_files") or []
    return {
        "snapshot_fingerprint": fingerprint or None,
        "branch": repository.get("branch") or lock_repo.get("branch") or repo_state.get("branch"),
        "head_commit": repository.get("head_commit") or lock_repo.get("head_commit") or repo_state.get("head_commit"),
        "dirty": bool(
            repository.get("changed_path_count")
            or lock_repo.get("dirty")
            or repo_state.get("dirty")
        ),
        "changed_path_count": int(
            repository.get("changed_path_count") or len(changed_paths)
        ),
    }


def compare_repository_snapshots(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    fields = ("snapshot_fingerprint", "branch", "head_commit", "dirty", "changed_path_count")
    changed = [key for key in fields if baseline.get(key) != candidate.get(key)]
    return {
        "drifted": bool(changed),
        "changed_fields": changed,
        "baseline": dict(baseline),
        "candidate": dict(candidate),
    }


def _workspace_policy(
    markdown: str,
    manifest: Mapping[str, Any],
) -> tuple[tuple[ContextClaimEnvelope, ...], dict[str, Any]]:
    foundation = _foundation(manifest)
    claims = workspace_context_claims(foundation)
    quality = dict(foundation.get("quality_report") or {})
    durable = foundation.get("durable_facts") or foundation.get("durable_knowledge") or []
    verification_complete = quality.get("repository_health") == "passing"
    rendering = dict(manifest.get("rendering") or {})
    expected_markdown_hash = str(rendering.get("markdown_sha256") or "")
    hash_valid = not expected_markdown_hash or expected_markdown_hash == hashlib.sha256(
        markdown.encode("utf-8")
    ).hexdigest()
    evaluation = evaluate_context_candidate(
        context_kind=ContextKind.WORKSPACE,
        candidate_claims=claims,
        rendered_text=markdown,
        metadata={
            "objective_independent": True,
            "copy_ready": quality.get("copy_ready") is True,
            "hash_valid": hash_valid,
            "snapshot_current": True,
            "permissions_current": True,
            "semantic_coverage_score": float(
                quality.get("semantic_coverage_score") or quality.get("score") or 0.0
            ),
            "durable_fact_count": len(durable),
            "verification_complete": verification_complete,
        },
    )
    return claims, evaluation.model_dump(mode="json")


def score_workspace_context(
    markdown: str,
    manifest: Mapping[str, Any],
    *,
    controller_enforced: bool = False,
) -> dict[str, Any]:
    foundation = _foundation(manifest)
    quality = dict(foundation.get("quality_report") or {})
    claims, policy = _workspace_policy(markdown, manifest)
    product = _status_points(_coverage_status(foundation, "product"), 20.0)
    product_section = _markdown_section(markdown, "## Product and boundaries")
    if product and ("…" in product_section or "..." in product_section):
        product = max(0.0, product - 3.0)
    capability = _status_points(_coverage_status(foundation, "capabilities"), 20.0)
    architecture_repository = (
        _status_points(_coverage_status(foundation, "architecture"), 10.0)
        + _status_points(_coverage_status(foundation, "repository"), 10.0)
    )
    durable = foundation.get("durable_facts") or foundation.get("durable_knowledge") or []
    durable_claims = [item for item in claims if item.kind == "durable_project_fact"]
    supported_durable = sum(bool(item.evidence_refs) for item in durable_claims)
    durable_points = min(10.0, 2.0 * len(durable)) + (
        5.0 * supported_durable / max(1, len(durable_claims))
        if durable_claims
        else 0.0
    )
    snapshot = workspace_repository_snapshot(manifest)
    verification_complete = quality.get("repository_health") == "passing"
    freshness = (5.0 if snapshot.get("snapshot_fingerprint") else 0.0) + (
        5.0 if verification_complete else 4.0
    )
    policy_failures = tuple(sorted(str(item) for item in policy.get("hard_failures") or []))
    safety = (
        (5.0 if not policy_failures else 0.0)
        + (5.0 if (manifest.get("focus") or {}).get("kind") == "project_snapshot" else 0.0)
    )
    estimated_tokens = max(1, (len(markdown) + 3) // 4)
    signal = 5.0 if estimated_tokens <= 4_000 else 3.0 if estimated_tokens <= 7_000 else 1.0 if estimated_tokens <= 10_000 else 0.0
    dimensions = {
        "product_truth": round(product, 2),
        "capability_and_workflow_coverage": round(capability, 2),
        "architecture_and_current_repository_usefulness": round(architecture_repository, 2),
        "durable_knowledge_and_provenance": round(min(15.0, durable_points), 2),
        "freshness_and_evidence_labels": round(freshness, 2),
        "background_and_non_destructive_safety": round(safety, 2),
        "signal_density": round(signal, 2),
    }
    score = round(sum(dimensions.values()), 2)
    findings: set[str] = set(policy_failures)
    if not durable:
        findings.add("DURABLE_PROVENANCE_EMPTY")
    if not verification_complete:
        findings.add("REQUIRED_VERIFICATION_MISSING")
    controller_decision = str(policy.get("decision") or "reject")
    copy_allowed = bool(
        quality.get("copy_ready") is True
        and (
            not controller_enforced
            or controller_decision in {"promote", "no_change"}
        )
    )
    if copy_allowed and score < 85:
        findings.add("AUTO_PROMOTION_UNJUSTIFIED")
    warnings = tuple(sorted(str(item) for item in policy.get("warnings") or []))
    verdict = "reject" if policy_failures else "review" if warnings or score < 85 else "promote"
    return {
        "rubric_version": WORKSPACE_RUBRIC_VERSION,
        "weights": WORKSPACE_RUBRIC_WEIGHTS,
        "score": score,
        "dimensions": dimensions,
        "policy_hard_failures": list(policy_failures),
        "warnings": list(warnings),
        "findings": sorted(findings),
        "verdict": verdict,
        "estimated_tokens": estimated_tokens,
        "claim_count": len(claims),
        "repository_snapshot": snapshot,
        "delivery_control": {
            "controller_enforced": controller_enforced,
            "controller_decision": controller_decision,
            "copy_allowed": copy_allowed,
        },
        "compiler_semantic_coverage_score": float(
            quality.get("semantic_coverage_score") or quality.get("score") or 0.0
        ),
    }


async def _render_session_case(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    baseline_case: Mapping[str, Any],
    gold_case: Mapping[str, Any],
) -> dict[str, Any]:
    checkpoint_id = UUID(str(baseline_case["checkpoint_id"]))
    checkpoint = await get_checkpoint(session, checkpoint_id)
    if checkpoint is None:
        raise BenchmarkInputError(f"checkpoint not found: {checkpoint_id}")
    if checkpoint.workspace_id != workspace_id:
        raise BenchmarkInputError(
            f"checkpoint {checkpoint_id} belongs to a different workspace"
        )
    expected_payload_hash = str(baseline_case["checkpoint_payload_sha256"])
    if checkpoint.payload_sha256 != expected_payload_hash:
        raise BenchmarkInputError(
            f"checkpoint payload hash mismatch: {checkpoint_id}"
        )
    request_verbatim = await resolve_session_handoff_request_verbatim(
        session,
        checkpoint,
        access_scope=AccessScope.local(),
    )
    if request_verbatim is None:
        raise BenchmarkInputError(
            f"checkpoint has no lossless request: {checkpoint_id}"
        )
    supporting_context = tuple(await resolve_session_handoff_supporting_context(
        session,
        checkpoint,
        request_verbatim=request_verbatim,
        access_scope=AccessScope.local(),
    ))
    attachments = tuple(await resolve_session_handoff_attachment_descriptors(
        session,
        checkpoint,
        request_verbatim=request_verbatim,
        access_scope=AccessScope.local(),
    ))
    checkpoint_data = checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    artifact = build_session_context_artifact(
        checkpoint,
        request_verbatim=request_verbatim,
        supporting_context=supporting_context,
        trusted_attachment_descriptors=attachments,
        allow_local_artifacts=False,
        checkpoint_data=checkpoint_data,
        repository_comparison=None,
    )
    content = str(artifact.get("content") or "")
    rendered_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    rubric = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=gold_case,
    )
    baseline_failures = {
        str(item) for item in baseline_case.get("hard_failures") or []
    }
    candidate_failures = set(rubric["hard_failures"])
    return {
        "case_id": baseline_case.get("case_id"),
        "checkpoint_id": str(checkpoint_id),
        "checkpoint_payload_sha256": checkpoint.payload_sha256,
        "baseline": {
            "rendered_sha256": baseline_case.get("rendered_sha256"),
            "rendered_bytes": baseline_case.get("rendered_bytes"),
            "score": baseline_case.get("score"),
            "verdict": baseline_case.get("verdict"),
            "hard_failures": sorted(baseline_failures),
        },
        "candidate": {
            "semantic_schema_version": artifact.get("semantic_schema_version"),
            "renderer_version": artifact.get("render_variant"),
            "rendered_sha256": rendered_hash,
            "rendered_bytes": len(content.encode("utf-8")),
            **rubric,
        },
        "comparison": {
            "score_delta": round(
                float(rubric["score"]) - float(baseline_case.get("score") or 0.0),
                2,
            ),
            "render_changed": rendered_hash != baseline_case.get("rendered_sha256"),
            "resolved_baseline_failures": sorted(baseline_failures - candidate_failures),
            "remaining_baseline_failures": sorted(baseline_failures & candidate_failures),
            "introduced_failures": sorted(candidate_failures - baseline_failures),
        },
    }


async def _workspace_benchmark(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    repo_path: str,
    baseline_workspace: Mapping[str, Any],
) -> dict[str, Any]:
    pack_id = UUID(str(baseline_workspace["context_pack_id"]))
    saved = await session.get(ContextPack, pack_id)
    if saved is None:
        raise BenchmarkInputError(f"baseline ContextPack not found: {pack_id}")
    if saved.workspace_id != workspace_id:
        raise BenchmarkInputError("baseline ContextPack belongs to a different workspace")
    saved_markdown_hash = hashlib.sha256(saved.markdown.encode("utf-8")).hexdigest()
    if saved_markdown_hash != baseline_workspace.get("markdown_sha256"):
        raise BenchmarkInputError("baseline Workspace Context markdown hash mismatch")
    try:
        saved_manifest = json.loads(saved.manifest or "{}")
    except json.JSONDecodeError as exc:
        raise BenchmarkInputError("baseline ContextPack manifest is invalid JSON") from exc
    saved_foundation = _foundation(saved_manifest)
    expected_semantic_hash = str(
        baseline_workspace.get("foundation_semantic_sha256") or ""
    )
    expected_artifact_hash = str(
        baseline_workspace.get("foundation_artifact_sha256") or ""
    )
    if (
        expected_semantic_hash
        and str(saved_foundation.get("semantic_sha256") or "")
        != expected_semantic_hash
    ):
        raise BenchmarkInputError(
            "baseline Workspace Context semantic hash mismatch"
        )
    if (
        expected_artifact_hash
        and str(saved_foundation.get("artifact_sha256") or "")
        != expected_artifact_hash
    ):
        raise BenchmarkInputError(
            "baseline Workspace Context artifact hash mismatch"
        )
    baseline_assessment = score_workspace_context(saved.markdown, saved_manifest)

    candidate = await ContextCompiler(session).compile_context_pack(
        "",
        workspace_id=workspace_id,
        repo_path=repo_path,
        persist=False,
        objective_kind="project_snapshot",
        objective_origin="project_snapshot",
        access_scope=AccessScope.local(),
    )
    candidate_assessment = score_workspace_context(
        candidate.markdown,
        candidate.manifest,
        controller_enforced=True,
    )
    candidate_markdown_hash = hashlib.sha256(
        candidate.markdown.encode("utf-8")
    ).hexdigest()
    drift = compare_repository_snapshots(
        baseline_assessment["repository_snapshot"],
        candidate_assessment["repository_snapshot"],
    )
    baseline_findings = set(baseline_workspace.get("hard_failures") or [])
    candidate_findings = set(candidate_assessment["findings"])
    return {
        "baseline": {
            "context_pack_id": str(pack_id),
            "recorded_score": baseline_workspace.get("brutal_score"),
            "recorded_verdict": baseline_workspace.get("verdict"),
            "recorded_findings": sorted(baseline_findings),
            "markdown_sha256": saved_markdown_hash,
            "recomputed": baseline_assessment,
        },
        "candidate": {
            "context_pack_id": candidate.context_pack_id,
            "persisted": False,
            "markdown_sha256": candidate_markdown_hash,
            "markdown_chars": len(candidate.markdown),
            **candidate_assessment,
        },
        "comparison": {
            "score_delta_from_recorded": round(
                float(candidate_assessment["score"])
                - float(baseline_workspace.get("brutal_score") or 0.0),
                2,
            ),
            "score_delta_from_recomputed": round(
                float(candidate_assessment["score"])
                - float(baseline_assessment["score"]),
                2,
            ),
            "resolved_baseline_findings": sorted(
                baseline_findings - candidate_findings
            ),
            "remaining_baseline_findings": sorted(
                baseline_findings & candidate_findings
            ),
            "introduced_findings": sorted(
                candidate_findings - baseline_findings
            ),
            "repository_drift": drift,
            "interpretation": (
                "Repository drift is reported separately; score changes across "
                "different snapshots are not a compiler-only causal comparison."
            ),
        },
    }


def _session_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    baseline_scores = [float((item.get("baseline") or {}).get("score") or 0.0) for item in cases]
    candidate_scores = [float((item.get("candidate") or {}).get("score") or 0.0) for item in cases]
    verdicts = [str((item.get("candidate") or {}).get("verdict") or "reject") for item in cases]
    count = len(cases)
    return {
        "assessment_kind": SESSION_ASSESSMENT_KIND,
        "promotion_scope": "background_projection_only",
        "count": count,
        "baseline_mean_score": round(sum(baseline_scores) / max(1, count), 2),
        "candidate_mean_score": round(sum(candidate_scores) / max(1, count), 2),
        "mean_score_delta": round(
            (sum(candidate_scores) - sum(baseline_scores)) / max(1, count),
            2,
        ),
        "promoted": verdicts.count("promote"),
        "review": verdicts.count("review"),
        "rejected": verdicts.count("reject"),
    }


async def run_context_quality_benchmark(
    session: AsyncSession,
    *,
    baseline: Mapping[str, Any],
    repo_path: str,
    mode: str = "all",
    frozen_gold: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"all", "sessions", "workspace"}:
        raise BenchmarkInputError("mode must be all, sessions, or workspace")
    validated_gold: dict[str, Any] | None = None
    gold_cases: dict[tuple[str, str], Mapping[str, Any]] = {}
    if mode in {"all", "sessions"}:
        if frozen_gold is None:
            raise BenchmarkInputError(
                "session benchmarking requires a separately supplied frozen gold "
                "manifest; candidate-derived expectations are forbidden"
            )
        validated_gold = validate_frozen_gold(frozen_gold, baseline=baseline)
        gold_cases = {
            (str(case["case_id"]), str(case["checkpoint_id"])): case
            for case in validated_gold["session_contexts"]
        }
    workspace_id = UUID(str((baseline.get("workspace") or {})["id"]))
    remove_guard = await install_read_only_sql_guard(session)
    try:
        session_rows: list[dict[str, Any]] = []
        if mode in {"all", "sessions"}:
            for baseline_case in baseline.get("session_contexts") or []:
                identity = (
                    str(baseline_case.get("case_id") or ""),
                    str(baseline_case.get("checkpoint_id") or ""),
                )
                session_rows.append(await _render_session_case(
                    session,
                    workspace_id=workspace_id,
                    baseline_case=baseline_case,
                    gold_case=gold_cases[identity],
                ))
        workspace_result = None
        if mode in {"all", "workspace"}:
            workspace_result = await _workspace_benchmark(
                session,
                workspace_id=workspace_id,
                repo_path=repo_path,
                baseline_workspace=baseline["workspace_context"],
            )
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "read_only": True,
            "selection": {
                "strategy": "frozen_exact_ids",
                "latest_selection_forbidden": True,
                "checkpoint_count": len(session_rows),
            },
            "baseline_schema_version": baseline.get("schema_version"),
            "baseline_sha256": baseline_sha256(baseline),
            "frozen_gold": (
                {
                    "schema_version": validated_gold.get("schema_version"),
                    "sha256": baseline_sha256(validated_gold),
                    "provenance": dict(validated_gold.get("provenance") or {}),
                    "case_count": len(validated_gold.get("session_contexts") or []),
                    "candidate_derived_expectations": False,
                }
                if validated_gold is not None
                else None
            ),
            "workspace_id": str(workspace_id),
            "sessions": {
                "summary": _session_summary(session_rows),
                "cases": session_rows,
            } if mode in {"all", "sessions"} else None,
            "workspace": workspace_result,
        }
    finally:
        remove_guard()
        await session.rollback()


__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "FROZEN_GOLD_SCHEMA_VERSION",
    "BenchmarkInputError",
    "SESSION_ASSESSMENT_KIND",
    "baseline_sha256",
    "compare_repository_snapshots",
    "load_frozen_baseline",
    "load_frozen_gold",
    "run_context_quality_benchmark",
    "score_session_artifact",
    "score_workspace_context",
    "sql_is_read_only",
    "validate_frozen_gold",
    "workspace_repository_snapshot",
]
