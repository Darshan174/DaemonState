from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from app.services.session_summary import (
    clean_session_message_text,
    derive_latest_session_topic,
)


_TURN_RE = re.compile(
    r"(?ms)^\[([A-Z_ -]+)\]\s*(.*?)(?=^\[[A-Z_ -]+\]\s*|\Z)"
)
_PATH_RE = re.compile(
    r"(?<![\w/])(?:app|frontend|src|tests?|docs|scripts|packages)/[\w.@+~/-]+"
    r"|(?<!\w)(?:/[\w.@+~-]+){2,}"
)
_NOISE_MARKERS = (
    "<apps_instructions>",
    "<collaboration_mode>",
    "<environment_context>",
    "<permissions instructions>",
    "<plugins_instructions>",
    "<skills_instructions>",
    "request_user_input availability",
    "the following is the codex agent history",
    "filesystem sandboxing defines",
    "at the start of your turn, you are the active agent",
)


class SessionCheckpointNotFoundError(ValueError):
    pass


def build_compaction_checkpoint_descriptor(
    messages: Iterable[tuple[str, str]],
    event: dict[str, Any],
    *,
    provider: str,
    ordinal: int,
) -> dict[str, Any]:
    """Describe a provider compaction boundary without retaining its opaque blob."""

    materialized = list(messages)
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    occurred_at = str(event.get("timestamp") or payload.get("timestamp") or "").strip() or None
    window_id = payload.get("window_id")
    identity = "|".join([
        provider,
        str(window_id if window_id is not None else ordinal),
        occurred_at or "unknown-time",
        str(len(materialized)),
    ])
    checkpoint_id = f"checkpoint-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}"
    return {
        "id": checkpoint_id,
        "kind": "provider_compaction",
        "provider": provider,
        "occurred_at": occurred_at,
        "turn_count": len(materialized),
        "user_turn_count": sum(role == "user" for role, _ in materialized),
        "assistant_turn_count": sum(role == "assistant" for role, _ in materialized),
        "window_id": window_id,
    }


def list_session_checkpoints(
    content: str,
    metadata: dict[str, Any] | None,
    *,
    session_title: str | None = None,
) -> list[dict[str, Any]]:
    descriptors = _checkpoint_descriptors(metadata)
    cards: list[dict[str, Any]] = []
    for descriptor in descriptors:
        restored = build_restored_context(
            content,
            descriptor,
            session_title=session_title,
        )
        cards.append({
            **descriptor,
            "label": "Before context compact",
            "objective": restored["objective"],
            "objective_preview": _cap(restored["objective"], 180),
            "agent_state_preview": _cap(restored["agent_reported_state"], 180),
            "restorable": True,
        })
    return cards


def restore_session_checkpoint(
    content: str,
    metadata: dict[str, Any] | None,
    checkpoint_id: str,
    *,
    session_title: str | None = None,
    source_document_id: str | None = None,
    session_id: str | None = None,
    harness: str | None = None,
    source_revision_number: int | None = None,
    source_content_sha256: str | None = None,
) -> dict[str, Any]:
    descriptor = next(
        (
            item for item in _checkpoint_descriptors(metadata)
            if item["id"] == str(checkpoint_id).strip()
        ),
        None,
    )
    if descriptor is None:
        raise SessionCheckpointNotFoundError("Compaction checkpoint not found in this session")
    restored = build_restored_context(
        content,
        descriptor,
        session_title=session_title,
    )
    return {
        "checkpoint": {
            **descriptor,
            "label": "Before context compact",
            "session_title": session_title,
            "session_id": session_id,
            "harness": harness,
        },
        "restore_context": {
            **restored,
            "source_document_id": source_document_id,
            "source_revision_number": source_revision_number,
            "source_content_sha256": source_content_sha256,
            "session_id": session_id,
            "session_title": session_title,
            "harness": harness,
        },
    }


