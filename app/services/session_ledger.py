from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Iterable

from app.models import SessionEvent
from app.services.session_events import event_payload
from app.services.session_summary import (
    clean_session_message_text,
    extract_delegated_user_request,
    is_continuation_control,
    is_session_instruction_noise,
    is_substantive_user_request,
)


SESSION_LEDGER_SCHEMA_VERSION = "session_context.v1"
SESSION_LEDGER_EVENT_TYPES = frozenset({
    "assistant_update",
    "compaction_boundary",
    "runtime_instruction",
    "user_request",
})
SESSION_LEDGER_FILE_TOOL_NAMES = (
    "Edit",
    "Write",
    "apply_patch",
)
MAX_LEDGER_ITEMS = 18
MAX_ITEM_CHARS = 900

_EXPLICIT_CHANGE = re.compile(
    r"\b(?:change(?:d)?\s+(?:the|that|this|our|my|your|requirement|direction)|"
    r"instead(?:\s+of)?|replace\s+(?:the|that|this|previous|earlier)|"
    r"rather\s+than|from\s+now\s+on|new\s+requirement|updated?\s+requirement|"
    r"no\s+longer\s+(?:need|want|use|require))\b",
    re.IGNORECASE,
)
_EXPLICIT_REMOVAL = re.compile(
    r"\b(?:cancel|disregard|forget|drop)\s+(?:the\s+)?(?:previous|earlier|last|that)\b|"
    r"\b(?:remove|delete)\s+(?:the\s+)?(?:previous|earlier|last)\s+"
    r"(?:instruction|requirement|request)\b|"
    r"\b(?:that|the\s+previous|the\s+earlier)\s+(?:is\s+)?(?:cancelled|canceled)\b",
    re.IGNORECASE,
)
_DECISION_SIGNAL = re.compile(
    r"\b(?:decid(?:e|ed)|we(?:'ll| will)|will use|keep|replace|exclude|"
    r"must|should|instead|except for|do not|don't)\b",
    re.IGNORECASE,
)
_PROGRESS_SIGNAL = re.compile(
    r"\b(?:added|built|captured|completed|confirmed|created|fixed|implemented|"
    r"in place|passed|removed|replaced|updated|wired|working)\b",
    re.IGNORECASE,
)
_CHECK_COMMAND = re.compile(
    r"(?:^|\s)(?:pytest|python\s+-m\s+pytest|npm\s+(?:test|run\s+(?:test|build|lint))|"
    r"pnpm\s+(?:test|build|lint)|yarn\s+(?:test|build|lint)|ruff|mypy|pyright|"
    r"cargo\s+test|go\s+test|vitest|jest|tsc)(?:\s|$)",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"(?<![\w])("
    r"(?:/(?:[^\s:'\"`<>|]+/)*[^\s:'\"`<>|]+\.[A-Za-z0-9]{1,12})|"
    r"(?:(?:app|frontend|tests|scripts|docs|src|migrations|alembic)/"
    r"[A-Za-z0-9_@+./-]+)|"
    r"(?:[A-Za-z0-9_.@+-]+\.(?:py|tsx?|jsx?|md|json|ya?ml|sql|toml|css|scss|sh))"
    r")(?![A-Za-z0-9])"
)
_CONTINUE_PREFIX = re.compile(
    r"^continue:\s*(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?\s*",
    re.IGNORECASE,
)


def build_session_ledgers(events: Iterable[SessionEvent]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[SessionEvent]] = defaultdict(list)
    for event in events:
        grouped[(event.provider, event.session_id)].append(event)

    ledgers = [
        build_session_ledger(sorted(values, key=lambda item: (item.sequence_number, item.id)))
        for values in grouped.values()
        if values
    ]
    ledgers.sort(
        key=lambda item: (
            item.get("updated_at") or "",
            item["provider"],
            item["session_id"],
        ),
        reverse=True,
    )
    return ledgers


