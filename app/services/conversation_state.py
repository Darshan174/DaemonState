from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from app.services.session_summary import (
    extract_user_failure_feedback_directive,
    extract_delegated_user_request,
    extract_user_authored_request,
    is_continuation_control,
    is_session_instruction_noise,
    is_user_failure_feedback,
    normalize_substantive_user_request,
)
from app.services.objective_resolution import (
    ObjectiveClassification,
    classify_objective,
)


_CANCEL_RE = re.compile(
    r"^\s*(?:cancel|drop|stop|forget|disregard)\b(?:\s+(?:it|this|that|the task))?[.!?]*\s*$",
    re.IGNORECASE,
)
_ACK_RE = re.compile(
    r"^\s*(?:done|finished|completed|ok(?:ay)?|thanks|thank you|got it|"
    r"understood|sounds good|looks good|great|perfect|cool)[.!?…]*\s*$",
    re.IGNORECASE,
)
_ACCEPT_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|correct|approved?|accept(?:ed)?|"
    r"yes[,;:]?\s*(?:do|apply|use|fix|proceed|go ahead)(?:\s+(?:it|that|this))?|"
    r"looks good[,;:]?\s*(?:please\s+)?go ahead|go ahead(?:\s+with\s+(?:it|that|this))?)"
    r"[.!?…]*\s*$",
    re.IGNORECASE,
)
_REJECT_RE = re.compile(
    r"^\s*(?:no|nope|reject(?:ed)?|don['’]?t\s+(?:do|use|apply)\s+(?:it|that|this))"
    r"[.!?…]*\s*$",
    re.IGNORECASE,
)
_SELECTION_RE = re.compile(
    r"^\s*(?:no[,;:]?\s*)?(?:(?:the|option)\s+)?"
    r"(?P<word>first|second|third|fourth|[1-4])(?:\s+one)?(?:\s+please)?[.!?…]*\s*$",
    re.IGNORECASE,
)
_CONTEXTUAL_ACTION_RE = re.compile(
    r"^\s*(?:please\s+)?(?:fix|do|apply|use|implement|change|update|remove|"
    r"replace|correct|restore|revert|redo|rework|review|finish|complete|proceed with)\s+"
    r"(?:it|this|that|those changes?|these changes?|the fix|the first one|the second one)"
    r"[.!?…]*\s*$|"
    r"^\s*(?:please\s+)?try\s+again[.!?…]*\s*$|"
    r"^\s*(?:please\s+)?try\s+(?:it|this|that)\s+again[.!?…]*\s*$|"
    r"^\s*(?:please\s+)?explain\s+why[.!?…]*\s*$|"
    r"^\s*(?:please\s+)?engineer\s+(?:it|this|that)\s+and\s+"
    r"fix\s+(?:it|this|that)[.!?…]*\s*$|"
    r"^\s*(?:please\s+)?(?:go\s+ahead\s+(?:and\s+)?)?fix\s+"
    r"(?:the\s+)?(?:(?:damn|fucking)\s+)?(?:issues?|problems?)"
    r"[.!?…]*\s*$",
    re.IGNORECASE,
)
_TASK_RESET_RE = re.compile(
    r"^\s*(?:new|separate|unrelated|different)\s+(?:task|request|topic)\b|"
    r"^\s*(?:switch|move)\s+(?:on\s+)?to\b|\bunrelated\b|"
    r"\b(?:forget|disregard|drop|cancel)\s+(?:the\s+)?"
    r"(?:previous|earlier|last)\s+(?:task|request|instruction)\b",
    re.IGNORECASE,
)
_TASK_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+)?continue\s+(?:with\s+)?(?:the\s+)?"
    r"(?:existing|current|same|previous)(?:\s+[a-z0-9_-]+){0,3}\s+"
    r"(?:task|request|work)\b|"
    r"^\s*(?:also|and|but|plus|then|additionally|furthermore|make\s+sure|ensure|"
    r"remember|keep|still|before\s+you\s+finish|while\s+you(?:'re|\s+are)\s+at\s+it)\b|"
    r"^\s*(?:please\s+)?(?:this|that|it|the\s+same|(?:these|those)\s+changes?|"
    r"the\s+(?:fix|result|work|task))\b|"
    r"^\s*(?:please\s+)?(?:do|apply|use|fix|change|update|remove|rename|replace|"
    r"redo|rework|finish|complete)\s+(?:this|that|it|the\s+(?:same|fix|work|change|result|task))\b|"
    r"^\s*(?:same|still)\s+(?:issue|problem|bug)\b|"
    r"^\s*(?:both|all|each)\s+(?:for|in|across|on)\b|"
    r"^\s*what\s+about\b",
    re.IGNORECASE,
)
_STATUS_INQUIRY_RE = re.compile(
    r"^\s*(?=[^?\n]{0,240}\b(?:complete|done|fixed|ready|resolved|working)\b)"
    r"(?:so\s+)?(?:"
    r"(?:is|are|was|were|did|does|has|have)\b|"
    r"(?:the|this|that|it)\s+[^?\n]{1,120}\b"
    r"(?:is|are|was|were|did|does|has|have)\b"
    r")[^?\n]*\?(?:[^\n]*)$",
    re.IGNORECASE,
)
_REFERENTIAL_FAILURE_RE = re.compile(
    r"^\s*(?:same|still)\s+(?:issue|problem|bug)\b|"
    r"^\s*so\s+(?:you|u)\s+can(?:not|['’]?t)\s+fix\s+(?:this|it|that)\b",
    re.IGNORECASE,
)
_DELIVERY_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+)?(?:commit|push|deploy|release|ship|publish)\b|"
    r"^\s*(?:please\s+)?(?:open|create|make)\s+(?:a\s+)?(?:pull\s+request|merge\s+request|pr)\b",
    re.IGNORECASE,
)
_PENDING_USER_ACTION_RE = re.compile(
    r"\b(?:authenticate|attach|choose|confirm|connect|enter|log\s*in|pick|provide|select|upload)\b",
    re.IGNORECASE,
)
_PENDING_PROPOSAL_RE = re.compile(
    r"\b(?:i\s+(?:can|could|recommend|suggest|would)|proposal|propose|"
    r"should\s+i|would\s+you\s+like|do\s+you\s+want|which\s+(?:one|option))\b",
    re.IGNORECASE,
)
_BINARY_QUESTION_RE = re.compile(
    r"^\s*(?:is|are|am|was|were|do|does|did|can|could|should|would|will|"
    r"have|has|had)\b[^?]*\?\s*$|"
    r"\b(?:is\s+that\s+correct|does\s+that\s+work|do\s+you\s+agree)\s*\?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_TASK_REQUEST_RE = re.compile(
    r"^\s*(?:please\s+)?(?:add|build|change|create|debug|diagnose|document|"
    r"explain|fix|implement|improve|investigate|make|remove|rename|replace|"
    r"review|test|update|write)\b",
    re.IGNORECASE,
)
_COMPLETION_RE = re.compile(
    r"\b(?:completed|done|finished|fixed|implemented|shipped|ready)\b",
    re.IGNORECASE,
)
_RESULT_CONTEXT_RE = re.compile(
    r"\b(?:root\s+cause|diagnos(?:is|ed)|found|observed|result|"
    r"the\s+(?:issue|problem|failure)\s+is|caused\s+by|"
    r"is\s+(?:causing|disabling|failing|blocking|breaking))\b",
    re.IGNORECASE,
)
_OPTION_LINE_RE = re.compile(
    r"^\s*(?:(?:[-*]\s*)?(?:option\s*)?)?(?P<number>[1-4])\s*[.):/-]\s*(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
_ORDERED_PROPOSAL_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:recommended|proposed)\s+"
    r"(?:correction\s+)?(?:order|plan|steps?|approach)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ORDERED_PROPOSAL_ITEM_RE = re.compile(
    r"^\s*(?P<number>[1-9][0-9]?)\s*[.)]\s+(?P<text>.+?)\s*$",
)


