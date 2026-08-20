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
    _compact_session_start_steps,
    _infer_session_task_mode,
    _sentences,
    build_session_handoff_contract,
    render_compact_session_handoff,
    session_handoff_render_issues,
)
from app.services.request_artifacts import TrustedRequestImageDescriptor


def _checkpoint_data(
    request: str,
    *,
    request_fragments: tuple[str | tuple[str, str], ...] = (),
    changed_files: tuple[str, ...] = (),
    relevant_files: tuple[str, ...] = (),
    active_blocker: str | None = None,
    next_action: str | None = None,
    superseded: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    sections: dict[str, list[dict[str, object]]] = {key: [] for key in CHECKPOINT_CATEGORIES}
    goal_payload: dict[str, object] = {
        "request_verbatim": request,
        "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
    }
    if request_fragments:
        stored_fragments: list[dict[str, object]] = []
        for index, fragment_value in enumerate(request_fragments, start=1):
            if isinstance(fragment_value, tuple):
                fragment, resolved = fragment_value
            else:
                fragment, resolved = fragment_value, ""
            stored_fragment: dict[str, object] = {
                "provider_event_id": f"msg-{index}",
                "sequence_number": index,
                "request_verbatim": fragment,
                "request_sha256": hashlib.sha256(fragment.encode()).hexdigest(),
            }
            if resolved:
                stored_fragment.update(
                    {
                        "resolved_statement": resolved,
                        "resolved_statement_sha256": hashlib.sha256(
                            resolved.encode()
                        ).hexdigest(),
                    }
                )
            stored_fragments.append(stored_fragment)
        goal_payload["request_fragments"] = stored_fragments
    sections["goal"] = [
        {
            "statement": request,
            "truth_state": "user_asserted",
            "state": "active",
            "payload": goal_payload,
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
    request_fragments: tuple[str | tuple[str, str], ...] = (),
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
        request_fragments=request_fragments,
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


def _tiny_png(rgba: bytes = b"\xff\x00\x00\xff") -> bytes:
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
            chunk(b"IDAT", zlib.compress(b"\x00" + rgba)),
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


def test_composite_attachment_links_only_to_its_declaring_follow_up(
    tmp_path,
) -> None:
    root = "now deeply investigate why the cards in the continue page aren't working"
    accepted_plan = (
        "Accepted the prior assistant proposal: Recommended correction order:\n"
        "1. Remove the two-compaction restriction from Continue.\n"
        "2. Make every card use one shared latest-session source.\n"
        "3. Reuse the floating button's real paste mechanism.\n"
        "4. Include the destination provider in the retry key.\n"
        "5. Distinguish desktop detection from account readiness."
    )
    image_bytes = _tiny_png()
    image_path = tmp_path / "codex-card-failure.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    failure_follow_up = (
        "this happened when i clicked codex card. WHY TF DOES THIS KEEP FAILING?\n"
        f'<image name=[Image #1] path="{image_path}">\n</image>'
    )
    request = (
        f"{root}\n\n"
        "## Additional user-authored requirements\n\n"
        f"### Follow-up 1\n{accepted_plan}\n\n"
        f"### Follow-up 2\n{failure_follow_up}"
    )
    contract, _data = _contract(
        request,
        request_fragments=(root, ("yes go ahead", accepted_plan), failure_follow_up),
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

    complaint = next(
        item
        for item in contract["requirements"]
        if item["text"] == "WHY TF DOES THIS KEEP FAILING?"
    )
    attachment = contract["attachment_dependencies"][0]
    assert attachment["required"] is True
    assert attachment["available"] is True
    assert attachment["requirement_ids"] == [complaint["id"]]
    assert complaint["attachment_ids"] == [attachment["id"]]
    linkage = next(
        item
        for item in contract["quality_report"]["checks"]
        if item["code"] == "required_attachment_requirement_linkage"
    )
    assert linkage["status"] == "pass"
    assert not any(
        item["code"] == "required_attachment_requirement_linkage"
        for item in contract["quality_report"]["blocking_issues"]
    )


def test_declared_attachment_with_two_same_fragment_outcomes_stays_ambiguous(
    tmp_path,
) -> None:
    image_bytes = _tiny_png()
    image_path = tmp_path / "ambiguous-follow-up.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    request = (
        "Fix authentication. Update API docs.\n"
        f'<image name=[Image #1] path="{image_path}">\n</image>'
    )
    contract, _data = _contract(
        request,
        request_fragments=(request,),
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

    assert [item["text"] for item in contract["requirements"]] == [
        "Fix authentication.",
        "Update API docs.",
    ]
    assert contract["attachment_dependencies"][0]["requirement_ids"] == []
    assert "required_attachment_requirement_linkage" in {
        item["code"] for item in contract["quality_report"]["blocking_issues"]
    }


def test_composite_attachments_never_cross_link_between_follow_ups(
    tmp_path,
) -> None:
    image_bytes = _tiny_png()
    login_path = tmp_path / "login-error.png"
    billing_path = tmp_path / "billing-error.png"
    login_path.write_bytes(image_bytes)
    billing_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    root = "Investigate both reported failures."
    login_follow_up = (
        "Fix the login failure shown here.\n"
        f'<image name=[Login] path="{login_path}">\n</image>'
    )
    billing_follow_up = (
        "Fix the billing failure shown here.\n"
        f'<image name=[Billing] path="{billing_path}">\n</image>'
    )
    request = (
        f"{root}\n\n"
        "## Additional user-authored requirements\n\n"
        f"### Follow-up 1\n{login_follow_up}\n\n"
        f"### Follow-up 2\n{billing_follow_up}"
    )
    contract, _data = _contract(
        request,
        request_fragments=(root, login_follow_up, billing_follow_up),
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(login_path),
                resolved_path=str(login_path),
                sha256=digest,
                mime_type="image/png",
            ),
            TrustedRequestImageDescriptor(
                path=str(billing_path),
                resolved_path=str(billing_path),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
    )

    login_requirement = next(
        item for item in contract["requirements"] if "login failure" in item["text"]
    )
    billing_requirement = next(
        item for item in contract["requirements"] if "billing failure" in item["text"]
    )
    attachments_by_path = {
        item["path"]: item for item in contract["attachment_dependencies"]
    }
    assert attachments_by_path[str(login_path)]["requirement_ids"] == [
        login_requirement["id"]
    ]
    assert attachments_by_path[str(billing_path)]["requirement_ids"] == [
        billing_requirement["id"]
    ]
    assert login_requirement["attachment_ids"] != billing_requirement["attachment_ids"]


def test_reused_attachment_path_without_event_binding_fails_closed(
    tmp_path,
) -> None:
    image_bytes = _tiny_png()
    shared_path = tmp_path / "shared.png"
    shared_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    login_follow_up = (
        "Fix the login failure shown here.\n"
        f'<image name=[Evidence] path="{shared_path}">\n</image>'
    )
    billing_follow_up = (
        "Fix the billing failure shown here.\n"
        f'<image   name=[Evidence]   path="{shared_path}">\n</image>'
    )
    request = (
        "Investigate both reported failures.\n\n"
        "## Additional user-authored requirements\n\n"
        f"### Follow-up 1\n{login_follow_up}\n\n"
        f"### Follow-up 2\n{billing_follow_up}"
    )
    contract, _data = _contract(
        request,
        request_fragments=(
            "Investigate both reported failures.",
            login_follow_up,
            billing_follow_up,
        ),
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(shared_path),
                resolved_path=str(shared_path),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
    )

    attachments = contract["attachment_dependencies"]
    assert len(attachments) == 2
    linked_text = [
        next(
            requirement["text"]
            for requirement in contract["requirements"]
            if requirement["id"] == attachment["requirement_ids"][0]
        )
        for attachment in attachments
    ]
    assert linked_text == [
        "Fix the login failure shown here.",
        "Fix the billing failure shown here.",
    ]
    assert all(attachment["available"] is False for attachment in attachments)
    assert all(
        attachment["resolution"] == "source_event_attachment_identity_ambiguous"
        for attachment in attachments
    )
    assert "required_attachments_resolved" in {
        item["code"] for item in contract["quality_report"]["blocking_issues"]
    }


def test_user_authored_composite_heading_is_not_treated_as_provenance(
    tmp_path,
) -> None:
    image_bytes = _tiny_png()
    image_path = tmp_path / "single-turn.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    request = (
        "Fix authentication.\n"
        "### Follow-up 1\n"
        "Update API docs.\n"
        f'<image name=[Evidence] path="{image_path}">\n</image>'
    )
    contract, _data = _contract(
        request,
        request_fragments=(request,),
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

    assert len(contract["requirements"]) == 2
    assert contract["attachment_dependencies"][0]["requirement_ids"] == []
    assert "required_attachment_requirement_linkage" in {
        item["code"] for item in contract["quality_report"]["blocking_issues"]
    }


def test_conflicting_attachment_identities_reusing_one_path_fail_closed(
    tmp_path,
) -> None:
    red_bytes = _tiny_png()
    blue_bytes = _tiny_png(b"\x00\x00\xff\xff")
    source_path = tmp_path / "reused-source.png"
    red_path = tmp_path / "red.png"
    blue_path = tmp_path / "blue.png"
    red_path.write_bytes(red_bytes)
    blue_path.write_bytes(blue_bytes)
    request = (
        "Fix the login screenshot.\n"
        f'<image name=[Login] path="{source_path}">\n</image>\n\n'
        "## Additional user-authored requirements\n\n"
        "### Follow-up 1\n"
        "Fix the billing screenshot.\n"
        f'<image name=[Billing] path="{source_path}">\n</image>'
    )
    contract, _data = _contract(
        request,
        request_fragments=(
            (
                "Fix the login screenshot.\n"
                f'<image name=[Login] path="{source_path}">\n</image>'
            ),
            (
                "Fix the billing screenshot.\n"
                f'<image name=[Billing] path="{source_path}">\n</image>'
            ),
        ),
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(source_path),
                resolved_path=str(red_path),
                sha256=hashlib.sha256(red_bytes).hexdigest(),
                mime_type="image/png",
            ),
            TrustedRequestImageDescriptor(
                path=str(source_path),
                resolved_path=str(blue_path),
                sha256=hashlib.sha256(blue_bytes).hexdigest(),
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
    )

    assert all(
        attachment["available"] is False
        for attachment in contract["attachment_dependencies"]
    )
    assert "required_attachments_resolved" in {
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
    assert session_handoff_render_issues(
        content,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    ) == []

def test_opencode_destination_complaint_compiles_to_grounded_read_only_brief(
    tmp_path,
) -> None:
    request = (
        "the opencode continue was somewhat successful, it pastes the prompt in "
        "the terminal instead of chatbox as shown in the screenshot\n\n"
        "this was th"
    )
    image_bytes = _tiny_png()
    image_path = tmp_path / "opencode-destination.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    production_paths = (
        "README.md",
        "app/api/continuations.py",
        "app/as_was.py",
        "app/instead_of.py",
        "app/services/continuation.py",
        "app/services/continuation_runtime.py",
        "app/services/harness_launcher.py",
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "ComposerPasteCommand.swift"
        ),
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "FocusedTextPasteService.swift"
        ),
        "tests/ComposerPasteCommandTest.swift",
        (
            "desktop/macos/DaemonStateOverlay/Tests/DaemonStateOverlayTests/"
            "FocusedTextPasteServiceTests.swift"
        ),
        "tests/test_harness_launcher.py",
    )
    contract, data = _contract(
        request,
        changed_files=production_paths,
        relevant_files=production_paths,
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

    assert contract["task_mode"] == "report"
    assert contract["execution_policy"]["permission_mode"] == "read_only"
    assert contract["execution_policy"]["may_edit"] is False
    intent = contract["intent"]
    assert intent["task_type_basis"] == "safety_default_unconfirmed"
    assert intent["reported_behavior"] == {
        "kind": "destination_mismatch",
        "flow": "OpenCode Continue",
        "object": "generated prompt",
        "actual_destination": "terminal",
        "expected_destination": "chat composer",
        "authority": "user_reported",
    }
    assert intent["source_quality"] == {
        "trailing_incomplete_fragment": "this was th",
        "operational_goal_excludes_trailing_fragment": True,
    }
    assert intent["normalized_requirement"].startswith(
        "Produce an evidence-backed report on the OpenCode Continue destination mismatch"
    )
    assert "this was th" not in intent["normalized_requirement"]
    assert len(contract["requirements"]) == 1
    assert contract["requirements"][0]["normalized_text"] == intent["normalized_requirement"]
    assert len(intent["acceptance_criteria"]) == 4
    assert contract["attachment_dependencies"][0]["required"] is True
    assert contract["attachment_dependencies"][0]["requirement_ids"] == ["R1"]
    assert intent["target_resolution"]["status"] == "candidate"
    assert [item["phrase"] for item in intent["targets"]] == ["chat composer"]
    candidate_paths = [
        item["path"] for item in intent["targets"][0]["candidates"]
    ]
    assert candidate_paths[:4] == [
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "ComposerPasteCommand.swift"
        ),
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "FocusedTextPasteService.swift"
        ),
        "app/services/harness_launcher.py",
        "app/services/continuation_runtime.py",
    ]
    assert "app/as_was.py" not in candidate_paths
    assert "app/instead_of.py" not in candidate_paths
    assert "README.md" not in candidate_paths[:4]

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    goal_section = content.split("## Goal", 1)[1].split("## State now", 1)[0]
    done_section = content.split("## Done when", 1)[1]
    assert intent["normalized_requirement"] in goal_section
    assert "\n> this was th\n" in goal_section
    assert "\nthis was th\n" not in goal_section
    assert "Quarantined trailing source fragment (verbatim; non-operative)" in goal_section
    assert "Source-quality note" in content
    assert "Intent classification: unconfirmed" in content
    assert "Expected destination" in content and "chat composer" in content
    assert "Required visual evidence" in content
    assert "opacity" not in content.casefold()
    assert "transparent" not in content.casefold()
    assert "card background" not in content.casefold()
    assert "apply only the minimum requirement-specific delta" not in content
    assert "does not authorize a requirement-specific delta" in content
    assert "do not edit files" in content
    assert request not in done_section
    assert intent["normalized_requirement"] in done_section
    assert {item["id"] for item in contract["verification_plan"]} == {
        "PV1",
        "PV2",
        "PV3",
        "PV4",
    }
    assert all(f"{item['id']}:" in done_section for item in contract["verification_plan"])
    assert all(item["evidence_locator"] for item in contract["verification_plan"])
    assert done_section.count("Evidence locator:") == len(contract["verification_plan"])
    assert (
        session_handoff_render_issues(
            content,
            request_verbatim=request,
            handoff_contract=contract,
            variant="compact_v2",
        )
        == []
    )

    contaminated = content.replace(
        "## Start here",
        "- Unknowns: whether transparency comes from the card background.\n\n"
        "## Start here",
    )
    contamination_issues = session_handoff_render_issues(
        contaminated,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    )
    contamination_failure = next(
        item
        for item in contamination_issues
        if item["code"] == "compact_session_context_critical_state_missing"
    )
    assert "cross_task_opacity_context" in contamination_failure["missing_fragments"]

    missing_destination = content.replace(
        "- Expected destination (derived directly from the user's contrast): chat composer.\n",
        "",
    )
    destination_issues = session_handoff_render_issues(
        missing_destination,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    )
    destination_failure = next(
        item
        for item in destination_issues
        if item["code"] == "compact_session_context_critical_state_missing"
    )
    assert "expected_destination" in destination_failure["missing_fragments"]


