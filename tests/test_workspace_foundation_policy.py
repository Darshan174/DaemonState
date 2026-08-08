from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.workspace_foundation import (
    CommandKind,
    RequiredCommandKey,
    RequiredVerificationCommand,
    VerificationPolicy,
    WorkspaceFoundationArtifact,
)
from app.services.context_compiler import _workspace_repository_inventory
from app.services.repo_indexer import IndexedFile, RepoFrame, RepoIndexer
from app.services.workspace_foundation import compile_workspace_foundation
from app.services.workspace_foundation_adapters import collect_required_check_policy
from app.services.workspace_foundation_renderer import render_workspace_foundation_markdown
from app.services.workspace_foundation_verification import WorkspaceVerificationObservation


def _frame(root: Path, *paths: str) -> RepoFrame:
    indexed_files: list[IndexedFile] = []
    for path in paths:
        raw = (root / path).read_bytes()
        indexed_files.append(
            IndexedFile(
                path=path,
                language="yaml",
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
            )
        )
    return RepoFrame(
        repo_path=str(root),
        branch="main",
        base_commit="base",
        head_commit="head",
        dirty=False,
        changed_files=[],
        untracked_files=[],
        indexed_files=indexed_files,
        package_manifests={},
        recent_commits=[],
        test_files=[],
        manifest_files=[],
        env_files=[],
        last_indexed_at="2026-08-06T00:00:00Z",
        snapshot_fingerprint="snapshot",
    )


def _write_workflow(root: Path, name: str, text: str) -> str:
    path = f".github/workflows/{name}"
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return path


def _observation(
    command: str,
    cwd: str,
    *,
    exit_code: int = 0,
    discriminator: str = "1",
) -> WorkspaceVerificationObservation:
    digest_digit = str(int(discriminator) % 10)
    return WorkspaceVerificationObservation(
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        observed_at=datetime(2026, 8, 6, 8, 30, tzinfo=timezone.utc),
        timed_out=False,
        payload_sha256=digest_digit * 64,
        output_sha256=str((int(discriminator) + 1) % 10) * 64,
        evidence_rule="local_harness_verification_observation.v1",
        evidence_id=f"run-observation:{discriminator}",
        agent_run_id="run",
        run_observation_id=f"verification-{discriminator}",
        outcome_observation_id="outcome",
    )


def test_policy_contract_keys_commands_by_command_and_working_directory() -> None:
    required = RequiredVerificationCommand(
        key=RequiredCommandKey(command="pytest -q", working_directory="backend"),
        name="Tests",
        kind=CommandKind.TEST,
        evidence_ref_ids=("evidence.workflow",),
    )
    incomplete = VerificationPolicy(
        discovery_complete=False,
        required_commands=(required,),
        incomplete_reasons=("unsupported workflow",),
        evidence_ref_ids=("evidence.workflow",),
    )

    assert incomplete.discovery_complete is False
    assert incomplete.required_commands[0].key.working_directory == "backend"
    assert VerificationPolicy().required_commands == ()
    with pytest.raises(ValidationError, match="incomplete reason"):
        VerificationPolicy(discovery_complete=True)
    with pytest.raises(ValidationError, match="duplicate command keys"):
        VerificationPolicy(
            discovery_complete=True,
            required_commands=(required, required),
            incomplete_reasons=(),
            evidence_ref_ids=("evidence.workflow",),
        )


def test_github_actions_policy_extracts_only_unconditional_checks(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
on: [push]
defaults:
  run:
    working-directory: services/api
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - name: Install dependencies
        run: pip install -e '.[dev]'
      - name: Lint
        run: ruff check app tests
      - name: Frontend tests
        working-directory: frontend
        run: npm test
      - name: Build frontend
        working-directory: frontend
        run: |
          npm run build
          cmp ../LICENSE dist/LICENSE
      - name: Optional tests
        if: github.ref == 'refs/heads/main'
        run: pytest optional/
      - name: Allowed failure
        continue-on-error: true
        run: pytest experimental/
      - name: Deploy release
        run: daemonstate db deploy
""",
    )

    policy = collect_required_check_policy(_frame(tmp_path, path))

    assert policy.discovery_complete is True
    assert policy.incomplete_reasons == ()
    assert [(item.command, item.working_directory) for item in policy.required_commands] == [
        ("ruff check app tests", "services/api"),
        ("npm test", "frontend"),
        ("npm run build\ncmp ../LICENSE dist/LICENSE", "frontend"),
    ]
    assert all(item.required for item in policy.required_commands)
    assert all(item.source.path == path for item in policy.required_commands)
    assert not any("install" in item.command.casefold() for item in policy.required_commands)
    assert not any("deploy" in item.command.casefold() for item in policy.required_commands)


def test_unsupported_workflow_retains_checks_from_exact_supported_source(
    tmp_path: Path,
) -> None:
    valid = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Tests
        run: pytest -q
""",
    )
    malformed = _write_workflow(
        tmp_path,
        "broken.yml",
        "jobs:\n  test:\n    steps: [\n",
    )

    policy = collect_required_check_policy(_frame(tmp_path, valid, malformed))

    assert policy.discovery_complete is False
    assert [(item.command, item.working_directory) for item in policy.required_commands] == [
        ("pytest -q", ".")
    ]
    assert policy.incomplete_reasons == ("yaml_parse_unsupported:.github/workflows/broken.yml",)