@dataclass(frozen=True)
class GoalFragment:
    event_id: str
    sequence_number: int
    request_verbatim: str
    normalized_request: str
    act: str
    resolved_statement: str | None = None
    assistant_event_id: str | None = None


@dataclass(frozen=True)
class ResolvedGoal:
    root_event_id: str
    root_request_verbatim: str
    fragments: tuple[GoalFragment, ...]
    composite_request_verbatim: str
    source_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class PendingInteraction:
    event_id: str
    kind: str
    prompt: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnTransition:
    event_id: str
    sequence_number: int
    user_text: str
    act: str
    active_goal_event_id: str | None
    assistant_event_id: str | None
    resolved_statement: str | None
    reason: str
    confidence: float
    blocks_copy: bool = False


@dataclass(frozen=True)
class ResolvedDecision:
    event_id: str
    act: str
    statement: str
    source_user_text: str
    assistant_event_id: str | None


@dataclass(frozen=True)
class ResolvedConversationState:
    schema_version: str
    active_goal: ResolvedGoal | None
    lifecycle: str
    transitions: tuple[TurnTransition, ...]
    decisions: tuple[ResolvedDecision, ...]
    pending_interaction: PendingInteraction | None
    unresolved_references: tuple[TurnTransition, ...]
    state_sha256: str

    def to_dict(self) -> dict[str, Any]:
        # Persist only the active task segment. Full replay transitions remain
        # available on the in-memory object for historical objective matching,
        # but superseded tasks and transport controls must not inflate or alter
        # the checkpoint handed to a new session.
        active_transitions = _active_scope_transitions(
            self.transitions,
            self.active_goal,
        )
        return {
            "schema_version": self.schema_version,
            "active_goal": asdict(self.active_goal) if self.active_goal else None,
            "lifecycle": self.lifecycle,
            "transitions": [asdict(item) for item in active_transitions],
            "decisions": [asdict(item) for item in self.decisions],
            "pending_interaction": (
                asdict(self.pending_interaction) if self.pending_interaction else None
            ),
            "unresolved_references": [asdict(item) for item in self.unresolved_references],
            "state_sha256": self.state_sha256,
        }