def test_non_opacity_attachment_plan_does_not_invent_css_work() -> None:
    handoff = {
        "execution_policy": {"may_edit": True},
        "intent": {
            "normalized_requirements": ["Fix the prompt destination shown in screenshot."],
            "target_resolution": {"status": "candidate"},
            "targets": [
                {
                    "candidates": [
                        {
                            "path": "app/services/continuation_runtime.py",
                        }
                    ]
                }
            ],
        },
        "attachment_dependencies": [{"id": "A1", "required": True}],
        "readiness": {"next_action": "Inspect the current prompt delivery path."},
        "requirements": [],
        "repository": {},
        "files": {"modified": [], "pre_existing_at_handoff": []},
    }

    steps = " ".join(_compact_session_start_steps(handoff)).casefold()

    assert "runtime route" in steps
    assert "opacity" not in steps
    assert "rgba" not in steps
    assert "backdrop" not in steps
    assert "transparent" not in steps


@pytest.mark.parametrize(
    "request_text",
    [
        (
            "Make OpenCode Continue paste the prompt into the chatbox instead "
            "of the terminal."
        ),
        (
            "Please paste the OpenCode Continue prompt into the chatbox instead "
            "of the terminal."
        ),
        (
            "Can you paste the OpenCode Continue prompt into the chatbox instead "
            "of the terminal?"
        ),
        (
            "Could you paste the OpenCode Continue prompt into the chatbox instead "
            "of the terminal?"
        ),
        (
            "I want you to paste the OpenCode Continue prompt into the chatbox "
            "instead of the terminal."
        ),
        (
            "Please ensure OpenCode Continue pastes the prompt into the chatbox "
            "instead of the terminal."
        ),
        (
            "Can you ensure OpenCode Continue pastes the prompt into the chatbox "
            "instead of the terminal?"
        ),
        (
            "I want you to ensure OpenCode Continue pastes the prompt into the "
            "chatbox instead of the terminal."
        ),
    ],
)
def test_imperative_destination_request_keeps_desired_direction(
    request_text: str,
) -> None:
    contract, _data = _contract(request_text)

    assert contract["task_mode"] == "change"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )
    assert contract["intent"]["normalized_requirement"] == (
        "Fix the OpenCode Continue so the generated prompt reaches the chat "
        "composer and never the terminal."
    )


