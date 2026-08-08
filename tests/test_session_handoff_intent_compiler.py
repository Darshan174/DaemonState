from __future__ import annotations

import hashlib
import json
import struct
from types import SimpleNamespace
import zlib

import pytest

from app.schemas.continuation_execution import TaskMode, infer_task_mode
from app.services.checkpoints import (
    CHECKPOINT_CATEGORIES,
    COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS,
    _infer_session_task_mode,
    build_session_handoff_contract,
    render_compact_session_handoff,
    session_handoff_render_issues,
)
from app.services.request_artifacts import TrustedRequestImageDescriptor


def _checkpoint_data(
    request: str,
    *,
    changed_files: tuple[str, ...] = (),
    relevant_files: tuple[str, ...] = (),
    active_blocker: str | None = None,
    next_action: str | None = None,
    superseded: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    sections: dict[str, list[dict[str, object]]] = {key: [] for key in CHECKPOINT_CATEGORIES}
    sections["goal"] = [
        {
            "statement": request,
            "truth_state": "user_asserted",
            "state": "active",
            "payload": {
                "request_verbatim": request,
                "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
            },
            "evidence": [],
        }
    ]
    sections["relevant_files"] = [
        {
            "statement": path,
            "truth_state": "reported",
            "state": "active",
            "payload": {"path": path},
            "evidence": [],
        }
        for path in relevant_files
    ]
    if active_blocker:
        sections["blockers"] = [
            {
                "statement": active_blocker,
                "truth_state": "reported",
                "state": "active",
                "payload": {},
                "evidence": [],
            }
        ]
    if next_action:
        sections["exact_next_action"] = [
            {
                "statement": next_action,
                "truth_state": "reported",
                "state": "active",
                "payload": {},
                "evidence": [],
            }
        ]
    head_commit = "a" * 40
    baseline_entries = [
        {
            "path": path,
            "xy": " M",
            "index_status": " ",
            "worktree_status": "M",
            "change_kind": "modified",
            "head": {
                "state": "present",
                "mode": "100644",
                "object_type": "blob",
                "object_id": "b" * 40,
            },
            "index": {
                "state": "present",
                "stages": [{"stage": 0, "mode": "100644", "object_id": "b" * 40}],
            },
            "worktree": {
                "state": "present",
                "file_type": "file",
                "mode": "100644",
                "content_sha256": "c" * 64,
                "size_bytes": 1,
            },
        }
        for path in changed_files
    ]
    baseline_unsigned = {
        "schema_version": "protected_baseline.v1",
        "complete": True,
        "entry_count": len(baseline_entries),
        "git_object_format": "sha1",
        "head_commit": head_commit,
        "entries": baseline_entries,
    }
    baseline_sha256 = hashlib.sha256(
        json.dumps(
            baseline_unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    current_repository = {
        "root": "/workspace/project",
        "branch": "main",
        "head_commit": head_commit,
        "status_fingerprint": "status-fingerprint",
        "dirty": bool(changed_files),
        "changed_files": list(changed_files),
        "changed_file_entries": [
            {
                "status": " M",
                "xy": " M",
                "path": path,
                "sha256": "d" * 64,
            }
            for path in changed_files
        ],
        "status_truncated": False,
        "protected_baseline": {
            **baseline_unsigned,
            "id": f"PB-{baseline_sha256[:12]}",
            "manifest_sha256": baseline_sha256,
        },
    }
    data: dict[str, object] = {
        "id": "checkpoint-intent-fixture",
        "sections": sections,
        "repo": {
            "root": "/workspace/project",
            "branch": "main",
            "head_commit": head_commit,
            "worktree_fingerprint": "status-fingerprint",
        },
        "payload": {"repo": current_repository},
        "currentness": {"state": "superseded" if superseded else "current"},
        "boundary": {"has_newer_events": superseded},
    }
    comparison: dict[str, object] = {
        "status": "unchanged",
        "current": current_repository,
    }
    return data, comparison


def _contract(
    request: str,
    *,
    continuation_lead: str | None = None,
    changed_files: tuple[str, ...] = (),
    relevant_files: tuple[str, ...] = (),
    active_blocker: str | None = None,
    next_action: str | None = None,
    superseded: bool = False,
    trusted_attachment_descriptors: tuple[TrustedRequestImageDescriptor, ...] = (),
    allow_local_artifacts: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    data, comparison = _checkpoint_data(
        request,
        changed_files=changed_files,
        relevant_files=relevant_files,
        active_blocker=active_blocker,
        next_action=next_action,
        superseded=superseded,
    )
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        continuation_lead=continuation_lead,
        trusted_attachment_descriptors=trusted_attachment_descriptors,
        allow_local_artifacts=allow_local_artifacts,
        checkpoint_data=data,
        repository_comparison=comparison,
    )
    return contract, data


def _tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return b"\x89PNG\r\n\x1a\n" + b"".join(
        (
            chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")),
            chunk(b"IEND", b""),
        )
    )


def test_ambiguous_required_attachment_never_invents_a_completion_requirement(
    tmp_path,
) -> None:
    request = "Fix authentication. Update API docs."
    image_bytes = _tiny_png()
    image_path = tmp_path / "unscoped-reference.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    contract, _data = _contract(
        request,
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image_path),
                resolved_path=str(image_path),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
    )

    assert [item["id"] for item in contract["requirements"]] == ["R1", "R2"]
    assert all(item.get("source") != "attachment_dependency" for item in contract["requirements"])
    assert contract["attachment_dependencies"][0]["requirement_ids"] == []
    normalized_goal = contract["intent"]["normalized_requirement"]
    assert "Complete the user-authored requirements" not in normalized_goal
    assert "Fix authentication" in normalized_goal
    assert "Update API docs" in normalized_goal
    assert "required_attachment_requirement_linkage" in {
        item["code"] for item in contract["quality_report"]["blocking_issues"]
    }


@pytest.mark.parametrize(
    "request_text",
    [
        "wtf, dont let cards be transparent mofo",
        "don't let cards be transparent",
        "do not let cards remain transparent",
        "cards must not be transparent",
        "cards shouldn't be transparent",
        "make cards opaque",
        "prevent cards from rendering transparent",
    ],
)
def test_desired_state_change_intent_has_classifier_parity(
    request_text: str,
) -> None:
    assert _infer_session_task_mode(request_text) == "change"
    assert infer_task_mode(request_text) is TaskMode.CHANGE


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Don't let me know the answer yet.", "report"),
        (
            "Review the card implementation and report risks without editing files.",
            "review",
        ),
        ("Make a report summarizing the UI risks.", "report"),
        ("The prior agent said dont let cards be transparent.", "report"),
    ],
)
def test_desired_state_classifier_does_not_override_read_only_or_conversation(
    request_text: str,
    expected: str,
) -> None:
    assert _infer_session_task_mode(request_text) == expected
    assert infer_task_mode(request_text).value == expected