def request_extends_active_task(request: str, *, active_requests: Iterable[str]) -> bool:
    if _TASK_RESET_RE.search(request):
        return False
    if _TASK_FOLLOWUP_RE.search(request) or _DELIVERY_FOLLOWUP_RE.search(request):
        return True
    # Shared generic words are not identity evidence. For example, "Fix the
    # login page" followed by "Fix the billing page" must start a new task,
    # even though both turns share ``fix`` and ``page``. Amend only when the
    # user wrote an explicit follow-up/reference marker above.
    return False


def request_requires_active_task_context(request: str) -> bool:
    """Return whether a turn is meaningful only when bound to prior task state."""

    text = str(request or "").strip()
    if not text:
        return False
    return bool(
        _TASK_FOLLOWUP_RE.search(text)
        or _DELIVERY_FOLLOWUP_RE.search(text)
        or _CONTEXTUAL_ACTION_RE.fullmatch(text)
        or _STATUS_INQUIRY_RE.fullmatch(text)
        or _REFERENTIAL_FAILURE_RE.search(text)
    )


def normalize_dialogue_user_request(value: str | None) -> str | None:
    """Normalize a task turn without rejecting policy vocabulary used as its subject."""

    text = str(value or "").strip()
    normalized = normalize_substantive_user_request(text)
    if normalized is not None:
        return normalized
    return text if text and _EXPLICIT_TASK_REQUEST_RE.search(text) else None