def test_question_about_destination_keeps_reported_direction() -> None:
    request = (
        "Why does OpenCode Continue paste the prompt into the terminal instead "
        "of the chatbox?"
    )
    contract, _data = _contract(request)

    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_change_request_with_observed_clause_does_not_reverse_reported_direction() -> None:
    request = (
        "Please investigate why OpenCode Continue pastes the prompt into the terminal "
        "instead of the chatbox, then fix it."
    )
    contract, _data = _contract(request)

    assert contract["task_mode"] == "change"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_report_scoped_ensure_keeps_read_only_observed_direction() -> None:
    request = (
        "Please ensure the report explains why OpenCode Continue pastes the prompt "
        "into the terminal instead of the chatbox."
    )
    contract, _data = _contract(request)

    assert contract["task_mode"] == "report"
    assert contract["execution_policy"]["may_edit"] is False
    assert contract["intent"]["reported_behavior"]["authority"] == "user_reported"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_negated_destination_requirement_keeps_prohibited_destination_as_actual() -> None:
    request = (
        "Please fix OpenCode so it does not paste the prompt into the terminal "
        "instead of the chatbox."
    )
    contract, _data = _contract(request)

    assert contract["task_mode"] == "change"
    assert contract["intent"]["reported_behavior"]["authority"] == "user_directed"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


