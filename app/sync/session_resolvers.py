from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.session_checkpoints import build_compaction_checkpoint_descriptor
from app.services.session_events import NormalizedSessionEvent
from app.services.session_summary import (
    derive_session_topic,
    derive_session_topics,
    extract_delegated_user_request,
    is_internal_session_content,
    is_session_instruction_noise,
)


class SessionResolutionError(Exception):
    """Raised when a local AI session cannot be resolved from an ID."""


@dataclass
class ResolvedSession:
    connector_type: str
    session_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[NormalizedSessionEvent] = field(default_factory=list)


@dataclass
class SessionDiscoveryResult:
    connector_type: str
    sessions: list[ResolvedSession] = field(default_factory=list)
    error: str | None = None


def discover_local_ai_sessions(
    connector_types: list[str] | tuple[str, ...] | None = None,
) -> list[SessionDiscoveryResult]:
    """Discover and fully resolve every readable local harness session.

    Missing harnesses are reported independently so one unavailable provider
    never prevents the others from syncing.
    """

    requested = connector_types or ("codex", "claude", "opencode")
    results: list[SessionDiscoveryResult] = []
    for raw_type in requested:
        connector_type = raw_type.strip().lower()
        try:
            if connector_type == "codex":
                sessions = _discover_codex_sessions()
            elif connector_type == "claude":
                sessions = _discover_claude_sessions()
            elif connector_type == "opencode":
                sessions = _discover_opencode_sessions()
            else:
                raise SessionResolutionError(
                    f"Unsupported AI session connector: {connector_type}"
                )
        except SessionResolutionError as exc:
            results.append(SessionDiscoveryResult(connector_type=connector_type, error=str(exc)))
            continue
        sessions = [
            item for item in sessions
            if not is_internal_session_content(item.content)
        ]
        results.append(SessionDiscoveryResult(connector_type=connector_type, sessions=sessions))
    return results


def resolve_local_ai_session(connector_type: str, session_id: str) -> ResolvedSession:
    connector_type = connector_type.strip().lower()
    if connector_type == "codex":
        return _resolve_codex_session(session_id)
    if connector_type == "claude":
        return _resolve_claude_session(session_id)
    if connector_type == "opencode":
        return _resolve_opencode_session(session_id)
    raise SessionResolutionError(f"Unsupported AI session connector: {connector_type}")


def _resolve_codex_session(session_id: str) -> ResolvedSession:
    root = _home_path(settings.codex_home, "CODEX_HOME", ".codex")
    sessions_dir = root / "sessions"
    if not sessions_dir.exists():
        raise SessionResolutionError(f"Codex session directory not found: {sessions_dir}")

    for path in _recent_files(sessions_dir, "*.jsonl"):
        resolved = _read_codex_rollout(path, session_id, root=root)
        if resolved is not None:
            _drop_codex_discovery_metadata(resolved)
            return resolved

    title = _codex_index_title(root, session_id)
    if title:
        raise SessionResolutionError(
            f"Found Codex session metadata for {session_id}, but no local transcript file was found."
        )
    raise SessionResolutionError(f"Codex session not found locally: {session_id}")


def _discover_codex_sessions() -> list[ResolvedSession]:
    root = _home_path(settings.codex_home, "CODEX_HOME", ".codex")
    sessions_dir = root / "sessions"
    if not sessions_dir.exists():
        raise SessionResolutionError(f"Codex session directory not found: {sessions_dir}")

    sessions: list[ResolvedSession] = []
    seen: set[str] = set()
    for path in _recent_files(sessions_dir, "*.jsonl"):
        session_id = _codex_session_id(path)
        if not session_id or session_id in seen:
            continue
        try:
            resolved = _read_codex_rollout(path, session_id, root=root)
        except SessionResolutionError:
            continue
        if resolved is not None:
            seen.add(session_id)
            sessions.append(resolved)
    _annotate_codex_forks(sessions)
    for resolved in sessions:
        _drop_codex_discovery_metadata(resolved)
    return sessions


