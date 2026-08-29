from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.evals.context_quality_benchmark import (
    FROZEN_GOLD_SCHEMA_VERSION,
    BenchmarkInputError,
    baseline_sha256,
    compare_repository_snapshots,
    load_frozen_baseline,
    load_frozen_gold,
    score_session_artifact,
    score_workspace_context,
    sql_is_read_only,
)
from app.schemas.context_quality import (
    ClaimCriticality,
    ClaimSelection,
    ContextClaimEnvelope,
    ContextKind,
)


BASELINE = Path(
    "docs/experiments/context-quality-engine-baseline-2026-08-20.json"
)
FROZEN_GOLD = Path(
    "docs/experiments/context-quality-engine-frozen-gold-2026-08-24.json"
)
GOLD_RUN_REPORT = Path(
    "docs/experiments/context-quality-engine-gold-run-2026-08-24.json"
)
UNIT_OBJECTIVE_PROVIDER_EVENT_ID = "msg_unit_objective"
UNIT_STALE_PROVIDER_EVENT_ID = "msg_unit_stale"
UNIT_OBJECTIVE_DATABASE_EVENT_ID = "00000000-0000-0000-0000-000000000010"


def _claim(
    stable_id: str,
    *,
    kind: str,
    section: str,
    statement: str,
    authority: str = "direct_user",
    truth_state: str = "historical",
    selection: ClaimSelection = ClaimSelection.INCLUDED,
) -> dict:
    return ContextClaimEnvelope(
        stable_id=stable_id,
        section=section,
        kind=kind,
        statement=statement,
        scope=ContextKind.SESSION,
        authority=authority,
        truth_state=truth_state,
        criticality=ClaimCriticality.HIGH,
        selection=selection,
        exclusion_reason=(
            "background_only_scope"
            if selection is ClaimSelection.EXCLUDED
            else None
        ),
        evidence_refs=(f"evidence:{stable_id}",),
    ).model_dump(mode="json")


def _background_artifact(
    objective: str,
    *,
    provider_event_ids: list[str] | None = None,
) -> dict:
    objective_provider_ids = (
        provider_event_ids
        if provider_event_ids is not None
        else [UNIT_OBJECTIVE_PROVIDER_EVENT_ID]
    )
    claims = [
        _claim(
            "session.prior_user_objective",
            kind="prior_user_objective",
            section="prior_user_objective",
            statement=objective,
        ),
        _claim(
            "session.progress",
            kind="progress",
            section="state",
            statement="The prior agent reported inspecting the composer.",
            authority="agent_report",
            truth_state="reported",
        ),
        _claim(
            "session.requirement",
            kind="open_requirement",
            section="open_context",
            statement="Explain the observed focus mismatch.",
        ),
        _claim(
            "session.failure",
            kind="failed_attempt",
            section="decisions_and_failed_approaches",
            statement="Window-title matching did not identify the composer.",
            authority="agent_report",
        ),
        _claim(
            "session.file",
            kind="relevant_file",
            section="relevant_surfaces",
            statement="app/services/harness_launcher.py",
            authority="repository_observation",
            truth_state="current",
        ),
        _claim(
            "session.unknown",
            kind="known_unknown",
            section="uncertainties",
            statement="Live focus remains unverified.",
            authority="compiler_inference",
            truth_state="unknown",
        ),
        _claim(
            "session.action",
            kind="inferred_action",
            section="excluded",
            statement="Edit the launcher.",
            authority="compiler_inference",
            truth_state="unknown",
            selection=ClaimSelection.EXCLUDED,
        ),
    ]
    claims[0]["evidence_refs"].extend(
        f"objective_provider_event:{event_id}"
        for event_id in objective_provider_ids
    )
    content = (
        "# Session Context — background for the user’s next request\n\n"
        "## Prior user objective\n\n"
        f"> {objective}\n\n"
        "## Uncertainties\n\n- [unknown] Live focus remains unverified.\n\n"
        "## Awaiting user instruction\n\nAwaiting user instruction."
    )
    return {
        "context_role": "background_only",
        "claim_manifest": claims,
        "content": content,
        "attachment_dependencies": [],
        "boundary": {"has_newer_events": False},
        "currentness": {"state": "current"},
        "repository": {"freshness": {"status": "unknown"}},
        "delivery": {"ready_for_execution": False},
        "quality_report": {"automatic_execution_ready": False},
        "quality_evaluation": {"hard_failures": [], "warnings": []},
        "objective_resolution": {
            "status": "resolved",
            "source_provider_event_ids": objective_provider_ids,
        },
        "estimated_tokens": 500,
    }