def resolve_conversation_state(
    events: Sequence[Any],
    *,
    boundary_sequence: int | None = None,
) -> ResolvedConversationState:
    """Replay user/assistant turns into one deterministic task-level state."""

    ordered = sorted(
        (
            event
            for event in events
            if boundary_sequence is None or _event_sequence(event) <= boundary_sequence
        ),
        key=lambda event: (_event_sequence(event), _event_id(event)),
    )
    root_fragment: GoalFragment | None = None
    fragments: list[GoalFragment] = []
    transitions: list[TurnTransition] = []
    decisions: list[ResolvedDecision] = []
    pending: PendingInteraction | None = None
    lifecycle = "unresolved"

    for event in ordered:
        event_type = str(getattr(event, "event_type", "") or "")
        role = str(getattr(event, "role", "") or "")
        content = str(getattr(event, "content", "") or "")
        if event_type == "assistant_update" or role == "assistant":
            concrete_pending = _pending_interaction(event, content)
            if concrete_pending is not None:
                pending = concrete_pending
            continue
        if event_type not in {"user_request", "runtime_instruction"} or (
            event_type == "runtime_instruction" and role != "user"
        ):
            continue
        raw = (
            extract_delegated_user_request(content)
            if event_type == "runtime_instruction"
            else extract_user_authored_request(content)
        )
        # Dialogue classification needs a trimmed view, but the checkpoint
        # contract needs the exact user-authored bytes (including a terminal
        # newline). Keep both representations so replay never silently rewrites
        # the source request while deciding what kind of turn it is.
        request_verbatim = str(raw or "")
        user_text = request_verbatim.strip()
        if not user_text:
            continue
        # Runtime/bootstrap policy is transport, not dialogue. Keeping it as an
        # ``ack`` transition still leaks it into the durable checkpoint payload
        # even though it cannot become the goal, so exclude it before replay.
        explicit_task_request = bool(_EXPLICIT_TASK_REQUEST_RE.search(user_text))
        if is_session_instruction_noise(user_text) and not explicit_task_request:
            continue
        event_id = _event_id(event)
        sequence = _event_sequence(event)
        active_root_id = root_fragment.event_id if root_fragment is not None else None
        objective_classification = classify_objective(user_text)
        feedback_directive = extract_user_failure_feedback_directive(
            user_text,
            # An actionable tail supplies evidence that the prefix refers to
            # prior work even when that root is missing from the bounded log.
            # Extraction may therefore use contextual feedback grammar; the
            # no-root branch below still fails closed for deictic directives.
            active_task=True,
        )
        transition: TurnTransition

        # "done" right after an explicit user-action request (for example
        # "please authenticate GitHub") answers that prerequisite; it is not a
        # bare completion marker, so let the acknowledgement branch bind it.
        answers_user_action = bool(
            objective_classification is ObjectiveClassification.COMPLETION_MARKER
            and pending is not None
            and pending.kind == "user_action"
            and _ACK_RE.fullmatch(user_text)
        )
        if not answers_user_action and objective_classification in {
            ObjectiveClassification.INTERRUPTION_MARKER,
            ObjectiveClassification.COMPLETION_MARKER,
            ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER,
        }:
            transition = _transition(
                event_id,
                sequence,
                user_text,
                objective_classification.value,
                active_root_id,
                pending,
                None,
                "non-objective status or transport text does not replace the active task",
                1.0,
                blocks_copy=root_fragment is None,
            )
            if root_fragment is None:
                lifecycle = "unresolved"
        elif _CANCEL_RE.fullmatch(user_text):
            transition = _transition(
                event_id, sequence, user_text, "cancel", active_root_id, pending,
                "The user cancelled the active task.", "explicit cancellation", 1.0,
            )
            root_fragment = None
            fragments = []
            decisions = []
            lifecycle = "cancelled"
            pending = None
        elif is_continuation_control(user_text):
            transition = _transition(
                event_id, sequence, user_text, "continue", active_root_id, pending,
                None, "continuation control preserves the active task", 1.0,
                blocks_copy=root_fragment is None,
            )
            lifecycle = "active" if root_fragment is not None else "unresolved"
            pending = None
        elif (selection := _selection(user_text)) is not None:
            resolved = _resolve_selection(selection, pending)
            blocks = resolved is None
            transition = _transition(
                event_id, sequence, user_text, "select" if resolved else "unresolved_reference",
                active_root_id, pending, resolved,
                "ordinal response resolved against parsed assistant options"
                if resolved
                else "ordinal response has no unique parsed option antecedent",
                0.98 if resolved else 0.0,
                blocks_copy=blocks,
            )
            if resolved:
                decisions.append(_decision(transition, resolved))
                if root_fragment is not None:
                    fragments.append(
                        _fragment(
                            event,
                            user_text,
                            "select",
                            resolved,
                            pending,
                            request_verbatim=request_verbatim,
                        )
                    )
            if resolved:
                lifecycle = "active" if root_fragment is not None else "unresolved"
            elif root_fragment is None:
                lifecycle = "unresolved"
            pending = None
        elif _ACCEPT_RE.fullmatch(user_text) or _REJECT_RE.fullmatch(user_text):
            accepted = bool(_ACCEPT_RE.fullmatch(user_text))
            pending_kind = pending.kind if pending is not None else None
            resolved = _resolve_binary_answer(accepted, pending)
            blocks = bool(root_fragment is None or resolved is None)
            act = "accept" if accepted else "reject"
            transition = _transition(
                event_id, sequence, user_text, act if not blocks else "unresolved_reference",
                active_root_id, pending, resolved,
                "binary response resolved against the pending assistant interaction"
                if resolved
                else "binary response has no unique actionable antecedent",
                0.92 if resolved else 0.25,
                blocks_copy=blocks,
            )
            if resolved:
                decisions.append(_decision(transition, resolved))
                if root_fragment is not None and (
                    (accepted and pending_kind == "proposal")
                    or pending_kind == "binary_question"
                ):
                    fragments.append(
                        _fragment(
                            event,
                            user_text,
                            act,
                            resolved,
                            pending,
                            request_verbatim=request_verbatim,
                        )
                    )
            rejected_result = bool(
                not accepted
                and root_fragment is not None
                and (
                    pending_kind in {"completion_claim", "result"}
                    or (
                        pending_kind == "binary_question"
                        and pending is not None
                        and _COMPLETION_RE.search(pending.prompt)
                    )
                    or pending_kind is None
                )
            )
            if rejected_result:
                lifecycle = "direction_required"
            elif not (resolved is None and lifecycle == "direction_required"):
                lifecycle = (
                    "user_accepted_unverified"
                    if accepted and pending_kind in {"completion_claim", "result"}
                    else "active"
                    if root_fragment is not None
                    else "unresolved"
                )
            pending = None
        elif _ACK_RE.fullmatch(user_text):
            if user_text.casefold().rstrip(".!?…") in {"done", "finished", "completed"} and (
                pending is not None and pending.kind == "user_action"
            ):
                act = "status_update"
                resolved = f"User reports the requested prerequisite complete: {pending.prompt}"
                reason = "completion word answers an explicit user-action request"
            elif pending is not None and pending.kind in {"completion_claim", "result"}:
                act = "accept"
                resolved = (
                    "Unverified user acceptance of the reported result: "
                    + pending.prompt
                )
                reason = "acknowledgement applies to the latest reported result"
                lifecycle = "user_accepted_unverified"
            else:
                act = "ack"
                resolved = None
                reason = "context-free acknowledgement does not rewrite task state"
            transition = _transition(
                event_id, sequence, user_text, act, active_root_id, pending, resolved, reason,
                0.9 if resolved else 1.0,
            )
            if resolved:
                decisions.append(_decision(transition, resolved))
            if lifecycle != "user_accepted_unverified" and not (
                lifecycle == "direction_required" and resolved is None
            ):
                lifecycle = "active" if root_fragment is not None else "unresolved"
            pending = None
        elif feedback_directive is not None:
            contextual_without_root = bool(
                root_fragment is None
                and _CONTEXTUAL_ACTION_RE.fullmatch(feedback_directive)
            )
            act = (
                "unresolved_reference"
                if contextual_without_root
                else "amend"
                if root_fragment is not None
                else "new_goal"
            )
            resolved = (
                "User rejected or reported a failure in the prior result, then directed: "
                + feedback_directive
            )
            if not contextual_without_root:
                fragment = _fragment(
                    event,
                    feedback_directive,
                    act,
                    resolved if root_fragment is not None else None,
                    pending,
                    request_verbatim=feedback_directive,
                )
                if root_fragment is None:
                    root_fragment = fragment
                    fragments = [fragment]
                    decisions = []
                else:
                    fragments.append(fragment)
            transition = _transition(
                event_id,
                sequence,
                user_text,
                act,
                root_fragment.event_id if root_fragment is not None else None,
                pending,
                None if contextual_without_root else resolved,
                (
                    "contextual direction after failure feedback has no active task"
                    if contextual_without_root
                    else "actionable direction was separated from failure feedback"
                ),
                0.0 if contextual_without_root else 0.98,
                blocks_copy=contextual_without_root,
            )
            lifecycle = "unresolved" if contextual_without_root else "active"
            pending = None
        elif _STATUS_INQUIRY_RE.fullmatch(user_text):
            has_root = root_fragment is not None
            transition = _transition(
                event_id,
                sequence,
                user_text,
                "status_inquiry" if has_root else "unresolved_reference",
                active_root_id,
                pending,
                (
                    "User requested the status of the preserved active task; "
                    "the task itself is unchanged."
                    if has_root
                    else None
                ),
                (
                    "status inquiry preserves the active task"
                    if has_root
                    else "status inquiry has no active task to identify"
                ),
                0.98 if has_root else 0.0,
                blocks_copy=not has_root,
            )
            lifecycle = "active" if has_root else "unresolved"
            pending = None
        elif _REFERENTIAL_FAILURE_RE.search(user_text):
            has_root = root_fragment is not None
            transition = _transition(
                event_id,
                sequence,
                user_text,
                "failure_feedback" if has_root else "unresolved_reference",
                active_root_id,
                pending,
                (
                    "User reports that the same failure remains; the preserved "
                    "active goal is unchanged."
                    if has_root
                    else None
                ),
                (
                    "referential failure feedback preserves the active task"
                    if has_root
                    else "referential failure feedback has no active task to identify"
                ),
                0.98 if has_root else 0.0,
                blocks_copy=not has_root,
            )
            lifecycle = "direction_required" if has_root else "unresolved"
            pending = None
        elif is_user_failure_feedback(
            user_text,
            active_task=root_fragment is not None,
        ):
            transition = _transition(
                event_id,
                sequence,
                user_text,
                "failure_feedback",
                active_root_id,
                pending,
                "User rejected or reported a failure in the prior result; the active goal is preserved.",
                "failure feedback preserves the active task and requires new user direction",
                0.98,
            )
            lifecycle = "direction_required" if root_fragment is not None else "unresolved"
            pending = None
        elif _CONTEXTUAL_ACTION_RE.fullmatch(user_text):
            resolved = _resolve_contextual_action(user_text, pending)
            resumed_after_feedback = bool(
                resolved is None
                and lifecycle == "direction_required"
                and root_fragment is not None
            )
            if resumed_after_feedback and root_fragment is not None:
                resolved = (
                    f"Apply the user's follow-up `{user_text}` to the preserved active task "
                    f"after the prior result was rejected: {root_fragment.normalized_request}"
                )
            blocks = root_fragment is None or resolved is None
            transition = _transition(
                event_id, sequence, user_text, "amend" if not blocks else "unresolved_reference",
                active_root_id, pending, resolved,
                "referential action resumed the preserved task after failure feedback"
                if resumed_after_feedback
                else "referential action bound to the latest concrete assistant context"
                if resolved
                else "referential action has no unique concrete antecedent",
                0.86 if resolved else 0.0,
                blocks_copy=blocks,
            )
            if root_fragment is not None and resolved:
                fragments.append(
                    _fragment(
                        event,
                        user_text,
                        "amend",
                        resolved,
                        pending,
                        request_verbatim=request_verbatim,
                    )
                )
                lifecycle = "active"
            pending = None
        elif objective_classification is ObjectiveClassification.DEICTIC and not (
            # An explicit scope follow-up ("both for session and workspace
            # context") is bindable to the active goal even though it is not
            # self-contained; only unanchored deictic turns stay unresolved.
            root_fragment is not None
            and _TASK_FOLLOWUP_RE.search(user_text)
            and not _TASK_RESET_RE.search(user_text)
        ):
            transition = _transition(
                event_id,
                sequence,
                user_text,
                "unresolved_reference",
                active_root_id,
                pending,
                None,
                "context-dependent objective has no safely bindable antecedent",
                0.0,
                blocks_copy=True,
            )
            lifecycle = "direction_required" if root_fragment is not None else "unresolved"
            pending = None
        else:
            normalized = normalize_dialogue_user_request(user_text)
            if normalized is None:
                transition = _transition(
                    event_id, sequence, user_text, "ack", active_root_id, pending, None,
                    "non-substantive user turn leaves the active task unchanged", 1.0,
                )
            else:
                fragment = _fragment(
                    event,
                    user_text,
                    "new_goal",
                    None,
                    pending,
                    normalized,
                    request_verbatim=request_verbatim,
                )
                extends = bool(
                    root_fragment is not None
                    and request_extends_active_task(
                        normalized,
                        active_requests=[item.normalized_request for item in fragments],
                    )
                )
                if extends:
                    fragment = GoalFragment(**{**asdict(fragment), "act": "amend"})
                    fragments.append(fragment)
                    act = "amend"
                else:
                    root_fragment = fragment
                    fragments = [fragment]
                    decisions = []
                    act = "new_goal"
                transition = _transition(
                    event_id, sequence, user_text, act,
                    root_fragment.event_id if root_fragment is not None else None,
                    pending, normalized,
                    "self-contained request extends the active task"
                    if extends
                    else "self-contained request starts the active task",
                    1.0,
                )
                lifecycle = "active"
            pending = None
        transitions.append(transition)

    active_goal = _resolved_goal(root_fragment, fragments)
    active_transitions = _active_scope_transitions(transitions, active_goal)
    unresolved = tuple(
        item for item in active_transitions if item.act == "unresolved_reference"
    )
    unsigned = {
        "schema_version": "conversation_state.v1",
        "active_goal": asdict(active_goal) if active_goal else None,
        "lifecycle": lifecycle,
        "transitions": [asdict(item) for item in active_transitions],
        "decisions": [asdict(item) for item in decisions],
        "pending_interaction": asdict(pending) if pending else None,
        "unresolved_references": [asdict(item) for item in unresolved],
    }
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ResolvedConversationState(
        schema_version="conversation_state.v1",
        active_goal=active_goal,
        lifecycle=lifecycle,
        transitions=tuple(transitions),
        decisions=tuple(decisions),
        pending_interaction=pending,
        unresolved_references=unresolved,
        state_sha256=digest,
    )