def build_restored_context(
    content: str,
    descriptor: dict[str, Any],
    *,
    session_title: str | None = None,
) -> dict[str, Any]:
    turns = _session_turns(content)
    turn_count = min(max(int(descriptor.get("turn_count") or 0), 0), len(turns))
    before_compaction = turns[:turn_count]
    user_messages = _meaningful_messages(before_compaction, role="user")
    assistant_messages = _meaningful_messages(before_compaction, role="assistant")

    objective = user_messages[-1] if user_messages else (session_title or "Continue this session")
    earlier_requirements = _distinct_recent(user_messages[:-1], limit=4)
    agent_state = assistant_messages[-1] if assistant_messages else "No agent-reported state was captured before compaction."
    prefix_content = _format_turns(before_compaction)
    objective_label = derive_latest_session_topic(
        prefix_content,
        explicit_title=None,
    ) or _cap(objective, 96)
    files = _referenced_files("\n".join(text for _, text in before_compaction))
    markdown = _render_restore_markdown(
        descriptor=descriptor,
        objective=objective,
        earlier_requirements=earlier_requirements,
        agent_state=agent_state,
        files=files,
    )
    return {
        "objective": objective,
        "objective_label": objective_label,
        "earlier_requirements": earlier_requirements,
        "agent_reported_state": agent_state,
        "referenced_files": files,
        "turn_count": turn_count,
        "markdown": markdown,
        "provenance": "transcript_before_provider_compaction",
        "truth_status": "reported_not_verified",
    }


def _checkpoint_descriptors(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw_items = (metadata or {}).get("compaction_checkpoints") or []
    if not isinstance(raw_items, list):
        return []
    descriptors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        checkpoint_id = str(raw.get("id") or "").strip()
        try:
            turn_count = max(int(raw.get("turn_count") or 0), 0)
        except (TypeError, ValueError):
            continue
        if not checkpoint_id or checkpoint_id in seen or turn_count <= 0:
            continue
        seen.add(checkpoint_id)
        descriptors.append({
            "id": checkpoint_id,
            "kind": str(raw.get("kind") or "provider_compaction"),
            "provider": str(raw.get("provider") or "unknown"),
            "occurred_at": raw.get("occurred_at"),
            "turn_count": turn_count,
            "user_turn_count": int(raw.get("user_turn_count") or 0),
            "assistant_turn_count": int(raw.get("assistant_turn_count") or 0),
            "window_id": raw.get("window_id"),
        })
    return descriptors


def _session_turns(content: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for raw_role, raw_text in _TURN_RE.findall(content or ""):
        role_key = raw_role.strip().lower()
        if role_key in {"user", "human", "you"}:
            role = "user"
        elif role_key in {"assistant", "ai", "codex", "claude", "opencode", "gpt"}:
            role = "assistant"
        else:
            continue
        text = raw_text.strip()
        if text:
            turns.append((role, text))
    return turns


def _meaningful_messages(
    turns: list[tuple[str, str]],
    *,
    role: str,
) -> list[str]:
    result: list[str] = []
    for turn_role, raw_text in turns:
        if turn_role != role:
            continue
        text = clean_session_message_text(raw_text)
        compact = re.sub(r"\s+", " ", text).strip()
        lowered = compact.lower()
        if not compact or any(marker in lowered for marker in _NOISE_MARKERS):
            continue
        result.append(_cap(compact, 1600))
    return result


def _distinct_recent(values: list[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in reversed(values):
        key = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(_cap(value, 700))
        if len(output) >= limit:
            break
    output.reverse()
    return output


def _referenced_files(text: str, *, limit: int = 12) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for match in _PATH_RE.finditer(text or ""):
        value = match.group(0).rstrip(".,:;)'\"]}")
        lowered = value.lower()
        if any(marker in lowered for marker in ("/temporaryitems/", "/var/folders/", "/private/tmp/")):
            continue
        if value in seen:
            continue
        seen.add(value)
        files.append(value)
        if len(files) >= limit:
            break
    return files


def _render_restore_markdown(
    *,
    descriptor: dict[str, Any],
    objective: str,
    earlier_requirements: list[str],
    agent_state: str,
    files: list[str],
) -> str:
    lines = [
        "# Restored context checkpoint",
        "",
        "Captured automatically immediately before the AI harness compacted this session.",
        "Transcript-derived agent claims are reported state, not verified project truth.",
        "",
        "## Continue from",
        "",
        objective,
    ]
    if earlier_requirements:
        lines.extend(["", "## Earlier user requirements", ""])
        lines.extend(f"- {item}" for item in earlier_requirements)
    lines.extend(["", "## Last agent-reported state", "", agent_state])
    if files:
        lines.extend(["", "## Referenced files", ""])
        lines.extend(f"- `{item}`" for item in files)
    lines.extend([
        "",
        "## Checkpoint boundary",
        "",
        f"- Turns captured: {int(descriptor.get('turn_count') or 0)}",
        f"- Compacted at: {descriptor.get('occurred_at') or 'time unavailable'}",
    ])
    return "\n".join(lines).strip()


def _format_turns(turns: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{role.upper()}]\n{text}" for role, text in turns)


def _cap(value: str | None, limit: int) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1].rstrip()}…"
