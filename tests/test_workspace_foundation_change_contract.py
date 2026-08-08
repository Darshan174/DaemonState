from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.workspace_foundation import (
    RepositoryChange,
    RepositoryChangeCompletionStatus,
    RepositoryChangeKind,
    RepositoryChangeRemainingWorkStatus,
    RepositoryChangeStatement,
    WorkspaceFoundationArtifact,
)
from app.services.workspace_foundation_renderer import (
    render_workspace_foundation_markdown,
)


_PRODUCT_SHA = "1" * 64
_CHANGE_SHA = "2" * 64
_PLAN_SHA = "3" * 64
_SNAPSHOT_SHA = "4" * 64


def _change(**updates: object) -> RepositoryChange:
    values: dict[str, object] = {
        "path": "app/services/deploy.py",
        "kind": RepositoryChangeKind.MODIFIED,
        "evidence_ref_ids": ("ev.change",),
    }
    values.update(updates)
    return RepositoryChange.model_validate(values)


def _artifact(
    change: RepositoryChange,
    *,
    plan_tier: str = "documentation_stated",
) -> WorkspaceFoundationArtifact:
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    return WorkspaceFoundationArtifact.from_payload(
        {
            "compiled_at": now,
            "compiler_version": "workspace_foundation_compiler.test",
            "product_profile": {
                "name": "Atlas",
                "summary": "Atlas deploys applications.",
                "evidence_ref_ids": ["ev.product"],
            },
            "evidence_references": [
                {
                    "id": "ev.product",
                    "tier": "documentation_stated",
                    "source_sha256": _PRODUCT_SHA,
                    "path": "README.md",
                },
                {
                    "id": "ev.change",
                    "tier": "code_observed",
                    "source_sha256": _CHANGE_SHA,
                    "rule": "git_status_entry.v1",
                },
                {
                    "id": "ev.plan",
                    "tier": plan_tier,
                    "source_sha256": _PLAN_SHA,
                    "path": "docs/deploy-plan.md",
                },
            ],
            "repository_state": {
                "repository_name": "atlas",
                "branch": "main",
                "head_commit": "a" * 40,
                "dirty": True,
                "captured_at": now,
                "snapshot_fingerprint": _SNAPSHOT_SHA,
                "changed_path_count": 1,
                "changes": [change.model_dump(mode="json")],
                "evidence_ref_ids": ["ev.change"],
            },
            "quality_report": {
                "status": "pass",
                "publishable": True,
                "copy_ready": True,
                "score": 100,
                "semantic_coverage_score": 100,
            },
        }
    )


def test_change_purpose_contract_defaults_fail_closed_to_unknown() -> None:
    change = _change()

    assert change.intended_behavior is None
    assert change.completion_status is RepositoryChangeCompletionStatus.UNKNOWN
    assert change.completion_evidence_ref_ids == ()
    assert (
        change.remaining_work_status
        is RepositoryChangeRemainingWorkStatus.UNKNOWN
    )
    assert change.remaining_work == ()
    assert change.remaining_work_evidence_ref_ids == ()

    rendered = render_workspace_foundation_markdown(_artifact(change))
    assert "Intended behavior: unknown" in rendered
    assert "Completion status: `unknown`" in rendered
    assert "Remaining work: unknown" in rendered


def test_known_change_statuses_require_structurally_consistent_evidence() -> None:
    with pytest.raises(ValidationError, match="known completion status requires evidence"):
        _change(completion_status="in_progress")

    with pytest.raises(ValidationError, match="unknown completion status forbids evidence"):
        _change(completion_evidence_ref_ids=("ev.plan",))

    with pytest.raises(ValidationError, match="identified remaining work requires"):
        _change(
            remaining_work_status="identified",
            remaining_work_evidence_ref_ids=("ev.plan",),
        )

    with pytest.raises(ValidationError, match="none-stated remaining work"):
        _change(
            remaining_work_status="none_stated",
            remaining_work=(
                RepositoryChangeStatement(
                    statement="Run the migration.",
                    evidence_ref_ids=("ev.plan",),
                ),
            ),
            remaining_work_evidence_ref_ids=("ev.plan",),
        )


def test_change_purpose_never_accepts_git_or_syntax_evidence() -> None:
    change = _change(
        intended_behavior=RepositoryChangeStatement(
            statement="Make deploys atomic.",
            evidence_ref_ids=("ev.change",),
        )
    )

    with pytest.raises(
        ValidationError,
        match="intended behavior requires documentation-stated or human-confirmed evidence",
    ):
        _artifact(change)


def test_renderer_shows_bounded_source_backed_change_contract() -> None:
    remaining_work = tuple(
        RepositoryChangeStatement(
            statement=f"Remaining step {index}.",
            evidence_ref_ids=("ev.plan",),
        )
        for index in range(1, 5)
    )
    change = _change(
        intended_behavior=RepositoryChangeStatement(
            statement="Make deploy submission atomic.",
            evidence_ref_ids=("ev.plan",),
        ),
        completion_status="in_progress",
        completion_evidence_ref_ids=("ev.plan",),
        remaining_work_status="identified",
        remaining_work=remaining_work,
        remaining_work_evidence_ref_ids=("ev.plan",),
    )

    rendered = render_workspace_foundation_markdown(_artifact(change))

    assert "Intended behavior (source-backed): Make deploy submission atomic." in rendered
    assert "Completion status (source-backed): `in_progress`" in rendered
    assert "Remaining work (source-backed; `identified`)" in rendered
    assert "Remaining step 1." in rendered
    assert "Remaining step 3." in rendered
    assert "Remaining step 4." not in rendered
    assert "1 additional source-backed remaining-work item(s) omitted" in rendered


def test_explicit_none_stated_is_not_rendered_as_independent_proof() -> None:
    change = _change(
        remaining_work_status="none_stated",
        remaining_work_evidence_ref_ids=("ev.plan",),
    )

    rendered = render_workspace_foundation_markdown(_artifact(change))

    assert "Remaining work (source-backed): `none_stated`" in rendered
    assert "not independent completion proof" in rendered