def _objective_sha256(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _add_required_attachment(
    artifact: dict,
    *,
    sha256: str,
    available: bool,
    receiver_availability: str | None = None,
) -> None:
    dependency = {
        "id": "A1",
        "name": "required screenshot",
        "required": True,
        "available": available,
        "sha256": sha256,
    }
    if receiver_availability is not None:
        dependency["receiver_availability"] = receiver_availability
    artifact["attachment_dependencies"] = [dependency]
    artifact["claim_manifest"].append(_claim(
        "session.attachment",
        kind="required_attachment",
        section="required_evidence",
        statement="Required screenshot (A1)",
        authority="direct_user",
        truth_state="historical",
    ))


def _gold_case(
    objective: str | None = None,
    *,
    objective_status: str = "resolved",
    required_attachment_count: int = 0,
    required_attachment_sha256s: list[str] | None = None,
    required_relevant_files: list[str] | None = None,
    forbidden_relevant_files: list[str] | None = None,
    required_intent_concepts: list[dict] | None = None,
    provider_event_ids: list[str] | None = None,
    binding_required: bool = True,
    forbidden_objective_sha256s: list[str] | None = None,
) -> dict:
    authority_provider_ids = (
        provider_event_ids
        if provider_event_ids is not None
        else [UNIT_OBJECTIVE_PROVIDER_EVENT_ID]
    )
    return {
        "case_id": "unit-case",
        "checkpoint_id": "00000000-0000-0000-0000-000000000001",
        "objective_status": objective_status,
        **(
            {
                "objective_text": objective,
                "objective_sha256": _objective_sha256(objective),
                "acceptable_objective_sha256s": [
                    _objective_sha256(objective)
                ],
                "required_intent_concepts": (
                    required_intent_concepts
                    if required_intent_concepts is not None
                    else [{"name": "unit_objective", "any_of": [objective]}]
                ),
                "forbidden_objective_sha256s": (
                    forbidden_objective_sha256s or []
                ),
                "objective_authority": {
                    "binding_required": binding_required,
                    "required_provider_event_ids": (
                        authority_provider_ids if binding_required else []
                    ),
                    "allowed_provider_event_ids": authority_provider_ids,
                },
                "evidence": {
                    "objective_event_ids": [UNIT_OBJECTIVE_DATABASE_EVENT_ID],
                    "objective_provider_event_ids": authority_provider_ids,
                },
            }
            if objective_status == "resolved" and objective is not None
            else {}
        ),
        "required_attachment_count": required_attachment_count,
        "required_attachment_sha256s": required_attachment_sha256s or [],
        "required_relevant_files": required_relevant_files or [],
        "forbidden_relevant_files": forbidden_relevant_files or [],
    }


def _frozen_gold(baseline: dict, *, cases: list[dict] | None = None) -> dict:
    gold_cases = cases
    if gold_cases is None:
        gold_cases = [
            {
                **_gold_case(
                    objective_status="unresolved",
                ),
                "case_id": case["case_id"],
                "checkpoint_id": case["checkpoint_id"],
            }
            for case in baseline["session_contexts"]
        ]
    return {
        "schema_version": FROZEN_GOLD_SCHEMA_VERSION,
        "baseline_sha256": baseline_sha256(baseline),
        "provenance": {
            "method": "manual_adjudication",
            "adjudicator": "test-rater",
            "reviewer_count": 1,
            "blinded": False,
            "candidate_artifacts_consulted": False,
            "candidate_resolver_output_consulted": False,
        },
        "session_contexts": gold_cases,
    }


def test_frozen_baseline_uses_exact_unique_checkpoint_ids() -> None:
    baseline = load_frozen_baseline(BASELINE)

    checkpoint_ids = [
        item["checkpoint_id"] for item in baseline["session_contexts"]
    ]
    assert len(checkpoint_ids) == 8
    assert len(checkpoint_ids) == len(set(checkpoint_ids))
    assert checkpoint_ids[0] == "723c8a15-3356-4525-bffa-0570788266de"


def test_checked_in_gold_is_bound_to_the_frozen_corpus() -> None:
    baseline = load_frozen_baseline(BASELINE)

    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)

    assert len(gold["session_contexts"]) == 8
    assert gold["provenance"]["reviewer_count"] == 1
    assert gold["provenance"]["blinded"] is False
    assert gold["provenance"]["candidate_artifacts_consulted"] is False
    assert gold["provenance"]["candidate_resolver_output_consulted"] is False
    assert all(
        case["objective_authority"]["binding_required"] is True
        and case["acceptable_objective_sha256s"]
        and case["required_intent_concepts"]
        and case["required_attachment_count"]
        == len(case["required_attachment_sha256s"])
        for case in gold["session_contexts"]
    )
    case_968 = next(
        case for case in gold["session_contexts"] if case["case_id"] == "968ab8a38e"
    )
    assert "msg_01a018c4-92ed-71a0-9fa6-19318e04bea1" not in case_968[
        "objective_authority"
    ]["required_provider_event_ids"]
    assert "msg_01a018cd-bd91-7172-b586-0bed91de9619" in case_968[
        "objective_authority"
    ]["allowed_provider_event_ids"]
    assert "010acfa9-f308-4853-b7c7-2ed0580c53d0" in case_968["evidence"][
        "objective_event_ids"
    ]
    assert case_968["required_attachment_count"] == 0
    assert case_968["required_attachment_sha256s"] == []
    assert case_968["objective_authority"][
        "required_provider_event_id_groups"
    ] == [[
        "msg_01a018cd-bd91-7172-b586-0bed91de9619",
        "msg_01a018cd-eb8a-77e0-99d9-2bede8ec1ae1",
    ]]


