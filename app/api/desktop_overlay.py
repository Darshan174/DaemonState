from __future__ import annotations

import asyncio
import ipaddress
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import Workspace
from app.services.access import AccessScope
from app.services.desktop_overlay import (
    MAX_SELECTED_SESSIONS,
    MAX_SELECTED_SESSION_ID_LENGTH,
    MAX_SELECTED_SESSION_TITLE_LENGTH,
    SELECTED_SESSION_PROVIDERS,
    DesktopOverlayError,
    DesktopOverlaySelectedSession,
    desktop_overlay_manager,
)
from app.services.session_library import build_session_library


router = APIRouter()


class DesktopOverlaySelectedSessionUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=20)
    session_id: str = Field(
        min_length=1,
        max_length=MAX_SELECTED_SESSION_ID_LENGTH,
    )
    title: str = Field(
        min_length=1,
        max_length=MAX_SELECTED_SESSION_TITLE_LENGTH,
    )
    ordinal: int = Field(strict=True, ge=1, le=MAX_SELECTED_SESSIONS)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("provider must be text")
        normalized = value.strip().lower()
        if normalized not in SELECTED_SESSION_PROVIDERS:
            raise ValueError("provider must be codex, claude, or opencode")
        return normalized

    @field_validator("session_id", "title", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("value must be text")
        return value.strip()


class DesktopOverlayUpdate(BaseModel):
    visible: bool
    workspace_id: UUID | None = None
    selected_sessions: list[DesktopOverlaySelectedSessionUpdate] | None = Field(
        default=None,
        max_length=MAX_SELECTED_SESSIONS,
    )

    @model_validator(mode="after")
    def require_workspace_when_showing(self) -> "DesktopOverlayUpdate":
        if self.visible and self.workspace_id is None:
            raise ValueError("workspace_id is required when visible is true")
        selected_sessions_supplied = "selected_sessions" in self.model_fields_set
        if selected_sessions_supplied and self.selected_sessions is None:
            raise ValueError("selected_sessions must be a list when supplied")
        if self.selected_sessions and self.workspace_id is None:
            raise ValueError("workspace_id is required when selected_sessions is non-empty")

        seen_identities: set[tuple[str, str]] = set()
        seen_ordinals: set[int] = set()
        for selected in self.selected_sessions or []:
            identity = (selected.provider, selected.session_id)
            if identity in seen_identities:
                raise ValueError("selected_sessions must be unique")
            if selected.ordinal in seen_ordinals:
                raise ValueError("selected session ordinals must be unique")
            seen_identities.add(identity)
            seen_ordinals.add(selected.ordinal)
        return self


@router.get("/desktop/overlay")
async def desktop_overlay_status(
    request: Request,
    workspace_id: UUID | None = Query(default=None),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    _require_local_desktop_request(request, access_scope)
    if workspace_id is not None and not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        status = await asyncio.to_thread(desktop_overlay_manager.status)
    except DesktopOverlayError as exc:
        raise _overlay_http_error(exc) from exc
    return status.to_dict()


@router.put("/desktop/overlay")
async def update_desktop_overlay(
    payload: DesktopOverlayUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    _require_local_desktop_request(request, access_scope)
    selected_sessions_supplied = "selected_sessions" in payload.model_fields_set
    workspace_id = (
        payload.workspace_id if payload.visible or bool(payload.selected_sessions) else None
    )
    if workspace_id is not None:
        if not access_scope.allows_workspace(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None or workspace.status != "active":
            raise HTTPException(status_code=404, detail="Workspace not found")
    selected_sessions = await _canonical_selected_sessions(
        payload.selected_sessions if selected_sessions_supplied else None,
        workspace_id=workspace_id,
        session=session,
        access_scope=access_scope,
    )
    try:
        status = await asyncio.to_thread(
            desktop_overlay_manager.set_visible,
            payload.visible,
            workspace_id=workspace_id,
            api_url=_local_api_url(request),
            selected_sessions=selected_sessions,
        )
    except DesktopOverlayError as exc:
        raise _overlay_http_error(exc) from exc
    return status.to_dict()


async def _canonical_selected_sessions(
    requested: list[DesktopOverlaySelectedSessionUpdate] | None,
    *,
    workspace_id: UUID | None,
    session: AsyncSession,
    access_scope: AccessScope,
) -> tuple[DesktopOverlaySelectedSession, ...] | None:
    if requested is None:
        return None
    if not requested:
        return ()
    if workspace_id is None:
        # The request model normally catches this. Keep the helper fail-closed
        # if it is reused independently.
        raise HTTPException(
            status_code=422,
            detail="workspace_id is required for selected sessions",
        )

    try:
        library = await build_session_library(
            session,
            workspace_id,
            access_scope=access_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    library_sessions: dict[tuple[str, str], dict] = {}
    for value in library.get("sessions", []):
        if not isinstance(value, dict):
            continue
        provider = str(value.get("connector_type") or "").strip().lower()
        session_id = str(value.get("session_id") or "").strip()
        if provider in SELECTED_SESSION_PROVIDERS and session_id:
            library_sessions[(provider, session_id)] = value

    canonical: list[DesktopOverlaySelectedSession] = []
    for selected in requested:
        library_session = library_sessions.get(
            (selected.provider, selected.session_id),
        )
        if library_session is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A selected session is not available in the requested "
                    "workspace's session library."
                ),
            )
        canonical_title = str(library_session.get("title") or "").strip()
        if not canonical_title or len(canonical_title) > MAX_SELECTED_SESSION_TITLE_LENGTH:
            canonical_title = selected.title
        canonical.append(
            DesktopOverlaySelectedSession(
                provider=selected.provider,
                session_id=selected.session_id,
                title=canonical_title,
                ordinal=selected.ordinal,
            )
        )
    return tuple(sorted(canonical, key=lambda value: value.ordinal))


def _local_api_url(request: Request) -> str:
    server = request.scope.get("server")
    port = (
        server[1]
        if (
            isinstance(server, (list, tuple))
            and len(server) == 2
            and isinstance(server[1], int)
            and not isinstance(server[1], bool)
            and 0 < server[1] <= 65_535
        )
        else None
    )
    scheme = str(request.scope.get("scheme") or "http").lower()
    if scheme not in {"http", "https"}:
        scheme = "http"
    resolved_port = port or (443 if scheme == "https" else 80)
    return f"{scheme}://127.0.0.1:{resolved_port}/api"


def _require_local_desktop_request(
    request: Request,
    access_scope: AccessScope,
) -> None:
    client = request.client
    host = str(client.host if client is not None else "").strip()
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        address = None
    is_loopback = bool(
        address
        and (
            address.is_loopback
            or (
                isinstance(address, ipaddress.IPv6Address)
                and address.ipv4_mapped is not None
                and address.ipv4_mapped.is_loopback
            )
        )
    )
    if not is_loopback or access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": (
                    "The floating context control can be changed only from "
                    "the local DaemonState app."
                ),
            },
        )


def _overlay_http_error(error: DesktopOverlayError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": error.code, "message": str(error)},
    )