@pytest.mark.parametrize(
    "request_text",
    [
        "OpenCode should paste the prompt into the chatbox instead of the terminal.",
        "OpenCode must paste the prompt into the chatbox instead of the terminal.",
        (
            "I would like you to paste the OpenCode prompt into the chatbox instead "
            "of the terminal."
        ),
        (
            "I would really like you to paste the OpenCode prompt into the chatbox "
            "instead of the terminal."
        ),
        "I'd like you to paste the OpenCode prompt into the chatbox instead of the terminal.",
    ],
)
def test_modal_destination_requirement_keeps_desired_direction_without_edit_authority(
    request_text: str,
) -> None:
    contract, _data = _contract(request_text)

    assert contract["execution_policy"]["may_edit"] is False
    assert contract["intent"]["reported_behavior"]["authority"] == "user_directed"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


@pytest.mark.parametrize(
    "request_text",
    [
        "OpenCode can paste the prompt into the terminal instead of the chatbox.",
        "I saw OpenCode paste the prompt into the terminal instead of the chatbox.",
    ],
)
def test_observed_bare_destination_clause_keeps_reported_direction(
    request_text: str,
) -> None:
    contract, _data = _contract(request_text)

    assert contract["intent"]["reported_behavior"]["authority"] == "user_reported"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_causal_destination_observation_does_not_treat_so_as_a_requirement() -> None:
    request = (
        "The app loses focus, so OpenCode Continue pastes the prompt into the terminal "
        "instead of the chatbox."
    )
    contract, _data = _contract(request)

    assert contract["intent"]["reported_behavior"]["authority"] == "user_reported"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


@pytest.mark.parametrize(
    "request_text",
    [
        (
            "Please fix this because I need OpenCode Continue to paste the prompt "
            "into the chatbox instead of the terminal."
        ),
        (
            "Please update it because I would prefer OpenCode Continue to paste "
            "the prompt into the chatbox instead of the terminal."
        ),
        (
            "We expect OpenCode Continue to paste the prompt into the chatbox "
            "instead of the terminal."
        ),
        (
            "Please fix this because I’d rather OpenCode Continue paste the prompt "
            "into the chatbox instead of the terminal."
        ),
        (
            "Please fix this because my requirement is for OpenCode Continue to "
            "paste the prompt into the chatbox instead of the terminal."
        ),
        (
            "Please fix this because OpenCode Continue is required to paste the "
            "prompt into the chatbox instead of the terminal."
        ),
        (
            "OpenCode is expected to paste the prompt into the chatbox instead of "
            "the terminal."
        ),
        (
            "Ideally, OpenCode would paste the prompt into the chatbox instead of "
            "the terminal."
        ),
        (
            "We hope OpenCode pastes the prompt into the chatbox instead of the terminal."
        ),
        (
            "We prefer that OpenCode pastes the prompt into the chatbox instead of "
            "the terminal."
        ),
        (
            "The expected behavior is for OpenCode Continue to paste the prompt "
            "into the chatbox instead of the terminal."
        ),
        (
            "It is expected that OpenCode Continue pastes the prompt into the "
            "chatbox instead of the terminal."
        ),
        (
            "Ideally OpenCode Continue pastes the prompt into the chatbox instead "
            "of the terminal."
        ),
    ],
)
def test_causal_desiderative_destination_keeps_requested_direction(
    request_text: str,
) -> None:
    contract, _data = _contract(request_text)

    assert contract["intent"]["reported_behavior"]["authority"] == "user_directed"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_negated_desiderative_keeps_prohibited_destination_as_actual() -> None:
    contract, _data = _contract(
        "We want OpenCode not to paste the prompt into the terminal instead of the chatbox."
    )

    assert contract["intent"]["reported_behavior"]["authority"] == "user_directed"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == "terminal"
    assert contract["intent"]["reported_behavior"]["expected_destination"] == (
        "chat composer"
    )