def build_session_ledger(events: list[SessionEvent]) -> dict[str, Any]:
    if not events:
        raise ValueError("Session events are required")

    provider = events[0].provider
    session_id = events[0].session_id
    requests: list[tuple[SessionEvent, str]] = []
    compactions: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []

    for event in events:
        request = _event_user_request(event)
        if request is not None:
            requests.append((event, request))

        if event.event_type == "compaction_boundary":
            payload = event_payload(event)
            compactions.append({
                "event_id": str(event.id),
                "provider_event_id": event.provider_event_id,
                "sequence_number": event.sequence_number,
                "occurred_at": event.occurred_at,
                "window_id": payload.get("window_id"),
            })

        if (
            event.event_type == "assistant_update"
            and event.content
            and not is_session_instruction_noise(event.content)
        ):
            for sentence in _sentences(event.content):
                if _DECISION_SIGNAL.search(sentence):
                    reported.append(_ledger_item(event, sentence, kind="decision", truth_state="reported"))
                elif _PROGRESS_SIGNAL.search(sentence):
                    reported.append(_ledger_item(event, sentence, kind="progress", truth_state="reported"))

        payload = event_payload(event)
        for path in _event_paths(event, payload):
            observed.append(_ledger_item(
                event,
                path,
                kind="file",
                truth_state=(
                    "observed"
                    if event.event_type in {"tool_call", "tool_result", "command_call", "command_result"}
                    else "reported"
                ),
            ))

        command = str(payload.get("command") or "").strip()
        if event.event_type == "command_result" and command and _CHECK_COMMAND.search(command):
            exit_code = payload.get("exit_code")
            status = "passed" if exit_code == 0 else "failed" if exit_code is not None else "completed"
            observed.append(_ledger_item(
                event,
                f"{_cap(command, 500)} {status}"
                + (f" (exit {exit_code})." if exit_code is not None else "."),
                kind="check",
                truth_state="observed",
            ))

    base: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    if requests:
        first_event, first_request = requests[0]
        base.append(_ledger_item(
            first_event,
            first_request,
            kind="original_request",
            truth_state="user_stated",
        ))
        for event, request in requests[1:]:
            item = _ledger_item(event, request, kind="instruction", truth_state="user_stated")
            if _EXPLICIT_REMOVAL.search(request):
                item["kind"] = "cancellation"
                item["confidence"] = "explicit"
                removed.append(item)
            elif _EXPLICIT_CHANGE.search(request):
                item["kind"] = "amendment"
                item["confidence"] = "explicit"
                changed.append(item)
            else:
                added.append(item)

    base_sequence = requests[0][0].sequence_number if requests else -1
    added.extend(item for item in reported if item["sequence_number"] > base_sequence)
    added.extend(item for item in observed if item["sequence_number"] > base_sequence)
    added_all = _dedupe_items(added)
    changed_all = _dedupe_items(changed)
    removed_all = _dedupe_items(removed)
    added = added_all[-MAX_LEDGER_ITEMS:]
    changed = changed_all[-MAX_LEDGER_ITEMS:]
    removed = removed_all[-MAX_LEDGER_ITEMS:]

    latest = events[-1]
    missing = (
        {
            "status": "unmeasured",
            "items": [],
            "reason_code": "post_compaction_context_not_observable",
            "reason": (
                "The agent provider does not expose the active context produced by compaction, "
                "so Context Engine cannot prove what was omitted."
            ),
        }
        if compactions
        else {
            "status": "not_applicable",
            "items": [],
            "reason_code": "no_compaction_boundary",
            "reason": "No compaction boundary was captured for this session.",
        }
    )
    return {
        "schema_version": SESSION_LEDGER_SCHEMA_VERSION,
        "provider": provider,
        "session_id": session_id,
        "source_document_id": str(latest.source_document_id),
        "base": base,
        "added": added,
        "changed": changed,
        "missing": missing,
        "removed": removed,
        "compactions": compactions,
        "counts": {
            "base": len(base),
            "added": len(added_all),
            "changed": len(changed_all),
            "missing": None,
            "removed": len(removed_all),
        },
        "truncated": {
            "base": 0,
            "added": len(added_all) - len(added),
            "changed": len(changed_all) - len(changed),
            "missing": 0,
            "removed": len(removed_all) - len(removed),
        },
        "coverage": {
            "event_count": len(events),
            "first_sequence_number": events[0].sequence_number,
            "last_sequence_number": latest.sequence_number,
            "post_compaction_context_observable": False,
        },
        "updated_at": latest.occurred_at or latest.created_at,
    }


def render_session_ledger_markdown(
    ledger: dict[str, Any],
    *,
    session_title: str,
) -> str:
    lines = [
        "# Continue with recovered session context",
        "",
        f"Session: {session_title}",
        f"Provider: {ledger['provider']}",
        f"Session ID: {ledger['session_id']}",
        "",
        "This context is reconstructed from source-backed session events.",
        "Agent-reported decisions and progress are not automatically treated as verified repository truth.",
    ]
    sections = (
        ("base", "Base · original request", ledger.get("base") or []),
        ("added", "Added since the request", ledger.get("added") or []),
        ("changed", "Changed explicitly by the user", ledger.get("changed") or []),
        ("removed", "Removed explicitly by the user", ledger.get("removed") or []),
    )
    for key, title, items in sections:
        lines.extend(["", f"## {title}", ""])
        hidden_count = int((ledger.get("truncated") or {}).get(key) or 0)
        if hidden_count:
            total_count = int((ledger.get("counts") or {}).get(key) or len(items))
            lines.append(
                f"- Scope note: the latest {len(items)} of {total_count} captured items "
                "are included; earlier items remain in the source session history."
            )
        if not items:
            lines.append("- None captured.")
            continue
        for item in items:
            lines.append(
                f"- [{item['truth_state']}; event {item['sequence_number']}] {item['text']}"
            )
    missing = ledger.get("missing") or {}
    lines.extend([
        "",
        "## Missing after compaction",
        "",
        f"- Status: {missing.get('status', 'unmeasured')}",
        f"- {missing.get('reason', 'Compaction loss could not be measured.')}",
        "",
        "Review this context against the current repository before acting on it.",
    ])
    return "\n".join(lines).strip()


