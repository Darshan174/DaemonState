from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _record_observation
from app.models import AgentRun, RunObservation
from app.services.redaction import redact_sensitive_text
from app.services.harness_launcher import (
    SESSION_ID_PATTERN,
    HarnessLaunchError,
    launch_harness_session,
)


MAX_PROVIDER_EVENT_LINE_BYTES = 131_072
MAX_PERSISTED_PROVIDER_EVENTS = 250
MAX_PROVIDER_EVENT_TEXT = 2_000
CODEX_RENDERABLE_EVENT_TYPES = frozenset({
    "item.started",
    "item.completed",
    "turn.completed",
})
OPENCODE_SESSION_EVENT_TYPES = frozenset({
    "error",
    "reasoning",
    "step_finish",
    "step_start",
    "text",
    "tool_use",
})


logger = logging.getLogger(__name__)


class HarnessSessionBridge:
    """Capture a provider session ID and open its visible desktop harness."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        run: AgentRun,
        provider: str,
        repo_path: str,
        open_desktop: bool = True,
    ) -> None:
        self.session = session
        self.run = run
        self.provider = str(provider or "").strip().lower()
        self.repo_path = str(repo_path or "").strip()
        self.open_desktop = open_desktop
        self._buffer = bytearray()
        self._state: dict[str, Any] | None = None
        self._persisted = False
        self._visibility_ready = False
        self._renderable_observed = False
        self._provider_event_count = 0
        self._events_truncated = False

    @property
    def state(self) -> dict[str, Any] | None:
        return _public_harness_session(self._state)

    async def observe_stdout_chunk(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buffer.extend(chunk)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                if len(self._buffer) > MAX_PROVIDER_EVENT_LINE_BYTES:
                    # A malformed provider line must not create unbounded state.
                    self._buffer.clear()
                return
            line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            await self._observe_line(line)

    async def finish(self) -> None:
        if not self._persisted and self._buffer:
            line = bytes(self._buffer)
            self._buffer.clear()
            await self._observe_line(line)
        if self._state is not None and not self._persisted:
            if self.provider == "codex" and not self._renderable_observed:
                self._state.update({
                    "code": "navigation_deferred",
                    "message": (
                        "Captured the Codex thread before any renderable "
                        "activity; automatic navigation was not requested."
                    ),
                })
            await self._persist_state()
        if self._events_truncated:
            await self._persist_event_truncation()

    async def _observe_line(self, line: bytes) -> None:
        if not line or len(line) > MAX_PROVIDER_EVENT_LINE_BYTES:
            return
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            return
        if not isinstance(event, dict):
            return

        await self._persist_provider_event(event)
        event_type = str(event.get("type") or "").strip()
        if self._state is None:
            session_id = _provider_session_id(self.provider, event)
            if session_id is None:
                return
            exact_session_supported = self.provider == "codex"
            self._visibility_ready = event.get("visibility_ready") is True
            self._state = {
                "provider": self.provider,
                "session_id": session_id,
                "cwd": self.repo_path,
                "launched": False,
                "navigation_requested": False,
                "navigation_verified": False,
                "mode": "desktop_app",
                "navigation": (
                    "session"
                    if exact_session_supported
                    else "app"
                ),
                "exact_session_supported": exact_session_supported,
            }
            return

        if (
            self.provider == "codex"
            and (
                event_type in CODEX_RENDERABLE_EVENT_TYPES
                or (
                    self._visibility_ready
                    and event_type == "turn.started"
                )
            )
        ):
            self._renderable_observed = True
            await self._request_navigation_and_persist()

    async def _request_navigation_and_persist(self) -> None:
        if self._state is None or self._persisted:
            return
        state = self._state
        session_id = str(state["session_id"])
        if (
            self.open_desktop
            and state.get("exact_session_supported") is True
        ):
            try:
                launch = await asyncio.to_thread(
                    launch_harness_session,
                    self.provider,
                    session_id,
                    cwd=self.repo_path,
                )
                state.update({
                    "launched": launch.get("launched") is True,
                    "navigation_requested": (
                        launch.get("navigation_requested") is True
                        or launch.get("launched") is True
                    ),
                    "navigation_verified": (
                        launch.get("navigation_verified") is True
                    ),
                    "mode": launch.get("mode") or "desktop_app",
                    "navigation": launch.get("navigation") or "session",
                    "exact_session_supported": (
                        launch.get("exact_session_supported") is True
                    ),
                })
            except HarnessLaunchError as exc:
                state.update({
                    "navigation_requested": False,
                    "navigation_verified": False,
                    "code": exc.code,
                    "message": str(exc),
                })
            except Exception:
                logger.exception("Could not open the captured Codex harness session")
                state.update({
                    "navigation_requested": False,
                    "navigation_verified": False,
                    "code": "launch_failed",
                    "message": "Could not open the Codex desktop app.",
                })

        await self._persist_state()

    async def _persist_state(self) -> None:
        if self._state is None or self._persisted:
            return
        state = self._state
        state["renderable_activity_observed"] = self._renderable_observed
        session_id = str(state["session_id"])
        content = (
            f"Requested navigation to {self.provider} harness session {session_id}."
            if state["navigation_requested"]
            else f"Captured {self.provider} harness session {session_id}."
        )
        try:
            await _record_observation(
                self.session,
                run=self.run,
                event_key="harness:session",
                event_type="session",
                content=content,
                files=[],
                extra_metadata={"observed_by": "local_harness"},
                extra_payload={"harness_session": state},
            )
            self.run.provider_session_id = session_id
            await self.session.commit()
            self._persisted = True
        except Exception:
            # The provider must keep running even if session-link persistence
            # fails. Command and repository evidence are recorded independently.
            logger.exception("Could not persist the captured harness session")

    async def _persist_provider_event(self, event: dict[str, Any]) -> None:
        self._provider_event_count += 1
        sequence = self._provider_event_count
        if sequence > MAX_PERSISTED_PROVIDER_EVENTS:
            self._events_truncated = True
            return
        normalized = _normalized_provider_event(
            self.provider,
            event,
            sequence=sequence,
        )
        event_type = str(normalized.get("type") or "unknown")
        text = str(normalized.get("text") or "").strip()
        content = f"{self.provider} provider event {event_type}."
        if text:
            content += f" {text}"
        try:
            await _record_observation(
                self.session,
                run=self.run,
                event_key=f"harness:provider-event:{sequence:06d}",
                event_type="provider_event",
                content=content,
                files=[],
                extra_metadata={"observed_by": "harness_session_bridge"},
                extra_payload={
                    "provider": self.provider,
                    "provider_event": normalized,
                },
            )
        except Exception:
            # Event persistence is observability, not execution authority.
            logger.exception("Could not persist a normalized provider event")

    async def _persist_event_truncation(self) -> None:
        try:
            await _record_observation(
                self.session,
                run=self.run,
                event_key="harness:provider-event:truncated",
                event_type="provider_event",
                content=(
                    f"{self.provider} provider event persistence reached the "
                    f"{MAX_PERSISTED_PROVIDER_EVENTS}-event safety limit."
                ),
                files=[],
                extra_metadata={"observed_by": "harness_session_bridge"},
                extra_payload={
                    "provider": self.provider,
                    "provider_event": {
                        "type": "stream.truncated",
                        "persisted_event_limit": MAX_PERSISTED_PROVIDER_EVENTS,
                        "observed_event_count": self._provider_event_count,
                    },
                },
            )
        except Exception:
            logger.exception("Could not persist provider-event truncation")


def _provider_session_id(
    provider: str,
    event: dict[str, Any],
) -> str | None:
    event_type = str(event.get("type") or "").strip()
    if provider == "codex":
        if event_type != "thread.started":
            return None
        candidate = event.get("thread_id")
    elif provider == "claude":
        if event_type != "system" or event.get("subtype") != "init":
            return None
        candidate = event.get("session_id")
    elif provider == "opencode":
        if event_type not in OPENCODE_SESSION_EVENT_TYPES:
            return None
        candidate = event.get("sessionID")
    else:
        return None
    session_id = str(candidate or "").strip()
    return (
        session_id
        if SESSION_ID_PATTERN.fullmatch(session_id)
        else None
    )


def _normalized_provider_event(
    provider: str,
    event: dict[str, Any],
    *,
    sequence: int,
) -> dict[str, Any]:
    event_type = str(event.get("type") or "unknown").strip()[:100] or "unknown"
    subtype = str(event.get("subtype") or "").strip()[:100]
    session_id = _provider_session_id(provider, event)
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    item_id = str(item.get("id") or event.get("id") or "").strip()[:255]
    item_type = str(item.get("type") or "").strip()[:100]
    text = redact_sensitive_text(_event_text(event))[:MAX_PROVIDER_EVENT_TEXT]
    terminal = _terminal_event_state(event)
    canonical = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return {
        "schema_version": "provider_event.v1",
        "provider": provider,
        "sequence": sequence,
        "type": event_type,
        **({"subtype": subtype} if subtype else {}),
        **({"session_id": session_id} if session_id else {}),
        **({"item_id": item_id} if item_id else {}),
        **({"item_type": item_type} if item_type else {}),
        **({"text": text} if text else {}),
        **({"terminal": terminal} if terminal is not None else {}),
        "raw_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _event_text(value: Any, *, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        return value.strip()[:MAX_PROVIDER_EVENT_TEXT]
    if isinstance(value, list):
        parts = [
            _event_text(item, depth=depth + 1)
            for item in value[:20]
        ]
        return " ".join(part for part in parts if part)
    if not isinstance(value, dict):
        return ""
    prioritized = (
        "text",
        "message",
        "content",
        "output",
        "result",
        "item",
        "part",
        "error",
    )
    for key in prioritized:
        if key not in value:
            continue
        text = _event_text(value[key], depth=depth + 1)
        if text:
            return text
    return ""


def _terminal_event_state(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "").strip().casefold()
    subtype = str(event.get("subtype") or "").strip().casefold()
    if event.get("is_error") is True or event_type == "error":
        return "failed"
    if subtype in {"error", "failed", "failure"}:
        return "failed"
    if event_type in {"turn.completed", "result"}:
        return "completed"
    return None


def harness_session_payload(
    observations: Iterable[RunObservation],
) -> dict[str, Any] | None:
    return _public_harness_session(_recorded_harness_session(observations))


async def record_staged_harness_session(
    session: AsyncSession,
    *,
    run: AgentRun,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Persist a context-loaded harness session that has started no turn."""

    public = _public_harness_session(state)
    if public is None:
        raise ValueError("staged harness session state is invalid")
    if public.get("execution_started") is not False:
        raise ValueError("a staged harness session must not start execution")
    session_id = str(public["session_id"])
    await _record_observation(
        session,
        run=run,
        event_key="harness:session",
        event_type="session",
        content=(
            f"Loaded continuation context into {public['provider']} session "
            f"{session_id}; waiting for the user's lead."
        ),
        files=[],
        extra_metadata={"observed_by": "continuation_stager"},
        extra_payload={"harness_session": state},
    )
    run.provider_session_id = session_id
    return public