def test_latest_destination_clause_overrides_explicitly_historical_behavior() -> None:
    contract, _data = _contract(
        "Previously, OpenCode Continue would paste the prompt into the terminal "
        "instead of the chatbox. Now it pastes the prompt into the chatbox instead "
        "of the terminal."
    )

    assert contract["intent"]["reported_behavior"]["authority"] == "user_reported"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == (
        "chat composer"
    )
    assert contract["intent"]["reported_behavior"]["expected_destination"] == "terminal"
    assert len(contract["requirements"]) == 1
    assert "reaches the chat composer instead of the terminal" in contract["requirements"][0][
        "normalized_text"
    ]


def test_explicit_current_destination_clause_outranks_later_history() -> None:
    contract, _data = _contract(
        "Now OpenCode Continue pastes the prompt into the chatbox instead of the "
        "terminal. Previously, it would paste the prompt into the terminal instead "
        "of the chatbox."
    )

    assert contract["intent"]["reported_behavior"]["authority"] == "user_reported"
    assert contract["intent"]["reported_behavior"]["actual_destination"] == (
        "chat composer"
    )
    assert contract["intent"]["reported_behavior"]["expected_destination"] == "terminal"
    assert len(contract["requirements"]) == 1
    assert "reaches the chat composer instead of the terminal" in contract["requirements"][0][
        "normalized_text"
    ]


@pytest.mark.parametrize(
    "valid_paragraph",
    [
        "This was intentional",
        "That behavior is expected",
        "It happens after login",
    ],
)
def test_short_complete_paragraph_is_not_quarantined_or_dropped(
    valid_paragraph: str,
) -> None:
    request = f"Investigate the current behavior.\n\n{valid_paragraph}"
    contract, _data = _contract(request)

    assert _sentences(request) == ["Investigate the current behavior.", valid_paragraph]
    assert contract["intent"]["source_quality"]["trailing_incomplete_fragment"] is None


def test_pasted_continuation_brief_scopes_behavior_to_trailing_review_lead() -> None:
    request = """# Continuation Brief v2

## Goal

Produce an evidence-backed report on the OpenCode destination mismatch.

Original user request (authoritative):
> OpenCode pastes the prompt in the terminal instead of chatbox.

## State now

- Reported behavior: OpenCode pastes the prompt in the terminal instead of chatbox.

## Start here

1. Inspect the current runtime.

## Do not repeat

- Do not guess.

## Done when

- R1: Record the destination.

this is the latest session context; rate this on quality"""
    contract, _data = _contract(request)

    assert [item["text"] for item in contract["requirements"]] == [
        "this is the latest session context; rate this on quality"
    ]
    assert contract["intent"]["reported_behavior"] is None
    assert contract["intent"]["acceptance_criteria"] == []
    assert "OpenCode destination mismatch" not in contract["intent"][
        "normalized_requirement"
    ]


@pytest.mark.parametrize(
    ("lead", "expected_mode"),
    [
        ("How good is this?", "report"),
        ("Can you score this?", "report"),
        ("Thoughts?", "report"),
        ("Do not edit; just explain the risks.", "report"),
        ("Now fix this", "change"),
    ],
)
def test_any_plain_trailing_lead_overrides_a_pasted_change_brief(
    lead: str,
    expected_mode: str,
) -> None:
    request = f"""# Continuation Brief v2

## Goal

Fix the authentication flow.

## State now

- Task type: change.

## Done when

- R1: The authentication flow works.
{lead}"""
    contract, _data = _contract(request)

    assert [item["text"] for item in contract["requirements"]] == [lead]
    assert contract["task_mode"] == expected_mode
    assert contract["execution_policy"]["may_edit"] is (expected_mode == "change")
    assert "authentication flow" not in contract["intent"]["normalized_requirement"]


@pytest.mark.parametrize(
    ("lead", "expected_requirements"),
    [
        (
            "Please review this handoff and rate its quality.\n\nThanks!",
            ["Please review this handoff and rate its quality."],
        ),
        (
            "Please review this handoff.\n\nDo not edit files.",
            ["Please review this handoff.", "Do not edit files."],
        ),
        ("- Please rate this", ["Please rate this"]),
        ("1. Rate this", ["Rate this"]),
        ("- Evaluate this handoff.", ["Evaluate this handoff."]),
        ("- Assess its quality.", ["Assess its quality."]),
        ("- Give me feedback on this.", ["Give me feedback on this."]),
        ("- Identify the weaknesses.", ["Identify the weaknesses."]),
        (
            "- R1 is wrong; assess this handoff.",
            ["R1 is wrong; assess this handoff."],
        ),
        (
            "- PV1 does not prove the claim; explain why.",
            ["PV1 does not prove the claim; explain why."],
        ),
        (
            "- R1: This is wrong; assess the handoff.",
            ["R1: This is wrong; assess the handoff."],
        ),
        (
            "- PV1: This does not prove R1; explain why.",
            ["PV1: This does not prove R1; explain why."],
        ),
    ],
)
def test_complete_trailing_lead_overrides_pasted_brief_across_formatting(
    lead: str,
    expected_requirements: list[str],
) -> None:
    request = f"""# Continuation Brief v2

## Goal

Fix the authentication flow.

## State now

- Task type: change.

## Done when

- R1: The authentication flow works.

{lead}"""
    contract, _data = _contract(request)

    assert [item["text"] for item in contract["requirements"]] == expected_requirements
    assert contract["execution_policy"]["may_edit"] is False
    assert "authentication flow" not in contract["intent"]["normalized_requirement"]


