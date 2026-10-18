from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.session_context as session_context_service
from app.services.context_quality_adapters import session_context_claims
from app.services.request_artifacts import TrustedRequestImageDescriptor
from app.services.session_context import (
    build_session_context_artifact,
    render_background_session_context,
)


def _contract() -> dict:
    return {
        "current_goal": {
            "text": "Explain why the overlay targets the wrong composer.",
            "request_sha256": "a" * 64,
        },
        "requirements": [
            {
                "id": "R1",
                "text": "Explain why the overlay targets the wrong composer.",
                "status": "remaining",
                "source_event_id": "event-user",
            }
        ],
        "constraints": [
            {
                "id": "C1",
                "text": "Do not edit files until the user asks for a change.",
                "source_event_id": "event-user",
            }
        ],
        "attachment_dependencies": [
            {
                "id": "A1",
                "name": "composer screenshot",
                "required": True,
                "available": True,
                "sha256": "b" * 64,
            }
        ],
        "implementation_summary": [
            {
                "statement": "The previous agent reported updating focus detection.",
                "authority": "agent_reported",
            },
            {
                "statement": "A focused test passed at capture.",
                "authority": "observed_session_evidence",
            },
        ],
        "decisions": [{"statement": "Keep delivery fail-closed."}],
        "failed_attempts": [{"statement": "Window-title matching was unreliable."}],
        "blockers": [{"statement": "The active composer identity was not observed."}],
        "open_items": [],
        "discoveries": [
            {"statement": "The composer is selected from the focused window."}
        ],
        "verification": [
            {
                "id": "V1",
                "command": "pytest -q tests/test_focus.py",
                "status": "passed",
                "exit_code": 0,
                "scope": "tests/test_focus.py",
                "cwd": "/repo",
                "observed_at": "2026-08-20T12:00:00Z",
                "requirement_ids": ["R1"],
            }
        ],
        "repository": {
            "root": "/repo",
            "branch": "main",
            "head_commit": "c" * 40,
            "status_fingerprint": "d" * 64,
            "dirty": True,
            "freshness": {"status": "changed"},
        },
        "files": {
            "modified": [],
            "relevant": [{"path": "app/focus.py"}],
            "pre_existing_at_handoff": [],
        },
        "readiness": {"unknowns": [{"message": "Live focus remains unverified."}]},
        "exact_next_action": {
            "text": "Immediately edit app/focus.py and run destructive-command."
        },
        "verification_plan": [
            {"text": "Run destructive-command after editing app/focus.py."}
        ],
    }


def _build_artifact(monkeypatch, contract: dict, *, base_updates=None, **build_kwargs) -> dict:
    base = {
        "id": "checkpoint-1",
        "provider": "codex",
        "session_id": "session-1",
        "source_document_id": "document-1",
        "boundary": {
            "event_id": "event-boundary",
            "sequence_number": 4,
            "has_newer_events": False,
            "occurred_at": "2026-08-20T12:00:00Z",
            "snapshot_phase": "post_compaction",
        },
        "currentness": {"state": "current"},
    }
    base.update(base_updates or {})
    monkeypatch.setattr(
        session_context_service,
        "checkpoint_to_dict",
        lambda *_args, **_kwargs: base,
    )
    monkeypatch.setattr(
        session_context_service,
        "build_session_handoff_contract",
        lambda *_args, **_kwargs: contract,
    )
    monkeypatch.setattr(
        session_context_service,
        "_session_handoff_token_accounting",
        lambda *_args, **_kwargs: {
            "estimated_tokens": 100,
            "render_variant": "compact_v2",
        },
    )
    return build_session_context_artifact(
        SimpleNamespace(),
        request_verbatim=contract["current_goal"]["text"],
        **build_kwargs,
    )