def test_hash_mismatch_and_truncation_fail_closed(tmp_path: Path, monkeypatch) -> None:
    from app.services import workspace_foundation_adapters as adapters

    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Tests
        run: pytest -q
""",
    )
    frame = _frame(tmp_path, path)
    (tmp_path / path).write_text("name: changed\njobs: {}\n", encoding="utf-8")

    mismatch = collect_required_check_policy(frame)

    assert mismatch.discovery_complete is False
    assert mismatch.required_commands == ()
    assert mismatch.incomplete_reasons == (f"workflow_snapshot_mismatch:{path}",)

    frame = _frame(tmp_path, path)
    monkeypatch.setattr(adapters, "MAX_GITHUB_WORKFLOW_BYTES", 4)
    truncated = collect_required_check_policy(frame)
    assert truncated.discovery_complete is False
    assert truncated.required_commands == ()
    assert truncated.incomplete_reasons == (f"workflow_truncated:{path}",)


@pytest.mark.parametrize(
    ("workflow", "reason"),
    [
        (
            """name: CI
shared: &shared
  run: pytest -q
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - *shared
""",
            "yaml_alias_or_anchor_unsupported",
        ),
        (
            """name: CI
jobs:
  test:
    uses: owner/repository/.github/workflows/tests.yml@main
""",
            "reusable_workflow_job_unsupported:test",
        ),
        (
            """name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Tests
        run: pytest ${{ matrix.path }}
""",
            "dynamic_check_command_unsupported:test:1",
        ),
        (
            """name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Tests
        name: Duplicate
        run: pytest -q
""",
            "yaml_parse_unsupported",
        ),
    ],
)
def test_unsupported_required_check_shapes_are_explicitly_incomplete(
    tmp_path: Path,
    workflow: str,
    reason: str,
) -> None:
    path = _write_workflow(tmp_path, "ci.yml", workflow)

    policy = collect_required_check_policy(_frame(tmp_path, path))

    assert policy.discovery_complete is False
    assert policy.required_commands == ()
    assert policy.incomplete_reasons == (f"{reason}:{path}",)


def test_no_workflow_directory_is_a_complete_empty_policy(tmp_path: Path) -> None:
    policy = collect_required_check_policy(_frame(tmp_path))

    assert policy.discovery_complete is True
    assert policy.required_commands == ()
    assert policy.sources == ()
    assert policy.incomplete_reasons == ()


def test_complete_required_policy_with_every_exact_check_passing_reports_passing(
    tmp_path: Path,
) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: Python tests
        run: pytest -q
      - name: Frontend tests
        working-directory: frontend
        run: npm test
""",
    )
    frame = _frame(tmp_path, path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
        verification_observations=(
            _observation("pytest -q", ".", discriminator="1"),
            _observation("npm test", "frontend", discriminator="2"),
        ),
    )

    assert artifact.verification_policy.discovery_complete is True
    assert [
        (item.key.command, item.key.working_directory)
        for item in artifact.verification_policy.required_commands
    ] == [("pytest -q", "."), ("npm test", "frontend")]
    assert artifact.quality_report.repository_health == "passing"
    evidence = {item.id: item for item in artifact.evidence_references}
    assert {
        evidence[reference_id].tier.value
        for reference_id in artifact.verification_policy.evidence_ref_ids
    } == {"code_observed"}

    rendered = render_workspace_foundation_markdown(artifact)
    assert "required-check policy `complete`/`github_actions`" in rendered
    assert "`2` required, `2` passed, `0` failed, `0` unverified" in rendered


def test_complete_required_policy_with_one_missing_result_remains_unknown(
    tmp_path: Path,
) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: Python tests
        run: pytest -q
      - name: Lint
        run: ruff check app tests