def test_blank_separated_generated_done_items_do_not_become_current_authority() -> None:
    request = """# Continuation Brief v2

## Goal

Fix the authentication flow.

## State now

- Task type: change.

## Done when

- R1: The authentication flow works.

- PV1: Run the focused authentication tests."""
    contract, _data = _contract(request)

    assert [item["text"] for item in contract["requirements"]] == [
        "Fix the authentication flow."
    ]
    assert contract["task_mode"] == "change"
    assert contract["execution_policy"]["may_edit"] is True


def test_historical_fix_does_not_complete_synthesized_destination_report() -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    data, comparison = _checkpoint_data(request)
    data["sections"]["progress"] = [
        {
            "statement": "Fixed OpenCode Continue prompt delivery in the desktop runtime.",
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        }
    ]
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["intent"]["task_type_basis"] == "safety_default_unconfirmed"
    assert contract["requirements"][0]["status"] != "reported_done"
    assert contract["reconciliation"]["counts"]["reported_done"] == 0


@pytest.mark.parametrize(
    "progress_statement",
    [
        "Updated OpenCode review screen prompt delivery.",
        "Completed the OpenCode review screen prompt delivery.",
        "Finished the OpenCode audit log prompt delivery.",
        (
            "Completed implementation of the OpenCode review and approval screen "
            "prompt delivery."
        ),
        "Finished the OpenCode audit and logging panel prompt delivery.",
        (
            "Completed the initial OpenCode destination analysis; final runtime "
            "findings remain pending."
        ),
        "Final report: the OpenCode destination investigation is still pending.",
        (
            "Completed the OpenCode destination analysis, but the final report "
            "is not ready."
        ),
        (
            "Completed the OpenCode destination analysis, but the report needs "
            "more work."
        ),
        (
            "Completed the OpenCode review and approval modal prompt-routing fix."
        ),
        (
            "Finished the OpenCode audit and telemetry dashboard prompt routing."
        ),
        (
            "Completed the OpenCode destination analysis; final report remains pending."
        ),
        (
            "Completed the OpenCode destination analysis. Final report is not ready."
        ),
        (
            "Completed the OpenCode destination analysis, but its report is not yet ready."
        ),
        "Completed the OpenCode destination analysis, but the report needs revision.",
        "Completed the OpenCode destination analysis, but the write-up is unfinished.",
        (
            "The OpenCode destination report was complete but is now incomplete."
        ),
        (
            "The OpenCode destination report is complete but still needs revision."
        ),
        "The OpenCode destination report is complete; later it became incomplete.",
        "The OpenCode destination report is complete; however, it became incomplete.",
        (
            "The OpenCode destination report is now incomplete, although it was "
            "complete yesterday."
        ),
    ],
)
def test_report_like_implementation_noun_does_not_complete_synthesized_report(
    progress_statement: str,
) -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    data, comparison = _checkpoint_data(request)
    data["sections"]["progress"] = [
        {
            "statement": progress_statement,
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        }
    ]
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["requirements"][0]["status"] != "reported_done"
    assert contract["reconciliation"]["counts"]["reported_done"] == 0


def test_explicit_completed_analysis_can_complete_synthesized_report() -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    data, comparison = _checkpoint_data(request)
    data["sections"]["progress"] = [
        {
            "statement": (
                "Completed the OpenCode Continue destination analysis and recorded "
                "the runtime findings."
            ),
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        }
    ]
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["requirements"][0]["status"] == "reported_done"
    assert contract["reconciliation"]["counts"]["reported_done"] == 1


@pytest.mark.parametrize(
    "progress_statement",
    [
        "Completed the OpenCode report; rollout remains pending.",
        "Completed the OpenCode report, but rollout remains pending.",
        "Completed the OpenCode report while rollout remains pending.",
        "Completed the OpenCode report and rollout remains pending.",
        "The OpenCode report is complete, although rollout remains pending.",
        (
            "The OpenCode report is now complete, although it was incomplete "
            "yesterday."
        ),
    ],
)
def test_completed_report_clause_is_not_negated_by_later_rollout_status(
    progress_statement: str,
) -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    data, comparison = _checkpoint_data(request)
    data["sections"]["progress"] = [
        {
            "statement": progress_statement,
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        }
    ]
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["requirements"][0]["status"] == "reported_done"
    assert contract["reconciliation"]["counts"]["reported_done"] == 1


def test_later_current_report_state_overrides_historical_incompletion() -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    data, comparison = _checkpoint_data(request)
    data["sections"]["progress"] = [
        {
            "statement": "The previously incomplete OpenCode report is now complete.",
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        }
    ]
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["requirements"][0]["status"] == "reported_done"
    assert contract["reconciliation"]["counts"]["reported_done"] == 1