def _read_codex_rollout(
    path: Path,
    session_id: str,
    *,
    root: Path,
) -> ResolvedSession | None:
    messages: list[tuple[str, str]] = []
    compaction_checkpoints: list[dict[str, Any]] = []
    provider_message_ids: list[str] = []
    final_answers: list[str] = []
    events: list[NormalizedSessionEvent] = []
    tool_calls: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {
        "tool": "codex",
        "source_path": str(path),
        "source_modified_at": _path_modified_iso(path),
    }
    matched = False
    source_cursor = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_number, raw in enumerate(fh, start=1):
                line_cursor = source_cursor
                source_cursor += len(raw)
                if session_id not in raw and not matched:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "session_meta":
                    payload = item.get("payload") or {}
                    payload_session_id = str(payload.get("id") or "").strip()
                    if not matched and payload_session_id == session_id:
                        matched = True
                    if payload_session_id == session_id:
                        metadata.update({
                            "session_id": session_id,
                            "started_at": payload.get("timestamp") or item.get("timestamp"),
                            "updated_at": item.get("timestamp") or payload.get("timestamp"),
                            "cwd": payload.get("cwd"),
                            "model": payload.get("model"),
                            "source": payload.get("originator") or "Codex",
                            "thread_source": payload.get("thread_source"),
                            "parent_thread_id": payload.get("parent_thread_id"),
                        })
                    elif (
                        matched
                        and payload_session_id
                        and metadata.get("thread_source") != "subagent"
                        and payload.get("thread_source") != "subagent"
                        and not metadata.get("forked_from_session_id")
                    ):
                        # "Continue in new task" stores the new task metadata first,
                        # followed by the copied parent rollout. That first embedded
                        # user-session ID is the direct parent.
                        metadata["forked_from_session_id"] = payload_session_id
                        metadata["forked_from_title"] = _codex_index_title(
                            root, payload_session_id
                        )
                    continue
                if not matched:
                    continue
                timestamp = item.get("timestamp")
                if timestamp:
                    metadata["updated_at"] = timestamp
                item_type = str(item.get("type") or "")
                if item_type in {"compacted", "context_compaction", "contextCompaction"}:
                    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                    window_id = payload.get("window_id")
                    if messages:
                        descriptor = build_compaction_checkpoint_descriptor(
                            messages,
                            item,
                            provider="codex",
                            ordinal=len(compaction_checkpoints) + 1,
                        )
                        if not any(
                            current["id"] == descriptor["id"]
                            for current in compaction_checkpoints
                        ):
                            compaction_checkpoints.append(descriptor)
                    events.append(NormalizedSessionEvent(
                        provider_event_id=_provider_event_id(
                            item,
                            fallback=f"compaction:{window_id or line_number}",
                        ),
                        sequence_number=line_number,
                        event_type="compaction_boundary",
                        occurred_at=timestamp,
                        payload={
                            "window_id": window_id,
                            "window_number": payload.get("window_number"),
                            "previous_window_id": payload.get("previous_window_id"),
                            "first_window_id": payload.get("first_window_id"),
                            "turn_count": len(messages),
                            "user_turn_count": sum(role == "user" for role, _ in messages),
                            "assistant_turn_count": sum(
                                role == "assistant" for role, _ in messages
                            ),
                        },
                        source_cursor=line_cursor,
                    ))
                    continue
                payload = item.get("payload") or {}
                if item_type == "response_item" and payload.get("type") == "message":
                    role = str(payload.get("role") or "assistant").strip().lower()
                    provider_message_id = str(payload.get("id") or "").strip()
                    if role in {"user", "assistant"} and provider_message_id:
                        provider_message_ids.append(provider_message_id)
                    text = _extract_content_text(payload.get("content"))
                    if text:
                        messages.append((role, text))
                        if role == "assistant" and payload.get("phase") == "final_answer":
                            final_answers.append(text)
                        event_text = _message_event_content(role, text)
                        event_type = _message_event_type(role, event_text)
                        events.append(NormalizedSessionEvent(
                            provider_event_id=_provider_event_id(
                                payload,
                                fallback=f"message:{line_number}",
                            ),
                            sequence_number=line_number,
                            event_type=event_type,
                            role=role,
                            occurred_at=timestamp,
                            content=event_text,
                            payload={"message_id": payload.get("id")},
                            source_cursor=line_cursor,
                        ))
                    continue
                if item_type == "response_item" and payload.get("type") in {
                    "custom_tool_call",
                    "function_call",
                }:
                    call_id = str(payload.get("call_id") or payload.get("id") or line_number)
                    name = str(payload.get("name") or "tool").strip()
                    tool_input = payload.get("input") or payload.get("arguments") or ""
                    parsed = _parse_codex_tool_input(tool_input)
                    tool_calls[call_id] = {"name": name, **parsed}
                    command_like = name in {"exec", "exec_command", "shell"}
                    events.append(NormalizedSessionEvent(
                        provider_event_id=_provider_event_id(
                            payload,
                            fallback=f"tool-call:{call_id}",
                            suffix="call",
                        ),
                        sequence_number=line_number,
                        event_type="command_call" if command_like else "tool_call",
                        role="assistant",
                        occurred_at=timestamp,
                        content=parsed.get("command") or None,
                        payload={
                            "call_id": call_id,
                            "tool_name": name,
                            "command": parsed.get("command"),
                            "cwd": parsed.get("cwd"),
                            "input": str(tool_input),
                        },
                        source_cursor=line_cursor,
                    ))
                    continue
                if item_type == "response_item" and payload.get("type") in {
                    "custom_tool_call_output",
                    "function_call_output",
                }:
                    call_id = str(payload.get("call_id") or payload.get("id") or line_number)
                    call = tool_calls.get(call_id, {})
                    output = _extract_content_text(payload.get("output"))
                    exit_code = _infer_exit_code(output)
                    command_like = call.get("name") in {"exec", "exec_command", "shell"}
                    events.append(NormalizedSessionEvent(
                        provider_event_id=_provider_event_id(
                            payload,
                            fallback=f"tool-result:{call_id}",
                            suffix="result",
                        ),
                        sequence_number=line_number,
                        event_type="command_result" if command_like else "tool_result",
                        role="tool",
                        occurred_at=timestamp,
                        content=output,
                        payload={
                            "call_id": call_id,
                            "tool_name": call.get("name"),
                            "command": call.get("command"),
                            "cwd": call.get("cwd"),
                            "exit_code": exit_code,
                            "passed": exit_code == 0 if exit_code is not None else None,
                        },
                        source_cursor=line_cursor,
                    ))
    except OSError:
        return None

    if not matched:
        return None
    content = _format_turns(messages)
    if not content:
        raise SessionResolutionError(f"Codex session {session_id} had no readable message content.")
    index_titles = _codex_index_titles(root, session_id)
    explicit_title = index_titles[-1] if index_titles else None
    metadata["_provider_message_ids"] = provider_message_ids
    metadata["_initial_index_title"] = index_titles[0] if index_titles else None
    metadata["title"] = derive_session_topic(
        content,
        explicit_title=explicit_title,
        tool="codex",
        session_id=session_id,
    )
    metadata["topics"] = derive_session_topics(
        content,
        explicit_title=explicit_title,
        cwd=metadata.get("cwd"),
        tool="codex",
        session_id=session_id,
    )
    if compaction_checkpoints:
        metadata["compaction_checkpoints"] = compaction_checkpoints
    if final_answers:
        metadata.update({
            "agent_reported_summary": final_answers[-1],
            "agent_reported_summary_kind": "completion",
            "agent_reported_summary_source": "provider_final_answer",
        })
    metadata["normalized_event_count"] = len(events)
    metadata["compaction_count"] = sum(
        event.event_type == "compaction_boundary" for event in events
    )
    return ResolvedSession("codex", session_id, content, metadata, events)


