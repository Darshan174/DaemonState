from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.session_summary import derive_session_topic


class SessionResolutionError(Exception):
    """Raised when a local AI session cannot be resolved from an ID."""


@dataclass
class ResolvedSession:
    connector_type: str
    session_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


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
            return resolved

    title = _codex_index_title(root, session_id)
    if title:
        raise SessionResolutionError(
            f"Found Codex session metadata for {session_id}, but no local transcript file was found."
        )
    raise SessionResolutionError(f"Codex session not found locally: {session_id}")


def _read_codex_rollout(
    path: Path,
    session_id: str,
    *,
    root: Path,
) -> ResolvedSession | None:
    messages: list[tuple[str, str]] = []
    metadata: dict[str, Any] = {"tool": "codex", "source_path": str(path)}
    matched = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if session_id not in raw and not matched:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "session_meta":
                    payload = item.get("payload") or {}
                    matched = payload.get("id") == session_id
                    if matched:
                        metadata.update({
                            "session_id": session_id,
                            "started_at": payload.get("timestamp") or item.get("timestamp"),
                            "cwd": payload.get("cwd"),
                            "model": payload.get("model"),
                            "source": payload.get("originator") or "Codex",
                        })
                    continue
                if not matched:
                    continue
                payload = item.get("payload") or {}
                if item.get("type") == "response_item" and payload.get("type") == "message":
                    role = payload.get("role") or "assistant"
                    text = _extract_content_text(payload.get("content"))
                    if text:
                        messages.append((role, text))
    except OSError:
        return None

    if not matched:
        return None
    content = _format_turns(messages)
    if not content:
        raise SessionResolutionError(f"Codex session {session_id} had no readable message content.")
    metadata["title"] = derive_session_topic(
        content,
        explicit_title=_codex_index_title(root, session_id),
        tool="codex",
        session_id=session_id,
    )
    return ResolvedSession("codex", session_id, content, metadata)


def _codex_index_title(root: Path, session_id: str) -> str | None:
    index_path = root / "session_index.jsonl"
    if not index_path.exists():
        return None
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
                    return item.get("thread_name") or item.get("title")
    except OSError:
        return None
    return None


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


def _read_claude_jsonl(path: Path, session_id: str) -> ResolvedSession | None:
    messages: list[tuple[str, str]] = []
    metadata: dict[str, Any] = {"tool": "claude_code", "source_path": str(path)}
    matched = path.stem == session_id
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
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
                message = item.get("message") if isinstance(item.get("message"), dict) else {}
                role = message.get("role") or item.get("type")
                text = _extract_content_text(message.get("content"))
                if not text:
                    continue
                messages.append((role or "message", text))
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
    return ResolvedSession("claude", session_id, content, metadata)


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
            select m.data as message_data, p.data as part_data, p.time_created as part_time
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
    for row in rows:
        role = "message"
        try:
            message_data = json.loads(row["message_data"] or "{}")
            role = message_data.get("role") or role
        except json.JSONDecodeError:
            pass
        try:
            part_data = json.loads(row["part_data"] or "{}")
        except json.JSONDecodeError:
            continue
        text = _extract_content_text(part_data)
        if text:
            messages.append((role, text))

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
    }
    return ResolvedSession("opencode", session_id, content, metadata)


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
