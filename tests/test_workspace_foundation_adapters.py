from __future__ import annotations

from app.services.context_compiler import (
    _empty_repo_frame,
    _workspace_repository_inventory,
)
from app.services.workspace_foundation import compile_workspace_foundation
from app.services.workspace_foundation_adapters import (
    _engineering_knowledge_document_priority,
    _engineering_knowledge_kind,
)


def test_inventory_only_audiences_are_not_promoted_without_a_source() -> None:
    frame = _empty_repo_frame()
    inventory = _workspace_repository_inventory(frame)
    inventory["readme"] = {
        "path": "",
        "title": "RemoteOnly",
        "summary": "Remote workspace",
        "audiences": ["Developers"],
    }

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=inventory,
        durable_foundation=None,
    )

    assert artifact.product_profile.name == "RemoteOnly"
    assert artifact.product_profile.intended_users == ()
    assert "purpose as unknown" in artifact.product_profile.summary
    assert not any(
        claim.kind.value == "audience" for claim in artifact.product_profile.claims
    )


def test_repository_rule_and_style_headings_are_source_scoped_conventions() -> None:
    assert _engineering_knowledge_document_priority("CONTRIBUTING.md") == 1
    assert _engineering_knowledge_kind("Product Rules") == "convention"
    assert _engineering_knowledge_kind("Code Style") == "convention"
    assert _engineering_knowledge_kind("Engineering Rules") == "convention"
