from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceDocument


def _parse_session_content(content: str) -> list[dict[str, str]]:
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [
                    {"role": m.get("role", "unknown"), "content": str(m.get("content", m.get("text", "")))}
                    for m in data if isinstance(m, dict)
                ]
            if isinstance(data, dict):
                msgs = data.get("messages") or data.get("conversation") or []
                if msgs:
                    return [
                        {"role": m.get("role", "unknown"), "content": str(m.get("content", m.get("text", "")))}
                        for m in msgs if isinstance(m, dict)
                    ]
        except (json.JSONDecodeError, TypeError):
            pass

    turns: list[dict[str, str]] = []
    current_role: str | None = None
    current_lines: list[str] = []
    role_re = re.compile(
        r"^(?:\*\*)?(?P<human>Human|User|You)|(?P<ai>Assistant|Claude|Codex|AI|opencode|GPT)(?:\*\*)?:\s*(?P<rest>.*)",
        re.IGNORECASE,
    )
    for line in content.split("\n"):
        m = role_re.match(line)
        if m:
            if current_role and current_lines:
                turns.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            current_role = "user" if m.group("human") else "assistant"
            current_lines = [m.group("rest") or ""]
        elif current_role is not None:
            current_lines.append(line)

    if current_role and current_lines:
        turns.append({"role": current_role, "content": "\n".join(current_lines).strip()})

    if turns:
        return turns

    return [{"role": "session", "content": content}]


async def ingest_ai_session(
    connector_type: str,
    session: AsyncSession,
    session_id: str,
    content: str,
    workspace_id: str | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    messages = _parse_session_content(content)

    full_text = "\n\n".join(
        f"[{m['role'].upper()}]\n{m['content']}"
        for m in messages
        if m.get("content", "").strip()
    )

    if not full_text.strip():
        return {"documents_fetched": 0, "documents_persisted": 0}

    external_id = f"{connector_type}:session:{session_id}"

    existing = await session.scalar(
        select(SourceDocument).where(SourceDocument.external_id == external_id)
    )

    now = datetime.utcnow()
    metadata = {
        "session_id": session_id,
        "tool": connector_type,
        "message_count": len(messages),
        "connector_type": connector_type,
        "ingested_at": now.isoformat(),
    }
    if workspace_id:
        metadata["workspace_id"] = workspace_id
    if metadata_extra:
        metadata.update({k: v for k, v in metadata_extra.items() if v not in (None, "", [])})
    meta = json.dumps(metadata)

    if existing:
        existing.content = full_text
        existing.metadata_json = meta
        existing.processed_at = None
        await session.commit()
        return {"documents_fetched": len(messages), "documents_persisted": 0, "documents_updated": 1}

    doc = SourceDocument(
        id=uuid4(),
        source_type="agent_session",
        external_id=external_id,
        content=full_text,
        metadata_json=meta,
    )
    session.add(doc)
    await session.commit()
    return {"documents_fetched": len(messages), "documents_persisted": 1}
