from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AgentRun, ContextPack, Workspace


async def test_continuation_request_key_is_unique_across_recompiled_packs(
    db_session,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Continuation idempotency",
        slug=f"continuation-idempotency-{uuid4().hex[:8]}",
    )
    packs = [
        ContextPack(
            id=uuid4(),
            workspace_id=workspace.id,
            objective="Continue the exact same user action",
            markdown="# Context pack\n",
            manifest=json.dumps({"schema_version": "context_pack.v2"}),
            repo_state_json="{}",
            idempotency_key=f"pack-{uuid4()}",
        )
        for _ in range(2)
    ]
    db_session.add_all([workspace, *packs])
    await db_session.flush()

    request_key = "continuation:stable-user-action"
    db_session.add(AgentRun(
        workspace_id=workspace.id,
        context_pack_id=packs[0].id,
        run_key=request_key,
        status="running",
    ))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(AgentRun(
                workspace_id=workspace.id,
                context_pack_id=packs[1].id,
                run_key=request_key,
                status="running",
            ))
            await db_session.flush()

    # Generic agent-run keys retain their original per-pack identity contract.
    db_session.add_all([
        AgentRun(
            workspace_id=workspace.id,
            context_pack_id=packs[0].id,
            run_key="caller-owned-key",
            status="running",
        ),
        AgentRun(
            workspace_id=workspace.id,
            context_pack_id=packs[1].id,
            run_key="caller-owned-key",
            status="running",
        ),
    ])
    await db_session.flush()
