from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from app.services.session_summary import normalize_substantive_user_request


OBJECTIVE_RESOLUTION_SCHEMA_VERSION = "session_objective_resolution.v1"


class ObjectiveClassification(StrEnum):
    SUBSTANTIVE = "substantive"
    DEICTIC = "deictic"
    INTERRUPTION_MARKER = "interruption_marker"
    COMPLETION_MARKER = "completion_marker"
    PROVIDER_COMPACTION_WRAPPER = "provider_compaction_wrapper"
    NON_SUBSTANTIVE = "non_substantive"


class ObjectiveResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ObjectiveAntecedent:
    text: str
    source: str
    source_event_id: str | None = None
    source_event_ids: tuple[str, ...] = ()
    source_provider_event_ids: tuple[str, ...] = ()
    source_session_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectiveResolution:
    classification: ObjectiveClassification
    status: ObjectiveResolutionStatus
    candidate_text: str
    resolved_text: str | None
    resolution_source: str | None
    reason: str
    antecedent_sha256: str | None = None
    source_event_id: str | None = None
    source_event_ids: tuple[str, ...] = ()
    source_provider_event_ids: tuple[str, ...] = ()
    source_session_event_ids: tuple[str, ...] = ()

    @property
    def blocks_copy(self) -> bool:
        return self.status is ObjectiveResolutionStatus.UNRESOLVED

    @property
    def blocks_execution(self) -> bool:
        if self.classification is ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER:
            return bool(
                self.status is ObjectiveResolutionStatus.UNRESOLVED
                or self.resolution_source != "embedded_current_user_request"
            )
        return bool(
            self.status is ObjectiveResolutionStatus.UNRESOLVED
            or self.classification
            in {
                ObjectiveClassification.INTERRUPTION_MARKER,
                ObjectiveClassification.COMPLETION_MARKER,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OBJECTIVE_RESOLUTION_SCHEMA_VERSION,
            "classification": self.classification.value,
            "status": self.status.value,
            "candidate_text": self.candidate_text,
            "candidate_sha256": _sha256(self.candidate_text),
            "resolved_text": self.resolved_text,
            "resolved_sha256": (
                _sha256(self.resolved_text) if self.resolved_text is not None else None
            ),
            "resolution_source": self.resolution_source,
            "reason": self.reason,
            "antecedent_sha256": self.antecedent_sha256,
            "source_event_id": self.source_event_id,
            "source_event_ids": list(self.source_event_ids),
            "source_provider_event_ids": list(self.source_provider_event_ids),
            "source_session_event_ids": list(self.source_session_event_ids),
            "blocks_copy": self.blocks_copy,
            "blocks_execution": self.blocks_execution,
            "requires_fresh_user_lead": self.blocks_execution,
        }


_INTERRUPTION_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"you\s+have\s+[\d,]+\s+(?:weighted\s+)?tokens?\s+left|"
    r"[\[(<]?\s*(?:conversation|generation|request|response|session|task|turn)?\s*"
    r"(?:interrupted|interruption|paused|stopped)"
    r"(?:\s+by\s+(?:the\s+)?user(?:\s+for\s+[a-z0-9 _-]+)?)?\s*[\])>]?"
    r")\s*[.!?…]*\s*$",
    re.IGNORECASE,
)
_COMPLETION_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"(?:(?:all|the)\s+agents?\s+(?:are|have)\s+)"
    r"(?:done|finished|completed)(?:\s+(?:with\s+)?(?:their\s+)?work)?|"
    r"(?:(?:all|it|that|this|the\s+(?:task|work))\s+(?:is\s+)?)?"
    r"(?:done|finished|completed|fixed|implemented|ready|resolved|shipped)"
    r"(?:\s+now)?"
    r")(?:\s*[,;:-]?\s*(?:thanks|thank\s+you))?[.!?…]*\s*$",
    re.IGNORECASE,
)
_PROVIDER_COMPACTION_WRAPPER_RE = re.compile(
    r"^\s*(?:this\s+(?:session|conversation)\s+is\s+being\s+continued\s+from|"
    r"this\s+is\s+a\s+continuation\s+of)\s+a\s+previous\s+conversation\s+"
    r"that\s+ran\s+out\s+of\s+context\b|"
    r"^\s*(?:the\s+)?summary\s+below\s+covers\s+the\s+earlier\s+portion\b",
    re.IGNORECASE,
)
_CURRENT_USER_REQUEST_TAG_RE = re.compile(
    r"<current_user_(?:request|instruction)>\s*(?P<request>[\s\S]+?)\s*"
    r"</current_user_(?:request|instruction)>",
    re.IGNORECASE,
)
_CURRENT_USER_REQUEST_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:current|latest)\s+user\s+"
    r"(?:request|instruction)\s*:?\s*(?P<inline>[^\n]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BARE_DEICTIC_RE = re.compile(
    r"^\s*(?:please\s+)?(?:this|that|it|those|these|the\s+same|"
    r"(?:the\s+)?(?:same\s+|current\s+|previous\s+)?"
    r"(?:issue|problem|bug|task|request|work|session\s+context)(?:\s+again)?)"
    r"[.!?…]*\s*$",
    re.IGNORECASE,
)
_ACCEPTANCE_REFERENCE_RE = re.compile(
    r"^\s*(?:yes[,;:]?\s*)?(?:go\s+ahead(?:\s+then)?(?:\s+and\s+(?:fix|address|"
    r"resolve)\s+(?:the\s+)?(?:(?:damn|fucking)\s+)?(?:issues?|problems?))?|"
    r"proceed|do\s+it|apply\s+it|"
    r"use\s+(?:it|that|this)|sounds\s+good|looks\s+good)"
    r"[.!?…]*\s*$",
    re.IGNORECASE,
)
_SCOPE_REFERENCE_RE = re.compile(
    r"^\s*(?:both|all|each)\s+(?:for|in|across|on)\b[\s\S]*$",
    re.IGNORECASE,
)
_ISSUE_REFERENCE_RE = re.compile(
    r"^\s*what\s+about\s+(?:the\s+)?(?:issues?|problems?|bugs?)\s+from\s+"
    r"(?:the\s+)?(?:session|task|request)(?:\s+id)?\s+(?:i|we)\s+"
    r"(?:shared|mentioned|provided|sent)\b[.!?…]*\s*$",
    re.IGNORECASE,
)
_REFERENTIAL_SUBSTANTIVE_TAIL_RE = re.compile(
    r"^\s*(?:same|still)\s+(?:issue|problem|bug)\b[\s,;:.!?—–-]*"
    r"(?P<tail>[\s\S]+)$",
    re.IGNORECASE,
)
_SUBSTANTIVE_TAIL_CUE_RE = re.compile(
    r"\b(?:compare|diagnose|explain|investigate|review|test|verify|why)\b|"
    r"\b(?:i|we)\s+(?:believe|suspect|think|wonder)\b",
    re.IGNORECASE,
)
_DEICTIC_ACTION_RE = re.compile(
    r"^\s*(?:please\s+)?(?P<action>fix|do|apply|use|implement|change|update|"
    r"remove|replace|correct|restore|revert|redo|rework|review|finish|complete|"
    r"continue|resume|proceed\s+with)\s+"
    r"(?:it|this|that|those|these|the\s+(?:fix|issue|problem|task|request|work|"
    r"same|first\s+one|second\s+one))[.!?…]*\s*$|"
    r"^\s*(?P<retry>try)(?:\s+(?:it|this|that))?\s+again[.!?…]*\s*$|"
    r"^\s*(?P<continue>continue|resume)(?:\s+(?:it|this|that|the\s+work|"
    r"the\s+task))?[.!?…]*\s*$|"
    r"^\s*(?:same|still)\s+(?P<failure>issue|problem|bug)\b[\s\S]*$|"
    r"\bignore\s+(?:the\s+)?(?:recent|last|previous|wrong)\b[\s\S]{0,160}"
    r"\b(?P<tail_continue>continue|resume)\b[.!?…]*\s*$",
    re.IGNORECASE,
)
_DEICTIC_STATUS_RE = re.compile(
    r"^\s*(?:so\s+)?(?:is|are|was|were|did|does|has|have)\s+"
    r"(?:it|this|that|the\s+(?:task|work|fix|issue|problem))\b[^\n]*\?\s*$|"
    r"^\s*(?:did|do|does|have|has|can|could)\s+(?:you|u)\s+"
    r"(?:fix|finish|complete|resolve|review|update)\s+"
    r"(?:it|this|that|the\s+(?:task|work|fix|issue|problem))\b[^\n]*\?\s*$|"
    r"^\s*(?:this|that|it)\s+(?:is|was)\s+(?:still\s+)?"
    r"(?:broken|incorrect|not\s+fixed|not\s+working|wrong)\b|"
    r"^[\s\S]{0,200}\b(?:does|did|is|was)\s+(?:it|this|that)\s+"
    r"(?:really\s+)?(?:fixed|resolved|work|working)\s*\?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_TASK_REQUEST_RE = re.compile(
    r"^\s*(?:please\s+)?(?:add|build|change|create|debug|diagnose|document|"
    r"explain|fix|implement|improve|investigate|make|remove|rename|replace|"
    r"review|test|update|write)\b",
    re.IGNORECASE,
)