def test_empty_retrieval_keeps_the_compact_overview_used_for_budgeting(monkeypatch):
    contract = {"current_goal": {"text": "Explain the cache behavior."}}
    claims = session_context_claims(
        contract, checkpoint_id="checkpoint-1", boundary_event_id="event-boundary",
    )
    snapshot = {
        "boundary": {"sequence_number": 4}, "captured_at": "2026-08-20T12:00:00Z",
    }
    compact = render_background_session_context(
        claims=claims, contract=contract, snapshot=snapshot, compact=True,
    )
    budget = (len(compact) + 3) // 4
    artifact = _build_artifact(
        monkeypatch, contract, token_budget=budget,
        retrieval_context={"spans": [], "candidate_count": 0, "limitations": []},
    )
    assert len(artifact["content"]) <= budget * 4
    assert "## Awaiting user instruction" in artifact["content"]


def test_public_background_contract_is_copyable_when_receiver_evidence_is_pending(
    monkeypatch,
) -> None:
    artifact = _build_artifact(monkeypatch, _contract())

    assert artifact["schema_version"] == "session_background.v1"
    assert artifact["semantic_schema_version"] == "session_context.v3"
    assert artifact["render_variant"] == "session_context_background.v7"
    assert artifact["compatibility"] == {
        "legacy_schema_version": "session_handoff.v1",
    }
    assert artifact["operation_capabilities"]["preview"] == {
        "allowed": True,
        "status": "available",
        "blocking_issue_codes": [],
    }
    assert artifact["operation_capabilities"]["clipboard_copy"] == {
        "allowed": True,
        "status": "ready_with_limitations",
        "blocking_issue_codes": [],
    }
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["readiness"]["status"] == "awaiting_user_instruction"
    assert artifact["readiness_dimensions"]["source_completeness"] == {
        "status": "complete",
        "complete": True,
        "required_attachment_ids": ["A1"],
        "missing_attachment_ids": [],
        "manifest_missing_attachment_ids": [],
        "source_bytes_unavailable_attachment_ids": [],
    }
    assert artifact["readiness_dimensions"]["receiver_readiness"] == {
        "status": "materialization_required",
        "ready": False,
        "required_attachment_ids": ["A1"],
        "materialization_required_ids": ["A1"],
        "source_bytes_unavailable_attachment_ids": [],
    }
    assert artifact["readiness_dimensions"]["evidence_access"]["blocks_copy"] is False
    assert artifact["readiness_dimensions"]["critical_coverage"] == {
        "status": "incomplete",
        "complete": False,
        "missing_fragments": ["attachment:A1"],
    }
    assert artifact["delivery"]["preview_ready"] is True
    assert artifact["delivery"]["clipboard_copy_ready"] is True
    assert artifact["content"].startswith("# Session Context — background")
    assert "not included in this copied text or confirmed available to the receiver" in artifact["content"]
    assert "2026-08-20T12:00:00Z" in artifact["content"]