def test_original_opencode_history_renders_one_coherent_golden_brief(tmp_path) -> None:
    request = (
        "the opencode continue was somewhat successful, it pastes the prompt in "
        "the terminal instead of chatbox as shown in the screenshot\n\n"
        "this was th"
    )
    paths = (
        "README.md",
        "app/api/continuations.py",
        "app/services/continuation.py",
        "app/services/continuation_runtime.py",
        "app/services/harness_launcher.py",
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "ComposerPasteCommand.swift"
        ),
        (
            "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
            "FocusedTextPasteService.swift"
        ),
    )
    data, comparison = _checkpoint_data(
        request,
        changed_files=paths,
        relevant_files=paths,
    )
    data["sections"]["progress"] = [
        {
            "statement": "Fixed the OpenCode Continue desktop prompt delivery path.",
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        },
        {
            "statement": (
                "Final verification is complete: 2,279 backend tests, 98 native "
                "Swift tests, and 444 frontend tests passed."
            ),
            "truth_state": "reported",
            "state": "active",
            "payload": {},
            "evidence": [],
        },
    ]
    data["sections"]["blockers"] = [
        {
            "statement": "I’m waiting for the exact final count before handing this back.",
            "truth_state": "reported",
            "state": "historical",
            "payload": {},
            "evidence": [],
        }
    ]
    verification_commands = [
        "pytest -q tests/test_harness_launcher.py",
        (
            ".venv/bin/pytest -q tests/test_continuations.py -k "
            "'staged_handoff or staged_opencode or desktop_composer or target_provider'"
        ),
        (
            ".venv/bin/ruff check app/services/checkpoints.py "
            'tests/test_continuations.py --config="pyproject.toml" '
            r"--note=C:\tmp\opencode"
        ),
    ]
    data["sections"]["verification"] = [
        {
            "statement": f"`{command}` passed.",
            "truth_state": "observed",
            "state": "passed",
            "payload": {"command": command, "passed": True, "exit_code": 0},
            "evidence": [],
        }
        for command in verification_commands
    ]
    image_bytes = _tiny_png()
    image_path = tmp_path / "opencode-golden.png"
    image_path.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        trusted_attachment_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image_path),
                resolved_path=str(image_path),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_artifacts=True,
        checkpoint_data=data,
        repository_comparison=comparison,
    )
    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )

    assert contract["requirements"][0]["status"] != "reported_done"
    assert contract["reconciliation"]["active_reported_blockers"] == []
    assert "Quarantined trailing source fragment (verbatim; non-operative)" in content
    assert "Reported behavior (user-authored)" in content
    assert "Expected destination" in content and "chat composer" in content
    assert "A1 supports R1" in content and digest in content
    ranked = content.split("- Ranked candidates requiring inspection:", 1)[1]
    expected_order = (
        "ComposerPasteCommand.swift",
        "FocusedTextPasteService.swift",
        "app/services/harness_launcher.py",
        "app/services/continuation_runtime.py",
    )
    candidate_paths = [
        item["path"]
        for target in contract["intent"]["targets"]
        for item in target.get("candidates") or []
    ][:5]
    assert all("/Tests/" not in path and not path.startswith("tests/") for path in candidate_paths)
    assert all(
        ranked.index(first) < ranked.index(second)
        for first, second in zip(expected_order, expected_order[1:])
    )
    overlap_line = next(
        line
        for line in content.splitlines()
        if line.startswith("- Candidate/protected-baseline overlap (inspection only):")
    )
    assert all(fragment in overlap_line for fragment in expected_order)
    assert "Active blocker" not in content
    assert "checks=V" not in content
    assert "verification=V1" not in content
    assert "verification=V2" in content
    assert "verification=V3" in content
    assert "verification=V2; requirements=unmapped" in content
    assert "verification=V3; requirements=unmapped" in content
    assert verification_commands[1] in content
    assert verification_commands[2] in content
    assert "…" not in content.split("## Done when", 1)[1]
    assert content.count("Evidence locator:") == len(contract["verification_plan"])
    assert "transparency comes from" not in content
    assert "Search likely UI components and styles" not in content
    assert "apply only the minimum requirement-specific delta" not in content
    assert session_handoff_render_issues(
        content,
        request_verbatim=request,
        handoff_contract=contract,
        variant="compact_v2",
    ) == []


def test_sparse_destination_candidates_exclude_tests_and_documentation() -> None:
    request = (
        "OpenCode Continue pastes the prompt in the terminal instead of the chatbox."
    )
    paths = (
        "app/services/continuation_runtime.py",
        "tests/ComposerPasteCommandTest.swift",
        "frontend/e2e/ComposerPasteCommand.ts",
        "specs/harness_launcher.py",
        "documentation/continuation_runtime.py",
        "ComposerPasteCommandTests.swift",
        (
            "desktop/macos/DaemonStateOverlay/UITests/"
            "ComposerPasteCommand.swift"
        ),
        "frontend/ComposerPasteCommand.cy.ts",
        "frontend/ComposerPasteCommand.e2e.ts",
        "integration_tests/ComposerPasteCommand.ts",
        "samples/ComposerPasteCommand.swift",
        "benchmarks/FocusedTextPasteService.swift",
        "qa/ComposerPasteCommand.swift",
        "test_helpers/HarnessLauncher.py",
        "unit-tests/ComposerPasteCommand.swift",
        "unit_tests/ComposerPasteCommand.swift",
        "SystemTests/ComposerPasteCommand.swift",
        "__snapshots__/ComposerPasteCommand.swift",
        "stories/ComposerPasteCommand.swift",
        "frontend/ComposerPasteCommand.integration.ts",
        "androidTest/ComposerPasteCommand.swift",
        "testFixtures/ComposerPasteCommand.swift",
        "build/ComposerPasteCommand.swift",
        "dist/ComposerPasteCommand.ts",
        "out/ComposerPasteCommand.js",
        "node_modules/ComposerPasteCommand.ts",
        "vendor/ComposerPasteCommand.swift",
        "DerivedData/ComposerPasteCommand.swift",
        "frontend/ComposerPasteCommand.d.ts",
        "README.md",
    )
    contract, _data = _contract(
        request,
        changed_files=paths,
        relevant_files=paths,
    )

    candidate_paths = [
        item["path"]
        for target in contract["intent"]["targets"]
        for item in target.get("candidates") or []
    ]
    assert candidate_paths == ["app/services/continuation_runtime.py"]


