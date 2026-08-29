from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.conversation_state import resolve_conversation_state
from app.services.context_quality_adapters import session_context_claims
from app.services.checkpoints import (
    DIALOGUE_CLASSIFIER_VERSION,
    _legacy_goal_requires_dialogue_replay,
    _resolved_replay_request,
    _validated_session_request,
)
from app.services.objective_resolution import (
    ObjectiveAntecedent,
    ObjectiveClassification,
    ObjectiveResolutionStatus,
    classify_objective,
    objective_antecedents,
    resolve_objective,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Fix the composer focus regression.", ObjectiveClassification.SUBSTANTIVE),
        ("Continue implementing the verified focus correction.", ObjectiveClassification.SUBSTANTIVE),
        ("fix it", ObjectiveClassification.DEICTIC),
        ("this", ObjectiveClassification.DEICTIC),
        ("session context again", ObjectiveClassification.DEICTIC),
        ("did u fix it?", ObjectiveClassification.DEICTIC),
        (
            "sry wrong prompt, ignore the recent naming stuff and continue",
            ObjectiveClassification.DEICTIC,
        ),
        ("You have 8176 weighted tokens left", ObjectiveClassification.INTERRUPTION_MARKER),
        ("[session interrupted]", ObjectiveClassification.INTERRUPTION_MARKER),
        (
            "[Request interrupted by user for tool use]",
            ObjectiveClassification.INTERRUPTION_MARKER,
        ),
        (
            "This session is being continued from a previous conversation that ran "
            "out of context. The summary below covers the earlier portion.",
            ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER,
        ),
        ("done", ObjectiveClassification.COMPLETION_MARKER),
        ("the work is completed, thanks", ObjectiveClassification.COMPLETION_MARKER),
        ("All agents are finished work", ObjectiveClassification.COMPLETION_MARKER),
        ("The agents have finished their work.", ObjectiveClassification.COMPLETION_MARKER),
        ("All agents are done", ObjectiveClassification.COMPLETION_MARKER),
    ],
)
def test_objective_classifier_separates_task_and_context_dependent_turns(
    value: str,
    expected: ObjectiveClassification,
) -> None:
    assert classify_objective(value) is expected


@pytest.mark.parametrize(
    "candidate",
    [
        "All agents are finished work",
        "The agents have finished their work.",
    ],
)
def test_agent_completion_status_requires_a_real_objective(candidate: str) -> None:
    result = resolve_objective(candidate)

    assert result.classification is ObjectiveClassification.COMPLETION_MARKER
    assert result.status is ObjectiveResolutionStatus.UNRESOLVED
    assert result.blocks_copy is True
    assert result.blocks_execution is True


def test_substantive_objective_resolves_without_antecedent() -> None:
    result = resolve_objective("Review the current checkpoint compiler.")

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == "Review the current checkpoint compiler."
    assert result.resolution_source == "direct_user_request"
    assert result.blocks_copy is False
    assert result.blocks_execution is False


def test_provider_compaction_blob_cannot_become_direct_user_objective() -> None:
    blob = (
        "This session is being continued from a previous conversation that ran out "
        "of context. The summary below covers the earlier portion.\n\n"
        "The assistant said many files were changed and work should continue."
    )

    result = resolve_objective(blob)

    assert result.classification is ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER
    assert result.status is ObjectiveResolutionStatus.UNRESOLVED
    assert result.resolved_text is None
    assert result.blocks_copy is True
    assert result.blocks_execution is True


def test_provider_wrapper_can_extract_separately_delimited_current_user_request() -> None:
    blob = (
        "This session is being continued from a previous conversation that ran out "
        "of context. The summary below covers the earlier portion.\n\n"
        "<current_user_request>Review the context compiler failures.</current_user_request>"
    )

    result = resolve_objective(blob)

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == "Review the context compiler failures."
    assert result.resolution_source == "embedded_current_user_request"
    assert result.blocks_copy is False
    assert result.blocks_execution is False


