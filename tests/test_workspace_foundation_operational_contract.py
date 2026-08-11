from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.workspace_foundation import WorkspaceFoundationArtifact


_SNAPSHOT = "1" * 64
_OTHER_SNAPSHOT = "2" * 64


def _payload() -> dict[str, Any]:
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return {
        "compiled_at": now,
        "compiler_version": "workspace_foundation_compiler.test",
        "product_profile": {
            "name": "Atlas",
            "summary": "Atlas deploys applications.",
            "evidence_ref_ids": ["evidence.product"],
        },
        "evidence_references": [
            {
                "id": "evidence.product",
                "tier": "documentation_stated",
                "source_sha256": "3" * 64,
                "path": "README.md",
            },
            {
                "id": "evidence.capability",
                "tier": "documentation_stated",
                "source_sha256": "4" * 64,
                "path": "README.md",
            },
            {
                "id": "evidence.change",
                "tier": "code_observed",
                "source_sha256": "5" * 64,
                "rule": "git_status_entry.v1",
            },
            {
                "id": "evidence.flow",
                "tier": "code_observed",
                "source_sha256": "6" * 64,
                "path": "app/api/deploy.py",
                "symbol": "deploy",
            },
            {
                "id": "evidence.test-run",
                "tier": "test_verified",
                "source_sha256": "7" * 64,
                "rule": "verification_observation.v1",
            },
            {
                "id": "evidence.intent",
                "tier": "documentation_stated",
                "source_sha256": "8" * 64,
                "path": "docs/deploy-plan.md",
            },
        ],
        "capabilities": [
            {
                "id": "capability.deploy",
                "name": "Deploy",
                "summary": "Submits deployments.",
                "state": "documented_only",
                "assessment": {
                    "declaration_status": "declared",
                    "implementation_coverage": "none",
                    "verification_status": "absent",
                },
                "evidence_ref_ids": ["evidence.capability"],
            }
        ],
        "production_flows": [
            {
                "id": "flow.deploy",
                "name": "Deploy request",
                "capability_ids": ["capability.deploy"],
                "snapshot": _SNAPSHOT,
                "entrypoint": {
                    "kind": "entrypoint",
                    "path": "app/api/deploy.py",
                    "symbol": "deploy",
                    "evidence_ref_ids": ["evidence.flow"],
                },
                "proof": "code_observed",
                "complete": False,
                "gaps": ["service stage was not established"],
                "evidence_ref_ids": ["evidence.flow"],
            }
        ],
        "verification_runs": [
            {
                "id": "run.tests",
                "command": "pytest -q",
                "working_directory": ".",
                "snapshot": _SNAPSHOT,
                "exit_code": 0,
                "result": "passed",
                "observed_at": now,
                "output_sha256": "9" * 64,
                "evidence_ref_ids": ["evidence.test-run"],
            }
        ],
        "repository_state": {
            "repository_name": "atlas",
            "branch": "main",
            "head_commit": "a" * 40,
            "dirty": True,
            "captured_at": now,
            "snapshot_fingerprint": _SNAPSHOT,
            "changed_path_count": 1,
            "changes": [
                {
                    "path": "app/services/deploy.py",
                    "kind": "modified",
                    "evidence_ref_ids": ["evidence.change"],
                }
            ],
            "evidence_ref_ids": ["evidence.change"],
        },
        "change_intents": [
            {
                "id": "intent.deploy",
                "capability": "Deploy",
                "capability_ids": ["capability.deploy"],
                "snapshot": _SNAPSHOT,
                "changed_paths": ["app/services/deploy.py"],
                "before_behavior": {
                    "statement": "Submissions could be duplicated.",
                    "evidence_ref_ids": ["evidence.intent"],
                },
                "after_behavior": {
                    "statement": "Submissions are idempotent.",
                    "evidence_ref_ids": ["evidence.intent"],
                },
                "completed": "in_progress",
                "completion_evidence_ref_ids": ["evidence.intent"],
                "remaining_status": "identified",
                "remaining": [
                    {
                        "statement": "Add a concurrency regression test.",
                        "evidence_ref_ids": ["evidence.intent"],
                    }
                ],
                "remaining_evidence_ref_ids": ["evidence.intent"],
                "affected_tests": ["tests/test_deploy.py"],
                "evidence_ref_ids": ["evidence.change", "evidence.intent"],
            }
        ],
        "quality_report": {
            "status": "pass",
            "publishable": True,
            "copy_ready": True,
            "score": 90,
            "semantic_coverage_score": 90,
        },
    }


