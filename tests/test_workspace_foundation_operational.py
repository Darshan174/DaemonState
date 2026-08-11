from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.workspace_foundation import (
    ArchitectureComponent,
    Capability,
    CommandVerificationStatus,
    DurableKnowledgeFact,
    EvidenceTier,
    ImplementationTrace,
    RepositoryChange,
    RepositoryState,
    WorkspaceCommand,
)
from app.services.workspace_foundation_operational import (
    compile_change_intents,
    compile_durable_facts,
    compile_production_flows,
    compile_verification_runs,
    operational_lane_statuses,
)


_SNAPSHOT = "a" * 64
_OUTPUT = "b" * 64


def _capability() -> Capability:
    return Capability.model_validate({
        "id": "capability.prepare",
        "name": "Prepare context",
        "summary": "Prepare a portable continuation context.",
        "state": "partial",
        "assessment": {
            "declaration_status": "declared",
            "implementation_coverage": "entrypoint_only",
            "verification_status": "absent",
            "production_surface_count": 1,
        },
        "evidence_ref_ids": ["ev.capability"],
    })


def test_operational_lanes_project_exact_snapshot_without_inventing_intent() -> None:
    capability = _capability()
    component = ArchitectureComponent.model_validate({
        "id": "component.desktop",
        "kind": "application",
        "name": "Desktop overlay",
        "responsibility": "Stages continuation context in a desktop composer.",
        "repository_paths": ["desktop/macos"],
        "evidence_ref_ids": ["ev.component"],
    })
    change = RepositoryChange.model_validate({
        "path": "desktop/macos/Overlay.swift",
        "kind": "modified",
        "role": "implementation",
        "capability_ids": [capability.id],
        "component_ids": [component.id],
        "related_test_paths": ["desktop/macos/Tests/OverlayTests.swift"],
        "evidence_ref_ids": ["ev.change"],
    })
    repository = RepositoryState.model_validate({
        "repository_name": "atlas",
        "branch": "main",
        "head_commit": "c" * 40,
        "dirty": True,
        "captured_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        "snapshot_fingerprint": _SNAPSHOT,
        "changed_path_count": 1,
        "changes": [change],
        "evidence_ref_ids": ["ev.repo"],
    })
    intents = compile_change_intents(
        repository,
        capabilities=(capability,),
        components=(component,),
    )

    assert len(intents) == 1
    assert intents[0].snapshot == _SNAPSHOT
    assert intents[0].capability == "Prepare context"
    assert intents[0].changed_paths == (change.path,)
    assert intents[0].affected_tests == (
        "desktop/macos/Tests/OverlayTests.swift",
    )
    assert intents[0].before_behavior is None
    assert intents[0].after_behavior is None
    assert intents[0].completed.value == "unknown"
    assert intents[0].remaining_status.value == "unknown"

    statuses = operational_lane_statuses(
        repository_state=repository,
        production_flows=(),
        verification_runs=(),
        change_intents=intents,
        durable_facts=(),
    )
    assert statuses["change_group_count"] == 1
    assert statuses["change_intent_known"] is False


def test_entrypoint_trace_becomes_partial_production_flow_with_named_gaps() -> None:
    capability = _capability()
    trace = ImplementationTrace.model_validate({
        "id": "trace.prepare",
        "name": "Prepare context",
        "summary": "Exact route owner and local call.",
        "kind": "production_call_flow",
        "coverage": "partial",
        "capability_ids": [capability.id],
        "hops": [
            {
                "source_path": "app/api/context.py",
                "target_path": "app/api/context.py",
                "relation": "owns",
                "source_symbol": "POST /context/prepare",
                "target_symbol": "prepare_context",
                "evidence_ref_ids": ["ev.route"],
            },
            {
                "source_path": "app/api/context.py",
                "target_path": "app/services/context_compiler.py",
                "relation": "calls",
                "source_symbol": "prepare_context",
                "target_symbol": "compile_context_pack",
                "evidence_ref_ids": ["ev.call"],
            },
        ],
        "gaps": ["Runtime execution remains unknown."],
    })

    flows = compile_production_flows(
        (trace,),
        capabilities=(capability,),
        snapshot=_SNAPSHOT,
    )

    assert len(flows) == 1
    flow = flows[0]
    assert flow.snapshot == _SNAPSHOT
    assert flow.entrypoint.path == "app/api/context.py"
    assert [stage.path for stage in flow.service] == ["app/api/context.py"]
    assert [stage.path for stage in flow.compiler] == [
        "app/services/context_compiler.py",
    ]
    assert flow.complete is False
    assert any("Persistence" in gap for gap in flow.gaps)
    assert any("output" in gap for gap in flow.gaps)


