from __future__ import annotations

import asyncio
import ipaddress
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import Workspace
from app.services.access import AccessScope
from app.services.desktop_overlay import (
    DesktopOverlayError,
    desktop_overlay_manager,
)


router = APIRouter()


class DesktopOverlayUpdate(BaseModel):
    visible: bool
    workspace_id: UUID | None = None

    @model_validator(mode="after")
    def require_workspace_when_showing(self) -> "DesktopOverlayUpdate":
        if self.visible and self.workspace_id is None:
            raise ValueError("workspace_id is required when visible is true")
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
    workspace_id = payload.workspace_id if payload.visible else None
    if workspace_id is not None:
        if not access_scope.allows_workspace(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None or workspace.status != "active":
            raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        status = await asyncio.to_thread(
            desktop_overlay_manager.set_visible,
            payload.visible,
            workspace_id=workspace_id,
            api_url=_local_api_url(request),
        )
    except DesktopOverlayError as exc:
        raise _overlay_http_error(exc) from exc
    return status.to_dict()


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