def _validate(payload: dict[str, Any]) -> WorkspaceFoundationArtifact:
    return WorkspaceFoundationArtifact.from_payload(payload)


def test_operational_lanes_accept_snapshot_bound_provenance() -> None:
    artifact = _validate(_payload())

    assert artifact.production_flows[0].snapshot == artifact.repository_state.snapshot_fingerprint
    assert artifact.verification_runs[0].result.value == "passed"
    assert artifact.change_intents[0].changed_paths == ("app/services/deploy.py",)


@pytest.mark.parametrize(
    ("lane", "message"),
    [
        ("production_flows", "production flow flow.deploy snapshot does not match"),
        ("verification_runs", "verification run run.tests snapshot does not match"),
        ("change_intents", "change intent intent.deploy snapshot does not match"),
    ],
)
def test_operational_lanes_reject_cross_snapshot_records(lane: str, message: str) -> None:
    payload = _payload()
    payload[lane][0]["snapshot"] = _OTHER_SNAPSHOT

    with pytest.raises(ValidationError, match=message):
        _validate(payload)


@pytest.mark.parametrize(
    ("lane", "message"),
    [
        ("production_flows", "production flow flow.deploy references unknown capabilities"),
        ("change_intents", "change intent intent.deploy references unknown capabilities"),
    ],
)
def test_operational_lanes_reject_unknown_capability_ids(lane: str, message: str) -> None:
    payload = _payload()
    payload[lane][0]["capability_ids"] = ["capability.unknown"]

    with pytest.raises(ValidationError, match=message):
        _validate(payload)


def test_change_intent_paths_must_exist_in_the_captured_change_set() -> None:
    payload = _payload()
    payload["change_intents"][0]["changed_paths"] = ["app/services/uncaptured.py"]

    with pytest.raises(ValidationError, match="paths absent from repository changes"):
        _validate(payload)


def test_verification_run_rejects_static_evidence() -> None:
    payload = _payload()
    payload["verification_runs"][0]["evidence_ref_ids"] = ["evidence.flow"]

    with pytest.raises(
        ValidationError,
        match="requires test-verified or runtime-verified evidence",
    ):
        _validate(payload)


@pytest.mark.parametrize("proof", ["test_verified", "runtime_verified"])
def test_production_flow_proof_requires_matching_supporting_evidence(proof: str) -> None:
    payload = _payload()
    payload["production_flows"][0]["proof"] = proof

    with pytest.raises(ValidationError, match=f"declares {proof} proof without"):
        _validate(payload)


def test_every_production_flow_stage_requires_static_endpoint_evidence() -> None:
    payload = _payload()
    payload["production_flows"][0]["entrypoint"]["evidence_ref_ids"] = [
        "evidence.intent"
    ]

    with pytest.raises(ValidationError, match="entrypoint stage lacks"):
        _validate(payload)


@pytest.mark.parametrize(
    ("field_path", "message"),
    [
        (("before_behavior", "evidence_ref_ids"), "before behavior requires"),
        (("after_behavior", "evidence_ref_ids"), "after behavior requires"),
        (("completion_evidence_ref_ids",), "completion status requires"),
        (("remaining_evidence_ref_ids",), "remaining-work status requires"),
        (("remaining", 0, "evidence_ref_ids"), "remaining-work item 1 requires"),
    ],
)
def test_change_intent_semantic_fields_reject_inferred_evidence(
    field_path: tuple[str | int, ...],
    message: str,
) -> None:
    payload = _payload()
    value: Any = payload["change_intents"][0]
    for part in field_path[:-1]:
        value = value[part]
    value[field_path[-1]] = ["evidence.change"]

    with pytest.raises(ValidationError, match=message):
        _validate(payload)


def test_runtime_evidence_is_valid_for_execution_records() -> None:
    payload = deepcopy(_payload())
    runtime_reference = {
        "id": "evidence.runtime",
        "tier": "runtime_verified",
        "source_sha256": "b" * 64,
        "rule": "runtime_observation.v1",
    }
    payload["evidence_references"].append(runtime_reference)
    payload["verification_runs"][0]["evidence_ref_ids"] = ["evidence.runtime"]
    payload["production_flows"][0]["proof"] = "runtime_verified"
    payload["production_flows"][0]["evidence_ref_ids"].append("evidence.runtime")

    artifact = _validate(payload)

    assert artifact.production_flows[0].proof.value == "runtime_verified"
    assert artifact.verification_runs[0].evidence_ref_ids == ("evidence.runtime",)


