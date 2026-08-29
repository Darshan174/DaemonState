from types import SimpleNamespace

import pytest

from app.services.conversation_state import resolve_conversation_state


def event(sequence: int, role: str, content: str, *, event_type: str | None = None):
    return SimpleNamespace(
        provider_event_id=f"event-{sequence}",
        sequence_number=sequence,
        event_type=event_type or ("user_request" if role == "user" else "assistant_update"),
        role=role,
        content=content,
    )


def test_numbered_choice_resolves_without_replacing_the_active_goal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the broken session cards."),
        event(2, "assistant", "Choose one:\n1. Fix opacity only\n2. Redesign every card"),
        event(3, "user", "the first one"),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Fix the broken session cards."
    assert "Selected option 1: Fix opacity only" in state.active_goal.composite_request_verbatim
    assert state.decisions[0].statement == "Selected option 1: Fix opacity only"
    assert state.unresolved_references == ()


def test_unbound_choice_preserves_goal_and_requires_clarification() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the broken session cards."),
        event(2, "user", "the first one"),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Fix the broken session cards."
    assert state.unresolved_references[0].user_text == "the first one"
    assert state.unresolved_references[0].blocks_copy is True


def test_failure_feedback_preserves_goal_and_requires_user_direction() -> None:
    request = "Implement reliable checkpoint selection."
    reaction = "ARE U FUCKING SERIOUS MOTHERFUCKER"
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "Implemented end to end; the handoff is ready."),
        event(3, "user", reaction),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.active_goal.composite_request_verbatim == request
    assert [item.request_verbatim for item in state.active_goal.fragments] == [request]
    assert state.transitions[-1].act == "failure_feedback"
    assert state.transitions[-1].blocks_copy is False
    assert state.lifecycle == "direction_required"
    assert state.unresolved_references == ()


def test_factual_failure_report_is_feedback_only_with_an_active_task() -> None:
    request = "Remove the obsolete banner."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "The banner is removed."),
        event(3, "user", "The banner is still displayed in the app."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.transitions[-1].act == "failure_feedback"
    assert state.lifecycle == "direction_required"


@pytest.mark.parametrize(
    "reaction",
    (
        "Why did you not fix it?",
        "How did you miss this?",
        "Seriously?",
        "WTF?",
        "This is completely wrong.",
        "Wrong.",
        "Incorrect.",
        "Not even close.",
        "You broke it.",
        "You made it worse.",
        "No, that's wrong.",
        "How could you get this so wrong?",
        "Why did you break it?",
        "It got worse.",
        "This is worse.",
        "That's wrong.",
    ),
)
def test_common_failure_reactions_never_replace_the_active_goal(reaction: str) -> None:
    request = "Repair Session Context goal selection."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "Done."),
        event(3, "user", reaction),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.transitions[-1].act == "failure_feedback"
    assert state.lifecycle == "direction_required"


@pytest.mark.parametrize("response", ("okay", "thanks", "yes", "no", "the first one"))
def test_context_free_response_does_not_clear_required_direction(response: str) -> None:
    request = "Repair Session Context goal selection."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "Done."),
        event(3, "user", "This is completely wrong."),
        event(4, "user", response),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.lifecycle == "direction_required"


@pytest.mark.parametrize(
    "direction",
    ("fix it", "redo it", "try again", "ENGINEER THIS AND FIX THIS"),
)
def test_explicit_contextual_direction_resumes_the_preserved_goal(direction: str) -> None:
    request = "Repair Session Context goal selection."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "Done."),
        event(3, "user", "This is completely wrong."),
        event(4, "user", direction),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.active_goal.fragments[-1].request_verbatim == direction
    assert state.transitions[-1].act == "amend"
    assert state.lifecycle == "active"


@pytest.mark.parametrize(
    "follow_up",
    (
        "both for session and workspace context",
        "What about the workspace context?",
    ),
)
def test_scope_follow_up_amends_the_concrete_active_goal(follow_up: str) -> None:
    request = "Make the OpenCode integration follow the Codex context logic."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "user", follow_up),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert [item.request_verbatim for item in state.active_goal.fragments] == [
        request,
        follow_up,
    ]
    assert state.transitions[-1].act == "amend"