def test_provider_wrapper_restored_from_antecedent_remains_context_only() -> None:
    blob = (
        "This session is being continued from a previous conversation that ran out "
        "of context. The summary below covers the earlier portion."
    )

    result = resolve_objective(
        blob,
        antecedents=(
            ObjectiveAntecedent(
                text="Review the context compiler failures.",
                source="conversation_active_goal",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == "Review the context compiler failures."
    assert result.blocks_copy is False
    assert result.blocks_execution is True
    assert result.to_dict()["requires_fresh_user_lead"] is True


def _event(sequence: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(int=sequence),
        provider_event_id=f"event-{sequence}",
        sequence_number=sequence,
        event_type="user_request",
        role="user",
        content=text,
    )


def _assistant_event(sequence: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(int=sequence),
        provider_event_id=f"assistant-{sequence}",
        sequence_number=sequence,
        event_type="assistant_update",
        role="assistant",
        content=text,
    )


def test_dialogue_replay_does_not_replace_active_goal_with_interruption_marker() -> None:
    state = resolve_conversation_state(
        [
            _event(1, "Review the context compiler failures."),
            _event(2, "[Request interrupted by user for tool use]"),
        ]
    )

    assert state.active_goal is not None
    assert state.active_goal.composite_request_verbatim == (
        "Review the context compiler failures."
    )
    assert state.transitions[-1].act == "interruption_marker"


def test_dialogue_replay_does_not_replace_active_goal_with_completion_status() -> None:
    state = resolve_conversation_state(
        [
            _event(1, "Review the context compiler failures."),
            _event(2, "All agents are finished work"),
        ]
    )

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == (
        "Review the context compiler failures."
    )
    assert state.transitions[-1].act == "completion_marker"
    assert state.transitions[-1].blocks_copy is False


def test_dialogue_replay_does_not_create_goal_from_provider_compaction_blob() -> None:
    state = resolve_conversation_state(
        [
            _event(
                1,
                "This session is being continued from a previous conversation that "
                "ran out of context. The summary below covers the earlier portion.",
            )
        ]
    )

    assert state.active_goal is None
    assert state.lifecycle == "unresolved"


@pytest.mark.parametrize(
    ("marker", "classification"),
    [
        (
            "[Request interrupted by user for tool use]",
            ObjectiveClassification.INTERRUPTION_MARKER,
        ),
        ("done", ObjectiveClassification.COMPLETION_MARKER),
        (
            "This session is being continued from a previous conversation that ran "
            "out of context. The summary below covers the earlier portion.",
            ObjectiveClassification.PROVIDER_COMPACTION_WRAPPER,
        ),
    ],
)
def test_replay_restores_context_before_marker_without_renewing_execution_authority(
    marker: str,
    classification: ObjectiveClassification,
) -> None:
    root = "Review the context compiler failures."
    events = [_event(1, root), _event(2, marker)]

    request = _resolved_replay_request(resolve_conversation_state(events), events)

    assert request is not None
    assert str(request) == root
    assert request.source_provider_event_ids == ("event-1",)
    assert request.source_session_event_ids == (str(UUID(int=1)),)
    assert request.objective_resolution is not None
    assert request.objective_resolution.classification is classification
    assert request.objective_resolution.candidate_text == marker
    assert request.objective_resolution.blocks_copy is False
    assert request.objective_resolution.blocks_execution is True
    assert request.objective_resolution.to_dict()["requires_fresh_user_lead"] is True


def test_replay_keeps_self_grounding_explanation_as_the_only_authority(
    monkeypatch,
) -> None:
    latest = (
        "same issue. why is this happening, explain. Cursor works, but why not "
        "OpenCode?"
    )
    events = [
        _event(1, "Fix the old focus-steal problem."),
        _event(2, latest),
    ]
    state = resolve_conversation_state(events)
    real_classifier = classify_objective
    monkeypatch.setattr(
        "app.services.checkpoints.classify_objective",
        lambda value: (
            ObjectiveClassification.DEICTIC
            if value == latest
            else real_classifier(value)
        ),
    )

    request = _resolved_replay_request(state, events)

    assert request is not None
    assert str(request) == latest
    assert request.source_provider_event_ids == ("event-2",)
    assert request.source_session_event_ids == (str(UUID(int=2)),)


def test_replay_scope_followup_walks_back_through_acceptance_to_named_root() -> None:
    events = [
        _event(1, "Can't the same Codex logic be used in OpenCode as well?"),
        _event(2, "go ahead then"),
        _event(3, "both for session and workspace context"),
        _event(4, "does it really work?"),
    ]

    request = _resolved_replay_request(resolve_conversation_state(events), events)

    assert request is not None
    assert request.source_provider_event_ids == (
        "event-1",
        "event-2",
        "event-3",
        "event-4",
    )
    assert request.source_session_event_ids == tuple(
        str(UUID(int=index)) for index in range(1, 5)
    )
    for event in events:
        assert event.content in str(request)
    assert "Original user objective:" in str(request)
    assert "Final user direction or status:" in str(request)


def test_replay_completed_branch_pivot_stops_at_referenced_session_turn() -> None:
    root = _event(1, "Fix the current Continue card failure shown in the screenshot.")
    referenced_session = _event(
        2,
        "fix it and also here the session ID: "
        "01a015e2-7993-78a3-a631-4eaa17955280 where I had OpenCode issues; "
        "also solve those session issues",
    )
    visual_follow_up = _event(
        4,
        "# Files mentioned by the user:\n\n"
        "## failure.png: /tmp/failure.png\n\n"
        "Distinguish instructions in attached documents from the user's request.\n\n"
        "## My request:\n"
        '<image name=[Image #1] path="/tmp/failure.png">\n</image>',
    )
    pivot = _event(6, "What about the issues from the session id i shared???")
    authorization = _event(7, "GO AHEAD AND FIX THE DAMN ISSUES")
    events = [
        root,
        referenced_session,
        _assistant_event(3, "Fixed and deployed the current Continue card failure."),
        visual_follow_up,
        _assistant_event(5, "Fixed and running; the screenshot mismatch is resolved."),
        pivot,
        authorization,
    ]

    request = _resolved_replay_request(resolve_conversation_state(events), events)

    assert request is not None
    assert request.source_provider_event_ids == ("event-2", "event-6", "event-7")
    assert root.content not in str(request)
    assert visual_follow_up.content not in str(request)
    assert referenced_session.content in str(request)
    assert pivot.content in str(request)
    assert authorization.content in str(request)

    without_completion = [
        root,
        referenced_session,
        visual_follow_up,
        pivot,
        authorization,
    ]
    unresolved_branch = _resolved_replay_request(
        resolve_conversation_state(without_completion),
        without_completion,
    )
    assert unresolved_branch is not None
    assert unresolved_branch.source_provider_event_ids == (
        "event-1",
        "event-2",
        "event-6",
        "event-7",
    )


def test_v3_checkpoint_goal_is_replayed_under_v4_classifier() -> None:
    assert DIALOGUE_CLASSIFIER_VERSION == "contextual_followups.v4"
    assert _legacy_goal_requires_dialogue_replay(
        "Review the Session Context compiler.",
        {"dialogue_classifier_version": "contextual_followups.v3"},
    ) is True
    assert _legacy_goal_requires_dialogue_replay(
        "Review the Session Context compiler.",
        {"dialogue_classifier_version": DIALOGUE_CLASSIFIER_VERSION},
    ) is False
    assert _validated_session_request(
        "[Request interrupted by user for tool use]"
    ) is None


def test_deictic_action_resolves_only_against_unique_structured_antecedent() -> None:
    result = resolve_objective(
        "fix it",
        antecedents=(
            ObjectiveAntecedent(
                text="Correct the composer so delivery targets the active chat.",
                source="conversation_active_goal",
                source_event_id="event-user-1",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.classification is ObjectiveClassification.DEICTIC
    assert result.resolved_text == (
        "Fix the antecedent objective:\n\n"
        "Correct the composer so delivery targets the active chat."
    )
    assert result.resolution_source == "conversation_active_goal"
    assert result.source_event_id == "event-user-1"
    assert result.blocks_copy is False


def test_bound_objective_keeps_provider_and_database_authority_ids_distinct() -> None:
    result = resolve_objective(
        "fix it",
        antecedents=(
            ObjectiveAntecedent(
                text="Correct the active composer target.",
                source="conversation_active_goal",
                source_event_id="provider-root",
                source_event_ids=("provider-root",),
                source_provider_event_ids=("provider-root",),
                source_session_event_ids=(
                    "11111111-1111-4111-8111-111111111111",
                ),
            ),
        ),
        candidate_source_event_ids=("provider-leaf",),
        candidate_source_provider_event_ids=("provider-leaf",),
        candidate_source_session_event_ids=(
            "22222222-2222-4222-8222-222222222222",
        ),
    )

    serialized = result.to_dict()
    assert serialized["source_provider_event_ids"] == [
        "provider-root",
        "provider-leaf",
    ]
    assert serialized["source_session_event_ids"] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]

    claims = session_context_claims(
        {
            "current_goal": {
                "text": result.resolved_text,
                "request_sha256": "a" * 64,
            },
            "objective_resolution": serialized,
        },
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )
    objective = next(item for item in claims if item.kind == "prior_user_objective")
    assert "objective_provider_event:provider-root" in objective.evidence_refs
    assert "objective_provider_event:provider-leaf" in objective.evidence_refs
    assert (
        "objective_session_event:11111111-1111-4111-8111-111111111111"
        in objective.evidence_refs
    )
    assert (
        "objective_session_event:22222222-2222-4222-8222-222222222222"
        in objective.evidence_refs
    )


@pytest.mark.parametrize(
    "candidate",
    [
        "fix it",
        "this",
        "session context again",
    ],
)
def test_unbound_deictic_candidate_fails_closed(candidate: str) -> None:
    result = resolve_objective(candidate)

    assert result.status is ObjectiveResolutionStatus.UNRESOLVED
    assert result.resolved_text is None
    assert result.blocks_copy is True


def test_go_ahead_binds_only_to_one_structured_active_objective() -> None:
    result = resolve_objective(
        "go ahead",
        antecedents=(
            ObjectiveAntecedent(
                text="Apply the reviewed composer focus correction.",
                source="conversation_active_goal",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == (
        "Proceed with the unique antecedent objective:\n\n"
        "Apply the reviewed composer focus correction."
    )
    assert result.blocks_copy is False
    assert result.blocks_execution is False


def test_wrong_prompt_correction_resumes_unique_antecedent() -> None:
    result = resolve_objective(
        "sry wrong prompt, ignore the recent naming stuff and continue",
        antecedents=(
            ObjectiveAntecedent(
                text="Brutally audit the Session Context compiler.",
                source="conversation_active_goal",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == (
        "Continue the antecedent objective:\n\n"
        "Brutally audit the Session Context compiler."
    )


def test_bare_pronoun_stays_unresolved_even_when_a_task_antecedent_exists() -> None:
    result = resolve_objective(
        "this",
        antecedents=(
            ObjectiveAntecedent(
                text="Review the active context projection.",
                source="conversation_active_goal",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.UNRESOLVED
    assert result.reason == "deictic_action_cannot_be_bound_safely"
    assert result.blocks_copy is True


@pytest.mark.parametrize(
    "marker",
    [
        "You have 8176 weighted tokens left",
        "done",
    ],
)
def test_non_objective_marker_restores_unique_active_goal(marker: str) -> None:
    result = resolve_objective(
        marker,
        antecedents=(
            ObjectiveAntecedent(
                text="Diagnose why Session Context copied an incomplete objective.",
                source="conversation_active_goal",
                source_event_id="event-root",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolved_text == (
        "Diagnose why Session Context copied an incomplete objective."
    )
    assert result.resolution_source == "conversation_active_goal"
    assert result.blocks_copy is False
    assert result.blocks_execution is True
    assert result.to_dict()["requires_fresh_user_lead"] is True


def test_same_priority_antecedents_must_be_unambiguous() -> None:
    result = resolve_objective(
        "fix it",
        antecedents=(
            ObjectiveAntecedent("Fix billing.", "supporting_user_turn"),
            ObjectiveAntecedent("Fix search.", "supporting_user_turn"),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.UNRESOLVED
    assert result.reason == "ambiguous_substantive_antecedent"


def test_active_conversation_goal_outranks_unrelated_supporting_turn() -> None:
    antecedents = objective_antecedents(
        conversation_state={
            "active_goal": {
                "root_event_id": "event-root",
                "root_request_verbatim": "Fix the active composer.",
                "composite_request_verbatim": "Fix the active composer.",
            }
        },
        supporting_context=[
            {
                "role": "user",
                "text": "Explain the old billing workflow.",
                "source": "prior_session_turn",
            }
        ],
    )

    result = resolve_objective("fix it", antecedents=antecedents)

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolution_source == "conversation_active_goal"
    assert "Fix the active composer." in str(result.resolved_text)
    assert "billing" not in str(result.resolved_text)


def test_replay_recovered_request_outranks_external_supporting_turn() -> None:
    result = resolve_objective(
        "fix it",
        antecedents=(
            ObjectiveAntecedent(
                "Fix the same-session composer target.",
                "recovered_handoff_request",
            ),
            ObjectiveAntecedent(
                "Fix the referenced billing example.",
                "supporting_user_turn",
            ),
        ),
    )

    assert result.status is ObjectiveResolutionStatus.RESOLVED
    assert result.resolution_source == "recovered_handoff_request"
    assert "composer target" in str(result.resolved_text)
    assert "billing" not in str(result.resolved_text)


def test_unresolved_objective_is_not_promoted_as_direct_user_claim() -> None:
    contract = {
        "current_goal": {
            "request_verbatim": "You have 8176 weighted tokens left",
            "text": "You have 8176 weighted tokens left",
            "request_sha256": "a" * 64,
        },
        "objective_resolution": {
            "classification": "interruption_marker",
            "status": "unresolved",
            "blocks_copy": True,
        },
    }

    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    assert not any(item.kind == "prior_user_objective" for item in claims)