_ANTECEDENT_SOURCE_PRIORITY = {
    "conversation_active_goal": 0,
    "recovered_handoff_request": 1,
    "conversation_root_goal": 2,
    "stored_root_request": 3,
    "stored_request_fragment": 4,
    "supporting_user_turn": 5,
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def classify_objective(value: str | None) -> ObjectiveClassification:
    """Classify one candidate without assuming that prior context exists."""

    text = str(value or "").strip()
    if _INTERRUPTION_MARKER_RE.fullmatch(text):
        return ObjectiveClassification.INTERRUPTION_MARKER
    if _COMPLETION_MARKER_RE.fullmatch(text):
        return ObjectiveClassification.COMPLETION_MARKER
    if _PROVIDER_COMPACTION_WRAPPER_RE.search(text):
        return ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER
    referential_tail = _REFERENTIAL_SUBSTANTIVE_TAIL_RE.fullmatch(text)
    if referential_tail is not None and _SUBSTANTIVE_TAIL_CUE_RE.search(
        referential_tail.group("tail")
    ):
        return ObjectiveClassification.SUBSTANTIVE
    if (
        _BARE_DEICTIC_RE.fullmatch(text)
        or _ACCEPTANCE_REFERENCE_RE.fullmatch(text)
        or _SCOPE_REFERENCE_RE.fullmatch(text)
        or _ISSUE_REFERENCE_RE.fullmatch(text)
        or _DEICTIC_ACTION_RE.search(text)
        or _DEICTIC_STATUS_RE.search(text)
    ):
        return ObjectiveClassification.DEICTIC
    if (
        normalize_substantive_user_request(text) is not None
        or (text and _EXPLICIT_TASK_REQUEST_RE.search(text))
    ):
        return ObjectiveClassification.SUBSTANTIVE
    return ObjectiveClassification.NON_SUBSTANTIVE


def _embedded_current_user_request(value: str) -> str | None:
    tag_match = _CURRENT_USER_REQUEST_TAG_RE.search(value)
    if tag_match is not None:
        candidate = tag_match.group("request").strip()
        return (
            candidate
            if classify_objective(candidate) is ObjectiveClassification.SUBSTANTIVE
            else None
        )
    heading_match = _CURRENT_USER_REQUEST_HEADING_RE.search(value)
    if heading_match is None:
        return None
    inline = str(heading_match.group("inline") or "").strip()
    candidate = inline or value[heading_match.end() :].strip()
    next_heading = re.search(r"^\s*#{1,6}\s+", candidate, re.MULTILINE)
    if next_heading is not None:
        candidate = candidate[: next_heading.start()].strip()
    return (
        candidate
        if classify_objective(candidate) is ObjectiveClassification.SUBSTANTIVE
        else None
    )


def objective_antecedents(
    *,
    conversation_state: Mapping[str, Any] | None = None,
    goal_payload: Mapping[str, Any] | None = None,
    supporting_context: Iterable[Mapping[str, Any]] = (),
) -> tuple[ObjectiveAntecedent, ...]:
    """Collect only structured, user-authored fields that can identify a prior task."""

    values: list[ObjectiveAntecedent] = []

    def add(value: Any, source: str, event_id: Any = None) -> None:
        text = str(value or "").strip()
        if not text:
            return
        values.append(
            ObjectiveAntecedent(
                text=text,
                source=source,
                source_event_id=str(event_id or "").strip() or None,
            )
        )

    state = conversation_state if isinstance(conversation_state, Mapping) else {}
    active_goal = state.get("active_goal")
    active_goal = active_goal if isinstance(active_goal, Mapping) else {}
    add(
        active_goal.get("composite_request_verbatim"),
        "conversation_active_goal",
        active_goal.get("root_event_id"),
    )
    add(
        active_goal.get("root_request_verbatim"),
        "conversation_root_goal",
        active_goal.get("root_event_id"),
    )

    payload = goal_payload if isinstance(goal_payload, Mapping) else {}
    add(
        payload.get("root_request_verbatim"),
        "stored_root_request",
        payload.get("root_event_id"),
    )
    fragments = payload.get("request_fragments")
    if isinstance(fragments, list):
        for item in fragments:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("dialogue_act") or item.get("act") or "") not in {
                "new_goal",
                "",
            }:
                continue
            add(
                item.get("request_verbatim"),
                "stored_request_fragment",
                item.get("provider_event_id") or item.get("event_id"),
            )

    for item in supporting_context:
        if not isinstance(item, Mapping) or str(item.get("role") or "").casefold() != "user":
            continue
        add(
            item.get("text"),
            "supporting_user_turn",
            item.get("source_event_id"),
        )
    return tuple(values)


