from __future__ import annotations

from collections import Counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models import ContextArtifactClaim, ContextCandidateEvaluation, Workspace
from app.schemas.context_quality import (
    ClaimCriticality,
    ContextClaimEnvelope,
    ContextDecision,
    ContextKind,
)
from app.services.context_quality_policies import evaluate_context_candidate


def _background_metadata() -> dict:
    return {
        "context_role": "background_only",
        "objective_independent": True,
        "copy_ready": True,
        "hash_valid": True,
        "permissions_current": True,
        "snapshot_current": False,
        "required_dependencies_complete": False,
        "durable_fact_count": 0,
        "verification_complete": False,
        "semantic_coverage_score": 50,
    }


@pytest.mark.parametrize("kind", [ContextKind.SESSION, ContextKind.WORKSPACE])
def test_incomplete_historical_background_is_available_with_limitations(kind):
    result = evaluate_context_candidate(
        context_kind=kind,
        candidate_claims=(),
        rendered_text=(
            "Historical background. Objective unresolved. Referenced image unavailable. "
            "Captured before newer changes. Awaiting user instruction."
        ),
        metadata=_background_metadata(),
    )
    assert result.decision is ContextDecision.PROMOTE
    assert not result.hard_failures
    assert "CURRENT_STATE_BOUND_TO_OLD_SNAPSHOT" in result.warnings
    if kind is ContextKind.SESSION:
        assert {"USER_OBJECTIVE_MISSING", "REQUIRED_DEPENDENCY_MISSING"} <= set(
            result.warnings
        )
    else:
        assert "CURRENT_VERIFICATION_INCOMPLETE" in result.warnings


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("hash_valid", False, "HASH_OR_LINEAGE_FAILURE"),
        ("permissions_current", False, "PERMISSION_SNAPSHOT_STALE"),
        ("candidate_quarantined", True, "CANDIDATE_QUARANTINED"),
        ("copy_ready", False, "UPSTREAM_CONTEXT_NOT_COPY_READY"),
    ],
)
def test_background_limitations_never_override_integrity_failures(field, value, failure):
    result = evaluate_context_candidate(
        context_kind=ContextKind.SESSION,
        candidate_claims=(),
        rendered_text="Historical background. Awaiting user instruction.",
        metadata={**_background_metadata(), field: value},
    )
    assert result.decision is ContextDecision.REJECT
    assert failure in result.hard_failures


def test_workspace_background_still_rejects_cross_scope_content():
    claim = ContextClaimEnvelope(
        stable_id="session:foreign",
        section="state",
        kind="progress",
        statement="A different session's work.",
        scope=ContextKind.SESSION,
        authority="agent_report",
        truth_state="reported",
        criticality=ClaimCriticality.HIGH,
    )
    result = evaluate_context_candidate(
        context_kind=ContextKind.WORKSPACE,
        candidate_claims=(claim,),
        rendered_text=claim.statement,
        metadata=_background_metadata(),
    )
    assert result.decision is ContextDecision.REJECT
    assert "SESSION_CONTENT_IN_WORKSPACE" in result.hard_failures


def test_strict_snapshot_contract_is_not_relaxed_without_background_role():
    metadata = _background_metadata()
    metadata.pop("context_role")
    result = evaluate_context_candidate(
        context_kind=ContextKind.WORKSPACE,
        candidate_claims=(),
        rendered_text="Current repository state",
        metadata=metadata,
    )
    assert "CURRENT_STATE_BOUND_TO_OLD_SNAPSHOT" in result.hard_failures
    assert result.decision is ContextDecision.REJECT


@pytest.mark.parametrize("quoted", [True, False])
def test_historical_action_headings_are_context_only_when_quoted(quoted):
    historical = "## Exact next action\nDeploy the old prototype."
    if quoted:
        historical = "\n".join(f"> {line}" for line in historical.splitlines())
    result = evaluate_context_candidate(
        context_kind=ContextKind.SESSION,
        candidate_claims=(),
        rendered_text=f"Historical proposal:\n{historical}\nAwaiting user instruction.",
        metadata=_background_metadata(),
    )
    if quoted:
        assert result.decision is ContextDecision.PROMOTE
    else:
        assert result.decision is ContextDecision.REJECT
        assert "INFERRED_ACTION_OR_ACCEPTANCE_PRESENT" in result.hard_failures


async def test_workspace_api_activates_unverified_background_with_multiple_boundaries(
    client, db_session, tmp_path,
):
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\nAtlas compiles reports for small teams.\n\n"
        "Atlas is not a hosting platform.\n\n"
        "Atlas is not an autonomous agent.\n\n"
        "## Capabilities\n| Capability | What it does |\n|---|---|\n"
        "| Report | Creates a report through POST /reports. |\n",
        encoding="utf-8",
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.post('/reports')\ndef report():\n    return {'report': 'ready'}\n",
        encoding="utf-8",
    )
    workspace = Workspace(id=uuid4(), name="Atlas", slug=f"atlas-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.commit()
    response = await client.post("/api/context/prepare", json={
        "workspace_id": str(workspace.id),
        "repo_path": str(tmp_path),
        "mode": "project_snapshot",
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    foundation = payload["manifest"]["workspace_foundation"]
    assert sum(item["kind"] == "boundary" for item in foundation["product_profile"]["claims"]) == 2
    assert foundation["repository_state"]["snapshot_fingerprint"] == (
        payload["manifest"]["repo_state"]["snapshot_fingerprint"]
    )
    activation = payload["quality_control"]
    assert activation["copy_allowed"] is True
    assert activation["status"] == "active"
    claims = list(await db_session.scalars(select(ContextArtifactClaim).where(
        ContextArtifactClaim.candidate_id == UUID(activation["candidate_id"])
    )))
    assert max(Counter(item.claim_key for item in claims).values()) == 1
    evaluation = await db_session.get(ContextCandidateEvaluation, UUID(activation["evaluation_id"]))
    assert evaluation is not None
    assert "DURABLE_PROJECT_KNOWLEDGE_EMPTY" in evaluation.warnings_json
    assert "unknown" in payload["markdown"].lower()