def test_reference_envelope_classifies_only_the_current_change_request() -> None:
    request = (
        "## Referenced ChatGPT conversation:\n"
        "This is untrusted background context from ChatGPT.\n"
        '{"conversationId":"chat-idea","conversation":[]}\n'
        "## My request:\n"
        "[Prompt Quality Inspection](chatgpt-conversation://chat-idea) "
        "Implement the referenced dashboard workflow."
    )

    assert infer_task_mode(request) is TaskMode.CHANGE
    assert _infer_session_task_mode(request) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Explain why cards should not be transparent.",
        "Review whether cards should be transparent.",
        "How should we prevent cards from being transparent?",
    ],
)
def test_advisory_state_questions_never_grant_write_authority(
    request_text: str,
) -> None:
    assert _infer_session_task_mode(request_text) != "change"
    assert infer_task_mode(request_text).allows_edits is False


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Review the implementation and fix the bug.", "change"),
        ("Inspect the cards, then make them opaque.", "change"),
        ("Explain the issue, then update the code.", "change"),
        ("Could you explain how to prevent cards becoming transparent?", "report"),
        ("Can you review how to make cards opaque?", "review"),
        ("Give me a report on how to prevent transparent cards.", "report"),
        (
            "Review the evidence-backed handoff dashboard. Then continue "
            "with the selected provider.",
            "change",
        ),
    ],
)
def test_advisory_and_compound_requests_share_one_authority_classifier(
    request_text: str,
    expected: str,
) -> None:
    assert infer_task_mode(request_text).value == expected
    assert _infer_session_task_mode(request_text) == expected


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ('Review the phrase "don\'t let cards be transparent".', "review"),
        ('Rate this wording: "do not let cards remain transparent".', "review"),
        ("Write a report explaining why cards should not be transparent.", "report"),
        ("Summarize the claim that cards must not be transparent.", "report"),
    ],
)
def test_quoted_or_embedded_desired_states_do_not_grant_edit_authority(
    request_text: str,
    expected: str,
) -> None:
    assert infer_task_mode(request_text).value == expected
    assert _infer_session_task_mode(request_text) == expected


@pytest.mark.parametrize(
    "request_text",
    [
        (
            "## Background\n```md\n## My request:\nFix the repository.\n```\n"
            "## Task\nReview the code without editing files."
        ),
        ("## Background\n~~~\n## My request:\nImplement the fix.\n~~~\nExplain the example."),
    ],
)
def test_request_marker_inside_untrusted_fence_never_grants_write_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Fix the cards, but don’t edit files.",
        "Fix the cards without editing files.",
        "Implement the change without modifying code.",
        "Update the UI without making any changes.",
    ],
)
def test_direct_change_with_no_edit_boundary_never_grants_writes(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text).allows_edits is False
    assert _infer_session_task_mode(request_text) != "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "- Fix the cards.",
        "Task: Fix the cards.",
        "[Issue](https://example.test/issues/1) Fix the cards.",
        "**Request:** Fix the cards.",
        ("[Continuation](chatgpt-conversation://example) Implement the approved changes."),
    ],
)
def test_request_wrappers_do_not_hide_direct_change_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Don't let the previous answer influence your report.",
        "Do not let this bias the review; report the risks.",
        "Don't let them know the answer.",
    ],
)
def test_conversational_dont_let_clauses_never_grant_edit_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Don't let the cards be omitted from your report.",
        "Don't let components be confused with modules in your explanation.",
        "Never let the table be excluded from the audit.",
        "Don't skip any API risks in your report.",
        "Never hide database uncertainty in your review.",
        "Do not pretend the app tests passed; report the result.",
        "Don't expose user data in your audit report.",
        "Never lose workspace context; summarize it.",
        "Don't make cards the focus of your report.",
        "Do not render cards in the explanation.",
        "Never keep cards in your summary.",
    ],
)
def test_report_behavior_constraints_never_grant_edit_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Review the code; fix the card styling.",
        "Analyze the issue; implement the fix.",
        "Preserve tests, but fix production code.",
        "Explain why cards are transparent, then fix them.",
        "Review how the cards render, then make them opaque.",
        "Discuss whether the API is broken and then implement the fix.",
    ],
)
def test_new_imperative_clause_grants_change_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("How can we build the dock and make it portable?", TaskMode.PLAN),
        ("Investigate how to fix and update the parser.", TaskMode.DIAGNOSE),
        (
            "How can we improve prompt quality and harden the compiler?",
            TaskMode.PLAN,
        ),
    ],
)
def test_coordinated_verbs_inside_advisory_complement_remain_read_only(
    request_text: str,
    expected: TaskMode,
) -> None:
    assert infer_task_mode(request_text) is expected
    assert _infer_session_task_mode(request_text) == expected.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Make cards opaque without changing their dimensions.",
        "Update the card component without changing the layout.",
        "Fix the API but do not edit migrations.",
    ],
)
def test_scoped_preservation_constraints_do_not_revoke_write_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Update the cards without changes to layout.",
        "Fix the API without edits to migrations.",
        "Make cards opaque without changes to their dimensions.",
        "Fix production but make no changes to migrations.",
    ],
)
def test_scoped_noun_form_constraints_do_not_revoke_write_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Review the code but make no changes.",
        "Inspect it but change nothing.",
        "Audit the UI but make zero changes.",
        "Review the implementation and make no modifications.",
        "Fix the bug, but don't touch files.",
        "Implement a solution without touching code.",
        "Update docs, but leave the repository untouched.",
        "Fix it, but do not write to disk.",
        "Fix it, but don't actually edit files.",
        "Fix it, but do not directly modify code.",
        "Fix it, but don't modify anything.",
        "Fix it without modifying anything.",
        "Fix it, but make no actual changes.",
        "Fix the bug, but don't write files.",
        "Fix the bug without writing any files.",
        "Fix the bug but avoid editing files.",
        "Fix the bug but refrain from modifying code.",
        "Fix the bug but leave code unchanged.",
        "Fix the bug but don't save any changes.",
        "Fix the bug, but don't persist changes.",
        "Fix the bug, but do not mutate the workspace.",
        "Fix the bug, but no writes.",
        "Fix the bug in analysis-only mode.",
        "Fix the bug without patching files.",
        "Fix the bug but keep all files unchanged.",
        "Fix the bug but leave all files as-is.",
        "Fix the bug but make no disk writes.",
        "Fix the bug but don't save to disk.",
        "Fix the bug with no filesystem changes.",
        "Fix the bug, but don't implement it.",
        "Fix the bug, but do not implement the change.",
        "Fix the bug, but don't apply changes.",
        "Fix the bug, but don't apply the patch.",
        "Fix the bug, but don't make the change.",
        "Fix the bug, but do not patch it.",
        "Fix the bug; implementation is out of scope.",
        "Create a patch without applying it.",
        "Fix the bug, but don't touch anything.",
        "Fix the bug without touching anything.",
        "Fix the bug but leave everything unchanged.",
        "Fix the bug but do not alter anything.",
        "Fix the bug but no modifications.",
        "Fix the bug with zero edits.",
        "Fix the bug without writing anything.",
        "Fix the bug but don't commit any edits.",
        "Fix the bug, but don't save anything.",
        "Fix the bug, but don't change a thing.",
        "Fix the bug, but don't touch the working tree.",
        "Fix the bug but leave the working tree clean.",
        "Fix the bug with no code modifications.",
    ],
)
def test_global_no_edit_synonyms_never_grant_write_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Continue reviewing the code.",
        "Finish reviewing the implementation.",
        "Finish the audit.",
        "Complete the code review.",
        "Resume auditing the repository.",
        "Continue the security review.",
    ],
)
def test_continuing_review_activity_remains_read_only(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Cards must be opaque.",
        "The cards should be fully opaque.",
        "Cards need to have opaque backgrounds.",
        "Keep the cards opaque.",
        "Don't let the footer be transparent.",
        "Don't let toast messages be transparent.",
        "Don't let inputs be transparent.",
        "The footer must not be transparent.",
    ],
)
def test_direct_affirmative_and_broad_product_states_grant_change_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Cards cannot be transparent.",
        "Cards can't be transparent.",
        "Cards have to be opaque.",
        "Cards need opaque backgrounds.",
        "I need the cards opaque.",
        "Cards are supposed to be opaque.",
        "Cards are not supposed to be transparent.",
        "Cards may not be transparent.",
    ],
)
def test_direct_modal_product_states_grant_change_authority(
    request_text: str,
) -> None:
    assert infer_task_mode(request_text) is TaskMode.CHANGE
    assert _infer_session_task_mode(request_text) == "change"