def _event_user_request(event: SessionEvent) -> str | None:
    raw: str | None = None
    if event.event_type == "user_request" and is_substantive_user_request(event.content):
        raw = event.content
    elif event.event_type == "runtime_instruction" and event.role == "user":
        raw = extract_delegated_user_request(event.content)
    if not raw or is_continuation_control(raw):
        return None
    clean = _clean_ledger_text(raw)
    return _cap(clean, MAX_ITEM_CHARS) if clean else None


def _ledger_item(
    event: SessionEvent,
    text: str,
    *,
    kind: str,
    truth_state: str,
) -> dict[str, Any]:
    clean = (
        _cap(text, MAX_ITEM_CHARS)
        if kind in {"file", "check"}
        else _cap(_clean_ledger_text(text), MAX_ITEM_CHARS)
    )
    identity = "|".join((
        event.provider,
        event.session_id,
        str(event.provider_event_id),
        kind,
        clean,
    ))
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "text": clean,
        "kind": kind,
        "truth_state": truth_state,
        "event_id": str(event.id),
        "provider_event_id": event.provider_event_id,
        "sequence_number": event.sequence_number,
        "occurred_at": event.occurred_at,
    }


def _sentences(value: str) -> list[str]:
    cleaned = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    return [
        part.strip(" -•\t")
        for part in re.split(r"(?<=[.!?])\s+|\s*[\r\n]+\s*", cleaned)
        if len(part.strip(" -•\t")) >= 4
    ]


def _extract_paths(value: str) -> list[str]:
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(value or ""):
        path = match.group(1).rstrip(".,);]}")
        lowered = path.lower()
        if any(part in lowered for part in (
            "node_modules/",
            ".git/objects/",
            "__pycache__/",
            "/temporaryitems/",
            "/var/folders/",
            "/private/tmp/",
        )):
            continue
        if path not in paths:
            paths.append(path)
    return paths[:30]


def _event_paths(event: SessionEvent, payload: dict[str, Any]) -> list[str]:
    if event.event_type == "tool_call":
        tool_name = str(payload.get("tool_name") or "").strip().lower()
        tool_input = payload.get("input")
        if tool_name == "apply_patch":
            patch_paths = re.findall(
                r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+?)\s*$|"
                r"^\*\*\* Move to:\s+(.+?)\s*$",
                str(tool_input or ""),
                flags=re.MULTILINE,
            )
            return _extract_paths("\n".join(
                candidate
                for match in patch_paths
                for candidate in match
                if candidate
            ))
        if tool_name in {"edit", "write"} and isinstance(tool_input, dict):
            file_path = (
                tool_input.get("file_path")
                or tool_input.get("path")
                or tool_input.get("filename")
            )
            return _extract_paths(str(file_path or ""))

    corpus = "\n".join(
        str(value)
        for value in (
            event.content if event.event_type in {"assistant_update", "tool_call", "command_call"} else None,
            payload.get("command"),
            payload.get("input"),
        )
        if value
    )
    paths = _extract_paths(corpus)
    if event.event_type == "assistant_update":
        return [
            path
            for path in paths
            if "/" in path and re.search(r"\.[A-Za-z0-9]{1,12}$", path)
        ]
    return paths


def _dedupe_items(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in sorted(values, key=lambda item: (item["sequence_number"], item["id"])):
        normalized = re.sub(r"\W+", " ", value["text"].lower()).strip()
        key = (value["kind"], normalized)
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _cap(value: str | None, limit: int) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1].rstrip()}…"


def _clean_ledger_text(value: str | None) -> str:
    text = clean_session_message_text(value)
    text = _CONTINUE_PREFIX.sub("", text)
    request_marker = text.lower().rfind("my request for codex:")
    if request_marker >= 0:
        text = text[request_marker + len("my request for codex:"):]
    return re.sub(r"\s+", " ", text).strip()