def test_out_of_order_hops_never_become_complete_production_flow() -> None:
    capability = _capability()
    paths = (
        "app/api/context.py",
        "app/services/context.py",
        "app/services/context_compiler.py",
        "app/models/context.py",
        "frontend/src/ContextView.tsx",
    )
    trace = ImplementationTrace.model_validate({
        "id": "trace.out-of-order",
        "name": "Out-of-order context trace",
        "summary": "The observed calls reach all named layers in the wrong order.",
        "kind": "production_call_flow",
        "coverage": "partial",
        "capability_ids": [capability.id],
        "hops": [
            {
                "source_path": paths[index],
                "target_path": paths[index + 1],
                "relation": "owns" if index == 0 else "calls",
                "evidence_ref_ids": [f"ev.hop.{index}"],
            }
            for index in range(len(paths) - 1)
        ],
        "gaps": ["Runtime execution remains unknown."],
    })

    flow = compile_production_flows(
        (trace,),
        capabilities=(capability,),
        snapshot=_SNAPSHOT,
    )[0]

    assert flow.service and flow.persistence and flow.compiler and flow.output
    assert flow.complete is False
    assert any("do not follow" in gap for gap in flow.gaps)


def test_executed_command_and_promoted_fact_enter_first_class_v2_lanes() -> None:
    command = WorkspaceCommand.model_validate({
        "id": "command.tests",
        "name": "Focused tests",
        "purpose": "Verify the exact affected surface.",
        "kind": "test",
        "origin": "observed",
        "command": "pytest -q tests/test_context.py",
        "verification": {
            "status": CommandVerificationStatus.PASSED,
            "verified_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            "exit_code": 0,
            "output_sha256": _OUTPUT,
            "summary": "12 tests passed.",
            "evidence_ref_ids": ["ev.run"],
        },
        "evidence_ref_ids": ["ev.run"],
    })
    runs = compile_verification_runs((command,), snapshot=_SNAPSHOT)
    assert len(runs) == 1
    assert runs[0].snapshot == _SNAPSHOT
    assert runs[0].result.value == "passed"
    assert runs[0].failures == ()

    legacy = DurableKnowledgeFact.model_validate({
        "id": "knowledge.decision",
        "identity_key": "decision:portable-context",
        "kind": "decision",
        "title": "Portable context",
        "statement": "Continuation artifacts remain provider-neutral.",
        "evidence_tier": EvidenceTier.HUMAN_CONFIRMED,
        "evidence_ref_ids": ["ev.decision"],
    })
    facts = compile_durable_facts((legacy,))
    assert len(facts) == 1
    assert facts[0].id.startswith("fact.")
    assert facts[0].promotion_reason.value == "human_confirmed"


def test_unverified_and_stale_commands_never_become_current_runs() -> None:
    commands = tuple(
        WorkspaceCommand.model_validate({
            "id": f"command.{status}",
            "name": status,
            "purpose": "Historical command state.",
            "kind": "test",
            "origin": "declared",
            "command": f"pytest -q {status}",
            "verification": (
                {"status": "unverified"}
                if status == "unverified"
                else {
                    "status": "stale",
                    "verified_at": datetime(2026, 8, 9, tzinfo=timezone.utc),
                    "exit_code": 0,
                    "output_sha256": _OUTPUT,
                    "summary": "Observed against another snapshot.",
                    "evidence_ref_ids": ["ev.stale"],
                }
            ),
            "evidence_ref_ids": ["ev.command"],
        })
        for status in ("unverified", "stale")
    )

    assert compile_verification_runs(commands, snapshot=_SNAPSHOT) == ()
