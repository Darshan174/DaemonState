from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.config import settings
from app.models import SourceDocument, Workspace
from app.sync.session_resolvers import (
    ResolvedSession,
    SessionDiscoveryResult,
    discover_local_ai_sessions,
)


def test_codex_discovery_reads_every_local_session_without_ids(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "18"
    sessions_dir.mkdir(parents=True)
    for index in (1, 2):
        session_id = f"session-{index}"
        path = sessions_dir / f"rollout-{index}.jsonl"
        path.write_text(
            "\n".join([
                json.dumps({
                    "type": "session_meta",
                    "timestamp": f"2026-07-18T0{index}:00:00Z",
                    "payload": {
                        "id": session_id,
                        "cwd": f"/workspace/product-{index}",
                        "model": "gpt-test",
                    },
                }),
                json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "text", "text": f"Plan product {index} launch"}],
                    },
                }),
            ]),
            encoding="utf-8",
        )

    monkeypatch.setattr(settings, "codex_home", str(codex_home))
    result = discover_local_ai_sessions(["codex"])[0]

    assert result.error is None
    assert {item.session_id for item in result.sessions} == {"session-1", "session-2"}
    assert all(item.metadata["topics"] for item in result.sessions)


async def test_library_sync_discovers_ingests_and_groups_sessions(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Automatic session library",
        slug=f"automatic-session-library-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.commit()

    resolved = [
        ResolvedSession(
            connector_type="codex",
            session_id="codex-alpha-beta",
            content=(
                "[USER]\nPlan billing for Alpha.\n\n"
                "[ASSISTANT]\nI mapped the flow.\n\n"
                "[USER]\nReview onboarding for Beta."
            ),
            metadata={
                "tool": "codex",
                "source_path": "/tmp/codex-alpha-beta.jsonl",
                "source_modified_at": "2026-07-18T08:00:00+00:00",
                "cwd": "/workspace/context-engine",
                "title": "Alpha and Beta planning",
                "topics": ["Alpha billing", "Beta onboarding"],
            },
        ),
        ResolvedSession(
            connector_type="codex",
            session_id="codex-release",
            content=(
                "[USER]\nPlan billing for Alpha.\n\n"
                "[ASSISTANT]\nBilling is ready for release."
            ),
            metadata={
                "tool": "codex",
                "source_path": "/tmp/codex-release.jsonl",
                "source_modified_at": "2026-07-18T09:00:00+00:00",
                "title": "Alpha release",
                "topics": ["Alpha billing", "Release readiness"],
            },
        ),
    ]

    def _discover(connector_types):
        assert tuple(connector_types) == ("codex", "claude", "opencode")
        return [
            SessionDiscoveryResult(connector_type="codex", sessions=resolved),
            SessionDiscoveryResult(
                connector_type="claude",
                error="Claude project history directory not found",
            ),
            SessionDiscoveryResult(
                connector_type="opencode",
                error="OpenCode database not found",
            ),
        ]

    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        _discover,
    )

    first = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["sync"]["automatic"] is True
    assert payload["sync"]["discovered"] == 2
    assert payload["library"]["stats"]["sessions"] == 2
    assert payload["library"]["stats"]["harnesses"] == 1
    assert payload["library"]["stats"]["live_sessions"] == 2
    alpha = next(
        topic
        for topic in payload["library"]["topics"]
        if topic["name"] == "Plan billing for Alpha"
    )
    assert alpha["session_count"] == 2

    second = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert second.status_code == 200
    assert second.json()["sync"]["unchanged"] == 2

    documents = list(await db_session.scalars(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.source_type == "agent_session",
        )
    ))
    assert len(documents) == 2

    launched = {}

    def _launch(connector_type, session_id, *, cwd=None):
        launched.update({
            "connector_type": connector_type,
            "session_id": session_id,
            "cwd": cwd,
        })
        return {
            "launched": True,
            "connector_type": connector_type,
            "harness": "Codex",
            "session_id": session_id,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
            "topic_anchor_supported": False,
        }

    monkeypatch.setattr("app.api.session_library.launch_harness_session", _launch)
    opened = await client.post(
        "/api/session-library/open",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(documents[0].id),
            "topic": "Alpha billing",
        },
    )
    assert opened.status_code == 200
    assert opened.json()["launched"] is True
    assert opened.json()["mode"] == "desktop_app"
    assert opened.json()["exact_session_supported"] is True
    assert opened.json()["topic_anchor_supported"] is False
    assert opened.json()["topic"] == "Alpha billing"
    assert launched["connector_type"] == "codex"
    assert launched["session_id"] in {"codex-alpha-beta", "codex-release"}
