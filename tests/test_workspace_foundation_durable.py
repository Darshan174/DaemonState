from __future__ import annotations

from uuid import uuid4

from app.schemas.continuation_execution import (
    ProjectContextItem,
    ProjectContextKind,
    ProjectContextProvenance,
    ProjectEvidenceLevel,
    ProjectFoundationSection,
    ProjectFoundationSnapshot,
)
from app.services.context_compiler import _workspace_repository_inventory
from app.services.project_foundation import CompiledProjectFoundation
from app.services.repo_indexer import RepoIndexer
from app.services.workspace_foundation import compile_workspace_foundation


async def test_malformed_single_source_corroboration_fails_closed(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    provenance = ProjectContextProvenance(
        source_document_id="source-1",
        evidence_span_id="span-1",
        source_type="agent_session",
        source_revision_number=1,
        source_content_sha256="a" * 64,
        evidence_text_sha256="b" * 64,
    )
    malformed = CompiledProjectFoundation(
        snapshot=ProjectFoundationSnapshot(
            workspace_id=uuid4(),
            repository_fingerprint="f" * 64,
            included_fact_count=1,
            source_document_count=1,
        ),
        items=(
            ProjectContextItem(
                id="P1",
                kind=ProjectContextKind.LEARNING,
                section=ProjectFoundationSection.ARCHITECTURE,
                title="Claimed corroboration",
                statement="A single source must not become corroborated knowledge.",
                identity_key="learning:single-source",
                evidence_level=ProjectEvidenceLevel.CORROBORATED,
                provenance_refs=(provenance,),
                corroboration_count=2,
            ),
        ),
    )
    frame = await RepoIndexer(None).inspect_repo(tmp_path)

    artifact = compile_workspace_foundation(
        frame=frame,
        inventory=_workspace_repository_inventory(frame),
        durable_foundation=malformed,
    )

    assert artifact.durable_knowledge == ()
