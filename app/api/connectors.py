from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db_session
from app.models import Connector, SourceDocument, SyncJob, Workspace

router = APIRouter()
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000000")

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
    "github": {
        "name": "GitHub",
        "description": "Issues, pull requests, and code review discussions",
        "color": "#24292e",
        "availability": "available",
        "provider": "native",
        "provider_label": "Personal Access Token",
    },
    "discord": {
        "name": "Discord",
        "description": "Server channels, threads, and community context",
        "color": "#5865F2",
        "availability": "coming_soon",
        "provider": "official_api",
        "provider_label": "Coming soon",
    },
    "ai_context": {
        "name": "AI Context",
        "description": "Codex, Claude Code, OpenCode, plans, diffs, and review notes",
        "color": "#10a37f",
        "availability": "available",
        "provider": "native",
        "provider_label": "Session import",
    },
    "local": {
        "name": "Local Files",
        "description": "Uploaded Markdown, text, JSON, CSV, and other local documents",
        "color": "#64748B",
        "availability": "available",
        "provider": "native",
        "provider_label": "Upload",
    },
    "zoom": {
        "name": "Zoom",
        "description": "Meeting transcripts and recording metadata",
        "color": "#0B5CFF",
        "availability": "coming_soon",
        "provider": "official_api",
        "provider_label": "Official API",
    },
    "gdrive": {
        "name": "Google Drive",
        "description": "Docs, Sheets, Slides, and folder content",
        "color": "#ffffff",
        "availability": "available",
        "provider": "official_api",
        "provider_label": "Official API",
    },
    "gmail": {
        "name": "Gmail",
        "description": "Email threads, attachments, and sender context",
        "color": "#ffffff",
        "availability": "available",
        "provider": "official_api",
        "provider_label": "Official API",
    },
    "codex": {
        "name": "Codex",
        "description": "OpenAI Codex sessions — decisions, code plans, and AI reasoning",
        "color": "#10a37f",
        "availability": "available",
        "provider": "native",
        "provider_label": "Session import",
    },
    "claude": {
        "name": "Claude",
        "description": "Anthropic Claude conversations — architecture choices and research threads",
        "color": "#D97757",
        "availability": "available",
        "provider": "native",
        "provider_label": "Session import",
    },
    "opencode": {
        "name": "OpenCode",
        "description": "OpenCode AI coding sessions — terminal context and implementation notes",
        "color": "#000000",
        "availability": "available",
        "provider": "native",
        "provider_label": "Session import",
    },
    "wispr_flow": {
        "name": "Wispr Flow",
        "description": "Voice notes, transcripts, and dictated project context",
        "color": "#111827",
        "availability": "coming_soon",
        "provider": "official_api",
        "provider_label": "Coming soon",
    },
}

GOOGLE_CONNECTORS = {"gdrive", "gmail"}
AI_SESSION_CONNECTORS = {"codex", "claude", "opencode"}
DISCONNECT_CONFIG_KEYS = {
    "account_id",
    "auth_mode",
    "email_address",
    "ingestion_mode",
    "last_webhook_event",
    "last_webhook_received_at",
    "message",
    "repositories",
    "scope",
    "source_focus",
    "sync_mode",
    "sync_mode_note",
    "sync_queued_at",
    "team_id",
    "team_name",
    "user_email",
}


def _get_env(key: str) -> str | None:
    import os
    return os.environ.get(key) or getattr(settings, key.lower(), None) or None


def _get_google_client_id() -> str | None:
    """Read GOOGLE_CLIENT_ID and strip accidental URL wrappers.

    Users sometimes paste the client ID as a full URL, e.g.:
      http://204406203409-xxx.apps.googleusercontent.com/
    Strip any scheme prefix and trailing slashes so Google accepts it.
    """
    import re
    raw = _get_env("GOOGLE_CLIENT_ID")
    if not raw:
        return None
    cleaned = re.sub(r'^https?://', '', raw).rstrip('/')
    return cleaned or None


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
    pub = (_get_env("PUBLIC_BASE_URL") or "").rstrip("/")
    return pub


def _request_base_url(request: Request | None) -> str:
    return str(request.base_url).rstrip("/") if request else ""


def _callback_url(path: str, request: Request | None = None) -> str:
    base = _public_base_url() or _request_base_url(request)
    return f"{base}{path}" if base else path