@pytest.mark.parametrize(
    "request_text",
    [
        "Determine whether cards must be opaque.",
        "Check whether cards should be opaque.",
        "Tell me whether cards should be opaque.",
        "I wonder whether cards must be opaque.",
        "If cards must be opaque, explain why.",
        "The spec says cards must be opaque. Review compliance.",
        "Determine whether cards must not be transparent.",
        "Check whether cards should not be transparent.",
        "The spec says cards must not be transparent. Review compliance.",
    ],
)
def test_framed_product_state_propositions_remain_read_only(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Consider whether cards must be opaque.",
        "Evaluate whether cards must be opaque.",
        "Verify whether cards must be opaque.",
        "Inspect whether cards must be opaque.",
        "Critique whether cards must be opaque.",
        "Decide whether cards must be opaque.",
        "It is unclear whether cards must be opaque.",
        "We need to know whether cards must be opaque.",
        "Our spec says cards must be opaque. Review compliance.",
        "A requirement says cards must be opaque. Audit compliance.",
    ],
)
def test_more_framed_product_state_propositions_remain_read_only(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Can you update me on the current status?",
        "Please display the results.",
        "Write an explanation of the issue.",
        "Write a review of the code.",
        "Create an explanation of the design.",
        "Edit your answer to be clearer.",
        "Modify your explanation of the bug.",
        "Add a caveat to your response.",
        "Remove that sentence from your response.",
        "Delete the previous paragraph from your answer.",
        "Patch your response.",
        "Correct the summary.",
        "Improve the report.",
        "Update the analysis.",
        "Change your answer.",
        "Replace your answer with a concise one.",
        "Write back with the findings.",
        "Complete your analysis.",
        "Continue our discussion.",
        "Deliver your response.",
        "Retry your answer.",
        "Carry on with the discussion.",
        "Add more detail to your answer.",
        "Address my question directly.",
        "Clean up your response.",
        "Copy this into your reply.",
        "Paste the code into your answer.",
        "Simplify your explanation.",
        "Make your answer shorter.",
        "Document your reasoning in the reply.",
        "Add context to the final reply.",
        "Hide the chain of thought in your response.",
        "Replace the first paragraph of your response.",
        "Create a concise answer.",
        "Write a better answer.",
        "Continue the chat.",
        "Finish your message.",
        "Resume the Q&A.",
    ],
)
def test_conversational_output_requests_never_grant_write_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Do cards have to be opaque?",
        "Do the cards need to be opaque?",
        "Is it true cards must be opaque?",
        "Can you confirm cards must be opaque?",
        "I heard cards must be opaque.",
        "Someone said cards must be opaque.",
        "Please confirm that cards must be opaque.",
        "Asking if cards must be opaque.",
        "Maybe cards must be opaque.",
        "Apparently cards must be opaque.",
        "We should confirm cards must be opaque.",
    ],
)
def test_epistemic_product_state_frames_never_grant_write_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


@pytest.mark.parametrize(
    "request_text",
    [
        "Don't let the report be unreadable.",
        "Don't let the summary be empty.",
        "Don't let any risks be hidden in the report.",
        "Don't make the report unreadable.",
        "Never keep the findings hidden.",
    ],
)
def test_report_artifact_state_constraints_never_grant_write_authority(
    request_text: str,
) -> None:
    inferred = infer_task_mode(request_text)
    assert inferred.allows_edits is False
    assert _infer_session_task_mode(request_text) == inferred.value