def test_checked_in_gold_run_report_records_the_fail_closed_result() -> None:
    report = json.loads(GOLD_RUN_REPORT.read_text(encoding="utf-8"))
    gold = json.loads(FROZEN_GOLD.read_text(encoding="utf-8"))

    assert report["frozen_gold"]["sha256"] == baseline_sha256(gold)
    assert report["frozen_gold"]["candidate_derived_expectations"] is False
    assert report["sessions"]["candidate_mean_score"] == 28.62
    assert report["sessions"]["candidate_mean_score_before_hard_caps"] == 85.125
    assert report["sessions"]["promoted"] == 1
    assert report["sessions"]["rejected"] == 7
    assert report["sessions"]["objective_authority_verified"] == 8
    assert report["sessions"]["exact_attachment_manifest_matches"] == 8
    assert report["sessions"]["required_attachment_hashes_recovered"] == 7
    assert [
        case["candidate_score"] for case in report["sessions"]["cases"]
    ] == [19, 19, 19, 19, 19, 19, 19, 96]
    assert report["sessions"]["failure_counts"] == {
        "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE": 5,
        "REQUIRED_DEPENDENCY_MISSING": 2,
    }


def test_external_gold_is_hash_bound_and_covers_exact_frozen_cases(
    tmp_path: Path,
) -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = _frozen_gold(baseline)
    gold_path = tmp_path / "context-quality-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    loaded = load_frozen_gold(gold_path, baseline=baseline)

    assert loaded["baseline_sha256"] == baseline_sha256(baseline)
    assert len(loaded["session_contexts"]) == len(baseline["session_contexts"])

    gold["baseline_sha256"] = "0" * 64
    gold_path.write_text(json.dumps(gold), encoding="utf-8")
    with pytest.raises(BenchmarkInputError, match="baseline_sha256"):
        load_frozen_gold(gold_path, baseline=baseline)


def test_external_gold_rejects_partial_case_coverage(tmp_path: Path) -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = _frozen_gold(baseline)
    gold["session_contexts"].pop()
    gold_path = tmp_path / "partial-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    with pytest.raises(BenchmarkInputError, match="exact baseline case set"):
        load_frozen_gold(gold_path, baseline=baseline)


def test_external_gold_rejects_candidate_consulted_provenance(
    tmp_path: Path,
) -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = _frozen_gold(baseline)
    gold["provenance"]["candidate_resolver_output_consulted"] = True
    gold_path = tmp_path / "candidate-consulted-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    with pytest.raises(
        BenchmarkInputError,
        match="candidate_resolver_output_consulted.*explicitly false",
    ):
        load_frozen_gold(gold_path, baseline=baseline)


def test_external_gold_requires_complete_attachment_hash_adjudication(
    tmp_path: Path,
) -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = _frozen_gold(baseline)
    gold["session_contexts"][0]["required_attachment_count"] = 1
    gold_path = tmp_path / "incomplete-attachment-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    with pytest.raises(
        BenchmarkInputError,
        match="must exactly match.*attachment hashes",
    ):
        load_frozen_gold(gold_path, baseline=baseline)


def test_external_gold_rejects_opaque_text_even_with_its_exact_hash(
    tmp_path: Path,
) -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = _frozen_gold(baseline)
    gold["session_contexts"][0].update({
        "objective_status": "resolved",
        "objective_text": "same issue",
        "objective_sha256": _objective_sha256("same issue"),
    })
    gold_path = tmp_path / "self-hashed-opaque-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    with pytest.raises(BenchmarkInputError, match="not independently resolved"):
        load_frozen_gold(gold_path, baseline=baseline)


def test_sql_guard_accepts_reads_and_rejects_writes() -> None:
    assert sql_is_read_only("SELECT * FROM work_checkpoints WHERE id = ?")
    assert sql_is_read_only("WITH rows AS (SELECT 1) SELECT * FROM rows")
    assert sql_is_read_only("PRAGMA table_info(work_checkpoints)")
    assert not sql_is_read_only("INSERT INTO context_packs(id) VALUES (?)")
    assert not sql_is_read_only("WITH rows AS (SELECT 1) DELETE FROM context_packs")
    assert not sql_is_read_only("UPDATE work_checkpoints SET capture_status = 'x'")