""",
    )
    frame = _frame(tmp_path, path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
        verification_observations=(
            _observation("pytest -q", ".", discriminator="3"),
        ),
    )

    assert artifact.quality_report.repository_health == "unknown"
    rendered = render_workspace_foundation_markdown(artifact)
    assert "`2` required, `1` passed, `0` failed, `1` unverified" in rendered


def test_incomplete_policy_with_every_known_check_passing_remains_unknown(
    tmp_path: Path,
) -> None:
    valid = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: Python tests
        run: pytest -q
""",
    )
    malformed = _write_workflow(tmp_path, "broken.yml", "jobs:\n  test:\n    steps: [\n")
    frame = _frame(tmp_path, valid, malformed)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
        verification_observations=(
            _observation("pytest -q", ".", discriminator="4"),
        ),
    )

    assert artifact.verification_policy.discovery_complete is False
    assert artifact.quality_report.repository_health == "unknown"
    rendered = render_workspace_foundation_markdown(artifact)
    assert "required-check policy `incomplete`" in rendered
    assert f"yaml_parse_unsupported:{malformed}" in rendered


def test_required_check_matching_preserves_and_requires_exact_working_directory(
    tmp_path: Path,
) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: Frontend tests
        working-directory: frontend
        run: npm test
""",
    )
    frame = _frame(tmp_path, path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
        verification_observations=(
            _observation("npm test", ".", discriminator="5"),
        ),
    )

    assert artifact.quality_report.repository_health == "unknown"
    commands = {
        (item.command, item.working_directory): item.verification.status.value
        for item in artifact.commands
    }
    assert commands[("npm test", "frontend")] == "unverified"
    assert commands[("npm test", ".")] == "passed"


def test_current_ad_hoc_failure_overrides_passing_required_policy(tmp_path: Path) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: Python tests
        run: pytest -q
""",
    )
    frame = _frame(tmp_path, path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
        verification_observations=(
            _observation("pytest -q", ".", discriminator="6"),
            _observation("ruff check app", ".", exit_code=1, discriminator="7"),
        ),
    )

    assert artifact.quality_report.repository_health == "failing"


def test_missing_workflow_directory_conflicting_with_index_fails_closed(
    tmp_path: Path,
) -> None:
    path = _write_workflow(
        tmp_path,
        "ci.yml",
        "name: CI\njobs: {}\n",
    )
    frame = _frame(tmp_path, path)
    (tmp_path / path).unlink()
    (tmp_path / ".github" / "workflows").rmdir()

    policy = collect_required_check_policy(frame)

    assert policy.discovery_complete is False
    assert policy.incomplete_reasons == (f"workflow_snapshot_mismatch:{path}",)


def test_missing_yaml_parser_is_explicitly_incomplete(tmp_path: Path, monkeypatch) -> None:
    from app.services import workspace_foundation_adapters as adapters

    path = _write_workflow(
        tmp_path,
        "ci.yml",
        """name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Tests
        run: pytest -q
""",
    )
    monkeypatch.setattr(adapters, "yaml", None)

    policy = collect_required_check_policy(_frame(tmp_path, path))

    assert policy.discovery_complete is False
    assert policy.required_commands == ()
    assert policy.incomplete_reasons == (f"yaml_parser_unavailable:{path}",)


def test_policy_evidence_participates_in_artifact_provenance_validation(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas verifies repository state.\n",
        encoding="utf-8",
    )
    frame = asyncio.run(RepoIndexer(None).inspect_repo(tmp_path))
    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=None,
    )
    false_positive = artifact.model_dump(mode="json")
    false_positive["quality_report"]["repository_health"] = "passing"
    with pytest.raises(
        ValidationError,
        match="passing repository health requires",
    ):
        WorkspaceFoundationArtifact.from_payload(false_positive)

    payload = artifact.model_dump(mode="json")
    payload["evidence_references"].append(
        {
            "id": "evidence.workflow",
            "tier": "code_observed",
            "source_sha256": "a" * 64,
            "path": ".github/workflows/ci.yml",
            "rule": "github_actions_required_checks.v1",
        }
    )
    payload["verification_policy"] = {
        "source": "github_actions",
        "discovery_complete": True,
        "required_commands": [
            {
                "key": {"command": "pytest -q", "working_directory": "."},
                "name": "Tests",
                "kind": "test",
                "evidence_ref_ids": ["evidence.workflow"],
            }
        ],
        "incomplete_reasons": [],
        "evidence_ref_ids": ["evidence.workflow"],
    }

    validated = WorkspaceFoundationArtifact.from_payload(payload)
    assert validated.verification_policy.discovery_complete is True
    tampered = validated.model_dump(mode="json")
    tampered["verification_policy"]["required_commands"][0]["evidence_ref_ids"] = [
        "evidence.missing"
    ]
    tampered["verification_policy"]["evidence_ref_ids"] = ["evidence.missing"]
    with pytest.raises(ValidationError, match="references unknown evidence"):
        WorkspaceFoundationArtifact.from_payload(tampered)
