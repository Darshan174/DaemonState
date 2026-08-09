from types import SimpleNamespace

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