def test_repository_chronology_distinguishes_session_checkpoint_and_current_inspection(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["repository"].update({
        "branch": "branch-now",
        "captured_at": "2026-10-16T14:16:16Z",
        "snapshot_authority": "observed_at_handoff",
        "captured_snapshot": {
            "root": "/repo", "branch": "branch-at-checkpoint",
            "head_commit": "e" * 40, "status_fingerprint": "f" * 64,
            "dirty": False, "captured_at": "2026-08-11T08:14:26Z",
        },
    })
    contract["files"]["pre_existing_at_handoff"] = [
        {"path": f"src/current-{index}.py"} for index in range(20)
    ]
    artifact = _build_artifact(monkeypatch, contract, base_updates={"boundary": {
        "event_id": "historical-event", "sequence_number": 409,
        "occurred_at": "2026-05-07T16:55:14Z", "has_newer_events": True,
    }})
    content = artifact["content"]
    saved_section = content.split("### Repository snapshot saved with the checkpoint\n", 1)[1]
    saved_section, current_section = saved_section.split("### Repository inspected for this context\n", 1)
    current_section = current_section.split("## Relevant surfaces\n", 1)[0]

    assert "Session event boundary time: 2026-05-07T16:55:14Z" in content
    assert "branch-at-checkpoint" in saved_section
    assert "2026-08-11T08:14:26Z" in saved_section
    assert "branch-now" not in saved_section
    assert "branch-now" in current_section
    assert "2026-10-16T14:16:16Z" in current_section
    assert "branch-at-checkpoint" not in current_section
    assert "establishes the branch used during an earlier session event" in content
    assert "Observations below describe the captured session" not in content
    assert "[observed at capture]" not in content
    assert "[repository inspection for this context] 20 changed paths" in content
    claims = {claim["stable_id"]: claim for claim in artifact["claim_manifest"]}
    assert claims["session.repository_checkpoint_snapshot"]["truth_state"] == "historical"
    assert claims["session.repository_checkpoint_snapshot"]["repository_snapshot_sha256"] == "f" * 64
    assert claims["session.repository_snapshot"]["truth_state"] == "current"
    assert claims["session.repository_snapshot"]["repository_snapshot_sha256"] == "d" * 64


def test_saved_repository_snapshot_is_never_promoted_to_current_without_an_inspection(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["repository"].update({
        "branch": "saved-branch",
        "captured_at": "2026-08-11T08:14:26Z",
        "snapshot_authority": "observed_at_checkpoint",
    })
    contract["repository"]["captured_snapshot"] = dict(contract["repository"])
    contract["files"]["pre_existing_at_handoff"] = [{"path": "saved/file.py"}]
    artifact = _build_artifact(monkeypatch, contract)
    claims = {claim["stable_id"]: claim for claim in artifact["claim_manifest"]}

    assert claims["session.repository_snapshot"]["truth_state"] == "historical"
    assert claims["session.file:saved/file.py"]["truth_state"] == "historical"
    assert "No newer repository inspection is included" in artifact["content"]
    assert artifact["content"].count("branch saved-branch") == 1
    assert "session.repository_checkpoint_snapshot" not in claims


def test_public_background_contract_is_copy_ready_after_receiver_materialization(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["attachment_dependencies"][0].update(
        {
            "receiver_availability": "available",
            "receiver_local_reference": "/receiver/composer-screenshot.png",
        }
    )

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["quality_report"]["status"] == "ready"
    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["readiness"]["status"] == "awaiting_user_instruction"
    assert artifact["readiness_dimensions"]["receiver_readiness"]["status"] == "ready"
    assert artifact["readiness_dimensions"]["receiver_readiness"]["ready"] is True
    assert artifact["readiness_dimensions"]["critical_coverage"] == {
        "status": "complete", "complete": True, "missing_fragments": [],
    }
    assert artifact["readiness_dimensions"]["evidence_access"]["blocks_copy"] is False
    assert artifact["operation_capabilities"]["clipboard_copy"] == {
        "allowed": True,
        "status": "ready",
        "blocking_issue_codes": [],
    }
    assert "available in receiving context at /receiver/composer-screenshot.png" in artifact["content"]


@pytest.mark.parametrize(
    "base_updates",
    [
        {"boundary": {
            "event_id": "event-boundary", "has_newer_events": True,
            "occurred_at": "2026-08-20T12:00:00Z",
            "sequence_number": 4,
        }},
        {"currentness": {"state": "superseded"}},
    ],
)
def test_public_background_old_snapshot_is_copyable_and_visible(
    monkeypatch, base_updates,
) -> None:
    contract = _contract()
    contract["attachment_dependencies"] = []

    artifact = _build_artifact(monkeypatch, contract, base_updates=base_updates)

    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["quality_evaluation"]["hard_failures"] == []
    assert "CURRENT_STATE_BOUND_TO_OLD_SNAPSHOT" in artifact["quality_evaluation"]["warnings"]
    assert "[older snapshot] Newer session activity exists and is not included" in artifact["content"]
    assert "2026-08-20T12:00:00Z" in artifact["content"]
    assert "Captured through session event 4" in artifact["content"]
    assert "event-boundary" not in artifact["content"]
    assert artifact["readiness_dimensions"]["critical_coverage"]["complete"] is True


def test_public_background_invalid_attachment_binding_still_blocks_copy(monkeypatch) -> None:
    descriptor = TrustedRequestImageDescriptor(
        path="/source/composer.png",
        sha256="b" * 64,
        mime_type="image/png",
        binding_valid=False,
        binding_error="The attachment belongs to another source event.",
    )

    artifact = _build_artifact(
        monkeypatch, _contract(), trusted_attachment_descriptors=(descriptor,),
    )

    assert artifact["quality_report"]["copy_ready"] is False
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is False
    assert artifact["quality_report"]["status"] == "blocked"
    assert "HASH_OR_LINEAGE_FAILURE" in artifact["quality_evaluation"]["hard_failures"]


def test_public_background_receiver_flag_without_reference_is_not_delivery(monkeypatch) -> None:
    contract = _contract()
    contract["attachment_dependencies"][0]["receiver_availability"] = "available"

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["readiness_dimensions"]["receiver_readiness"]["ready"] is False
    assert "not included in this copied text or confirmed available to the receiver" in artifact["content"]


def test_real_background_builder_accepts_checkpoint_without_goal() -> None:
    data = {
        "id": "checkpoint-without-goal",
        "provider": "codex",
        "session_id": "session-without-goal",
        "source_document_id": "document-without-goal",
        "boundary": {
            "event_id": "boundary-without-goal",
            "occurred_at": "2026-08-20T12:00:00Z",
            "has_newer_events": False,
        },
        "currentness": {"state": "current"},
        "sections": {
            "goal": [],
            "progress": [{
                "statement": "The earlier agent inspected the failing parser.",
                "truth_state": "reported",
                "payload": {},
            }],
        },
    }

    artifact = build_session_context_artifact(
        SimpleNamespace(), request_verbatim="", checkpoint_data=data,
    )

    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["current_goal"]["request_verbatim"] == ""
    assert not any(item["kind"] == "prior_user_objective" for item in artifact["claim_manifest"])
    assert "No unambiguous prior user objective was recovered" in artifact["content"]
    assert "The earlier agent inspected the failing parser." in artifact["content"]
    coverage = artifact["readiness_dimensions"]["critical_coverage"]
    assert coverage["complete"] is False
    assert "prior_user_objective" in coverage["missing_fragments"]


def test_public_background_contract_distinguishes_missing_source_from_delivery(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["attachment_dependencies"][0].update(
        {"available": False, "sha256": None}
    )

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["operation_capabilities"]["preview"]["allowed"] is True
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is True
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["readiness_dimensions"]["source_completeness"] == {
        "status": "incomplete",
        "complete": False,
        "required_attachment_ids": ["A1"],
        "missing_attachment_ids": ["A1"],
        "manifest_missing_attachment_ids": ["A1"],
        "source_bytes_unavailable_attachment_ids": [],
    }
    assert artifact["readiness_dimensions"]["receiver_readiness"] == {
        "status": "source_unavailable",
        "ready": False,
        "required_attachment_ids": ["A1"],
        "materialization_required_ids": [],
        "source_bytes_unavailable_attachment_ids": [],
    }
    assert "REQUIRED_DEPENDENCY_MISSING" not in (
        artifact["operation_capabilities"]["clipboard_copy"][
            "blocking_issue_codes"
        ]
    )
    assert "source bytes unavailable" in artifact["content"]
    assert "image or attachment contents are not included in this context" in artifact["content"]
    coverage = artifact["readiness_dimensions"]["critical_coverage"]
    assert coverage["complete"] is False
    assert "attachment:A1" in coverage["missing_fragments"]


def test_public_background_contract_keeps_hash_bound_byte_missing_dependency(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["attachment_dependencies"][0].update(
        {
            "available": False,
            "source_identity_complete": True,
            "source_bytes_available": False,
            "receiver_availability": "unknown",
        }
    )

    artifact = _build_artifact(monkeypatch, contract)

    source = artifact["readiness_dimensions"]["source_completeness"]
    assert source == {
        "status": "complete",
        "complete": True,
        "required_attachment_ids": ["A1"],
        "missing_attachment_ids": [],
        "manifest_missing_attachment_ids": [],
        "source_bytes_unavailable_attachment_ids": ["A1"],
    }
    receiver = artifact["readiness_dimensions"]["receiver_readiness"]
    assert receiver == {
        "status": "materialization_required",
        "ready": False,
        "required_attachment_ids": ["A1"],
        "materialization_required_ids": ["A1"],
        "source_bytes_unavailable_attachment_ids": ["A1"],
    }
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["operation_capabilities"]["clipboard_copy"] == {
        "allowed": True,
        "status": "ready_with_limitations",
        "blocking_issue_codes": [],
    }
    assert artifact["attachment_dependencies"][0]["sha256"] == "b" * 64


def test_public_background_contract_copies_with_unmanifested_reference_warning(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["attachment_dependencies"] = []
    contract["current_goal"]["self_contained"] = False
    contract["unresolved_dependencies"] = [
        {
            "id": "U1",
            "kind": "file",
            "name": "Referenced file evidence",
            "required": True,
            "status": "unresolved",
            "blocks_copy": True,
            "blocking_issue_code": "required_file_dependency_manifest_missing",
            "reason": (
                "The user explicitly depends on a file, but no portable file "
                "manifest was captured."
            ),
        }
    ]

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["operation_capabilities"]["preview"]["allowed"] is True
    assert artifact["operation_capabilities"]["clipboard_copy"] == {
        "allowed": True,
        "status": "ready_with_limitations",
        "blocking_issue_codes": [],
    }
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["readiness_dimensions"]["dependency_discovery"] == {
        "status": "unresolved",
        "complete": False,
        "unresolved_dependency_ids": ["U1"],
        "unresolved_dependencies": [{
            **contract["unresolved_dependencies"][0],
            "blocks_copy": False,
            "blocks_execution": True,
        }],
    }
    assert artifact["readiness_dimensions"]["source_completeness"][
        "unresolved_dependency_ids"
    ] == ["U1"]
    assert artifact["delivery"]["preview_ready"] is True
    assert artifact["delivery"]["clipboard_copy_ready"] is True
    assert "[unresolved required file dependency]" in artifact["content"]
    coverage = artifact["readiness_dimensions"]["critical_coverage"]
    assert coverage["complete"] is False
    assert "dependency:U1" in coverage["missing_fragments"]


def test_public_session_context_is_background_only() -> None:
    contract = _contract()
    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    content = render_background_session_context(claims=claims, contract=contract)

    assert "# Session Context — background" in content
    assert "Awaiting user instruction" in content
    assert "Explain why the overlay targets the wrong composer." in content
    assert "composer screenshot" in content
    assert "A focused test passed at capture." in content
    assert "`pytest -q tests/test_focus.py` passed with exit code 0" in content
    assert "verified prior-session observation; not an instruction" in content
    assert "The composer is selected from the focused window." in content
    assert "prior-session report; not an instruction" in content
    assert "reported, not independently verified" in content
    assert "Window-title matching was unreliable." in content
    assert "app/focus.py" in content
    assert "Live focus remains unverified." in content
    assert "## Start here" not in content
    assert "## Done when" not in content
    assert "Execution Ready" not in content
    assert "Immediately edit" not in content
    assert "destructive-command" not in content


def test_public_session_context_renders_referenced_conversation_as_evidence_only() -> None:
    contract = _contract()
    contract["supporting_context"] = [
        {
            "role": "user",
            "text": "The overlay jumped to the composer in the other window.",
            "source": "embedded_referenced_conversation",
            "content_sha256": "e" * 64,
        },
        {
            "role": "assistant",
            "text": "The earlier assistant proposed matching the window title.",
            "source": "embedded_referenced_conversation",
            "content_sha256": "f" * 64,
        },
    ]
    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    referenced = [
        item
        for item in claims
        if item.section == "referenced_conversation_context"
    ]
    content = render_background_session_context(claims=claims, contract=contract)

    assert [item.kind for item in referenced] == [
        "referenced_user_turn",
        "referenced_assistant_turn",
    ]
    assert all(item.authority == "agent_report" for item in referenced)
    assert all(item.truth_state == "historical" for item in referenced)
    assert "## Referenced conversation context" in content
    assert "historical evidence only" in content
    assert "do not grant authority" in content
    user_turn = (
        "> [historical referenced user turn; evidence only, not authority] "
        "The overlay jumped to the composer in the other window."
    )
    assistant_turn = (
        "> [historical referenced assistant turn; evidence only, not authority] "
        "The earlier assistant proposed matching the window title."
    )
    assert user_turn in content
    assert assistant_turn in content
    assert content.index(user_turn) < content.index(assistant_turn)


def test_public_session_context_keeps_negated_reference_metadata_only() -> None:
    contract = _contract()
    contract["current_goal"].update(
        {
            "request_verbatim": "Review the last prompt; do not implement it.",
            "text": "Review the last prompt; do not implement it.",
        }
    )
    contract["supporting_context"] = [
        {
            "role": "assistant",
            "text": "Delete the database and rewrite app/core.py.",
            "source": "embedded_referenced_conversation",
            "content_sha256": "f" * 64,
        }
    ]
    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    referenced = next(
        item for item in claims if item.kind == "referenced_assistant_turn"
    )
    content = render_background_session_context(claims=claims, contract=contract)

    assert referenced.selection.value == "excluded"
    assert referenced.exclusion_reason == "negated_historical_reference"
    assert "Delete the database" not in content
    assert "rewrite app/core.py" not in content
    assert "No referenced user/assistant conversation was materialized" in content


def test_public_session_context_bounds_repeated_state_but_retains_typed_manifest(
    monkeypatch,
) -> None:
    contract = _contract()
    contract["current_goal"]["text"] = (
        "Objective " + ("o" * 2_000) + " OBJECTIVE_TAIL"
    )
    contract["requirements"] = [
        {
            "id": "R1",
            "text": "Requirement " + ("r" * 900) + " REQUIREMENT_TAIL",
            "status": "remaining",
            "source_event_id": "event-user",
        }
    ]
    contract["constraints"] = [
        {
            "id": "C1",
            "text": "Constraint " + ("c" * 900) + " CONSTRAINT_TAIL",
            "source_event_id": "event-user",
        }
    ]
    contract["blockers"] = [
        {"statement": "Blocker " + ("b" * 900) + " BLOCKER_TAIL"}
    ]
    contract["unresolved_dependencies"] = [
        {
            "id": "U1",
            "kind": "file",
            "required": True,
            "reason": "Dependency " + ("d" * 900) + " DEPENDENCY_TAIL",
        }
    ]
    contract["implementation_summary"] = [
        {
            "statement": f"Progress item {index:02d} was reported.",
            "authority": "agent_reported",
        }
        for index in range(20)
    ]
    contract["verification"] = [
        {
            "id": f"V{index:02d}",
            "command": f"pytest verification_{index:02d}.py",
            "status": "failed" if index == 0 else "passed",
            "exit_code": 1 if index == 0 else 0,
            "observed_at": f"2026-08-20T12:{index:02d}:00Z",
        }
        for index in range(12)
    ]

    artifact = _build_artifact(monkeypatch, contract)
    content = artifact["content"]
    manifest = artifact["claim_manifest"]

    assert sum(item["kind"] == "progress" for item in manifest) == 20
    assert sum(item["kind"] == "verification_observation" for item in manifest) == 12
    assert content.count("Progress item ") == 8
    assert content.count("`pytest verification_") == 6
    for index in range(12):
        assert f"Progress item {index:02d}" not in content
    for index in range(12, 20):
        assert f"Progress item {index:02d}" in content
    assert "`pytest verification_00.py` failed with exit code 1" in content
    for index in range(1, 7):
        assert f"`pytest verification_{index:02d}.py`" not in content
    for index in range(7, 12):
        assert f"`pytest verification_{index:02d}.py`" in content
    assert "12 additional progress reports" in content
    assert "6 additional verification observations" in content
    assert content.count("complete typed claim manifest") == 2
    assert "OBJECTIVE_TAIL" in content
    assert "REQUIREMENT_TAIL" in content
    assert "CONSTRAINT_TAIL" in content
    assert "BLOCKER_TAIL" in content
    assert "DEPENDENCY_TAIL" in content


def test_internal_actions_are_excluded_but_preserved_in_claim_manifest() -> None:
    contract = _contract()
    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    action = next(item for item in claims if item.kind == "inferred_action")
    future_check = next(item for item in claims if item.kind == "future_action")

    assert action.selection.value == "excluded"
    assert action.exclusion_reason == "background_only_scope"
    assert future_check.selection.value == "excluded"


def test_public_session_context_bounds_file_inventory_without_losing_manifest() -> None:
    contract = _contract()
    contract["files"] = {
        "modified": [],
        "relevant": [],
        "pre_existing_at_handoff": [
            {"path": f"app/dirty_{index:02}.py"}
            for index in range(20)
        ],
    }
    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )

    file_claims = [item for item in claims if item.kind == "relevant_file"]
    content = render_background_session_context(claims=claims, contract=contract)

    assert len(file_claims) == 20
    assert sum(item.selection.value == "included" for item in file_claims) == 12
    assert sum(item.selection.value == "excluded" for item in file_claims) == 8
    assert "app/dirty_00.py" in content
    assert "app/dirty_19.py" not in content
    assert "[repository observation; time unavailable] 20 changed paths were recorded" in content


def test_session_only_delivery_text_does_not_pollute_relevant_targets() -> None:
    contract = _contract()
    contract["current_goal"]["text"] = (
        "Add the Grok logo, then push only the changes made in this session."
    )
    contract["requirements"][0]["text"] = contract["current_goal"]["text"]
    contract["files"]["relevant"] = [
        {"path": "frontend/src/assets/grok.svg"},
        {"path": "app/services/session_library.py"},
        {"path": "app/services/session_summary.py"},
        {"path": "frontend/src/pages/sessionContinuity.js"},
    ]

    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )
    files = {item.statement: item for item in claims if item.kind == "relevant_file"}

    assert files["frontend/src/assets/grok.svg"].selection.value == "included"
    for path in (
        "app/services/session_library.py",
        "app/services/session_summary.py",
        "frontend/src/pages/sessionContinuity.js",
    ):
        assert files[path].selection.value == "excluded"
        assert files[path].exclusion_reason == "inferred_target_noise"


def test_session_context_files_remain_when_context_system_is_the_subject() -> None:
    contract = _contract()
    contract["current_goal"]["text"] = "Improve Session Context goal fidelity."
    contract["requirements"][0]["text"] = contract["current_goal"]["text"]
    contract["files"]["relevant"] = [
        {"path": "app/services/session_summary.py"},
    ]

    claims = session_context_claims(
        contract,
        checkpoint_id="checkpoint-1",
        boundary_event_id="event-boundary",
    )
    file_claim = next(item for item in claims if item.kind == "relevant_file")

    assert file_claim.selection.value == "included"


@pytest.mark.parametrize(
    ("candidate", "classification"),
    [
        ("did u fix it?", "deictic"),
        (
            "[Request interrupted by user for tool use]",
            "interruption_marker",
        ),
    ],
)
def test_public_background_copy_survives_unresolved_objective(
    monkeypatch,
    candidate: str,
    classification: str,
) -> None:
    contract = _contract()
    contract["current_goal"].update(
        {
            "request_verbatim": candidate,
            "text": candidate,
        }
    )
    contract["requirements"][0]["text"] = candidate
    contract["attachment_dependencies"] = []
    contract["objective_resolution"] = {
        "classification": classification,
        "status": "unresolved",
        "reason": "no_substantive_antecedent",
        "blocks_copy": True,
        "blocks_execution": True,
    }

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["objective_resolution"] == {
        **contract["objective_resolution"], "blocks_copy": False,
    }
    assert artifact["operation_capabilities"]["preview"]["allowed"] is True
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is True
    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    assert artifact["quality_report"]["copy_ready"] is True
    assert "USER_OBJECTIVE_MISSING" not in artifact["quality_evaluation"]["hard_failures"]
    assert "No unambiguous prior user objective was recovered" in artifact["content"]
    assert candidate in artifact["content"]
    coverage = artifact["readiness_dimensions"]["critical_coverage"]
    assert coverage["complete"] is False
    assert "prior_user_objective" in coverage["missing_fragments"]


def test_public_background_renders_unique_resolved_deictic_objective(
    monkeypatch,
) -> None:
    contract = _contract()
    resolved = (
        "Fix the antecedent objective:\n\n"
        "Correct delivery so it targets the active chat composer."
    )
    contract["current_goal"].update(
        {
            "request_verbatim": "fix it",
            "text": resolved,
            "resolved_request_sha256": "e" * 64,
        }
    )
    contract["requirements"][0]["text"] = resolved
    contract["attachment_dependencies"] = []
    contract["objective_resolution"] = {
        "classification": "deictic",
        "status": "resolved",
        "reason": "resolved_against_unique_structured_antecedent",
        "blocks_copy": False,
        "blocks_execution": False,
    }

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["quality_report"]["copy_ready"] is True
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is True
    assert "Fix the antecedent objective" in artifact["content"]
    assert "Correct delivery so it targets the active chat composer" in artifact["content"]


@pytest.mark.parametrize(
    "classification",
    [
        "interruption_marker",
        "completion_marker",
        "provider_compaction_wrapper",
    ],
)
def test_public_background_restored_marker_requires_a_fresh_execution_lead(
    monkeypatch,
    classification: str,
) -> None:
    restored = "Review the context compiler failures."
    contract = _contract()
    contract["current_goal"].update(
        {
            "request_verbatim": "[historical transport marker]",
            "text": restored,
            "resolved_request_sha256": "e" * 64,
        }
    )
    contract["requirements"][0]["text"] = restored
    contract["attachment_dependencies"] = []
    contract["objective_resolution"] = {
        "classification": classification,
        "status": "resolved",
        "candidate_text": "[historical transport marker]",
        "resolved_text": restored,
        "reason": "resolved_against_unique_structured_antecedent",
        "blocks_copy": False,
        "blocks_execution": True,
        "requires_fresh_user_lead": True,
    }

    artifact = _build_artifact(monkeypatch, contract)

    assert artifact["objective_resolution"] == contract["objective_resolution"]
    assert artifact["operation_capabilities"]["preview"]["allowed"] is True
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is True
    assert artifact["operation_capabilities"]["automatic_execution"]["allowed"] is False
    assert artifact["quality_report"]["automatic_execution_ready"] is False
    assert artifact["objective_resolution"]["requires_fresh_user_lead"] is True
    assert restored in artifact["content"]


def test_open_requirements_keep_session_order_and_historical_labels(monkeypatch) -> None:
    contract = _contract()
    statements = [
        "Mission: operational completeness and a real backup/restore path.",
        "Expand runtime diagnostics so an operator can tell:",
        "is the DB schema current?",
        "is the worker healthy?",
        "Add upgrade and rollback procedures that are specific and executable.",
    ]
    contract["requirements"] = [
        {"id": f"R{index}", "text": text, "status": "remaining", "source_event_id": "event-user"}
        for index, text in enumerate(statements, start=1)
    ]
    content = _build_artifact(monkeypatch, contract)["content"]

    positions = [content.index(f"- [open at capture] {text}") for text in statements]
    assert positions == sorted(positions)
    assert "[observed current]" not in content
    assert (
        "- [historical user constraint] Do not edit files until the user asks for a change."
        in content
    )