@pytest.mark.parametrize(
    "follow_up",
    (
        "same issue, BUT i think it is because the account uses free models",
        "same issue. so u cant fix this",
    ),
)
def test_referential_failure_preserves_the_concrete_active_goal(follow_up: str) -> None:
    request = "Fix the OpenCode session integration failure."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "The issue is fixed."),
        event(3, "user", follow_up),
    ])

    assert state.active_goal is not None
    assert state.active_goal.composite_request_verbatim == request
    assert state.transitions[-1].act == "failure_feedback"
    assert state.lifecycle == "direction_required"


def test_status_inquiry_preserves_the_concrete_active_goal() -> None:
    request = "Fix the OpenCode session integration failure."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "I changed the provider adapter."),
        event(3, "user", "so the opencode issue is fixed? answer short and to the point"),
    ])

    assert state.active_goal is not None
    assert state.active_goal.composite_request_verbatim == request
    assert state.transitions[-1].act == "status_inquiry"
    assert state.lifecycle == "active"


def test_generic_fix_issues_direction_rebinds_after_failure() -> None:
    request = "Fix the OpenCode session integration failures."
    direction = "GO AHEAD AND FIX THE DAMN ISSUES"
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "The issue is fixed."),
        event(3, "user", "same issue"),
        event(4, "user", direction),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.active_goal.fragments[-1].request_verbatim == direction
    assert state.transitions[-1].act == "amend"
    assert state.lifecycle == "active"


@pytest.mark.parametrize(
    "orphan",
    (
        "same issue",
        "so the opencode issue is fixed?",
        "GO AHEAD AND FIX THE DAMN ISSUES",
    ),
)
def test_context_dependent_turn_without_a_goal_fails_closed(orphan: str) -> None:
    state = resolve_conversation_state([event(1, "user", orphan)])

    assert state.active_goal is None
    assert state.transitions[-1].act == "unresolved_reference"
    assert state.transitions[-1].blocks_copy is True
    assert state.lifecycle == "unresolved"


@pytest.mark.parametrize(
    ("user_text", "directive"),
    (
        ("You didn't fix it, now fix the compiler.", "fix the compiler."),
        ("Still broken — fix it.", "fix it."),
        ("This is wrong. Redo it.", "Redo it."),
        ("Why the hell did you do that? Revert it.", "Revert it."),
    ),
)
def test_feedback_and_direction_in_one_turn_preserves_and_amends_goal(
    user_text: str,
    directive: str,
) -> None:
    request = "Repair Session Context goal selection."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", "Done."),
        event(3, "user", user_text),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.active_goal.fragments[-1].request_verbatim == directive
    assert state.transitions[-1].act == "amend"
    assert state.lifecycle == "active"


@pytest.mark.parametrize("rejection", ("no", "nope", "reject"))
@pytest.mark.parametrize(
    "completion",
    (
        "Done.",
        "I fixed it.",
        "The implementation is complete.",
        "I fixed it. Does that work?",
    ),
)
def test_rejecting_an_assistant_result_requires_new_direction(
    rejection: str,
    completion: str,
) -> None:
    request = "Repair Session Context goal selection."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "assistant", completion),
        event(3, "user", rejection),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.lifecycle == "direction_required"


def test_rejecting_a_proposal_does_not_masquerade_as_result_failure() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve Session Context."),
        event(2, "assistant", "I recommend adding an optional history panel."),
        event(3, "user", "no"),
    ])

    assert state.active_goal is not None
    assert state.transitions[-1].act == "reject"
    assert state.lifecycle == "active"


@pytest.mark.parametrize(
    "user_text",
    (
        "This is wrong. Fix it.",
        "Still broken — redo it.",
        "You failed. Try again.",
    ),
)
def test_contextual_feedback_direction_without_a_root_fails_closed(
    user_text: str,
) -> None:
    state = resolve_conversation_state([
        event(1, "user", user_text),
    ])

    assert state.active_goal is None
    assert state.lifecycle == "unresolved"
    assert state.transitions[-1].act == "unresolved_reference"
    assert state.transitions[-1].blocks_copy is True