def _resolved_goal(
    root: GoalFragment | None,
    fragments: list[GoalFragment],
) -> ResolvedGoal | None:
    if root is None or not fragments:
        return None
    primary = root.request_verbatim.strip()
    if len(fragments) == 1:
        # With one authoritative request there is nothing to synthesize. The
        # composite is therefore the original request byte-for-byte, rather
        # than a normalized rendering of it.
        composite = root.request_verbatim
    else:
        lines = [primary, "", "## Additional user-authored requirements"]
        for index, fragment in enumerate(fragments[1:], start=1):
            lines.extend(["", f"### Follow-up {index}", fragment.request_verbatim.strip()])
            if fragment.resolved_statement:
                lines.extend([
                    "",
                    "Resolved against the immediately preceding assistant context:",
                    fragment.resolved_statement,
                ])
        composite = "\n".join(lines).strip()
    return ResolvedGoal(
        root_event_id=root.event_id,
        root_request_verbatim=root.request_verbatim,
        fragments=tuple(fragments),
        composite_request_verbatim=composite,
        source_event_ids=tuple(item.event_id for item in fragments),
    )


def _pending_interaction(event: Any, content: str) -> PendingInteraction | None:
    prompt = re.sub(r"\s+", " ", content).strip()
    if not prompt:
        return None
    ordered_proposal = _unique_ordered_proposal(content)
    options = tuple(
        match.group("text").strip()
        for line in content.splitlines()
        if (match := _OPTION_LINE_RE.match(line)) is not None
    )
    if ordered_proposal is not None:
        # A numbered implementation sequence is one proposal, not a set of
        # mutually exclusive choices. Bind a later "yes/go ahead" only when
        # there is one explicitly labelled plan, and carry only that plan
        # rather than promoting the assistant's surrounding diagnosis.
        kind = "proposal"
        prompt = ordered_proposal
        options = ()
    elif len(options) >= 2:
        kind = "options"
    elif _PENDING_USER_ACTION_RE.search(prompt) and (
        "?" in prompt or re.search(r"\b(?:please|need you to|you must|once you)\b", prompt, re.I)
    ):
        kind = "user_action"
    elif _PENDING_PROPOSAL_RE.search(prompt):
        kind = "proposal"
    elif _BINARY_QUESTION_RE.search(prompt):
        kind = "binary_question"
    elif _COMPLETION_RE.search(prompt):
        kind = "completion_claim"
    elif _RESULT_CONTEXT_RE.search(prompt):
        kind = "result"
    else:
        return None
    return PendingInteraction(
        event_id=_event_id(event),
        kind=kind,
        prompt=prompt[:1_200],
        options=options,
    )


