from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db_session
from app.models import Connector, SyncJob, Workspace

router = APIRouter()

# ── Catalog ────────────────────────────────────────────────────

CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    "slack": {
        "name": "Slack",
        "description": "Channels, DMs, and thread history",
        "color": "#4A154B",
        "availability": "available",
        "provider": "native",
        "provider_label": "Built in",
    },
    "zoom": {
        "name": "Zoom",
        "description": "Meeting transcripts and recording metadata",
        "color": "#0B5CFF",
        "availability": "available",
        "provider": "official_api",
        "provider_label": "Official API",
    },
    "gdrive": {
        "name": "Google Drive",
        "description": "Docs, Sheets, Slides, and folder content",
        "color": "#0F9D58",
        "availability": "available",
        "provider": "official_api",
        "provider_label": "Official API",
    },
    "gmail": {
        "name": "Gmail",
        "description": "Email threads, attachments, and sender context",
        "color": "#EA4335",
        "availability": "available",
        "provider": "official_api",
        "provider_label": "Official API",
    },
}

GOOGLE_CONNECTORS = {"gdrive", "gmail"}


def _get_env(key: str) -> str | None:
    import os
    return os.environ.get(key) or None


def _public_base_url() -> str:
    """Return the externally-reachable base URL (no trailing slash).

    Priority:
    1. REPLIT_DEV_DOMAIN env var  →  https://<domain>
    2. PUBLIC_BASE_URL env var    →  used as-is (strip trailing slash)
    Fallback to empty string (caller must still work but redirect_uri will be wrong).
    """
    import os
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if dev_domain:
        return f"https://{dev_domain}"
    pub = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return pub


def _slack_configured() -> bool:
    return bool(_get_env("SLACK_CLIENT_ID") and _get_env("SLACK_CLIENT_SECRET"))


def _zoom_configured() -> bool:
    return bool(_get_env("ZOOM_CLIENT_ID") and _get_env("ZOOM_CLIENT_SECRET"))


def _google_configured() -> bool:
    return bool(_get_env("GOOGLE_CLIENT_ID") and _get_env("GOOGLE_CLIENT_SECRET"))



def _connector_setup_status(connector_type: str) -> dict[str, Any]:
    base = _public_base_url()
    if connector_type == "slack":
        configured = _slack_configured()
        managed = configured
        redirect_uri = _get_env("SLACK_REDIRECT_URI") or (f"{base}/api/connectors/slack/callback" if base else None)
        return {
            "connector_type": "slack",
            "configured": configured,
            "managed_available": managed,
            "managed_install_url": "/api/connectors/slack/install" if managed else None,
            "missing": [] if configured else ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"],
            "message": None if configured else "Add SLACK_CLIENT_ID and SLACK_CLIENT_SECRET to enable one-click OAuth.",
            "redirect_uri": redirect_uri,
        }
    if connector_type == "zoom":
        configured = _zoom_configured()
        redirect_uri = _get_env("ZOOM_REDIRECT_URI") or (f"{base}/api/connectors/zoom/callback" if base else None)
        return {
            "connector_type": "zoom",
            "configured": configured,
            "managed_available": configured,
            "managed_install_url": "/api/connectors/zoom/install" if configured else None,
            "missing": [] if configured else ["ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"],
            "message": None,
            "redirect_uri": redirect_uri,
        }
    if connector_type in GOOGLE_CONNECTORS:
        configured = _google_configured()
        redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or (f"{base}/api/connectors/{connector_type}/callback" if base else None)
        return {
            "connector_type": connector_type,
            "configured": configured,
            "managed_available": configured,
            "managed_install_url": f"/api/connectors/{connector_type}/install" if configured else None,
            "missing": [] if configured else ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
            "message": None,
            "redirect_uri": redirect_uri,
        }
    return {"connector_type": connector_type, "configured": True, "managed_available": False, "managed_install_url": None, "missing": [], "redirect_uri": None}


# ── DB helpers ─────────────────────────────────────────────────

async def _get_workspace(workspace_id: str, session: AsyncSession) -> Workspace:
    try:
        ws_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid workspace_id")
    ws = await session.get(Workspace, ws_uuid)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