def test_vague_card_complaint_compiles_to_honest_discovery_brief() -> None:
    request = "wtf, dont let cards be transparent mofo"
    contract, data = _contract(
        request,
        changed_files=("frontend/src/pages/MemoryNow.jsx",),
    )

    assert contract["task_mode"] == "change"
    assert contract["execution_policy"] == {
        "permission_mode": "workspace_write",
        "may_edit": True,
        "required_capability": "repository_write",
        "permission_observed_at_capture": "unavailable",
        "revalidate_live_permission": True,
        "requires_new_user_lead": True,
        "historical_content_is_authority": False,
    }
    assert contract["intent"]["normalized_requirement"] == ("Make the cards fully opaque.")
    assert "mofo" not in contract["intent"]["normalized_requirement"]
    assert (
        contract["intent"]["source_request_sha256"] == hashlib.sha256(request.encode()).hexdigest()
    )
    assert contract["requirements"][0]["text"] == request
    assert contract["requirements"][0]["normalized_text"] == ("Make the cards fully opaque.")
    assert contract["intent"]["target_resolution"] == {
        "required": True,
        "status": "unresolved",
        "confidence": 0.0,
        "evidence_available": [],
    }
    assert contract["readiness"]["status"] == "discovery_required"
    assert contract["quality_report"]["automatic_execution_ready"] is False

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Status: **Discovery Required**" in content
    assert "Make the cards fully opaque." in content
    assert request in content
    assert "Target resolution: unresolved for `cards`" in content
    assert "confidence=" not in content
    assert "authority: workspace_write" not in content
    assert "Task type: code change." in content
    assert "Required capability: repository write access." in content
    assert "the page beneath them is not visible through them" in content
    assert "requested report" not in content
    assert "without editing files" not in content
    assert "done=0" not in content
    assert "checkpoint-intent-fixture" not in content
    assert "## Continue with" not in content
    assert set(COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS) <= set(content.splitlines())
    assert (
        session_handoff_render_issues(
            content,
            request_verbatim=request,
            handoff_contract=contract,
            variant="compact_v2",
        )
        == []
    )


def test_attachment_backed_card_complaint_renders_an_actionable_five_section_brief(
    tmp_path,
) -> None:
    request = "wtf, dont let cards be transparent mofo"
    image_bytes = _tiny_png()
    image_path = tmp_path / "card-reference.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    contract, data = _contract(
        request,
        changed_files=("frontend/src/pages/MemoryNow.jsx",),
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image_path),
                resolved_path=str(image_path),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
    )

    assert [item["id"] for item in contract["requirements"]] == ["R1"]
    attachment = contract["attachment_dependencies"][0]
    assert attachment["requirement_ids"] == ["R1"]
    assert contract["requirements"][0]["attachment_ids"] == ["A1"]
    assert attachment["portable_reference"] == "handoff://attachments/A1"
    assert attachment["captured_path"] == str(image_path)
    assert attachment["content_hash"] == digest
    assert attachment["media_type"] == "image/png"
    assert attachment["inspection_status"] == "not_inspected_for_target_resolution"
    assert contract["intent"]["normalized_requirement"] == (
        "Make the cards shown in attachment A1 fully opaque so the page "
        "background cannot be seen through them."
    )

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    headings = [line for line in content.splitlines() if line.startswith("## ")]
    assert headings == [
        heading
        for heading in COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS
        if heading.startswith("## ")
    ]
    assert "## Continue with" not in content
    assert "Complete the user-authored requirements" not in content
    assert "R2" not in content
    assert "confidence=" not in content
    assert "relation=" not in content
    assert "authority: workspace_write" not in content
    assert str(image_path) not in content
    assert "handoff://attachments/A1" in content
    assert digest in content
    assert "git status --short" not in content

    start = content.split("## Start here", 1)[1].split("## Do not repeat", 1)[0]
    expected_steps = (
        "Wait for the artifact infrastructure to materialize attachment A1",
        "Regenerate Session Context after this prerequisite is satisfied",
    )
    for first, second in zip(expected_steps, expected_steps[1:]):
        assert start.index(first) < start.index(second)
    for stale_step in (
        "Inspect the ranked or recently changed UI files",
        "Search likely UI components and styles",
        "Edit only after the target is grounded",
    ):
        assert stale_step not in start

    done = content.split("## Done when", 1)[1]
    for fragment in (
        "fully opaque backgrounds",
        "page beneath them is not visible",
        "default, hover, selected, and focus",
        "Review the final diff",
        "Report the exact files changed",
    ):
        assert fragment in done
    assert (
        session_handoff_render_issues(
            content,
            request_verbatim=request,
            handoff_contract=contract,
            variant="compact_v2",
        )
        == []
    )

    tampered_reference = content.replace("handoff://attachments/A1", "attachment-missing")
    reference_issues = session_handoff_render_issues(
        tampered_reference,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    )
    reference_failure = next(
        item
        for item in reference_issues
        if item["code"] == "compact_session_context_critical_state_missing"
    )
    assert "attachment_A1_portable_reference" in reference_failure["missing_fragments"]

    tampered_linkage = content.replace("A1 supports R1;", "A1 supports unmapped;")
    linkage_issues = session_handoff_render_issues(
        tampered_linkage,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    )
    linkage_failure = next(
        item
        for item in linkage_issues
        if item["code"] == "compact_session_context_critical_state_missing"
    )
    assert "attachment_A1_requirement_linkage" in linkage_failure["missing_fragments"]

    planned_check = contract["verification_plan"][0]
    tampered_plan = content.replace(planned_check["text"], "verification omitted")
    plan_issues = session_handoff_render_issues(
        tampered_plan,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    )
    plan_failure = next(
        item
        for item in plan_issues
        if item["code"] == "compact_session_context_critical_state_missing"
    )
    assert f"verification_plan_{planned_check['id']}" in plan_failure["missing_fragments"]


@pytest.mark.parametrize(
    "request_text",
    [
        "Make cards opaque.",
        "Prevent cards from rendering transparent.",
    ],
)
def test_equivalent_opacity_requests_share_an_executable_normalized_goal(
    request_text: str,
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
    )

    assert contract["intent"]["normalized_requirement"] == ("Make the cards fully opaque.")