def _unique_ordered_proposal(content: str) -> str | None:
    """Return one explicitly labelled sequential proposal, if unambiguous."""

    headings = list(_ORDERED_PROPOSAL_HEADING_RE.finditer(content))
    if len(headings) != 1:
        return None

    heading = headings[0]
    numbered: list[tuple[int, str]] = []
    started = False
    for line in content[heading.end() :].splitlines():
        stripped = line.strip()
        if not stripped and not started:
            continue
        match = _ORDERED_PROPOSAL_ITEM_RE.fullmatch(line)
        if match is None:
            if started:
                break
            return None
        started = True
        numbered.append((int(match.group("number")), match.group("text").strip()))

    if len(numbered) < 2 or [number for number, _ in numbered] != list(
        range(1, len(numbered) + 1)
    ):
        return None
    heading_text = re.sub(r"^\s*#{1,6}\s*", "", heading.group(0)).strip().rstrip(":")
    return "\n".join(
        [f"{heading_text}:", *(f"{number}. {text}" for number, text in numbered)]
    )


def _selection(value: str) -> int | None:
    match = _SELECTION_RE.fullmatch(value)
    if match is None:
        return None
    return {"first": 1, "second": 2, "third": 3, "fourth": 4}.get(
        match.group("word").casefold(),
        int(match.group("word")) if match.group("word").isdigit() else None,
    )