def _select_antecedent(
    candidate: str,
    antecedents: Iterable[ObjectiveAntecedent],
) -> tuple[ObjectiveAntecedent | None, str]:
    candidate_key = _normalized(candidate).casefold()
    candidates: list[ObjectiveAntecedent] = []
    seen: set[tuple[int, str]] = set()
    for item in antecedents:
        if classify_objective(item.text) is not ObjectiveClassification.SUBSTANTIVE:
            continue
        normalized = _normalized(item.text)
        if not normalized or normalized.casefold() == candidate_key:
            continue
        priority = _ANTECEDENT_SOURCE_PRIORITY.get(item.source, 100)
        key = (priority, normalized.casefold())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)
    if not candidates:
        return None, "no_substantive_antecedent"
    best_priority = min(
        _ANTECEDENT_SOURCE_PRIORITY.get(item.source, 100) for item in candidates
    )
    best = [
        item
        for item in candidates
        if _ANTECEDENT_SOURCE_PRIORITY.get(item.source, 100) == best_priority
    ]
    unique = {_normalized(item.text).casefold(): item for item in best}
    if len(unique) != 1:
        return None, "ambiguous_substantive_antecedent"
    return next(iter(unique.values())), "unique_structured_antecedent"


def _bind_deictic(candidate: str, antecedent: str) -> str | None:
    if _ACCEPTANCE_REFERENCE_RE.fullmatch(candidate):
        return f"Proceed with the unique antecedent objective:\n\n{antecedent.strip()}"
    if _SCOPE_REFERENCE_RE.fullmatch(candidate):
        return (
            "Apply the user's scope clarification to the antecedent objective:\n\n"
            f"{antecedent.strip()}\n\nScope clarification:\n{candidate.strip()}"
        )
    if _ISSUE_REFERENCE_RE.fullmatch(candidate):
        return f"Address the referenced antecedent issues:\n\n{antecedent.strip()}"
    if _DEICTIC_STATUS_RE.search(candidate):
        return f"Report the status of the antecedent objective:\n\n{antecedent.strip()}"
    match = _DEICTIC_ACTION_RE.search(candidate)
    if match is None:
        return None
    if match.group("failure"):
        prefix = "Continue addressing the unresolved antecedent objective"
    elif match.group("retry"):
        prefix = "Retry the antecedent objective"
    elif match.group("continue") or match.group("tail_continue"):
        prefix = "Continue the antecedent objective"
    else:
        action = _normalized(match.group("action") or "continue").capitalize()
        prefix = f"{action} the antecedent objective"
    return f"{prefix}:\n\n{antecedent.strip()}"