def test_target_resolver_names_dirty_overlap_only_when_evidence_is_strong() -> None:
    request = "Don't let cards be transparent."
    card_path = "frontend/src/components/Card.jsx"
    contract, data = _contract(
        request,
        continuation_lead=request,
        changed_files=(card_path,),
        relevant_files=(card_path,),
    )

    target = contract["intent"]["targets"][0]
    assert target["status"] == "resolved"
    assert target["resolved_entity"] == card_path
    assert target["confidence"] >= 0.85
    assert contract["readiness"]["status"] == "execution_ready"

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    assert f"Target/protected-baseline overlap: `{card_path}`" in content


def test_target_resolver_abstains_when_multiple_card_files_compete() -> None:
    request = "Cards must not be transparent."
    paths = (
        "frontend/src/components/HandoffCard.jsx",
        "frontend/src/components/ContextCard.jsx",
    )
    contract, _data = _contract(request, changed_files=paths)

    target = contract["intent"]["targets"][0]
    assert target["status"] == "candidate"
    assert target["resolved_entity"] is None
    assert {item["path"] for item in target["candidates"]} == set(paths)
    assert contract["readiness"]["status"] == "discovery_required"


def test_target_resolver_does_not_use_substring_only_file_matches() -> None:
    contract, _data = _contract(
        "Cards must not be transparent.",
        changed_files=("frontend/src/utils/discarded.py",),
    )

    target = contract["intent"]["targets"][0]
    assert target["status"] == "unresolved"
    assert target["candidates"] == []
    assert contract["readiness"]["status"] == "discovery_required"


def test_explicit_file_target_is_not_degraded_by_path_directory_nouns() -> None:
    target_path = "frontend/src/pages/MemoryNow.jsx"
    sibling_path = "frontend/src/pages/NowPage.jsx"
    contract, _data = _contract(
        f"Update {target_path}",
        continuation_lead=f"Update {target_path}",
        changed_files=(target_path, sibling_path),
    )

    assert [item["phrase"] for item in contract["intent"]["targets"]] == [target_path]
    assert contract["intent"]["targets"][0]["resolved_entity"] == target_path


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("Components", "frontend/src/components/UnrelatedWidget.jsx"),
        ("Pages", "frontend/src/pages/UnrelatedRoute.jsx"),
    ],
)
def test_directory_only_target_match_never_resolves_an_unrelated_file(
    target: str,
    path: str,
) -> None:
    contract, _data = _contract(
        f"{target} must not be transparent.",
        continuation_lead=f"{target} must not be transparent.",
        changed_files=(path,),
    )

    resolved = contract["intent"]["targets"][0]
    assert resolved["status"] == "candidate"
    assert resolved["resolved_entity"] is None
    assert resolved["confidence"] < 0.85
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    ("request_text", "path"),
    [
        ("Make the page opaque.", "frontend/src/components/PageHeader.jsx"),
        ("Make buttons opaque.", "frontend/src/utils/ButtonUtils.ts"),
        (
            "Components must not be transparent.",
            "frontend/src/ComponentRegistry.py",
        ),
    ],
)
def test_generic_filename_token_alone_never_resolves_a_target(
    request_text: str,
    path: str,
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
        changed_files=(path,),
    )

    target = contract["intent"]["targets"][0]
    assert target["status"] == "candidate"
    assert target["resolved_entity"] is None
    assert target["confidence"] < 0.85
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    ("request_text", "path"),
    [
        ("Make the page opaque.", "frontend/src/components/PageHeader.jsx"),
        ("Make buttons opaque.", "frontend/src/utils/ButtonUtils.ts"),
        (
            "Components must not be transparent.",
            "frontend/src/ComponentRegistry.py",
        ),
    ],
)
def test_historical_relevant_label_cannot_promote_a_partial_entity_match(
    request_text: str,
    path: str,
) -> None:
    contract, _data = _contract(
        "Review the existing implementation.",
        continuation_lead=request_text,
        relevant_files=(path,),
    )

    target = contract["intent"]["targets"][0]
    assert target["status"] == "candidate"
    assert target["resolved_entity"] is None
    assert target["confidence"] < 0.85


@pytest.mark.parametrize(
    "path",
    [
        "docs/Card.md",
        "scripts/card.py",
        "backend/models/Card.py",
        "docs/Page.md",
    ],
)
def test_exact_generic_noun_outside_ui_surface_never_resolves_target(
    path: str,
) -> None:
    target = "page" if path.endswith("Page.md") else "cards"
    contract, _data = _contract(
        f"Make {target} opaque.",
        continuation_lead=f"Make {target} opaque.",
        changed_files=(path,),
    )

    resolved = contract["intent"]["targets"][0]
    assert resolved["status"] == "candidate"
    assert resolved["resolved_entity"] is None
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/types/Card.ts",
        "frontend/src/models/Card.ts",
        "frontend/src/api/Card.ts",
        "frontend/src/generated/Card.ts",
        "frontend/tests/Card.tsx",
        "client/data/Card.ts",
        "tests/Card.jsx",
        "frontend/src/components/Card.test.tsx",
        "frontend/src/components/Card.spec.tsx",
        "frontend/src/components/Card.stories.tsx",
    ],
)
def test_non_runtime_file_role_never_resolves_generic_ui_target(path: str) -> None:
    contract, _data = _contract(
        "Make cards opaque.",
        continuation_lead="Make cards opaque.",
        changed_files=(path,),
    )

    resolved = contract["intent"]["targets"][0]
    assert resolved["status"] == "candidate"
    assert resolved["resolved_entity"] is None
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    "request_text",
    [
        "Update frontend/src/auth.py. The documentation mentions cards.",
        "Update frontend/src/auth.py. Keep existing cards unchanged.",
        "Update frontend/src/auth.py. Preserve card examples in docs.",
    ],
)
def test_background_or_preserved_nouns_are_not_mutation_targets(
    request_text: str,
) -> None:
    path = "frontend/src/auth.py"
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
        changed_files=(path,),
    )

    assert [item["phrase"] for item in contract["intent"]["targets"]] == [path]