def _resolve_selection(index: int, pending: PendingInteraction | None) -> str | None:
    if pending is None or pending.kind != "options" or not (1 <= index <= len(pending.options)):
        return None
    return f"Selected option {index}: {pending.options[index - 1]}"


def _resolve_binary_answer(
    accepted: bool,
    pending: PendingInteraction | None,
) -> str | None:
    if pending is None or pending.kind not in {
        "proposal",
        "user_action",
        "binary_question",
        "completion_claim",
        "result",
    }:
        return None
    if pending.kind == "proposal":
        verb = "Accepted" if accepted else "Rejected"
        return f"{verb} the prior assistant proposal: {pending.prompt}"
    if pending.kind == "binary_question":
        answer = "yes" if accepted else "no"
        return f"User answered {answer} to the assistant's question: {pending.prompt}"
    if pending.kind == "user_action":
        answer = "affirmed" if accepted else "declined"
        return f"User {answer} the assistant's requested prerequisite: {pending.prompt}"
    verb = "Accepted" if accepted else "Rejected"
    return f"{verb} the assistant-reported result without independent verification: {pending.prompt}"


def _resolve_contextual_action(
    user_text: str,
    pending: PendingInteraction | None,
) -> str | None:
    if pending is None or pending.kind not in {"proposal", "completion_claim", "result"}:
        return None
    return f"Apply the user's follow-up `{user_text}` to this prior context: {pending.prompt}"