def _slack_configured() -> bool:
    return bool(_get_env("SLACK_CLIENT_ID") and _get_env("SLACK_CLIENT_SECRET"))


def _slack_managed_install_url() -> str | None:
    url = _get_env("SLACK_MANAGED_INSTALL_URL")
    return url.rstrip("?&") if url else None


def _decrypt_managed_token(encrypted_token: str) -> str:
    key = _get_env("ENCRYPTION_KEY")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="ENCRYPTION_KEY is required for managed Slack OAuth callbacks.",
        )
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="cryptography is required for managed Slack OAuth callbacks.",
        ) from exc
    try:
        return Fernet(key.encode()).decrypt(encrypted_token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid managed Slack OAuth token.") from exc


def _zoom_configured() -> bool:
    return bool(_get_env("ZOOM_CLIENT_ID") and _get_env("ZOOM_CLIENT_SECRET"))


def _google_configured() -> bool:
    return bool(_get_google_client_id() and _get_env("GOOGLE_CLIENT_SECRET"))



def _connector_setup_status(connector_type: str, request: Request | None = None) -> dict[str, Any]:
    base = _public_base_url() or _request_base_url(request)
    if connector_type == "slack":
        configured = _slack_configured()
        managed_url = _slack_managed_install_url()
        managed = bool(managed_url and configured)
        redirect_uri = _get_env("SLACK_REDIRECT_URI") or (f"{base}/api/connectors/slack/callback" if base else None)
        return {
            "connector_type": "slack",
            "configured": configured,
            "managed_available": managed,
            "managed_install_url": "/api/connectors/slack/managed/install" if managed else None,
            "missing": [] if configured else ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"],
            "status": "disconnected",
            "message": (
                "Managed Slack OAuth is available."
                if managed
                else None if configured
                else "Add SLACK_CLIENT_ID and SLACK_CLIENT_SECRET for self-hosted OAuth, or configure SLACK_MANAGED_INSTALL_URL for one-click OAuth."
            ),
            "redirect_uri": redirect_uri,
        }
    if connector_type == "zoom":
        configured = False
        redirect_uri = _get_env("ZOOM_REDIRECT_URI") or (f"{base}/api/connectors/zoom/callback" if base else None)
        return {
            "connector_type": "zoom",
            "configured": configured,
            "managed_available": configured,
            "managed_install_url": "/api/connectors/zoom/install" if configured else None,
            "missing": [] if configured else ["ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"],
            "status": "coming_soon",
            "message": None,
            "redirect_uri": redirect_uri,
        }
    if connector_type in GOOGLE_CONNECTORS:
        configured = _google_configured()
        redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or (f"{base}/api/connectors/{connector_type}/callback" if base else None)
        label = CONNECTOR_CATALOG[connector_type]["name"]
        return {
            "connector_type": connector_type,
            "configured": configured,
            "managed_available": configured,
            "managed_install_url": f"/api/connectors/{connector_type}/install" if configured else None,
            "missing": [] if configured else ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
            "status": "disconnected",
            "message": None if configured else f"Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable {label} OAuth.",
            "redirect_uri": redirect_uri,
        }
    if connector_type == "github":
        return {
            "connector_type": "github",
            "configured": True,
            "managed_available": False,
            "managed_install_url": None,
            "missing": [],
            "redirect_uri": None,
            "status": "disconnected",
            "message": "Provide a GitHub Personal Access Token with repo:read scope and a list of owner/repo targets.",
        }
    if connector_type in AI_SESSION_CONNECTORS:
        return {"connector_type": connector_type, "configured": True, "managed_available": False, "managed_install_url": None, "missing": [], "redirect_uri": None, "status": "disconnected"}
    if connector_type in {"ai_context", "local"}:
        return {"connector_type": connector_type, "configured": True, "managed_available": False, "managed_install_url": None, "missing": [], "redirect_uri": None, "status": "disconnected"}
    status = "coming_soon" if CONNECTOR_CATALOG.get(connector_type, {}).get("availability") == "coming_soon" else "disconnected"
    return {"connector_type": connector_type, "configured": False, "managed_available": False, "managed_install_url": None, "missing": [], "redirect_uri": None, "status": status}


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


async def _get_or_create_default_workspace(session: AsyncSession) -> Workspace:
    ws = await session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if ws is None:
        ws = Workspace(id=DEFAULT_WORKSPACE_ID, name="Default", slug="default")
        session.add(ws)
        await session.flush()
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


def _decorate_setup_status(status: dict[str, Any]) -> dict[str, Any]:
    connector_type = status["connector_type"]
    status.setdefault("type", connector_type)
    status.setdefault("status", "connected" if status.get("configured") else "disconnected")
    return status


def _catalog_connector_entry(
    connector_type: str,
    connector: Connector | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    catalog = CONNECTOR_CATALOG[connector_type]
    setup = _connector_setup_status(connector_type, request)
    default_status = "disconnected"
    status = connector.status if connector else default_status
    configured = bool(setup.get("configured")) and catalog["availability"] == "available"
    if connector and connector.status == "connected":
        configured = True
    message = setup.get("message")
    if catalog["availability"] == "coming_soon":
        configured = False
        message = message or f"{catalog['name']} ingestion is not available yet."
    return {
        "connector_id": str(connector.id) if connector else None,
        "id": str(connector.id) if connector else connector_type,
        "type": connector_type,
        "connector_type": connector_type,
        "name": catalog["name"],
        "description": catalog["description"],
        "color": catalog["color"],
        "availability": catalog["availability"],
        "status": status,
        "provider": catalog["provider"],
        "provider_label": catalog.get("provider_label"),
        "is_configured": configured,
        "config": _loads_json_dict(connector.config_json) if connector else {},
        "message": message,
    }


def _loads_json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _revoke_slack_token(access_token: str) -> dict[str, Any] | None:
    if not access_token:
        return None
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                "https://slack.com/api/auth.revoke",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            data = response.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error", "slack_revoke_failed")}
    return {"ok": True}


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
    request: Request,
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if workspace_id:
        ws = await _get_workspace(workspace_id, session)
        result = await session.scalars(select(Connector).where(Connector.workspace_id == ws.id))
    else:
        result = await session.scalars(select(Connector))
    connectors = {c.connector_type: c for c in result}
    setup_status = [_decorate_setup_status(_connector_setup_status(ct, request)) for ct in CONNECTOR_CATALOG]
    return {
        "connectors": [_catalog_connector_entry(ct, connectors.get(ct), request) for ct in CONNECTOR_CATALOG],
        "setupStatus": setup_status,
    }


@router.get("/connectors/setup-status")
async def connector_setup_status(request: Request) -> list[dict]:
    return [_decorate_setup_status(_connector_setup_status(ct, request)) for ct in CONNECTOR_CATALOG]


@router.get("/connectors/processing-summary")
async def connector_processing_summary(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    docs = list(await session.scalars(select(SourceDocument)))
    if workspace_id:
        try:
            workspace_uuid = UUID(workspace_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid workspace_id")
        connector_types = set(await session.scalars(
            select(Connector.connector_type).where(Connector.workspace_id == workspace_uuid)
        ))
        docs = [
            doc for doc in docs
            if _source_document_matches_workspace(doc, workspace_id, connector_types)
        ]
    totals: dict[str, int] = {ct: 0 for ct in CONNECTOR_CATALOG}
    processed: dict[str, int] = {ct: 0 for ct in CONNECTOR_CATALOG}
    unprocessed: dict[str, int] = {ct: 0 for ct in CONNECTOR_CATALOG}
    for doc in docs:
        key = _processing_summary_key(doc)
        totals[key] = totals.get(key, 0) + 1
        if doc.processed_at is None:
            unprocessed[key] = unprocessed.get(key, 0) + 1
        else:
            processed[key] = processed.get(key, 0) + 1
    items = [{
        "connectorType": ct,
        "connector_type": ct,
        "processedDocuments": processed.get(ct, 0),
        "unprocessedDocuments": unprocessed.get(ct, 0),
        "total_documents": totals.get(ct, 0),
    } for ct in CONNECTOR_CATALOG]
    return {"items": items}


def _processing_summary_key(doc: SourceDocument) -> str:
    source_type = doc.source_type
    if source_type == "agent_session":
        connector_type = str(_loads_json_dict(doc.metadata_json).get("connector_type") or "")
        if connector_type in AI_SESSION_CONNECTORS:
            return connector_type
        return "ai_context"
    if source_type.startswith("ai_context"):
        return "ai_context"
    return source_type


def _source_document_matches_workspace(
    doc: SourceDocument,
    workspace_id: str,
    connector_types: set[str],
) -> bool:
    metadata = _loads_json_dict(doc.metadata_json)
    if metadata.get("workspace_id"):
        return str(metadata["workspace_id"]) == workspace_id

    source_type = doc.source_type
    if source_type in connector_types:
        return True
    if source_type in {"github_issue", "github_pr"} and "github" in connector_types:
        return True
    if source_type.startswith("ai_context") and connector_types.intersection(
        {"ai_context", *AI_SESSION_CONNECTORS}
    ):
        return True
    if source_type == "agent_session" and connector_types.intersection(
        {"ai_context", *AI_SESSION_CONNECTORS}
    ):
        return True

    return source_type in {"local", "local_folder", "browser_upload", "paste"}


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
    redirect_uri = _get_env("SLACK_REDIRECT_URI") or _callback_url("/api/connectors/slack/callback", request)
    state = f"{workspace_id}:{secrets.token_urlsafe(16)}"
    scopes = "channels:history,channels:join,channels:read,groups:history,groups:read,users:read,team:read"
    params = urlencode({
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
    })
    url = f"https://slack.com/oauth/v2/authorize?{params}"
    return RedirectResponse(url)


@router.get("/connectors/slack/managed/install")
async def slack_managed_install(
    workspace_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    await _get_workspace(workspace_id, session)
    managed_url = _slack_managed_install_url()
    if not managed_url:
        raise HTTPException(
            status_code=503,
            detail="Managed Slack OAuth is not configured on this server.",
        )
    callback_url = _callback_url("/api/connectors/slack/callback", request)
    separator = "&" if "?" in managed_url else "?"
    params = urlencode({"workspace_id": workspace_id, "callback_url": callback_url})
    return RedirectResponse(f"{managed_url}{separator}{params}")


@router.get("/connectors/slack/callback")
async def slack_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    encrypted_token: str | None = None,
    team_id: str | None = None,
    team_name: str | None = None,
    scope: str | None = None,
    authed_user_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    if error:
        return _oauth_close_html(success=False, message=f"Slack OAuth error: {error}")
    if not state:
        return _oauth_close_html(success=False, message="Missing state.")

    workspace_id = state.split(":")[0]
    try:
        ws = await _get_workspace(workspace_id, session)
    except HTTPException:
        return _oauth_close_html(success=False, message="Workspace not found.")

    if encrypted_token:
        try:
            access_token = _decrypt_managed_token(encrypted_token)
        except HTTPException as exc:
            return _oauth_close_html(success=False, message=str(exc.detail))

        connector = await _get_or_create_connector(ws.id, "slack", session)
        connector.status = "connected"
        connector.credentials_json = json.dumps({"access_token": access_token})
        config = json.loads(connector.config_json or "{}")
        config.update({
            "team_name": team_name or "",
            "team_id": team_id or "",
            "scope": scope or "",
            "authed_user_id": authed_user_id or "",
            "auth_mode": "managed_oauth",
        })
        connector.config_json = json.dumps(config)
        await session.commit()
        await session.refresh(connector)
        return _oauth_close_html(success=True, message="Slack connected successfully.")

    if not code:
        return _oauth_close_html(success=False, message="Missing code.")

    import httpx
    client_id = _get_env("SLACK_CLIENT_ID")
    client_secret = _get_env("SLACK_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _oauth_close_html(success=False, message="Slack OAuth is not configured on this server.")
    redirect_uri = _get_env("SLACK_REDIRECT_URI") or _callback_url("/api/connectors/slack/callback", request)

    try:
        async with httpx.AsyncClient() as http:
            params: dict[str, str] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            }
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
    await session.refresh(connector)
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
        raise HTTPException(status_code=400, detail="Zoom connector is not available yet.")
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
    client_id = _get_google_client_id()
    if not client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured on this server.")
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or _callback_url(f"/api/connectors/{connector_type}/callback", request)
    state = f"{workspace_id}:{connector_type}:{secrets.token_urlsafe(16)}"
    scope = _GOOGLE_SCOPES[connector_type]
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return RedirectResponse(url)


@router.get("/connectors/{connector_type}/callback")
async def google_callback(
    connector_type: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
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
    client_id = _get_google_client_id() or ""
    client_secret = _get_env("GOOGLE_CLIENT_SECRET") or ""
    redirect_uri = _get_env("GOOGLE_REDIRECT_URI") or _callback_url(f"/api/connectors/{connector_type}/callback", request)

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
    await session.refresh(connector)
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


@router.post("/connectors/{connector_type}/connect")
async def connect_catalog_connector(
    connector_type: str,
    payload: dict | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if connector_type not in CONNECTOR_CATALOG:
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector_type in {"ai_context", "local"}:
        await _get_or_create_default_workspace(session)
        connector = await _get_or_create_connector(DEFAULT_WORKSPACE_ID, connector_type, session)
        connector.status = "connected"
        connector.config_json = json.dumps((payload or {}).get("config", {}))
        await session.commit()
        await session.refresh(connector)
        entry = _catalog_connector_entry(connector_type, connector)
        entry["connector_id"] = str(connector.id)
        return entry
    raise HTTPException(
        status_code=400,
        detail=f"{CONNECTOR_CATALOG[connector_type]['name']} connector is not currently supported for direct connect.",
    )


# ── AI session ingest ──────────────────────────────────────────

def _ai_context_source_type(tool: str | None) -> tuple[str, str]:
    raw = (tool or "").strip().lower().replace("-", "_")
    if raw in {"codex"}:
        return "ai_context_codex", "codex"
    if raw in {"claude", "claude_code"}:
        return "ai_context_claude_code", "claude_code"
    if raw in {"opencode", "open_code"}:
        return "ai_context_opencode", "opencode"
    if raw:
        return "ai_context", "generic"
    return "ai_context", "generic"


@router.post("/connectors/ai-context/import", status_code=201)
async def import_ai_context_documents(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not documents:
        raise HTTPException(status_code=422, detail="documents must not be empty")

    created_ids: list[str] = []
    for item in documents:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        source_type, tool = _ai_context_source_type(item.get("tool"))
        metadata = dict(item.get("metadata") or {})
        for key in ("session_type", "session_id", "started_at", "ended_at"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        metadata["tool"] = tool
        metadata["ingested_via"] = "ai_context_import"
        doc = SourceDocument(
            source_type=source_type,
            external_id=item.get("external_id") or f"ai-context:{secrets.token_urlsafe(12)}",
            content=content,
            author=item.get("author"),
            source_url=item.get("source_url"),
            metadata_json=json.dumps(metadata),
        )
        session.add(doc)
        await session.flush()
        created_ids.append(str(doc.id))

    if not created_ids:
        raise HTTPException(status_code=422, detail="documents must contain content")
    await session.commit()
    return {"created": len(created_ids), "document_ids": created_ids, "source_type": "ai_context"}


class AISessionIngestRequest(BaseModel):
    workspace_id: str
    connector_type: str
    session_id: str
    content: str


@router.post("/connectors/ai-session/ingest")
async def ingest_ai_session(
    body: AISessionIngestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    from app.sync.ai_session import ingest_ai_session as _ingest
    from app.services.ingest import IngestionService
    from app.models import SourceDocument
    from sqlalchemy import select as sa_select

    if body.connector_type not in AI_SESSION_CONNECTORS:
        raise HTTPException(status_code=422, detail=f"Unknown AI session connector: {body.connector_type}")
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Session content must not be empty.")

    ws = await _get_workspace(body.workspace_id, session)
    connector = await _get_or_create_connector(ws.id, body.connector_type, session)

    ingest_result = await _ingest(
        body.connector_type,
        session,
        body.session_id,
        body.content,
        workspace_id=str(ws.id),
    )

    external_id = f"{body.connector_type}:session:{body.session_id}"
    unprocessed_docs = list(await session.scalars(
        sa_select(SourceDocument)
        .where(SourceDocument.external_id == external_id)
        .where(SourceDocument.processed_at.is_(None))
    ))
    ingestor = IngestionService(session)
    components_created = 0
    for doc in unprocessed_docs:
        n = await ingestor.process_document(doc.id)
        components_created += n
    await session.commit()
    extract_result = {
        "documents_processed": len(unprocessed_docs),
        "components_created": components_created,
    }

    config = json.loads(connector.config_json or "{}")
    config["total_processed_count"] = (
        config.get("total_processed_count", 0)
        + extract_result.get("documents_processed", 0)
    )
    config["items_synced"] = config.get("items_synced", 0) + ingest_result.get("documents_persisted", 0)
    connector.config_json = json.dumps(config)
    connector.status = "connected"
    connector.last_sync_at = datetime.utcnow()
    await session.commit()
    await session.refresh(connector)

    return {
        **_connector_to_dict(connector),
        "ingest": ingest_result,
        "extract": extract_result,
    }


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
    if connector.connector_type in {"discord", "zoom", "wispr_flow"}:
        job.status = "failed"
        job.error_type = "unsupported_connector"
        job.error_message = f"{CONNECTOR_CATALOG.get(connector.connector_type, {}).get('name', connector.connector_type)} is not supported yet."
        job.completed_at = datetime.utcnow()
    session.add(job)
    await session.commit()
    await session.refresh(job)

    if job.status == "pending" and connector.connector_type not in {"local", "ai_context"}:
        background_tasks.add_task(_run_sync_job, str(job.id), str(cid), settings.database_url)
    return {
        "job_id": str(job.id),
        "connector_id": str(cid),
        "status": job.status,
        "error_type": job.error_type,
        "error_message": job.error_message,
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
        connector = await session.get(Connector, cid)
        if connector is None:
            raise HTTPException(status_code=404, detail="Connector not found")
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
    credentials = _loads_json_dict(connector.credentials_json)
    revoke_result = None
    if connector.connector_type == "slack":
        revoke_result = await _revoke_slack_token(str(credentials.get("access_token") or ""))
    connector.status = "disconnected"
    connector.credentials_json = "{}"
    config = _loads_json_dict(connector.config_json)
    for key in DISCONNECT_CONFIG_KEYS:
        config.pop(key, None)
    connector.config_json = json.dumps(config)
    await session.commit()
    await session.refresh(connector)
    response = {"ok": True, **_connector_to_dict(connector)}
    if revoke_result is not None:
        response["revoke"] = revoke_result
    return response


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


def _sync_result_with_skip_counts(sync_result: dict[str, Any]) -> dict[str, Any]:
    result = dict(sync_result)
    if "documents_skipped" not in result:
        fetched = _metadata_int(result.get("documents_fetched"))
        persisted = _metadata_int(result.get("documents_persisted"))
        result["documents_skipped"] = max(fetched - persisted, 0)
    return result


def _metadata_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
    """Background task: mark job running → sync source documents → extract → mark completed."""
    from app.database import _make_async_url
    from app.sync.slack import sync_slack
    from app.extract.basic import extract_from_source_documents
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
        job.started_at = datetime.utcnow()
        await session.commit()

        try:
            sync_result: dict[str, Any] = {}
            extract_result: dict[str, Any] = {}

            if connector.connector_type == "slack":
                sync_result = await sync_slack(connector, session)
                extract_result = await extract_from_source_documents("slack", session)
            elif connector.connector_type == "github":
                from app.sync.github import sync_github
                sync_result = await sync_github(connector, session)
                extract_result = await extract_from_source_documents("github", session)
            elif connector.connector_type == "gmail":
                from app.sync.google import sync_gmail
                sync_result = await sync_gmail(connector, session)
                extract_result = await extract_from_source_documents("gmail", session)
            elif connector.connector_type == "gdrive":
                from app.sync.google import sync_gdrive
                sync_result = await sync_gdrive(connector, session)
                extract_result = await extract_from_source_documents("gdrive", session)
            elif connector.connector_type in AI_SESSION_CONNECTORS:
                # AI session connectors ingest inline; sync just re-runs extraction
                sync_result = {"documents_fetched": 0, "documents_persisted": 0}
                extract_result = await extract_from_source_documents(connector.connector_type, session)
            else:
                # Generic stub for connectors not yet implemented
                sync_result = {"documents_fetched": 0, "documents_persisted": 0}
            sync_result = _sync_result_with_skip_counts(sync_result)

            result_metadata: dict[str, Any] = {
                "sync_mode": "polling",
                **sync_result,
                **extract_result,
            }
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.result_metadata_json = json.dumps(result_metadata)

            config = json.loads(connector.config_json or "{}")
            config["items_synced"] = (
                config.get("items_synced", 0)
                + sync_result.get("documents_persisted", 0)
            )
            config["total_processed_count"] = (
                config.get("total_processed_count", 0)
                + extract_result.get("documents_processed", 0)
            )
            connector.config_json = json.dumps(config)
            connector.last_sync_at = datetime.utcnow()
            await session.commit()

        except Exception as exc:
            import traceback
            job.status = "failed"
            job.error_type = type(exc).__name__
            job.error_message = f"{exc}\n{traceback.format_exc()}"
            job.completed_at = datetime.utcnow()
            await session.commit()

    await engine.dispose()