def test_self_contained_feedback_direction_can_start_a_root() -> None:
    state = resolve_conversation_state([
        event(1, "user", "This is wrong. Fix the Session Context compiler."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Fix the Session Context compiler."
    assert state.lifecycle == "active"


@pytest.mark.parametrize(
    "command",
    ("/status", "/compact", "/model gpt-5", "/help", "/resume", "/clear", "/reset"),
)
def test_provider_command_never_replaces_the_active_goal(command: str) -> None:
    request = "Fix the session cards."
    state = resolve_conversation_state([
        event(1, "user", request),
        event(2, "user", command),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert [item.request_verbatim for item in state.active_goal.fragments] == [request]
    assert state.transitions[-1].act in {"ack", "continue"}


def test_fix_it_binds_to_one_concrete_diagnosis() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Investigate why copying is disabled."),
        event(2, "assistant", "The fixed character gate is disabling valid prompts."),
        event(3, "user", "fix it"),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Investigate why copying is disabled."
    assert "fixed character gate" in state.active_goal.composite_request_verbatim
    assert state.transitions[-1].act == "amend"


def test_binary_answer_resolves_against_a_pending_proposal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve the continuation handoff."),
        event(2, "assistant", "I recommend separating semantic readiness from budget fit."),
        event(3, "user", "Yes, do it."),
    ])

    assert state.active_goal is not None
    assert state.transitions[-1].act == "accept"
    assert "Accepted the prior assistant proposal" in state.decisions[-1].statement


def test_yes_go_ahead_binds_one_recommended_ordered_plan_as_a_proposal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Investigate why the Continue cards are disabled."),
        event(
            2,
            "assistant",
            (
                "The diagnosis contains several historical observations.\n\n"
                "### Recommended correction order\n\n"
                "1. Remove the Continue-only maturity lock.\n"
                "2. Keep Execute's historical-copy gate.\n"
                "3. Verify the destination-specific paste result.\n"
                "4. Preserve unrelated workspace changes.\n"
                "5. Run the focused tests."
            ),
        ),
        event(3, "user", "yes go ahead"),
    ])

    assert state.active_goal is not None
    assert state.unresolved_references == ()
    assert state.transitions[-1].act == "accept"
    accepted = state.decisions[-1].statement
    assert "Accepted the prior assistant proposal" in accepted
    assert "Remove the Continue-only maturity lock" in accepted
    assert "Run the focused tests" in accepted
    assert "historical observations" not in accepted


def test_yes_does_not_bind_multiple_recommended_ordered_plans() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve Continue."),
        event(
            2,
            "assistant",
            (
                "Recommended plan:\n1. Keep the current UI.\n2. Fix delivery.\n\n"
                "Proposed plan:\n1. Replace the UI.\n2. Remove delivery."
            ),
        ),
        event(3, "user", "yes"),
    ])

    assert state.active_goal is not None
    assert state.unresolved_references[-1].user_text == "yes"
    assert state.unresolved_references[-1].blocks_copy is True


def test_done_answers_a_requested_prerequisite_without_completing_the_task() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Push the branch."),
        event(2, "assistant", "Please authenticate GitHub, then I can push."),
        event(3, "user", "done"),
    ])

    assert state.active_goal is not None
    assert state.lifecycle == "active"
    assert state.transitions[-1].act == "status_update"


def test_user_acceptance_does_not_claim_verified_completion() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the cards."),
        event(2, "assistant", "The card opacity is fixed and the UI test passed."),
        event(3, "user", "looks good"),
    ])

    assert state.lifecycle == "user_accepted_unverified"
    assert state.active_goal is not None
    assert "unverified" in state.decisions[-1].statement.casefold()


def test_yes_to_reported_completion_remains_unverified_acceptance() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the cards."),
        event(2, "assistant", "The card opacity is fixed and the UI test passed."),
        event(3, "user", "yes"),
    ])

    assert state.lifecycle == "user_accepted_unverified"
    assert "without independent verification" in state.decisions[-1].statement