def _fragment(
    event: Any,
    user_text: str,
    act: str,
    resolved: str | None,
    pending: PendingInteraction | None,
    normalized: str | None = None,
    *,
    request_verbatim: str | None = None,
) -> GoalFragment:
    return GoalFragment(
        event_id=_event_id(event),
        sequence_number=_event_sequence(event),
        request_verbatim=(
            request_verbatim if request_verbatim is not None else user_text
        ),
        normalized_request=normalized or user_text,
        act=act,
        resolved_statement=resolved,
        assistant_event_id=pending.event_id if pending else None,
    )


def _transition(
    event_id: str,
    sequence: int,
    user_text: str,
    act: str,
    active_goal_event_id: str | None,
    pending: PendingInteraction | None,
    resolved: str | None,
    reason: str,
    confidence: float,
    *,
    blocks_copy: bool = False,
) -> TurnTransition:
    return TurnTransition(
        event_id=event_id,
        sequence_number=sequence,
        user_text=user_text,
        act=act,
        active_goal_event_id=active_goal_event_id,
        assistant_event_id=pending.event_id if pending else None,
        resolved_statement=resolved,
        reason=reason,
        confidence=confidence,
        blocks_copy=blocks_copy,
    )


def _decision(transition: TurnTransition, statement: str) -> ResolvedDecision:
    return ResolvedDecision(
        event_id=transition.event_id,
        act=transition.act,
        statement=statement,
        source_user_text=transition.user_text,
        assistant_event_id=transition.assistant_event_id,
    )


def _event_id(event: Any) -> str:
    return str(
        getattr(event, "provider_event_id", None)
        or getattr(event, "id", None)
        or f"event-{_event_sequence(event)}"
    )


def _event_sequence(event: Any) -> int:
    value = getattr(event, "sequence_number", 0)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _active_scope_transitions(
    transitions: Iterable[TurnTransition],
    active_goal: ResolvedGoal | None,
) -> tuple[TurnTransition, ...]:
    if active_goal is None:
        return ()
    return tuple(
        item
        for item in transitions
        if item.active_goal_event_id == active_goal.root_event_id
    )