@pytest.mark.parametrize(
    ("objective", "objective_status"),
    [
        ("same issue", "unresolved"),
        ("did u fix it?", "unresolved"),
        ("You have 8153 weighted tokens left", "not_a_task"),
        ("[Request interrupted by user]", "not_a_task"),
        ("<session interrupted>", "not_a_task"),
    ],
)
def test_self_derived_objective_hashes_cannot_promote_ambiguous_or_non_task_text(
    objective: str,
    objective_status: str,
) -> None:
    artifact = _background_artifact(objective)
    baseline_case = {
        "hard_failures": [],
        # This is the old circularity: candidate-side request text hashed and
        # inserted as its own supposed independent expectation.
        "independent_expectations": {
            "objective_sha256": _objective_sha256(objective),
        },
    }

    missing_gold = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
    )
    self_hashed_gold = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(objective),
    )
    adjudicated = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(objective_status=objective_status),
    )

    assert "INDEPENDENT_FROZEN_GOLD_MISSING" in missing_gold["hard_failures"]
    assert missing_gold["score"] == 0
    assert missing_gold["verdict"] == "reject"
    assert (
        "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE"
        in self_hashed_gold["hard_failures"]
    )
    assert self_hashed_gold["verdict"] == "reject"
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in adjudicated["hard_failures"]
    assert adjudicated["verdict"] == "reject"


def test_screenshot_reference_without_a_manifest_fails_by_adjudicated_count() -> None:
    objective = "Fix the layout regression shown in this screenshot."
    artifact = _background_artifact(objective)
    baseline_case = {
        "hard_failures": [],
        "independent_expectations": {
            "objective_sha256": _objective_sha256(objective),
            # The old path had no resolver-produced attachment hashes and thus
            # treated the empty candidate dependency set as complete.
            "required_attachment_sha256s": [],
        },
    }

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(
            objective,
            required_attachment_count=1,
        ),
    )

    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" in result["hard_failures"]
    assert result["frozen_gold"]["required_attachment_count"] == 1
    assert result["score"] <= 19
    assert result["verdict"] == "reject"


def test_exact_attachment_manifest_with_unavailable_bytes_has_distinct_failure() -> None:
    objective = "Explain the visual failure shown in the screenshot."
    attachment_sha = "c" * 64
    artifact = _background_artifact(objective)
    _add_required_attachment(
        artifact,
        sha256=attachment_sha,
        available=False,
    )
    artifact["quality_evaluation"]["hard_failures"] = [
        "REQUIRED_DEPENDENCY_MISSING"
    ]

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(
            objective,
            required_attachment_count=1,
            required_attachment_sha256s=[attachment_sha],
        ),
    )

    assert "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE" in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" not in result["hard_failures"]
    assert "REQUIRED_DEPENDENCY_MISSING" not in result["hard_failures"]
    assert result["frozen_gold"]["attachment_match"]["identity_complete"] is True
    assert result["score"] <= 19


def test_receiver_only_attachment_materialization_is_a_warning_not_omission() -> None:
    objective = "Explain the visual failure shown in the screenshot."
    attachment_sha = "d" * 64
    artifact = _background_artifact(objective)
    _add_required_attachment(
        artifact,
        sha256=attachment_sha,
        available=True,
        receiver_availability="materialization_required",
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(
            objective,
            required_attachment_count=1,
            required_attachment_sha256s=[attachment_sha],
        ),
    )

    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" not in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE" not in result["hard_failures"]
    assert result["frozen_gold"]["attachment_match"] == {
        "expected_count": 1,
        "expected_sha256s": [attachment_sha],
        "candidate_manifest_count": 1,
        "candidate_claim_count": 1,
        "candidate_sha256s": [attachment_sha],
        "missing_required_identity": False,
        "missing_sha256s": [],
        "unexpected_required_dependencies": False,
        "unexpected_manifest_count": 0,
        "unexpected_sha256s": [],
        "identity_complete": True,
        "source_bytes_available": True,
        "source_bytes_unavailable_ids": [],
        "receiver_materialization_pending_ids": ["A1"],
    }
    assert "REQUIRED_ATTACHMENT_RECEIVER_MATERIALIZATION_PENDING" in result[
        "warnings"
    ]
    assert result["verdict"] == "review"