def test_first_class_durable_fact_must_match_its_declared_evidence_tier() -> None:
    payload = _payload()
    payload["durable_facts"] = [{
        "id": "fact.decision",
        "identity_key": "decision:deploy",
        "kind": "decision",
        "title": "Deployment identity",
        "statement": "Deployment requests use stable identities.",
        "evidence_tier": "human_confirmed",
        "promotion_reason": "human_confirmed",
        "evidence_ref_ids": ["evidence.intent"],
    }]

    with pytest.raises(ValidationError, match="declares human_confirmed without evidence"):
        _validate(payload)


def test_corroborated_durable_fact_requires_independent_source_hashes() -> None:
    payload = _payload()
    payload["evidence_references"].extend([
        {
            "id": "evidence.corroborated-a",
            "tier": "corroborated",
            "source_sha256": "c" * 64,
            "rule": "corroboration.v1",
        },
        {
            "id": "evidence.corroborated-b",
            "tier": "corroborated",
            "source_sha256": "c" * 64,
            "rule": "corroboration.v1",
        },
    ])
    payload["durable_facts"] = [{
        "id": "fact.corroborated",
        "identity_key": "decision:deploy",
        "kind": "decision",
        "title": "Deployment identity",
        "statement": "Deployment requests use stable identities.",
        "evidence_tier": "corroborated",
        "promotion_reason": "independent_corroboration",
        "corroboration_count": 2,
        "evidence_ref_ids": [
            "evidence.corroborated-a",
            "evidence.corroborated-b",
        ],
    }]

    with pytest.raises(ValidationError, match="lacks independent source lineages"):
        _validate(payload)


def test_semantic_score_cannot_reach_95_with_empty_operational_gates() -> None:
    payload = _payload()
    payload["quality_report"]["score"] = 95
    payload["quality_report"]["semantic_coverage_score"] = 95

    with pytest.raises(ValidationError, match="requires operational gates"):
        _validate(payload)


def test_semantic_score_95_accepts_only_a_fully_admitted_operational_package() -> None:
    payload = _payload()
    payload["verification_policy"] = {
        "discovery_complete": True,
        "required_commands": [{
            "key": {"command": "pytest -q", "working_directory": "."},
            "name": "Tests",
            "kind": "test",
            "evidence_ref_ids": ["evidence.flow"],
        }],
        "incomplete_reasons": [],
        "evidence_ref_ids": ["evidence.flow"],
    }
    flow = payload["production_flows"][0]
    flow.update({
        "service": [{
            "kind": "service",
            "path": "app/services/deploy.py",
            "symbol": "deploy",
            "evidence_ref_ids": ["evidence.flow"],
        }],
        "persistence": [{
            "kind": "persistence",
            "path": "app/models/deployment.py",
            "symbol": "save",
            "evidence_ref_ids": ["evidence.flow"],
        }],
        "compiler": [{
            "kind": "compiler",
            "path": "app/services/deploy_compiler.py",
            "symbol": "compile_result",
            "evidence_ref_ids": ["evidence.flow"],
        }],
        "output": {
            "kind": "output",
            "path": "app/api/deploy.py",
            "symbol": "DeploymentResponse",
            "evidence_ref_ids": ["evidence.flow"],
        },
        "proof": "test_verified",
        "complete": True,
        "gaps": [],
        "evidence_ref_ids": ["evidence.flow", "evidence.test-run"],
    })
    payload["durable_facts"] = [{
        "id": "fact.deploy-boundary",
        "identity_key": "decision:deploy-boundary",
        "kind": "decision",
        "title": "Deployment boundary",
        "statement": "Deployment idempotency is enforced at persistence.",
        "evidence_tier": "code_observed",
        "promotion_reason": "mechanically_verified",
        "evidence_ref_ids": ["evidence.flow"],
    }]
    payload["quality_report"]["score"] = 95
    payload["quality_report"]["semantic_coverage_score"] = 95

    artifact = _validate(payload)

    assert artifact.quality_report.semantic_coverage_score == 95