def test_ui_target_candidates_exclude_generated_vendor_and_test_outputs() -> None:
    request = "Make the cards fully opaque."
    paths = (
        "frontend/src/components/Card.jsx",
        "build/components/Card.jsx",
        "dist/components/Card.jsx",
        "vendor/components/Card.jsx",
        "androidTest/components/Card.jsx",
        "frontend/components/Card.d.ts",
        "commonTest/components/Card.jsx",
        "jvmTest/components/Card.jsx",
        "testDebug/components/Card.jsx",
    )
    contract, _data = _contract(
        request,
        changed_files=paths,
        relevant_files=paths,
    )

    candidate_paths = [
        item["path"]
        for target in contract["intent"]["targets"]
        for item in target.get("candidates") or []
    ]
    assert candidate_paths == ["frontend/src/components/Card.jsx"]


def test_sole_inferred_destination_owner_remains_a_candidate_until_inspected() -> None:
    request = (
        "Make OpenCode Continue paste the prompt into the chatbox instead of the terminal."
    )
    paths = (
        "desktop/macos/DaemonStateOverlay/Sources/DaemonStateOverlay/"
        "ComposerPasteCommand.swift",
    )
    contract, _data = _contract(
        request,
        changed_files=paths,
        relevant_files=paths,
    )

    target = contract["intent"]["targets"][0]
    assert target["status"] == "candidate"
    assert target["resolved_entity"] is None
    assert contract["intent"]["target_resolution"]["status"] == "candidate"
    assert contract["readiness"]["status"] == "discovery_required"
    assert contract["quality_report"]["automatic_execution_ready"] is False


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
    assert conversational["readiness"]["status"] == "intent_resolution_required"
    assert "explicit current objective" in conversational["readiness"]["next_action"]
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


def test_unconfirmed_report_fallback_requires_intent_instead_of_inventing_work() -> None:
    request = "This is terrible."
    contract, data = _contract(request)

    assert contract["intent"]["task_type_basis"] == "safety_default_unconfirmed"
    assert contract["readiness"]["status"] == "intent_resolution_required"
    assert "explicit current objective" in contract["readiness"]["next_action"]
    assert contract["quality_report"]["automatic_execution_ready"] is False

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Status: **Intent Resolution Required**" in content
    assert "Task type: unconfirmed (read-only fallback only)." in content
    assert "Task type: report." not in content
    assert "Complete the requested report" not in content
    assert "Status: **Execution Ready**" not in content


def test_failure_feedback_state_is_copyable_context_but_never_action_authority() -> None:
    request = "Make frontend/src/Card.jsx opaque."
    reaction = "ARE U FUCKING SERIOUS MOTHERFUCKER"
    path = "frontend/src/Card.jsx"
    data, comparison = _checkpoint_data(
        request,
        changed_files=(path,),
        relevant_files=(path,),
        next_action="Continue the requested change.",
    )
    goal_payload = data["sections"]["goal"][0]["payload"]
    goal_payload["conversation_state"] = {
        "schema_version": "conversation_state.v1",
        "active_goal": {
            "root_event_id": "goal-event",
            "root_request_verbatim": request,
            "fragments": [],
            "composite_request_verbatim": request,
            "source_event_ids": ["goal-event"],
        },
        "lifecycle": "direction_required",
        "transitions": [
            {
                "event_id": "feedback-event",
                "sequence_number": 3,
                "user_text": reaction,
                "act": "failure_feedback",
                "active_goal_event_id": "goal-event",
                "assistant_event_id": "assistant-event",
                "resolved_statement": "Prior result rejected; active goal preserved.",
                "reason": "failure feedback preserves the active task",
                "confidence": 1.0,
                "blocks_copy": False,
            }
        ],
        "decisions": [],
        "pending_interaction": None,
        "unresolved_references": [],
        "state_sha256": "a" * 64,
    }
    contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )

    assert contract["current_goal"]["request_verbatim"] == request
    assert contract["readiness"]["status"] == "direction_required"
    assert contract["execution_policy"]["may_edit"] is False
    assert contract["execution_policy"]["permission_mode"] == "read_only"
    assert contract["quality_report"]["copy_ready"] is True
    assert contract["quality_report"]["automatic_execution_ready"] is False

    content = render_compact_session_handoff(
        SimpleNamespace(),
        request_verbatim=request,
        contract=contract,
        checkpoint_data=data,
    )
    assert "Status: **Direction Required**" in content
    assert "supplies context, not permission to act" in content
    assert "await explicit current direction" in content
    assert reaction not in content
    assert _compact_session_start_steps(contract) == [
        "Restore the recovered task and failure feedback as context only. Do not "
        "continue, inspect, or edit until the user gives an explicit current direction."
    ]

    goal_payload["conversation_state"]["unresolved_references"] = [
        {
            "event_id": "unresolved-event",
            "user_text": "fix it",
            "act": "unresolved_reference",
            "blocks_copy": True,
        }
    ]
    blocked_contract = build_session_handoff_contract(
        SimpleNamespace(),
        request_verbatim=request,
        checkpoint_data=data,
        repository_comparison=comparison,
    )
    assert blocked_contract["quality_report"]["status"] == "blocked"
    assert blocked_contract["readiness"]["status"] == "direction_required"
    assert "Do not continue, inspect, or edit" in blocked_contract["readiness"][
        "next_action"
    ]


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