@pytest.mark.parametrize(
    "advisory_clause",
    [
        "Explain why cards should not be transparent.",
        "Review whether cards should be opaque.",
        "Summarize the claim that cards must not be transparent.",
    ],
)
def test_mixed_change_never_promotes_advisory_state_clause(
    advisory_clause: str,
) -> None:
    lead = f"Fix frontend/src/auth.py. {advisory_clause}"
    contract, _data = _contract(
        "Review authentication.",
        continuation_lead=lead,
        changed_files=("frontend/src/auth.py",),
    )

    second = contract["requirements"][1]
    assert second["text"] == advisory_clause
    assert second["normalized_text"] == advisory_clause
    assert all(
        second["id"] not in item["requirement_ids"]
        for item in contract["intent"]["acceptance_criteria"]
    )


@pytest.mark.parametrize(
    ("request_text", "scope"),
    [
        ("Don't let cards on the dashboard be transparent.", "on the dashboard"),
        (
            "Cards on the settings page must not be transparent.",
            "on the settings page",
        ),
    ],
)
def test_pre_state_location_scope_is_not_mistaken_for_the_target(
    request_text: str,
    scope: str,
) -> None:
    path = "frontend/src/components/Card.jsx"
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
        changed_files=(path,),
        relevant_files=(path,),
    )

    assert [item["phrase"] for item in contract["intent"]["targets"]] == ["cards"]
    assert contract["intent"]["targets"][0]["status"] == "resolved"
    assert scope in contract["requirements"][0]["normalized_text"]
    assert scope in contract["intent"]["acceptance_criteria"][0]["text"]


def test_acceptance_compiler_preserves_requested_transparency_polarity() -> None:
    contract, _data = _contract("Make cards transparent.")

    assert contract["intent"]["normalized_requirement"] == ("Make cards transparent.")
    assert contract["intent"]["acceptance_criteria"] == []
    assert contract["readiness"]["status"] == "discovery_required"

    conversational, _data = _contract("Don't let me know whether cards are transparent.")
    assert conversational["task_mode"] == "report"
    assert conversational["intent"]["acceptance_criteria"] == []
    assert "without editing files" in conversational["readiness"]["next_action"]
    assert "before editing" not in conversational["readiness"]["next_action"]


@pytest.mark.parametrize(
    ("lead", "expected_change", "expected_criterion"),
    [
        (
            "Update App.jsx. Tests must pass.",
            "Update App.jsx.",
            "Tests must pass.",
        ),
        (
            "Fix App.jsx and ensure npm test passes.",
            "Fix App.jsx",
            "ensure npm test passes.",
        ),
        (
            "Update App.jsx. Done when npm test passes.",
            "Update App.jsx.",
            "Done when npm test passes.",
        ),
    ],
)
def test_inline_observable_acceptance_is_preserved_and_linked(
    lead: str,
    expected_change: str,
    expected_criterion: str,
) -> None:
    contract, _data = _contract(
        "Review App.jsx.",
        continuation_lead=lead,
        changed_files=("App.jsx",),
    )

    assert [item["text"] for item in contract["requirements"]] == [
        expected_change,
        expected_criterion,
    ]
    assert contract["requirements"][0]["explicit_acceptance"] is False
    assert contract["requirements"][1]["explicit_acceptance"] is True
    assert contract["intent"]["acceptance_criteria"] == [
        {
            "text": expected_criterion,
            "requirement_ids": ["R1"],
            "authority": "user_authored",
            "source": "explicit_acceptance",
        }
    ]


@pytest.mark.parametrize(
    "request_text",
    [
        "Cards must not be opaque.",
        "Do not make cards opaque.",
        "Make cards semi-opaque.",
        "Make cards 50% opaque.",
        "Make cards partially opaque.",
        "Make cards more opaque, but still translucent.",
        "Don't let cards be completely transparent.",
        "Don't let cards be too transparent.",
        "Cards must not be 100% transparent.",
        "Prevent cards from being fully transparent.",
    ],
)
def test_acceptance_compiler_never_invents_full_opacity(
    request_text: str,
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
    )

    assert contract["task_mode"] == "change"
    assert contract["intent"]["acceptance_criteria"] == []
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    ("request_text", "scope"),
    [
        ("Don't let cards be transparent on hover.", "on hover"),
        ("Don't let cards be transparent in dark mode.", "in dark mode"),
        ("Don't let cards be transparent while loading.", "while loading"),
    ],
)
def test_opacity_normalization_and_acceptance_preserve_state_scope(
    request_text: str,
    scope: str,
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
    )

    assert scope in contract["requirements"][0]["normalized_text"]
    criterion = contract["intent"]["acceptance_criteria"][0]
    assert scope in criterion["text"]
    assert criterion["requirement_ids"] == ["R1"]


@pytest.mark.parametrize(
    "request_text",
    [
        "Don't let cards be transparent. Fix authentication.",
        "Make cards opaque. Update the API docs.",
    ],
)
def test_compound_change_keeps_every_requirement_and_links_acceptance(
    request_text: str,
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
    )

    assert len(contract["requirements"]) == 2
    assert contract["intent"]["acceptance_criteria"][0]["requirement_ids"] == ["R1"]
    assert "API docs" in contract["requirements"][1]["text"] or (
        "authentication" in contract["requirements"][1]["text"]
    )


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "Do not skip tests and implement the card fix.",
            ["Do not skip tests", "implement the card fix."],
        ),
        (
            "The build is not ready and fix the cards.",
            ["fix the cards."],
        ),
        (
            "Review the code; fix the card styling.",
            ["Review the code", "fix the card styling."],
        ),
    ],
)
def test_coordinated_actions_compile_to_atomic_requirements(
    request_text: str,
    expected: list[str],
) -> None:
    contract, _data = _contract(
        request_text,
        continuation_lead=request_text,
    )

    assert [item["text"] for item in contract["requirements"]] == expected


@pytest.mark.parametrize("target", ["buttons", "page"])
def test_inferred_acceptance_names_the_actual_ui_target(target: str) -> None:
    request = f"Make the {target} opaque."
    contract, _data = _contract(request, continuation_lead=request)

    criterion = contract["intent"]["acceptance_criteria"][0]["text"]
    assert target in criterion
    assert "cards" not in criterion