def _codex_session_id(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "session_meta":
                    continue
                session_id = str((item.get("payload") or {}).get("id") or "").strip()
                return session_id or None
    except OSError:
        return None
    return None


def _codex_index_title(root: Path, session_id: str) -> str | None:
    titles = _codex_index_titles(root, session_id)
    return titles[-1] if titles else None


def _codex_index_titles(root: Path, session_id: str) -> list[str]:
    index_path = root / "session_index.jsonl"
    if not index_path.exists():
        return []
    titles: list[str] = []
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if session_id not in raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if item.get("id") == session_id:
                    title = str(item.get("thread_name") or item.get("title") or "").strip()
                    if title and (not titles or titles[-1] != title):
                        titles.append(title)
    except OSError:
        return []
    return titles


def _annotate_codex_forks(sessions: list[ResolvedSession]) -> None:
    """Attach user-task lineage without confusing Codex sub-agents for forks.

    Codex currently replays provider message records when the user chooses
    "Continue in new task", but user-created tasks do not always receive an
    explicit ``parent_thread_id``. Exact provider message IDs let us recover
    that relationship without guessing from similar titles or text.
    """

    for child in sessions:
        metadata = child.metadata
        if metadata.get("thread_source") == "subagent":
            continue
        if metadata.get("forked_from_session_id"):
            continue
        explicit_parent = str(metadata.get("parent_thread_id") or "").strip()
        if explicit_parent and explicit_parent != child.session_id:
            metadata["forked_from_session_id"] = explicit_parent
            continue

        child_ids = list(dict.fromkeys(metadata.get("_provider_message_ids") or []))
        if len(child_ids) < 2:
            continue
        child_started_at = str(metadata.get("started_at") or "")
        child_initial_title = str(metadata.get("_initial_index_title") or "").strip()
        best: tuple[int, int, str, ResolvedSession] | None = None

        for parent in sessions:
            if parent.session_id == child.session_id:
                continue
            parent_started_at = str(parent.metadata.get("started_at") or "")
            if child_started_at and parent_started_at and parent_started_at >= child_started_at:
                continue
            parent_ids = list(dict.fromkeys(
                parent.metadata.get("_provider_message_ids") or []
            ))
            prefix_length = _shared_prefix_length(parent_ids, child_ids)
            if prefix_length < 2:
                continue
            parent_title = str(parent.metadata.get("title") or "").strip()
            title_match = int(bool(child_initial_title and child_initial_title == parent_title))
            candidate = (prefix_length, title_match, parent_started_at, parent)
            if best is None or candidate[:3] > best[:3]:
                best = candidate

        if best is None:
            continue
        parent = best[3]
        metadata["forked_from_session_id"] = parent.session_id
        metadata["forked_from_title"] = parent.metadata.get("title")


def _shared_prefix_length(left: list[str], right: list[str]) -> int:
    length = 0
    for left_id, right_id in zip(left, right):
        if left_id != right_id:
            break
        length += 1
    return length


def _drop_codex_discovery_metadata(session: ResolvedSession) -> None:
    session.metadata.pop("_provider_message_ids", None)
    session.metadata.pop("_initial_index_title", None)


def _resolve_claude_session(session_id: str) -> ResolvedSession:
    root = _home_path(settings.claude_home, "CLAUDE_HOME", ".claude")
    projects_dir = root / "projects"
    if not projects_dir.exists():
        raise SessionResolutionError(f"Claude project history directory not found: {projects_dir}")

    candidates = list(projects_dir.glob(f"**/{session_id}.jsonl"))
    if not candidates:
        candidates = [p for p in _recent_files(projects_dir, "*.jsonl") if _file_contains(p, session_id)]

    for path in candidates:
        resolved = _read_claude_jsonl(path, session_id)
        if resolved is not None:
            return resolved
    raise SessionResolutionError(f"Claude session not found locally: {session_id}")


def _discover_claude_sessions() -> list[ResolvedSession]:
    root = _home_path(settings.claude_home, "CLAUDE_HOME", ".claude")
    projects_dir = root / "projects"
    if not projects_dir.exists():
        raise SessionResolutionError(f"Claude project history directory not found: {projects_dir}")

    sessions: list[ResolvedSession] = []
    seen: set[str] = set()
    for path in _recent_files(projects_dir, "*.jsonl"):
        session_id = _claude_session_id(path)
        if not session_id or session_id in seen:
            continue
        try:
            resolved = _read_claude_jsonl(path, session_id)
        except SessionResolutionError:
            continue
        if resolved is not None:
            seen.add(session_id)
            sessions.append(resolved)
    return sessions


def _read_claude_jsonl(path: Path, session_id: str) -> ResolvedSession | None:
    messages: list[tuple[str, str]] = []
    events: list[NormalizedSessionEvent] = []
    tool_calls: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {
        "tool": "claude_code",
        "source_path": str(path),
        "source_modified_at": _path_modified_iso(path),
    }
    matched = path.stem == session_id
    source_cursor = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_number, raw in enumerate(fh, start=1):
                line_cursor = source_cursor
                source_cursor += len(raw)
                if session_id not in raw and not matched:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if item.get("sessionId") == session_id:
                    matched = True
                if not matched:
                    continue
                if item.get("timestamp"):
                    metadata["updated_at"] = item["timestamp"]
                item_type = str(item.get("type") or "").strip().lower()
                subtype = str(item.get("subtype") or "").strip().lower()
                if item_type == "summary" or "compact" in subtype:
                    events.append(NormalizedSessionEvent(
                        provider_event_id=_provider_event_id(
                            item,
                            fallback=f"compaction:{line_number}",
                        ),
                        sequence_number=line_number * 1000,
                        event_type="compaction_boundary",
                        occurred_at=item.get("timestamp"),
                        content=_none_if_blank(item.get("summary")),
                        payload={
                            "subtype": subtype or None,
                            "leaf_uuid": item.get("leafUuid"),
                            "turn_count": len(messages),
                        },
                        source_cursor=line_cursor,
                    ))
                    continue
                if item.get("isMeta") is True:
                    continue
                message = item.get("message") if isinstance(item.get("message"), dict) else {}
                role = str(message.get("role") or item.get("type") or "message").lower()
                message_content = message.get("content")
                if isinstance(message_content, list):
                    for block_index, block in enumerate(message_content, start=1):
                        if not isinstance(block, dict):
                            continue
                        block_type = str(block.get("type") or "")
                        sequence = line_number * 1000 + block_index
                        if block_type == "tool_use":
                            call_id = str(block.get("id") or f"{line_number}:{block_index}")
                            name = str(block.get("name") or "tool")
                            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                            command = _none_if_blank(
                                tool_input.get("command") or tool_input.get("cmd")
                            )
                            cwd = _none_if_blank(tool_input.get("cwd") or item.get("cwd"))
                            command_like = bool(command) or name.lower() in {
                                "bash", "shell", "exec", "exec_command"
                            }
                            tool_calls[call_id] = {
                                "name": name,
                                "command": command,
                                "cwd": cwd,
                                "command_like": command_like,
                            }
                            events.append(NormalizedSessionEvent(
                                provider_event_id=_provider_event_id(
                                    block,
                                    fallback=f"tool-call:{call_id}",
                                    suffix="call",
                                ),
                                sequence_number=sequence,
                                event_type="command_call" if command_like else "tool_call",
                                role="assistant",
                                occurred_at=item.get("timestamp"),
                                content=command,
                                payload={
                                    "call_id": call_id,
                                    "tool_name": name,
                                    "command": command,
                                    "cwd": cwd,
                                    "input": tool_input,
                                },
                                source_cursor=line_cursor,
                            ))
                        elif block_type == "tool_result":
                            call_id = str(
                                block.get("tool_use_id")
                                or block.get("id")
                                or f"{line_number}:{block_index}"
                            )
                            call = tool_calls.get(call_id, {})
                            output = _extract_content_text(block.get("content"))
                            is_error = block.get("is_error") is True
                            exit_code = _infer_exit_code(output)
                            if call.get("command_like") and exit_code is None:
                                exit_code = 1 if is_error else 0
                            events.append(NormalizedSessionEvent(
                                provider_event_id=_provider_event_id(
                                    block,
                                    fallback=f"tool-result:{call_id}",
                                    suffix="result",
                                ),
                                sequence_number=sequence,
                                event_type=(
                                    "command_result"
                                    if call.get("command_like")
                                    else "tool_result"
                                ),
                                role="tool",
                                occurred_at=item.get("timestamp"),
                                content=output,
                                payload={
                                    "call_id": call_id,
                                    "tool_name": call.get("name"),
                                    "command": call.get("command"),
                                    "cwd": call.get("cwd"),
                                    "exit_code": exit_code,
                                    "passed": (
                                        exit_code == 0 if exit_code is not None else not is_error
                                    ),
                                },
                                source_cursor=line_cursor,
                            ))
                text = _extract_claude_message_text(message.get("content"))
                if not text:
                    continue
                messages.append((role or "message", text))
                event_text = _message_event_content(role, text)
                events.append(NormalizedSessionEvent(
                    provider_event_id=_provider_event_id(
                        message,
                        fallback=f"message:{line_number}",
                    ),
                    sequence_number=line_number * 1000,
                    event_type=_message_event_type(role, event_text),
                    role=role,
                    occurred_at=item.get("timestamp"),
                    content=event_text,
                    payload={"message_uuid": item.get("uuid")},
                    source_cursor=line_cursor,
                ))
                metadata.setdefault("started_at", item.get("timestamp"))
                metadata.update({
                    "session_id": session_id,
                    "cwd": item.get("cwd") or metadata.get("cwd"),
                    "model": item.get("model") or metadata.get("model"),
                    "branch": item.get("gitBranch") or metadata.get("branch"),
                })
    except OSError:
        return None

    if not matched:
        return None
    content = _format_turns(messages)
    if not content:
        raise SessionResolutionError(f"Claude session {session_id} had no readable message content.")
    metadata["title"] = derive_session_topic(
        content,
        explicit_title=metadata.get("title"),
        tool="claude_code",
        session_id=session_id,
    )
    metadata["topics"] = derive_session_topics(
        content,
        explicit_title=metadata.get("title"),
        cwd=metadata.get("cwd"),
        tool="claude_code",
        session_id=session_id,
    )
    latest_agent_message = _latest_agent_message(messages)
    if latest_agent_message:
        metadata.update({
            "agent_reported_summary": latest_agent_message,
            "agent_reported_summary_kind": "update",
            "agent_reported_summary_source": "provider_message",
        })
    metadata["normalized_event_count"] = len(events)
    metadata["compaction_count"] = sum(
        event.event_type == "compaction_boundary" for event in events
    )
    return ResolvedSession("claude", session_id, content, metadata, events)


def _claude_session_id(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                session_id = str(item.get("sessionId") or "").strip()
                if session_id:
                    return session_id
    except OSError:
        return None
    stem = path.stem.strip()
    return stem or None


def _resolve_opencode_session(session_id: str) -> ResolvedSession:
    root = _home_path(settings.opencode_home, "OPENCODE_HOME", ".local/share/opencode")
    db_path = root / "opencode.db"
    if not db_path.exists():
        raise SessionResolutionError(f"OpenCode database not found: {db_path}")

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        session_row = conn.execute(
            "select id, title, directory, model, time_created, time_updated from session where id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise SessionResolutionError(f"OpenCode session not found locally: {session_id}")
        rows = conn.execute(
            """
            select p.id as part_id, m.id as message_id, m.data as message_data,
                   p.data as part_data, p.time_created as part_time
            from part p
            left join message m on m.id = p.message_id
            where p.session_id = ?
            order by p.time_created, p.id
            """,
            (session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise SessionResolutionError(f"Could not read OpenCode database: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()

    messages: list[tuple[str, str]] = []
    events: list[NormalizedSessionEvent] = []
    for index, row in enumerate(rows, start=1):
        role = "message"
        message_data: dict[str, Any] = {}
        try:
            message_data = json.loads(row["message_data"] or "{}")
            role = message_data.get("role") or role
        except json.JSONDecodeError:
            pass
        try:
            part_data = json.loads(row["part_data"] or "{}")
        except json.JSONDecodeError:
            continue
        part_type = str(part_data.get("type") or "").strip().lower()
        occurred_at = _millis_to_iso(row["part_time"])
        provider_event_id = str(row["part_id"] or f"part:{index}")
        if part_type in {"compaction", "summary"}:
            events.append(NormalizedSessionEvent(
                provider_event_id=provider_event_id,
                sequence_number=index,
                event_type="compaction_boundary",
                occurred_at=occurred_at,
                content=_none_if_blank(part_data.get("summary")),
                payload={"part_type": part_type, "turn_count": len(messages)},
            ))
            continue
        if part_type in {"tool", "tool_use", "tool_result"}:
            state = part_data.get("state") if isinstance(part_data.get("state"), dict) else {}
            tool_input = state.get("input") if isinstance(state.get("input"), dict) else {}
            name = str(part_data.get("tool") or part_data.get("name") or "tool")
            call_id = str(part_data.get("callID") or part_data.get("call_id") or provider_event_id)
            command = _none_if_blank(tool_input.get("command") or tool_input.get("cmd"))
            cwd = _none_if_blank(tool_input.get("cwd") or session_row["directory"])
            output = _extract_content_text(state.get("output") or part_data.get("output"))
            status = str(state.get("status") or part_data.get("status") or "").lower()
            is_result = bool(output) or status in {"completed", "error", "failed"}
            command_like = bool(command) or name.lower() in {
                "bash", "shell", "exec", "exec_command"
            }
            exit_code = _infer_exit_code(output)
            if is_result and command_like and exit_code is None:
                exit_code = 1 if status in {"error", "failed"} else 0
            events.append(NormalizedSessionEvent(
                provider_event_id=provider_event_id,
                sequence_number=index,
                event_type=(
                    "command_result"
                    if is_result and command_like
                    else "tool_result"
                    if is_result
                    else "command_call"
                    if command_like
                    else "tool_call"
                ),
                role="tool" if is_result else "assistant",
                occurred_at=occurred_at,
                content=output if is_result else command,
                payload={
                    "call_id": call_id,
                    "tool_name": name,
                    "command": command,
                    "cwd": cwd,
                    "exit_code": exit_code,
                    "passed": exit_code == 0 if exit_code is not None else None,
                    "status": status or None,
                    "input": tool_input,
                },
            ))
            continue
        text = _extract_content_text(part_data)
        if text:
            messages.append((role, text))
            event_text = _message_event_content(str(role).lower(), text)
            events.append(NormalizedSessionEvent(
                provider_event_id=provider_event_id,
                sequence_number=index,
                event_type=_message_event_type(str(role).lower(), event_text),
                role=str(role).lower(),
                occurred_at=occurred_at,
                content=event_text,
                payload={"message_id": row["message_id"], "part_type": part_type or None},
            ))

    content = _format_turns(messages)
    if not content:
        raise SessionResolutionError(f"OpenCode session {session_id} had no readable message content.")

    metadata = {
        "tool": "opencode",
        "session_id": session_id,
        "title": derive_session_topic(
            content,
            explicit_title=session_row["title"],
            tool="opencode",
            session_id=session_id,
        ),
        "source_path": str(db_path),
        "cwd": session_row["directory"],
        "model": session_row["model"],
        "started_at": _millis_to_iso(session_row["time_created"]),
        "ended_at": _millis_to_iso(session_row["time_updated"]),
        "updated_at": _millis_to_iso(session_row["time_updated"]),
    }
    metadata["topics"] = derive_session_topics(
        content,
        explicit_title=metadata.get("title"),
        cwd=metadata.get("cwd"),
        tool="opencode",
        session_id=session_id,
    )
    latest_agent_message = _latest_agent_message(messages)
    if latest_agent_message:
        metadata.update({
            "agent_reported_summary": latest_agent_message,
            "agent_reported_summary_kind": "update",
            "agent_reported_summary_source": "provider_message",
        })
    metadata["normalized_event_count"] = len(events)
    metadata["compaction_count"] = sum(
        event.event_type == "compaction_boundary" for event in events
    )
    return ResolvedSession("opencode", session_id, content, metadata, events)


def _discover_opencode_sessions() -> list[ResolvedSession]:
    root = _home_path(settings.opencode_home, "OPENCODE_HOME", ".local/share/opencode")
    db_path = root / "opencode.db"
    if not db_path.exists():
        raise SessionResolutionError(f"OpenCode database not found: {db_path}")

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "select id from session order by time_updated desc, id desc"
        ).fetchall()
    except sqlite3.Error as exc:
        raise SessionResolutionError(f"Could not read OpenCode database: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()

    sessions: list[ResolvedSession] = []
    for row in rows:
        session_id = str(row[0] or "").strip()
        if not session_id:
            continue
        try:
            sessions.append(_resolve_opencode_session(session_id))
        except SessionResolutionError:
            continue
    return sessions


def _home_path(setting_value: str | None, env_name: str, default_relative: str) -> Path:
    raw = setting_value or os.environ.get(env_name)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / default_relative


def _recent_files(root: Path, pattern: str) -> list[Path]:
    try:
        files = [p for p in root.glob(f"**/{pattern}") if p.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _file_contains(path: Path, needle: str) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return any(needle in line for line in fh)
    except OSError:
        return False


def _extract_content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if value.get("type") == "text" and value.get("text"):
            return str(value["text"]).strip()
        parts = []
        for key in ("text", "content"):
            text = _extract_content_text(value.get(key))
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, list):
        parts = [_extract_content_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return ""


def _extract_claude_message_text(value: Any) -> str:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and item.get("type") in {
                "tool_result",
                "tool_use",
                "thinking",
            }:
                continue
            text = _extract_claude_message_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        if value.get("type") == "text":
            return str(value.get("text") or "").strip()
        if "text" in value:
            return str(value.get("text") or "").strip()
        return ""
    return str(value).strip() if isinstance(value, str) else ""


def _latest_agent_message(messages: list[tuple[str, str]]) -> str | None:
    agent_roles = {"assistant", "ai", "codex", "claude", "opencode", "gpt"}
    for role, text in reversed(messages):
        if str(role or "").strip().lower() in agent_roles and text.strip():
            return text.strip()[:4000]
    return None


def _message_event_type(role: str, text: str) -> str:
    if role in {"system", "developer"} or is_session_instruction_noise(text):
        return "runtime_instruction"
    if role in {"user", "human", "you"}:
        return "user_request"
    if role in {"assistant", "ai", "codex", "claude", "opencode", "gpt"}:
        return "assistant_update"
    return "session_message"


def _message_event_content(role: str, text: str) -> str:
    if role in {"user", "human", "you"}:
        return extract_delegated_user_request(text) or text
    return text


def _provider_event_id(
    payload: dict[str, Any],
    *,
    fallback: str,
    suffix: str | None = None,
) -> str:
    native = str(
        payload.get("id")
        or payload.get("call_id")
        or payload.get("event_id")
        or fallback
    ).strip()
    if suffix:
        native = f"{native}:{suffix}"
    if len(native) <= 255:
        return native
    import hashlib

    return f"event-{hashlib.sha256(native.encode('utf-8')).hexdigest()}"


def _parse_codex_tool_input(value: Any) -> dict[str, str | None]:
    if isinstance(value, dict):
        return {
            "command": _none_if_blank(value.get("cmd") or value.get("command")),
            "cwd": _none_if_blank(value.get("workdir") or value.get("cwd")),
        }
    raw = str(value or "")
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        loaded = None
    if isinstance(loaded, dict):
        return _parse_codex_tool_input(loaded)
    return {
        "command": _js_property(raw, "cmd") or _js_property(raw, "command"),
        "cwd": _js_property(raw, "workdir") or _js_property(raw, "cwd"),
    }


def _js_property(value: str, key: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(key)}\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')",
        value,
        re.DOTALL,
    )
    if not match:
        return None
    literal = match.group(1)
    if literal.startswith('"'):
        try:
            return _none_if_blank(json.loads(literal))
        except json.JSONDecodeError:
            return _none_if_blank(literal[1:-1])
    inner = literal[1:-1]
    return _none_if_blank(
        inner.replace("\\'", "'").replace("\\n", "\n").replace("\\\\", "\\")
    )


def _infer_exit_code(output: str) -> int | None:
    lowered = output.lower()
    for pattern in (
        r'"exit_code"\s*:\s*(-?\d+)',
        r"(?:exit|exited with)\s+code\s*[:=]?\s*(-?\d+)",
        r"process exited with code\s+(-?\d+)",
    ):
        match = re.search(pattern, lowered)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    if "script completed" in lowered:
        return 0
    if "script failed" in lowered or "command failed" in lowered:
        return 1
    return None


def _none_if_blank(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _format_turns(messages: list[tuple[str, str]]) -> str:
    parts = []
    for role, text in messages:
        clean = text.strip()
        if not clean:
            continue
        label = str(role or "message").upper()
        parts.append(f"[{label}]\n{clean}")
    return "\n\n".join(parts).strip()


def _millis_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _path_modified_iso(path: Path) -> str | None:
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None