def recorded_harness_session(
    observations: Iterable[RunObservation],
) -> dict[str, Any] | None:
    return _recorded_harness_session(observations)


def _recorded_harness_session(
    observations: Iterable[RunObservation],
) -> dict[str, Any] | None:
    candidates = sorted(
        (
            observation
            for observation in observations
            if observation.event_key == "harness:session"
        ),
        key=lambda item: (
            item.observed_at or item.created_at,
            str(item.id),
        ),
        reverse=True,
    )
    for observation in candidates:
        try:
            payload = json.loads(observation.payload_json or "{}")
        except (TypeError, ValueError):
            continue
        state = payload.get("harness_session") if isinstance(payload, dict) else None
        if not isinstance(state, dict):
            continue
        provider = str(state.get("provider") or "").strip().lower()
        session_id = str(state.get("session_id") or "").strip()
        if provider not in {"codex", "claude", "opencode"}:
            continue
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            continue
        return dict(state)
    return None


def _public_harness_session(
    state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    provider = str(state.get("provider") or "").strip().lower()
    session_id = str(state.get("session_id") or "").strip()
    if provider not in {"codex", "claude", "opencode"}:
        return None
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        return None
    result: dict[str, Any] = {
        "provider": provider,
        "session_id": session_id,
        "launched": state.get("launched") is True,
        "navigation_requested": state.get("navigation_requested") is True,
        "navigation_verified": state.get("navigation_verified") is True,
        "mode": str(state.get("mode") or "desktop_app"),
        "navigation": str(state.get("navigation") or "app"),
        "exact_session_supported": (
            state.get("exact_session_supported") is True
        ),
        "renderable_activity_observed": (
            state.get("renderable_activity_observed") is True
        ),
    }
    if "awaiting_user" in state:
        result["awaiting_user"] = state.get("awaiting_user") is True
    if "execution_started" in state:
        result["execution_started"] = state.get("execution_started") is True
    if "activation_boundary_verified" in state:
        result["activation_boundary_verified"] = (
            state.get("activation_boundary_verified") is True
        )
    if "observed_turn_count" in state:
        try:
            result["observed_turn_count"] = max(
                0,
                int(state.get("observed_turn_count") or 0),
            )
        except (TypeError, ValueError):
            result["observed_turn_count"] = 0
    for key in (
        "code",
        "message",
        "context_delivery",
        "context_sha256",
        "developer_instructions_sha256",
        "context_schema_version",
    ):
        value = str(state.get(key) or "").strip()
        if value:
            result[key] = value
    identity = state.get("continuation_identity")
    if isinstance(identity, dict):
        result["continuation_identity"] = {
            key: str(identity.get(key) or "").strip() or None
            for key in (
                "task_id",
                "selected_objective",
                "checkpoint_id",
                "source_provider",
                "source_session_id",
            )
        }
    return result