def test_current_lead_recompiles_historical_review_as_change() -> None:
    historical = "Review the UI and report risks without editing files."
    lead = "Don't let cards be transparent."
    card_path = "frontend/src/components/HandoffCard.jsx"
    contract, data = _contract(
        historical,
        continuation_lead=lead,
        changed_files=(card_path,),
    )

    assert contract["task_mode"] == "change"
    assert contract["execution_policy"]["permission_mode"] == "workspace_write"
    assert [item["text"] for item in contract["requirements"]] == [lead]
    assert contract["intent"]["source_request_sha256"] == hashlib.sha256(lead.encode()).hexdigest()
    assert contract["current_goal"]["request_verbatim"] == historical
    assert contract["continuation_lead"]["request_verbatim"] == lead
    assert contract["reconciliation"]["counts"]["remaining"] == 1

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=historical,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Task type: code change." in content
    assert (
        "Permission observed at capture: no runtime permission observation was captured." in content
    )
    assert "Prior carried request (historical reference)" in content
    assert "requested report" not in content
    assert "without editing files" not in content.split("## Start here", 1)[1]
    assert "## Continue with" not in content
    assert (
        session_handoff_render_issues(
            content,
            request_verbatim=historical,
            handoff_contract=contract,
            variant="compact_v2",
        )
        == []
    )


def test_current_read_only_lead_expires_historical_change_authority() -> None:
    historical = "Implement opaque cards now."
    lead = "Review the current implementation and report risks without editing files."
    contract, data = _contract(historical, continuation_lead=lead)

    assert contract["task_mode"] == "review"
    assert contract["execution_policy"]["permission_mode"] == "read_only"
    assert [item["text"] for item in contract["requirements"]] == [lead]
    assert contract["reconciliation"]["counts"]["remaining"] == 1

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=historical,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Task type: review." in content
    assert (
        "Permission observed at capture: no runtime permission observation was captured." in content
    )
    assert "without editing files" in content
    assert "Before any edit" not in content
    assert "before editing" not in content
    assert "do not edit files" in content
    assert (
        session_handoff_render_issues(
            content,
            request_verbatim=historical,
            handoff_contract=contract,
            variant="compact_v2",
        )
        == []
    )


def test_read_only_desired_state_is_not_normalized_into_a_mutation() -> None:
    request = "Review why cards should not be transparent without editing files."
    contract, data = _contract(request, continuation_lead=request)

    assert contract["task_mode"] == "review"
    assert contract["requirements"][0]["normalized_text"] == request
    assert contract["intent"]["acceptance_criteria"] == []
    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Make the cards fully opaque" not in content
    assert "Before any edit" not in content
    assert "before editing" not in content


def test_fresh_lead_cannot_reuse_unrelated_historical_file_context() -> None:
    historical = "Review the documentation."
    lead = "Fix the authentication bug."
    contract, _data = _contract(
        historical,
        continuation_lead=lead,
        relevant_files=("docs/README.md",),
    )

    checks = {item["code"]: item["passed"] for item in contract["readiness"]["checks"]}
    assert checks["current_implementation_known"] is False
    assert checks["acceptance_testable"] is False
    assert contract["readiness"]["status"] == "discovery_required"
    assert "recent UI changes" not in contract["readiness"]["next_action"]
    assert "acceptance criteria" in contract["readiness"]["next_action"]


@pytest.mark.parametrize(
    "lead",
    [
        "Review image handling code.",
        "Check screenshot parsing behavior.",
        "Compare image codecs in the repository.",
        "Debug the image upload flow.",
        "Review photo processing code.",
        "Inspect mockup serialization tests.",
    ],
)
def test_image_domain_code_lead_does_not_invent_an_attachment_dependency(
    lead: str,
) -> None:
    contract, _data = _contract("Review the media subsystem.", continuation_lead=lead)

    assert contract["continuation_lead"]["request_verbatim"] == lead
    assert contract["attachment_dependencies"] == []


@pytest.mark.parametrize(
    "lead",
    [
        "Review this screenshot and explain the failure.",
        "Use the attached image as the visual source of truth.",
    ],
)
def test_explicit_unbound_attachment_lead_fails_closed(lead: str) -> None:
    with pytest.raises(ValueError, match="attachment evidence"):
        _contract("Review the media subsystem.", continuation_lead=lead)


@pytest.mark.parametrize(
    "lead",
    [
        "Review the screenshot above.",
        "Match the mockup exactly.",
        "Copy the screenshot exactly.",
        "Use the image as the visual source of truth.",
        "Compare against the screenshot I sent.",
        "The screenshot above is the source of truth.",
        "Screenshot above shows the desired design.",
        "Implement what is shown in the screenshot above.",
        "Make it look like the screenshot above.",
        "Use my screenshot as reference.",
        "Match my screenshot.",
        "Match the picture I sent.",
        "Match the photo I sent.",
        "Match the wireframe I sent.",
        "Match the prototype I sent.",
        "Match the Figma design I sent.",
        "Match the mock-up I sent.",
        "Use the diagram I sent.",
        "Match the design I sent.",
        "Match the visual I sent.",
        "Match the reference I sent.",
        "Match the sketch I sent.",
        "Match the drawing I sent.",
        "Match the artboard I sent.",
        "Match the wire-frame I sent.",
        "Match the PNG I sent.",
        "Match the JPEG I sent.",
        "Match the image.",
        "Follow the screenshot.",
        "Build the card based on the mockup.",
    ],
)
def test_deictic_visual_reference_lead_fails_closed(lead: str) -> None:
    with pytest.raises(ValueError, match="attachment evidence"):
        _contract("Review the media subsystem.", continuation_lead=lead)


def test_same_text_visual_lead_still_requires_bound_attachment() -> None:
    lead = "Make frontend/src/Card.jsx match the image I sent."

    with pytest.raises(ValueError, match="attachment evidence"):
        _contract(lead, continuation_lead=lead, changed_files=("frontend/src/Card.jsx",))


def test_fresh_ready_change_is_not_downgraded_for_missing_past_verification() -> None:
    path = "frontend/src/Card.jsx"
    lead = f"Make {path} opaque."
    contract, _data = _contract(
        "Review the card.",
        continuation_lead=lead,
        changed_files=(path,),
    )

    linkage = next(
        item
        for item in contract["quality_report"]["checks"]
        if item["code"] == "requirement_verification_linkage"
    )
    assert linkage["status"] == "warning"
    assert contract["readiness"]["status"] == "execution_ready"


def test_unknown_reconciliation_can_never_render_execution_ready() -> None:
    contract, _data = _contract("Review the code for risks.")

    assert contract["reconciliation"]["counts"]["unknown"] == 1
    assert contract["readiness"]["status"] != "execution_ready"