def resolve_objective(
    candidate: str | None,
    *,
    antecedents: Iterable[ObjectiveAntecedent] = (),
    candidate_source_event_ids: Iterable[str] = (),
    candidate_source_provider_event_ids: Iterable[str] = (),
    candidate_source_session_event_ids: Iterable[str] = (),
) -> ObjectiveResolution:
    """Resolve a candidate conservatively, or return an explicit copy blocker."""

    candidate_text = str(candidate or "").strip()
    candidate_event_ids = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in candidate_source_event_ids
            if str(value).strip()
        )
    )
    candidate_provider_event_ids = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in candidate_source_provider_event_ids
            if str(value).strip()
        )
    )
    candidate_session_event_ids = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in candidate_source_session_event_ids
            if str(value).strip()
        )
    )
    classification = classify_objective(candidate_text)
    if classification is ObjectiveClassification.SUBSTANTIVE:
        return ObjectiveResolution(
            classification=classification,
            status=ObjectiveResolutionStatus.RESOLVED,
            candidate_text=candidate_text,
            resolved_text=candidate_text,
            resolution_source="direct_user_request",
            reason="candidate_is_self_contained",
            source_event_id=(candidate_event_ids[-1] if candidate_event_ids else None),
            source_event_ids=candidate_event_ids,
            source_provider_event_ids=candidate_provider_event_ids,
            source_session_event_ids=candidate_session_event_ids,
        )

    if classification is ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER:
        extracted_request = _embedded_current_user_request(candidate_text)
        if extracted_request is not None:
            return ObjectiveResolution(
                classification=classification,
                status=ObjectiveResolutionStatus.RESOLVED,
                candidate_text=candidate_text,
                resolved_text=extracted_request,
                resolution_source="embedded_current_user_request",
                reason="explicit_current_user_request_extracted_from_provider_wrapper",
                source_event_id=(candidate_event_ids[-1] if candidate_event_ids else None),
                source_event_ids=candidate_event_ids,
                source_provider_event_ids=candidate_provider_event_ids,
                source_session_event_ids=candidate_session_event_ids,
            )

    if classification is ObjectiveClassification.NON_SUBSTANTIVE:
        return ObjectiveResolution(
            classification=classification,
            status=ObjectiveResolutionStatus.UNRESOLVED,
            candidate_text=candidate_text,
            resolved_text=None,
            resolution_source=None,
            reason="candidate_does_not_define_user_work",
            source_event_id=(candidate_event_ids[-1] if candidate_event_ids else None),
            source_event_ids=candidate_event_ids,
            source_provider_event_ids=candidate_provider_event_ids,
            source_session_event_ids=candidate_session_event_ids,
        )

    antecedent, antecedent_reason = _select_antecedent(candidate_text, antecedents)
    if antecedent is None:
        return ObjectiveResolution(
            classification=classification,
            status=ObjectiveResolutionStatus.UNRESOLVED,
            candidate_text=candidate_text,
            resolved_text=None,
            resolution_source=None,
            reason=antecedent_reason,
            source_event_id=(candidate_event_ids[-1] if candidate_event_ids else None),
            source_event_ids=candidate_event_ids,
            source_provider_event_ids=candidate_provider_event_ids,
            source_session_event_ids=candidate_session_event_ids,
        )

    antecedent_event_ids = tuple(
        dict.fromkeys(
            (
                *antecedent.source_event_ids,
                *(
                    (antecedent.source_event_id,)
                    if antecedent.source_event_id
                    else ()
                ),
            )
        )
    )
    authority_event_ids = tuple(
        dict.fromkeys((*antecedent_event_ids, *candidate_event_ids))
    )
    authority_provider_event_ids = tuple(
        dict.fromkeys(
            (*antecedent.source_provider_event_ids, *candidate_provider_event_ids)
        )
    )
    authority_session_event_ids = tuple(
        dict.fromkeys(
            (*antecedent.source_session_event_ids, *candidate_session_event_ids)
        )
    )

    if classification is ObjectiveClassification.DEICTIC:
        resolved_text = _bind_deictic(candidate_text, antecedent.text)
        if resolved_text is None:
            return ObjectiveResolution(
                classification=classification,
                status=ObjectiveResolutionStatus.UNRESOLVED,
                candidate_text=candidate_text,
                resolved_text=None,
                resolution_source=antecedent.source,
                reason="deictic_action_cannot_be_bound_safely",
                antecedent_sha256=_sha256(antecedent.text),
                source_event_id=antecedent.source_event_id,
                source_event_ids=authority_event_ids,
                source_provider_event_ids=authority_provider_event_ids,
                source_session_event_ids=authority_session_event_ids,
            )
    else:
        # A transport interruption or context-free completion marker does not
        # replace the active task. Restore the authoritative antecedent verbatim.
        resolved_text = antecedent.text

    return ObjectiveResolution(
        classification=classification,
        status=ObjectiveResolutionStatus.RESOLVED,
        candidate_text=candidate_text,
        resolved_text=resolved_text,
        resolution_source=antecedent.source,
        reason="resolved_against_unique_structured_antecedent",
        antecedent_sha256=_sha256(antecedent.text),
        source_event_id=antecedent.source_event_id,
        source_event_ids=authority_event_ids,
        source_provider_event_ids=authority_provider_event_ids,
        source_session_event_ids=authority_session_event_ids,
    )


__all__ = [
    "OBJECTIVE_RESOLUTION_SCHEMA_VERSION",
    "ObjectiveAntecedent",
    "ObjectiveClassification",
    "ObjectiveResolution",
    "ObjectiveResolutionStatus",
    "classify_objective",
    "objective_antecedents",
    "resolve_objective",
]
