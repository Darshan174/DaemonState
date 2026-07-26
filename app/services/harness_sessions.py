from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _record_observation
from app.models import AgentRun, RunObservation
from app.services.harness_launcher import (
    SESSION_ID_PATTERN,
    HarnessLaunchError,
    launch_harness_session,
)


MAX_PROVIDER_EVENT_LINE_BYTES = 131_072
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

    @property
    def state(self) -> dict[str, Any] | None:
        return _public_harness_session(self._state)

    async def observe_stdout_chunk(self, chunk: bytes) -> None:
        if self._persisted or not chunk:
            return
        self._buffer.extend(chunk)
        while not self._persisted:
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
            await self._request_navigation_and_persist()

    async def _observe_line(self, line: bytes) -> None:
        if not line or len(line) > MAX_PROVIDER_EVENT_LINE_BYTES:
            return
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            return
        if not isinstance(event, dict):
            return

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
            self._persisted = True
        except Exception:
            # The provider must keep running even if session-link persistence
            # fails. Command and repository evidence are recorded independently.
            logger.exception("Could not persist the captured harness session")


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


def harness_session_payload(
    observations: Iterable[RunObservation],
) -> dict[str, Any] | None:
    return _public_harness_session(_recorded_harness_session(observations))


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
    }
    for key in ("code", "message"):
        value = str(state.get(key) or "").strip()
        if value:
            result[key] = value
    return result