async def _get_or_create_connector(
    workspace_id: UUID,
    connector_type: str,
    session: AsyncSession,
) -> Connector:
    result = await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type == connector_type,
        )
    )
    connector = result.first()
    if not connector:
        connector = Connector(
            workspace_id=workspace_id,
            connector_type=connector_type,
            status="disconnected",
        )
        session.add(connector)
        await session.flush()
    return connector


def _connector_to_dict(connector: Connector) -> dict[str, Any]:
    config = json.loads(connector.config_json or "{}")
    updated_at = connector.__dict__.get("updated_at")
    created_at = connector.__dict__.get("created_at")
    last_sync_at = connector.__dict__.get("last_sync_at")
    return {
        "id": str(connector.id),
        "workspace_id": str(connector.workspace_id),
        "connector_type": connector.connector_type,
        "status": connector.status,
        "config": config,
        "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


# ── Workspace endpoints ────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str
    slug: str | None = None


@router.get("/workspaces")
async def list_workspaces(session: AsyncSession = Depends(get_db_session)) -> list[dict]:
    result = await session.scalars(select(Workspace).order_by(Workspace.created_at))
    workspaces = list(result)
    if not workspaces:
        ws = Workspace(name="Default", slug="default")
        session.add(ws)
        await session.commit()
        await session.refresh(ws)
        workspaces = [ws]
    return [{"id": str(ws.id), "name": ws.name, "slug": ws.slug} for ws in workspaces]


@router.post("/workspaces", status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    slug = payload.slug or payload.name.lower().replace(" ", "-")
    ws = Workspace(name=payload.name, slug=slug)
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    return {"id": str(ws.id), "name": ws.name, "slug": ws.slug}


# ── Connector list + setup status ──────────────────────────────

@router.get("/connectors")
async def list_connectors(
    workspace_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    ws = await _get_workspace(workspace_id, session)
    result = await session.scalars(
        select(Connector).where(Connector.workspace_id == ws.id)
    )
    connectors = {c.connector_type: c for c in result}
    return [_connector_to_dict(c) for c in connectors.values()]


@router.get("/connectors/setup-status")
async def connector_setup_status() -> list[dict]:
    return [_connector_setup_status(ct) for ct in CONNECTOR_CATALOG]


@router.get("/connectors/processing-summary")
async def connector_processing_summary(
    workspace_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    ws = await _get_workspace(workspace_id, session)
    result = await session.scalars(
        select(Connector).where(Connector.workspace_id == ws.id)
    )
    items = []
    for connector in result:
        config = json.loads(connector.config_json or "{}")
        items.append({
            "connectorType": connector.connector_type,
            "connector_type": connector.connector_type,
            "processedDocuments": config.get("processed_count", 0),
            "unprocessedDocuments": 0,
        })
    return {"items": items}


# ── Slack OAuth ────────────────────────────────────────────────

@router.post("/connectors/slack/oauth-settings")
async def save_slack_oauth_settings(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    import os
    client_id = payload.get("client_id", "").strip()
    client_secret = payload.get("client_secret", "").strip()
    redirect_uri = payload.get("redirect_uri", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="client_id and client_secret are required")
    os.environ["SLACK_CLIENT_ID"] = client_id
    os.environ["SLACK_CLIENT_SECRET"] = client_secret
    if redirect_uri:
        os.environ["SLACK_REDIRECT_URI"] = redirect_uri
    return {"ok": True, "message": "Slack OAuth settings saved for this session."}


@router.get("/connectors/slack/install")
async def slack_install(workspace_id: str, request: Request) -> RedirectResponse:
    client_id = _get_env("SLACK_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Slack OAuth is not configured on this server.")
    redirect_uri = _get_env("SLACK_REDIRECT_URI") or f"{_public_base_url()}/api/connectors/slack/callback"
    state = f"{workspace_id}:{secrets.token_urlsafe(16)}"
    scopes = "channels:history,channels:read,groups:history,groups:read,users:read,team:read"
    url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/connectors/slack/callback")
async def slack_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    if error:
        return _oauth_close_html(success=False, message=f"Slack OAuth error: {error}")
    if not code or not state:
        return _oauth_close_html(success=False, message="Missing code or state.")

    workspace_id = state.split(":")[0]
    try:
        ws = await _get_workspace(workspace_id, session)
    except HTTPException:
        return _oauth_close_html(success=False, message="Workspace not found.")

    import httpx
    client_id = _get_env("SLACK_CLIENT_ID")
    client_secret = _get_env("SLACK_CLIENT_SECRET")
    redirect_uri = _get_env("SLACK_REDIRECT_URI")

    try:
        async with httpx.AsyncClient() as http:
            params: dict[str, str] = {
                "client_id": client_id or "",
                "client_secret": client_secret or "",
                "code": code,
            }
            if redirect_uri:
                params["redirect_uri"] = redirect_uri
            resp = await http.post("https://slack.com/api/oauth.v2.access", data=params)
            data = resp.json()
    except Exception as exc:
        return _oauth_close_html(success=False, message=f"OAuth exchange failed: {exc}")

    if not data.get("ok"):
        return _oauth_close_html(success=False, message=data.get("error", "Slack OAuth failed."))

    access_token = data.get("access_token") or data.get("authed_user", {}).get("access_token", "")
    team = data.get("team", {})
    connector = await _get_or_create_connector(ws.id, "slack", session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({"access_token": access_token})
    config = json.loads(connector.config_json or "{}")
    config.update({
        "team_name": team.get("name", ""),
        "team_id": team.get("id", ""),
        "scope": data.get("scope", ""),
        "auth_mode": "oauth",
    })
    connector.config_json = json.dumps(config)
    await session.commit()
    return _oauth_close_html(success=True, message="Slack connected successfully.")


# ── Zoom OAuth ─────────────────────────────────────────────────

@router.get("/connectors/zoom/install")
async def zoom_install(workspace_id: str, request: Request) -> RedirectResponse:
    client_id = _get_env("ZOOM_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Zoom OAuth is not configured on this server.")
    redirect_uri = _get_env("ZOOM_REDIRECT_URI") or f"{_public_base_url()}/api/connectors/zoom/callback"
    state = f"{workspace_id}:{secrets.token_urlsafe(16)}"
    url = (
        f"https://zoom.us/oauth/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/connectors/zoom/callback")
async def zoom_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    if error:
        return _oauth_close_html(success=False, message=f"Zoom OAuth error: {error}")
    if not code or not state:
        return _oauth_close_html(success=False, message="Missing code or state.")

    workspace_id = state.split(":")[0]
    try:
        ws = await _get_workspace(workspace_id, session)
    except HTTPException:
        return _oauth_close_html(success=False, message="Workspace not found.")

    import base64
    import httpx
    client_id = _get_env("ZOOM_CLIENT_ID") or ""
    client_secret = _get_env("ZOOM_CLIENT_SECRET") or ""
    redirect_uri = _get_env("ZOOM_REDIRECT_URI") or f"{_public_base_url()}/api/connectors/zoom/callback"
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://zoom.us/oauth/token",
                headers={"Authorization": f"Basic {credentials}"},
                params={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            )
            data = resp.json()
    except Exception as exc:
        return _oauth_close_html(success=False, message=f"OAuth exchange failed: {exc}")

    if "access_token" not in data:
        return _oauth_close_html(success=False, message=data.get("reason", "Zoom OAuth failed."))

    connector = await _get_or_create_connector(ws.id, "zoom", session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
    })
    config = json.loads(connector.config_json or "{}")
    config.update({"auth_mode": "oauth", "ingestion_mode": "transcripts_only"})
    connector.config_json = json.dumps(config)
    await session.commit()
    return _oauth_close_html(success=True, message="Zoom connected successfully.")


@router.post("/connectors/zoom/connect")
async def zoom_connect_token(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    workspace_id = payload.get("workspace_id")
    token = payload.get("token", "").strip()
    if not workspace_id or not token:
        raise HTTPException(status_code=422, detail="workspace_id and token are required")
    ws = await _get_workspace(workspace_id, session)
    connector = await _get_or_create_connector(ws.id, "zoom", session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({"access_token": token})
    config = json.loads(connector.config_json or "{}")
    config.update({"auth_mode": "manual_token", "ingestion_mode": "transcripts_only"})
    connector.config_json = json.dumps(config)
    await session.commit()
    await session.refresh(connector)
    return _connector_to_dict(connector)


# ── Google Drive & Gmail OAuth ─────────────────────────────────

_GOOGLE_SCOPES = {
    "gdrive": "https://www.googleapis.com/auth/drive.readonly",
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
}


@router.get("/connectors/{connector_type}/install")
async def google_install(
    connector_type: str,
    workspace_id: str,
    request: Request,
) -> RedirectResponse:
    if connector_type not in GOOGLE_CONNECTORS:
        raise HTTPException(status_code=404, detail="Connector not found")
    client_id = _get_env("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured on this server.")
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or f"{_public_base_url()}/api/connectors/{connector_type}/callback"
    state = f"{workspace_id}:{connector_type}:{secrets.token_urlsafe(16)}"
    scope = _GOOGLE_SCOPES[connector_type]
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/connectors/{connector_type}/callback")
async def google_callback(
    connector_type: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    if connector_type not in GOOGLE_CONNECTORS:
        raise HTTPException(status_code=404, detail="Connector not found")
    if error:
        return _oauth_close_html(success=False, message=f"Google OAuth error: {error}")
    if not code or not state:
        return _oauth_close_html(success=False, message="Missing code or state.")

    parts = state.split(":")
    workspace_id = parts[0]
    try:
        ws = await _get_workspace(workspace_id, session)
    except HTTPException:
        return _oauth_close_html(success=False, message="Workspace not found.")

    import httpx
    client_id = _get_env("GOOGLE_CLIENT_ID") or ""
    client_secret = _get_env("GOOGLE_CLIENT_SECRET") or ""
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or f"{_public_base_url()}/api/connectors/{connector_type}/callback"

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
    except Exception as exc:
        return _oauth_close_html(success=False, message=f"OAuth exchange failed: {exc}")

    if "access_token" not in data:
        return _oauth_close_html(success=False, message=data.get("error_description", "Google OAuth failed."))

    connector = await _get_or_create_connector(ws.id, connector_type, session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_in": data.get("expires_in"),
    })
    config = json.loads(connector.config_json or "{}")
    config.update({"auth_mode": "oauth"})
    connector.config_json = json.dumps(config)
    await session.commit()
    label = "Google Drive" if connector_type == "gdrive" else "Gmail"
    return _oauth_close_html(success=True, message=f"{label} connected successfully.")


# ── Notion (token-based) ───────────────────────────────────────

@router.post("/connectors/notion/connect")
async def notion_connect(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    workspace_id = payload.get("workspace_id")
    token = payload.get("token", "").strip()
    if not workspace_id or not token:
        raise HTTPException(status_code=422, detail="workspace_id and token are required")
    ws = await _get_workspace(workspace_id, session)
    connector = await _get_or_create_connector(ws.id, "notion", session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({"access_token": token})
    config = json.loads(connector.config_json or "{}")
    config.update({"auth_mode": "manual_token"})
    connector.config_json = json.dumps(config)
    await session.commit()
    return _connector_to_dict(connector)


# ── GitHub (token-based) ───────────────────────────────────────

@router.post("/connectors/github/connect")
async def github_connect(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    workspace_id = payload.get("workspace_id")
    token = payload.get("token", "").strip()
    repositories = payload.get("repositories", [])
    if not workspace_id or not token:
        raise HTTPException(status_code=422, detail="workspace_id and token are required")
    ws = await _get_workspace(workspace_id, session)
    connector = await _get_or_create_connector(ws.id, "github", session)
    connector.status = "connected"
    connector.credentials_json = json.dumps({"access_token": token})
    config = json.loads(connector.config_json or "{}")
    config.update({"auth_mode": "manual_token", "repositories": repositories})
    connector.config_json = json.dumps(config)
    await session.commit()
    await session.refresh(connector)
    return _connector_to_dict(connector)


# ── Sync & disconnect ──────────────────────────────────────────

@router.post("/connectors/{connector_id}/sync")
async def sync_connector(
    connector_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connector_id")
    connector = await session.get(Connector, cid)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector.status not in ("connected", "error"):
        raise HTTPException(status_code=422, detail="Connector is not connected")

    job = SyncJob(connector_id=cid, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    background_tasks.add_task(_run_sync_job, str(job.id), str(cid), settings.database_url)
    return {
        "job_id": str(job.id),
        "connector_id": str(cid),
        "status": "pending",
        "message": f"Sync queued for {connector.connector_type}.",
    }


@router.get("/connectors/{connector_id}/sync-status")
async def get_sync_status(
    connector_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict | None:
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connector_id")
    result = await session.scalars(
        select(SyncJob)
        .where(SyncJob.connector_id == cid)
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    job = result.first()
    if not job:
        return None
    return _job_to_dict(job)


@router.get("/connectors/{connector_id}/sync-jobs")
async def list_sync_jobs(
    connector_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connector_id")
    result = await session.scalars(
        select(SyncJob)
        .where(SyncJob.connector_id == cid)
        .order_by(SyncJob.created_at.desc())
        .limit(20)
    )
    return [_job_to_dict(j) for j in result]


@router.delete("/connectors/{connector_id}")
async def disconnect_connector(
    connector_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connector_id")
    connector = await session.get(Connector, cid)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    connector.status = "disconnected"
    connector.credentials_json = "{}"
    config = json.loads(connector.config_json or "{}")
    config.pop("team_name", None)
    config.pop("team_id", None)
    config.pop("auth_mode", None)
    connector.config_json = json.dumps(config)
    await session.commit()
    return {"ok": True}


# ── Helpers ────────────────────────────────────────────────────

def _job_to_dict(job: SyncJob) -> dict:
    d = job.__dict__
    created_at = d.get("created_at")
    started_at = d.get("started_at")
    completed_at = d.get("completed_at")
    return {
        "id": str(job.id),
        "job_id": str(job.id),
        "connector_id": str(job.connector_id),
        "status": job.status,
        "error_type": d.get("error_type"),
        "error_message": d.get("error_message"),
        "result_metadata": json.loads(d.get("result_metadata_json") or "{}"),
        "started_at": started_at.isoformat() if started_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "created_at": created_at.isoformat() if created_at else None,
    }


def _oauth_close_html(success: bool, message: str) -> Response:
    color = "#16a34a" if success else "#dc2626"
    icon = "✓" if success else "✗"
    script = "window.opener && window.opener.postMessage('oauth-complete', '*'); window.close();"
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OAuth</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:#fff;border-radius:12px;padding:2rem 2.5rem;box-shadow:0 4px 24px #0001;text-align:center;max-width:380px}}
.icon{{font-size:2.5rem;color:{color}}}p{{color:#374151;margin:.75rem 0 0}}</style></head>
<body><div class="card"><div class="icon">{icon}</div><p>{message}</p></div>
<script>{script}</script></body></html>"""
    return Response(content=html, media_type="text/html")


async def _run_sync_job(job_id: str, connector_id: str, database_url: str) -> None:
    """Background task: mark job running → do minimal sync → mark completed."""
    from app.database import _make_async_url
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    engine = create_async_engine(_make_async_url(database_url))
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        job = await session.get(SyncJob, UUID(job_id))
        connector = await session.get(Connector, UUID(connector_id))
        if not job or not connector:
            await engine.dispose()
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            docs_fetched = 0
            result_metadata: dict[str, Any] = {
                "documents_fetched": docs_fetched,
                "documents_persisted": 0,
                "documents_processed": 0,
                "sync_mode": "polling",
            }
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.result_metadata_json = json.dumps(result_metadata)

            config = json.loads(connector.config_json or "{}")
            config["total_processed_count"] = config.get("total_processed_count", 0)
            connector.config_json = json.dumps(config)
            connector.last_sync_at = datetime.now(timezone.utc)
            await session.commit()
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

    await engine.dispose()