def test_unexpected_required_attachment_is_not_misreported_as_an_omission() -> None:
    objective = "Explain the visual failure shown in the required screenshot."
    expected_sha = "e" * 64
    unexpected_sha = "f" * 64
    artifact = _background_artifact(objective)
    _add_required_attachment(
        artifact,
        sha256=expected_sha,
        available=True,
        receiver_availability="available",
    )
    artifact["attachment_dependencies"].append({
        "id": "A2",
        "required": True,
        "available": True,
        "receiver_availability": "available",
        "sha256": unexpected_sha,
    })
    artifact["claim_manifest"].append(_claim(
        "session.attachment.unexpected",
        kind="required_attachment",
        section="required_evidence",
        statement="Unexpected screenshot (A2)",
        authority="direct_user",
        truth_state="historical",
    ))

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(
            objective,
            required_attachment_count=1,
            required_attachment_sha256s=[expected_sha],
        ),
    )

    match = result["frozen_gold"]["attachment_match"]
    assert match["missing_required_identity"] is False
    assert match["unexpected_required_dependencies"] is True
    assert match["unexpected_manifest_count"] == 1
    assert match["unexpected_sha256s"] == [unexpected_sha]
    assert "UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY" in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" not in result["hard_failures"]
    assert result["score"] <= 19


def test_zero_attachment_gold_rejects_a_spurious_required_dependency() -> None:
    objective = "Finish the remaining OpenCode live verification."
    artifact = _background_artifact(objective)
    _add_required_attachment(
        artifact,
        sha256="a" * 64,
        available=False,
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    match = result["frozen_gold"]["attachment_match"]
    assert match["expected_count"] == 0
    assert match["missing_required_identity"] is False
    assert match["unexpected_required_dependencies"] is True
    assert match["unexpected_manifest_count"] == 1
    assert "UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY" in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" not in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE" not in result["hard_failures"]


def test_session_rubric_rewards_background_only_projection() -> None:
    objective = "Explain why OpenCode selects the wrong composer after a session launch."
    artifact = _background_artifact(objective)

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    assert result["verdict"] == "promote"
    assert result["score"] >= 85
    assert result["assessment_kind"] == "background_projection_safety"
    assert result["promotion_scope"] == "background_projection_only"
    assert result["dimensions"]["background_only_semantics"] == 10
    assert result["hard_failures"] == []


def test_session_rubric_applies_independent_objective_and_dependency_caps() -> None:
    artifact = _background_artifact("same issue, so u cant fix this")
    baseline_case = {"hard_failures": []}
    gold_case = _gold_case(
        "Explain why the selected composer does not receive the handoff.",
        required_attachment_count=1,
        required_attachment_sha256s=["a" * 64],
    )

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=gold_case,
    )

    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]
    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" in result["hard_failures"]
    assert result["score"] <= 19
    assert result["verdict"] == "reject"


def test_session_rubric_accepts_a_concrete_user_confirmed_problem_statement() -> None:
    objective = (
        "so the issue u r fixing is this: DaemonState sends OpenCode a delayed "
        "new-session link, and the attempt must cancel permanently on the first "
        "focus change."
    )
    artifact = _background_artifact(objective)
    baseline_case = {"hard_failures": []}

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(objective),
    )

    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" not in result["hard_failures"]


def test_independent_objective_hash_accepts_exact_concrete_continue_request() -> None:
    objective = "Continue implementing the verified composer focus correction."
    artifact = _background_artifact(objective)
    baseline_case = {"hard_failures": []}

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(objective),
    )

    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" not in result["hard_failures"]
    assert result["dimensions"]["goal_and_dependency_fidelity"] == 30