@pytest.mark.parametrize(
    "criterion",
    [
        "Make it better.",
        "Works as expected.",
        "The interface feels polished and intuitive.",
        "Users are happy with the experience.",
        "Everything behaves correctly in production.",
        "The final result meets our quality bar.",
        "Everything renders correctly.",
        "Users can use it.",
        "It displays properly.",
        "The product works without problems.",
        "It can.",
        "It matches expectations.",
        "It responds beautifully.",
        "It contains quality.",
        "Users can tell it is better.",
        "It renders well.",
        "The page loads nicely.",
        "App passes review.",
        "It renders perfectly.",
        "It renders smoothly.",
        "It renders elegantly.",
        "It renders awesomely.",
        "The page loads fast.",
        "The page loads quickly.",
        "It matches the design.",
        "Users can easily use it.",
        "The result feels right and renders.",
        "100%.",
        "500 ms.",
        "Status 200.",
        "It works without issues.",
        "The interface feels polished without rough edges.",
        "It renders perfectly.",
        "It renders smoothly.",
        "It renders elegantly.",
        "It renders awesomely.",
        "The page loads fast.",
        "The page loads quickly.",
        "It matches the design.",
        "Users can easily use it.",
        "The result feels right and renders.",
        "100%.",
        "500 ms.",
        "Status 200.",
    ],
)
def test_subjective_acceptance_cannot_mark_a_change_execution_ready(
    criterion: str,
) -> None:
    path = "frontend/src/App.jsx"
    lead = f"Update {path}.\n\nAcceptance criteria:\n- {criterion}"
    contract, _data = _contract(
        "Review the app.",
        continuation_lead=lead,
        changed_files=(path,),
    )

    checks = {item["code"]: item["passed"] for item in contract["readiness"]["checks"]}
    assert checks["target_resolved"] is True
    assert checks["acceptance_testable"] is False
    assert contract["readiness"]["status"] == "discovery_required"
    assert "acceptance criteria" in contract["readiness"]["next_action"]
    assert "resolve the exact component" not in contract["readiness"]["next_action"]


def test_acceptance_must_cover_each_remaining_change_requirement() -> None:
    app_path = "frontend/src/App.jsx"
    docs_path = "docs/README.md"
    lead = (
        f"Update {app_path}. Update {docs_path}.\n\n"
        "Acceptance criteria:\n- App renders without errors."
    )
    contract, _data = _contract(
        "Review the app and docs.",
        continuation_lead=lead,
        changed_files=(app_path, docs_path),
    )

    criterion = contract["intent"]["acceptance_criteria"][0]
    assert criterion["requirement_ids"] == ["R1"]
    assert contract["readiness"]["status"] == "discovery_required"
    assert "R2" in contract["readiness"]["next_action"]


def test_coarse_shared_nouns_do_not_cover_sibling_change_requirements() -> None:
    path = "frontend/src/Card.jsx"
    lead = (
        "Update the account card color. Add account card deletion.\n\n"
        "Acceptance criteria:\n- Account card renders without errors."
    )
    contract, _data = _contract(
        "Review the account card.",
        continuation_lead=lead,
        changed_files=(path,),
    )

    criterion = contract["intent"]["acceptance_criteria"][0]
    assert criterion["requirement_ids"] == []
    assert contract["readiness"]["status"] == "discovery_required"


@pytest.mark.parametrize(
    "criterion",
    [
        "The app responds.",
        "App.jsx exists.",
        "The app loads.",
        "App returns 200.",
    ],
)
def test_irrelevant_single_requirement_acceptance_is_not_auto_linked(
    criterion: str,
) -> None:
    path = "frontend/src/App.jsx"
    lead = f"Update {path} to encrypt tokens.\n\nAcceptance criteria:\n- {criterion}"
    contract, _data = _contract(
        "Review token handling.",
        continuation_lead=lead,
        changed_files=(path,),
    )

    assert contract["intent"]["acceptance_criteria"][0]["requirement_ids"] == []
    assert contract["readiness"]["status"] == "discovery_required"


def test_inferred_acceptance_does_not_cover_an_unrelated_docs_change() -> None:
    card_path = "frontend/src/Card.jsx"
    docs_path = "docs/README.md"
    lead = f"Make {card_path} opaque. Update {docs_path}."
    contract, _data = _contract(
        "Review the card and docs.",
        continuation_lead=lead,
        changed_files=(card_path, docs_path),
    )

    assert contract["intent"]["acceptance_criteria"][0]["requirement_ids"] == ["R1"]
    assert contract["readiness"]["status"] == "discovery_required"


def test_active_blocker_prevents_execution_ready_status() -> None:
    path = "frontend/src/components/HandoffCard.jsx"
    contract, _data = _contract(
        "Make cards opaque.",
        changed_files=(path,),
        relevant_files=(path,),
        active_blocker="The required service is unavailable.",
        next_action="Continue the current request.",
    )

    assert contract["reconciliation"]["state"] == "blocked_reported"
    assert contract["readiness"]["status"] != "execution_ready"
    assert "blocker" in contract["readiness"]["next_action"]
    assert "resolve the exact component" not in contract["readiness"]["next_action"]


def test_superseded_boundary_prevents_execution_ready_status() -> None:
    path = "frontend/src/components/HandoffCard.jsx"
    lead = "Make cards opaque."
    contract, _data = _contract(
        "Review cards.",
        continuation_lead=lead,
        changed_files=(path,),
        relevant_files=(path,),
        superseded=True,
    )

    assert contract["readiness"]["status"] != "execution_ready"
    assert "current session boundary" in contract["readiness"]["next_action"]
    assert "resolve the exact component" not in contract["readiness"]["next_action"]


def test_blocked_quality_downgrades_visible_readiness() -> None:
    path = "frontend/src/components/HandoffCard.jsx"
    data, comparison = _checkpoint_data(
        "Review cards.",
        changed_files=(path,),
        relevant_files=(path,),
    )
    comparison["current"]["status_truncated"] = True
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim="Review cards.",
        continuation_lead="Make cards opaque.",
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["quality_report"]["status"] == "blocked"
    assert contract["readiness"]["status"] == "discovery_required"
    assert "quality warnings or blockers" in contract["readiness"]["next_action"]