def test_unrelated_request_supersedes_the_active_goal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the session cards."),
        event(2, "assistant", "I found the card styles."),
        event(3, "user", "Create a GitHub issue for the billing outage."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == (
        "Create a GitHub issue for the billing outage."
    )
    assert len(state.active_goal.fragments) == 1


def test_standalone_imperatives_with_generic_shared_words_are_separate_tasks() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix the login page."),
        event(2, "user", "Fix the billing page."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Fix the billing page."
    assert [item.act for item in state.transitions] == ["new_goal", "new_goal"]
    assert len(state.active_goal.fragments) == 1


def test_superseded_unresolved_reference_does_not_block_the_new_goal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Fix checkout."),
        event(2, "user", "the first one"),
        event(3, "user", "Create a report for billing."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == "Create a report for billing."
    assert state.unresolved_references == ()
    assert state.to_dict()["unresolved_references"] == []
    assert all(
        item["active_goal_event_id"] == "event-3"
        for item in state.to_dict()["transitions"]
    )


def test_plain_binary_answer_without_an_antecedent_requires_clarification() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve the handoff."),
        event(2, "user", "yes"),
    ])

    assert state.active_goal is not None
    assert state.unresolved_references[-1].user_text == "yes"
    assert state.unresolved_references[-1].blocks_copy is True


def test_binary_question_is_not_mislabeled_as_an_accepted_proposal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Diagnose the CI failure."),
        event(2, "assistant", "Does it only fail on CI?"),
        event(3, "user", "yes"),
    ])

    assert state.active_goal is not None
    assert "User answered yes to the assistant's question" in (
        state.active_goal.composite_request_verbatim
    )
    assert "proposal" not in state.decisions[-1].statement.casefold()


def test_plain_assistant_status_is_not_a_fix_it_antecedent() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Investigate the log failure."),
        event(2, "assistant", "I am still inspecting logs."),
        event(3, "user", "fix it"),
    ])

    assert state.active_goal is not None
    assert len(state.active_goal.fragments) == 1
    assert state.unresolved_references[-1].user_text == "fix it"


def test_noninteractive_update_does_not_erase_a_concrete_proposal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve the handoff."),
        event(2, "assistant", "I recommend a semantic readiness dimension."),
        event(3, "assistant", "The existing response shape remains backwards compatible."),
        event(4, "user", "yes"),
    ])

    assert state.unresolved_references == ()
    assert "Accepted the prior assistant proposal" in state.decisions[-1].statement


def test_open_question_does_not_accept_yes_as_a_meaningful_answer() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Diagnose the CI failure."),
        event(2, "assistant", "Why is the CI job failing?"),
        event(3, "user", "yes"),
    ])

    assert state.unresolved_references[-1].user_text == "yes"
    assert len(state.active_goal.fragments) == 1


def test_assistant_future_status_is_not_an_actionable_proposal() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Investigate the logs."),
        event(2, "assistant", "I am still inspecting logs and I will report back."),
        event(3, "user", "fix it"),
    ])

    assert state.unresolved_references[-1].user_text == "fix it"
    assert len(state.active_goal.fragments) == 1


def test_cancel_clears_active_decisions_from_the_serialized_state() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Improve the handoff."),
        event(2, "assistant", "I recommend compact mode."),
        event(3, "user", "yes"),
        event(4, "user", "cancel"),
    ])

    assert state.active_goal is None
    assert state.decisions == ()
    assert state.to_dict()["decisions"] == []


def test_explicit_task_can_legitimately_mention_runtime_policy_vocabulary() -> None:
    state = resolve_conversation_state([
        event(1, "user", "Document filesystem sandboxing for plugin authors."),
    ])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == (
        "Document filesystem sandboxing for plugin authors."
    )


def test_replay_hash_is_stable_and_boundary_scoped() -> None:
    events = [
        event(1, "user", "Fix the session cards."),
        event(2, "assistant", "I found the card styles."),
        event(3, "user", "Also fix the hover state."),
    ]

    first = resolve_conversation_state(events)
    second = resolve_conversation_state(list(reversed(events)))
    bounded = resolve_conversation_state(events, boundary_sequence=1)

    assert first.state_sha256 == second.state_sha256
    assert bounded.active_goal is not None
    assert len(bounded.active_goal.fragments) == 1
    assert bounded.state_sha256 != first.state_sha256


def test_single_goal_preserves_the_exact_user_request_boundary() -> None:
    request = "  Fix the session cards exactly.\n"

    state = resolve_conversation_state([event(1, "user", request)])

    assert state.active_goal is not None
    assert state.active_goal.root_request_verbatim == request
    assert state.active_goal.composite_request_verbatim == request
    assert state.active_goal.fragments[0].request_verbatim == request