def test_frozen_intent_contract_accepts_a_faithful_paraphrase() -> None:
    artifact = _background_artifact(
        "Diagnose why the OpenCode composer handoff remains empty, then fix it."
    )
    gold_case = _gold_case(
        "Fix the recurring OpenCode empty-composer handoff failure.",
        required_intent_concepts=[
            {"name": "action", "any_of": ["fix", "diagnose"]},
            {"name": "provider", "any_of": ["OpenCode"]},
            {"name": "surface", "any_of": ["composer handoff"]},
            {"name": "failure", "any_of": ["empty", "failure"]},
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    match = result["frozen_gold"]["objective_match"]
    assert match["matched"] is True
    assert match["text_match_method"] == "required_intent_concepts"
    assert match["authority"]["status"] == "verified"
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" not in result["hard_failures"]


def test_intent_contract_expands_a_coordinated_shared_head() -> None:
    artifact = _background_artifact(
        "Verify the flow for both session and workspace context."
    )
    gold_case = _gold_case(
        "Verify the flow for both Session Context and Workspace Context.",
        required_intent_concepts=[
            {"name": "verification", "any_of": ["verify"]},
            {"name": "session_scope", "any_of": ["session context"]},
            {"name": "workspace_scope", "any_of": ["workspace context"]},
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    match = result["frozen_gold"]["objective_match"]
    assert match["matched"] is True
    assert match["text_match_method"] == "required_intent_concepts"
    assert match["matched_phrases"] == {
        "verification": "verify",
        "session_scope": "session context",
        "workspace_scope": "workspace context",
    }


def test_intent_contract_does_not_expand_arbitrary_token_gaps() -> None:
    artifact = _background_artifact(
        "Verify session and workspace files in the context view."
    )
    gold_case = _gold_case(
        "Verify both Session Context and Workspace Context.",
        required_intent_concepts=[
            {"name": "verification", "any_of": ["verify"]},
            {"name": "session_scope", "any_of": ["session context"]},
            {"name": "workspace_scope", "any_of": ["workspace context"]},
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    match = result["frozen_gold"]["objective_match"]
    assert match["missing_concepts"] == ["session_scope", "workspace_scope"]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_stale_objective_with_shared_generic_terms_fails_required_intent() -> None:
    artifact = _background_artifact(
        "Fix the recurring OpenCode billing failure."
    )
    gold_case = _gold_case(
        "Fix the recurring OpenCode empty-composer handoff failure.",
        required_intent_concepts=[
            {"name": "action", "any_of": ["fix"]},
            {"name": "provider", "any_of": ["OpenCode"]},
            {"name": "surface", "any_of": ["composer", "handoff"]},
            {"name": "failure", "any_of": ["failure", "issue"]},
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    match = result["frozen_gold"]["objective_match"]
    assert match["text_match_method"] == "none"
    assert match["missing_concepts"] == ["surface"]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_matching_objective_with_a_stale_authority_event_fails() -> None:
    objective = "Fix the recurring OpenCode empty-composer handoff failure."
    artifact = _background_artifact(
        objective,
        provider_event_ids=[UNIT_STALE_PROVIDER_EVENT_ID],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["status"] == "invalid_or_incomplete"
    assert authority["disallowed_resolution_provider_event_ids"] == [
        UNIT_STALE_PROVIDER_EVENT_ID
    ]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_database_event_ids_cannot_satisfy_provider_authority_binding() -> None:
    objective = "Fix the recurring OpenCode composer handoff issue."
    artifact = _background_artifact(objective, provider_event_ids=[])
    artifact["objective_resolution"]["source_event_ids"] = [
        UNIT_OBJECTIVE_DATABASE_EVENT_ID
    ]
    artifact["claim_manifest"][0]["evidence_refs"].append(
        f"objective_source_event:{UNIT_OBJECTIVE_DATABASE_EVENT_ID}"
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["resolution_provider_event_ids"] == []
    assert authority["claim_provider_event_ids"] == []
    assert authority["missing_resolution_provider_event_ids"] == [
        UNIT_OBJECTIVE_PROVIDER_EVENT_ID
    ]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_case_968_rejects_chain_that_keeps_completed_seq78_active() -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)
    gold_case = next(
        case for case in gold["session_contexts"] if case["case_id"] == "968ab8a38e"
    )
    artifact = _background_artifact(
        gold_case["objective_text"],
        provider_event_ids=[
            "msg_01a018c4-92ed-71a0-9fa6-19318e04bea1",
            "msg_01a018cd-eb8a-77e0-99d9-2bede8ec1ae1",
            "msg_01a0190f-7ddd-7fd3-acb0-088c577d17ba",
            "msg_01a01978-fdb9-7ab2-9fec-fe14c0fe937b",
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["disallowed_resolution_provider_event_ids"] == [
        "msg_01a018c4-92ed-71a0-9fa6-19318e04bea1"
    ]
    assert authority["disallowed_claim_provider_event_ids"] == [
        "msg_01a018c4-92ed-71a0-9fa6-19318e04bea1"
    ]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_case_968_accepts_raw_adjudicated_live_issue_chain() -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)
    gold_case = next(
        case for case in gold["session_contexts"] if case["case_id"] == "968ab8a38e"
    )
    artifact = _background_artifact(
        gold_case["objective_text"],
        provider_event_ids=[
            "msg_01a018cd-eb8a-77e0-99d9-2bede8ec1ae1",
            "msg_01a0190f-7ddd-7fd3-acb0-088c577d17ba",
            "msg_01a01978-fdb9-7ab2-9fec-fe14c0fe937b",
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["status"] == "verified"
    assert result["frozen_gold"]["attachment_match"]["identity_complete"] is True
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" not in result["hard_failures"]
    assert "UNEXPECTED_REQUIRED_ATTACHMENT_DEPENDENCY" not in result["hard_failures"]


def test_case_968_accepts_the_canonical_duplicate_transport_alternative() -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)
    gold_case = next(
        case for case in gold["session_contexts"] if case["case_id"] == "968ab8a38e"
    )
    artifact = _background_artifact(
        gold_case["objective_text"],
        provider_event_ids=[
            "msg_01a018cd-bd91-7172-b586-0bed91de9619",
            "msg_01a0190f-7ddd-7fd3-acb0-088c577d17ba",
            "msg_01a01978-fdb9-7ab2-9fec-fe14c0fe937b",
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["status"] == "verified"
    assert authority["missing_resolution_provider_event_id_groups"] == []
    assert authority["missing_claim_provider_event_id_groups"] == []


def test_case_968_rejects_a_chain_missing_both_duplicate_root_transports() -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)
    gold_case = next(
        case for case in gold["session_contexts"] if case["case_id"] == "968ab8a38e"
    )
    duplicate_group = sorted([
        "msg_01a018cd-bd91-7172-b586-0bed91de9619",
        "msg_01a018cd-eb8a-77e0-99d9-2bede8ec1ae1",
    ])
    artifact = _background_artifact(
        gold_case["objective_text"],
        provider_event_ids=[
            "msg_01a0190f-7ddd-7fd3-acb0-088c577d17ba",
            "msg_01a01978-fdb9-7ab2-9fec-fe14c0fe937b",
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["missing_resolution_provider_event_id_groups"] == [
        duplicate_group
    ]
    assert authority["missing_claim_provider_event_id_groups"] == [
        duplicate_group
    ]
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_minimal_required_authority_does_not_require_allowed_antecedents() -> None:
    baseline = load_frozen_baseline(BASELINE)
    gold = load_frozen_gold(FROZEN_GOLD, baseline=baseline)
    gold_case = next(
        case for case in gold["session_contexts"] if case["case_id"] == "3682a763b2"
    )
    artifact = _background_artifact(
        gold_case["objective_text"],
        provider_event_ids=gold_case["objective_authority"][
            "required_provider_event_ids"
        ],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    authority = result["frozen_gold"]["objective_match"]["authority"]
    assert authority["status"] == "verified"
    assert authority["missing_resolution_provider_event_ids"] == []
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" not in result["hard_failures"]


def test_forbidden_stale_objective_hash_overrides_matching_concepts() -> None:
    stale = "Fix the OpenCode composer handoff issue."
    artifact = _background_artifact(stale)
    gold_case = _gold_case(
        "Diagnose the OpenCode composer handoff issue.",
        required_intent_concepts=[
            {"name": "provider", "any_of": ["OpenCode"]},
            {"name": "surface", "any_of": ["composer handoff"]},
            {"name": "issue", "any_of": ["issue"]},
        ],
        forbidden_objective_sha256s=[_objective_sha256(stale)],
    )

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    match = result["frozen_gold"]["objective_match"]
    assert match["forbidden_hash"] is True
    assert match["text_match_method"] == "none"
    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]


def test_legacy_gold_without_authority_binding_is_warned_and_penalized() -> None:
    objective = "Explain the verified composer focus correction."
    artifact = _background_artifact(objective, provider_event_ids=[])
    gold_case = _gold_case(objective, binding_required=False)

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=gold_case,
    )

    assert result["frozen_gold"]["objective_match"]["matched"] is True
    assert (
        result["frozen_gold"]["objective_match"]["authority"]["status"]
        == "legacy_unavailable"
    )
    assert "OBJECTIVE_AUTHORITY_BINDING_UNAVAILABLE" in result["warnings"]
    assert result["dimensions"]["goal_and_dependency_fidelity"] == 25
    assert result["verdict"] == "review"


def test_session_rubric_rejects_unseen_opaque_objective_without_failure_label() -> None:
    artifact = _background_artifact("same issue")

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective_status="unresolved"),
    )

    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]
    assert result["verdict"] == "reject"


def test_session_rubric_rejects_unseen_concrete_wrong_objective() -> None:
    artifact = _background_artifact(
        "Implement the billing webhook retry policy."
    )
    baseline_case = {"hard_failures": []}

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(
            "Explain why OpenCode selects the wrong composer after launch."
        ),
    )

    assert "UNRESOLVED_OR_WRONG_ACTIVE_OBJECTIVE" in result["hard_failures"]
    assert result["verdict"] == "reject"


def test_session_rubric_rejects_unseen_required_attachment_omission() -> None:
    artifact = _background_artifact(
        "Explain the visual failure shown in the required screenshot."
    )
    baseline_case = {"hard_failures": []}

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(
            "Explain the visual failure shown in the required screenshot.",
            required_attachment_count=1,
            required_attachment_sha256s=["b" * 64],
        ),
    )

    assert "REQUIRED_ATTACHMENT_DEPENDENCY_OMITTED" in result["hard_failures"]
    assert result["score"] <= 19
    assert result["verdict"] == "reject"


def test_session_rubric_rejects_unseen_target_mismatch() -> None:
    artifact = _background_artifact(
        "Explain why OpenCode selects the wrong composer after launch."
    )
    objective = "Explain why OpenCode selects the wrong composer after launch."
    baseline_case = {"hard_failures": []}

    result = score_session_artifact(
        artifact,
        baseline_case=baseline_case,
        gold_case=_gold_case(
            objective,
            required_relevant_files=["desktop/macos/Composer.swift"],
            forbidden_relevant_files=["app/services/harness_launcher.py"],
        ),
    )

    assert "TARGET_INFERENCE_MISMATCH" in result["hard_failures"]
    assert result["verdict"] == "reject"


def test_session_rubric_rejects_unseen_session_only_target_noise() -> None:
    objective = "Explain why OpenCode selects the wrong composer after launch."
    artifact = _background_artifact(objective)
    artifact["claim_manifest"].append(_claim(
        "session.noisy-file",
        kind="relevant_file",
        section="relevant_surfaces",
        statement="app/services/session_library.py",
        authority="agent_report",
        truth_state="reported",
    ))

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    assert (
        "TARGET_INFERENCE_CONTAMINATED_BY_SESSION_ONLY_PUSH"
        in result["hard_failures"]
    )
    assert result["verdict"] == "reject"


def test_session_rubric_rejects_generated_action_and_done_sections() -> None:
    objective = "Explain why OpenCode selects the wrong composer after a session launch."
    artifact = _background_artifact(objective)
    artifact["content"] += "\n\n## Start here\n\n1. Edit it.\n\n## Done when\n\n- Fixed."

    result = score_session_artifact(
        artifact,
        baseline_case={"hard_failures": []},
        gold_case=_gold_case(objective),
    )

    assert "INFERRED_ACTION_PRESENT" in result["hard_failures"]
    assert "GENERATED_ACCEPTANCE_CRITERIA_PRESENT" in result["hard_failures"]
    assert result["score"] <= 49


def test_workspace_rubric_reproduces_brutal_baseline_shape() -> None:
    foundation = {
        "product_profile": {
            "claims": [{
                "kind": "purpose",
                "value": "DaemonState preserves project context.",
                "evidence_ref_ids": ["README.md:L1"],
            }]
        },
        "capabilities": [{"id": "capability.one", "name": "Continue"}],
        "architecture_components": [{"id": "component.one", "name": "API"}],
        "structural_edges": [],
        "production_flows": [],
        "verification_runs": [],
        "change_intents": [],
        "durable_facts": [],
        "repository_state": {
            "snapshot_fingerprint": "a" * 64,
            "branch": "main",
            "head_commit": "b" * 40,
            "changed_path_count": 2,
        },
        "quality_report": {
            "copy_ready": True,
            "semantic_coverage_score": 65.5,
            "repository_health": "unknown",
            "issues": [],
            "section_coverage": [
                {"section": "product", "status": "complete"},
                {"section": "capabilities", "status": "partial"},
                {"section": "architecture", "status": "partial"},
                {"section": "repository", "status": "partial"},
                {"section": "durable_knowledge", "status": "missing"},
            ],
        },
    }
    markdown = (
        "# Workspace Context\n\n## Product and boundaries\n\n"
        "- DaemonState preserves project context…\n\n"
        "## Current repository state\n\n" + ("x" * 17_000)
    )
    manifest = {
        "focus": {"kind": "project_snapshot"},
        "workspace_foundation": foundation,
        "rendering": {},
    }

    result = score_workspace_context(markdown, manifest)

    assert result["score"] == 59
    assert result["verdict"] == "review"
    assert result["findings"] == [
        "AUTO_PROMOTION_UNJUSTIFIED",
        "DURABLE_PROVENANCE_EMPTY",
        "REQUIRED_VERIFICATION_MISSING",
    ]

    controlled = score_workspace_context(
        markdown,
        manifest,
        controller_enforced=True,
    )
    assert controlled["delivery_control"] == {
        "controller_enforced": True,
        "controller_decision": "review",
        "copy_allowed": False,
    }
    assert "AUTO_PROMOTION_UNJUSTIFIED" not in controlled["findings"]


def test_repository_drift_is_explicit_and_field_level() -> None:
    before = {
        "snapshot_fingerprint": "a" * 64,
        "branch": "main",
        "head_commit": "b" * 40,
        "dirty": False,
        "changed_path_count": 0,
    }
    after = {**before, "snapshot_fingerprint": "c" * 64, "changed_path_count": 2}

    comparison = compare_repository_snapshots(before, after)

    assert comparison["drifted"] is True
    assert comparison["changed_fields"] == [
        "snapshot_fingerprint",
        "changed_path_count",
    ]
