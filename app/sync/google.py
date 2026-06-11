from __future__ import annotations

import base64
import json
import logging
from html import unescape
from re import sub
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.connectors import _get_env, _get_google_client_id
from app.models import Connector, SourceDocument

logger = logging.getLogger(__name__)

MAX_GMAIL_MESSAGES = 50
MAX_DRIVE_FILES = 50
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"


async def sync_gmail(connector: Connector, session: AsyncSession) -> dict:
    token = await _access_token(connector, session)
    docs_fetched = 0
    docs_persisted = 0
    duplicates_skipped = 0
    empty_skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30) as http:
        headers = {"Authorization": f"Bearer {token}"}
        resp = await http.get(
            f"{GMAIL_BASE_URL}/users/me/messages",
            headers=headers,
            params={"maxResults": MAX_GMAIL_MESSAGES},
        )
        if resp.status_code == 401:
            token = await _refresh_access_token(connector, session)
            headers = {"Authorization": f"Bearer {token}"}
            resp = await http.get(
                f"{GMAIL_BASE_URL}/users/me/messages",
                headers=headers,
                params={"maxResults": MAX_GMAIL_MESSAGES},
            )
        _raise_google_error(resp, "Gmail messages.list")
        messages = resp.json().get("messages", [])

        for item in messages:
            message_id = item.get("id")
            if not message_id:
                continue
            try:
                detail = await http.get(
                    f"{GMAIL_BASE_URL}/users/me/messages/{message_id}",
                    headers=headers,
                    params={"format": "full"},
                )
                _raise_google_error(detail, f"Gmail messages.get {message_id}")
                message = detail.json()
            except Exception as exc:
                errors.append(f"{message_id}: {exc}")
                continue

            docs_fetched += 1
            external_id = f"gmail:{message_id}"
            if await _document_exists(external_id, session):
                duplicates_skipped += 1
                continue

            metadata = _gmail_metadata(message, connector)
            content = _gmail_content(message, metadata)
            if not content.strip():
                empty_skipped += 1
                continue

            session.add(
                SourceDocument(
                    id=uuid4(),
                    source_type="gmail",
                    external_id=external_id,
                    content=content,
                    author=metadata.get("from"),
                    source_url=f"https://mail.google.com/mail/u/0/#all/{message_id}",
                    metadata_json=json.dumps(metadata),
                )
            )
            docs_persisted += 1

        await session.commit()

    logger.info("Gmail sync complete: %d fetched, %d persisted", docs_fetched, docs_persisted)
    return {
        "documents_fetched": docs_fetched,
        "documents_persisted": docs_persisted,
        "documents_skipped": duplicates_skipped + empty_skipped,
        "duplicates_skipped": duplicates_skipped,
        "empty_skipped": empty_skipped,
        "errors": errors,
    }


async def sync_gdrive(connector: Connector, session: AsyncSession) -> dict:
    token = await _access_token(connector, session)
    docs_fetched = 0
    docs_persisted = 0
    duplicates_skipped = 0
    empty_skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30) as http:
        headers = {"Authorization": f"Bearer {token}"}
        files_resp = await http.get(
            f"{DRIVE_BASE_URL}/files",
            headers=headers,
            params={
                "pageSize": MAX_DRIVE_FILES,
                "fields": "files(id,name,mimeType,webViewLink,modifiedTime,owners(displayName,emailAddress))",
                "q": "trashed = false",
            },
        )
        if files_resp.status_code == 401:
            token = await _refresh_access_token(connector, session)
            headers = {"Authorization": f"Bearer {token}"}
            files_resp = await http.get(
                f"{DRIVE_BASE_URL}/files",
                headers=headers,
                params={
                    "pageSize": MAX_DRIVE_FILES,
                    "fields": "files(id,name,mimeType,webViewLink,modifiedTime,owners(displayName,emailAddress))",
                    "q": "trashed = false",
                },
            )
        _raise_google_error(files_resp, "Drive files.list")
        files = files_resp.json().get("files", [])

        for item in files:
            file_id = item.get("id")
            if not file_id:
                continue
            docs_fetched += 1
            external_id = f"gdrive:{file_id}"
            if await _document_exists(external_id, session):
                duplicates_skipped += 1
                continue

            mime_type = item.get("mimeType", "")
            try:
                content = await _download_drive_text(http, headers, file_id, mime_type)
            except Exception as exc:
                errors.append(f"{item.get('name', file_id)}: {exc}")
                continue

            text = content.strip()
            if not text:
                empty_skipped += 1
                continue

            owners = item.get("owners") or []
            owner = owners[0] if owners else {}
            metadata = {
                "workspace_id": str(connector.workspace_id),
                "file_id": file_id,
                "name": item.get("name", ""),
                "mime_type": mime_type,
                "modified_time": item.get("modifiedTime"),
                "owner": owner.get("displayName") or owner.get("emailAddress"),
                "owner_email": owner.get("emailAddress"),
                "web_view_link": item.get("webViewLink"),
            }
            session.add(
                SourceDocument(
                    id=uuid4(),
                    source_type="gdrive",
                    external_id=external_id,
                    content=f"[Drive File] {item.get('name', 'Untitled')}\n\n{text[:20000]}",
                    author=metadata.get("owner"),
                    source_url=item.get("webViewLink"),
                    metadata_json=json.dumps(metadata),
                )
            )
            docs_persisted += 1

        await session.commit()

    logger.info("Google Drive sync complete: %d fetched, %d persisted", docs_fetched, docs_persisted)
    return {
        "documents_fetched": docs_fetched,
        "documents_persisted": docs_persisted,
        "documents_skipped": duplicates_skipped + empty_skipped,
        "duplicates_skipped": duplicates_skipped,
        "empty_skipped": empty_skipped,
        "errors": errors,
    }


async def _access_token(connector: Connector, session: AsyncSession) -> str:
    credentials = _credentials(connector)
    token = str(credentials.get("access_token") or "")
    if token:
        return token
    if credentials.get("refresh_token"):
        return await _refresh_access_token(connector, session)
    raise ValueError(f"No Google access token found on {connector.connector_type} connector.")


async def _refresh_access_token(connector: Connector, session: AsyncSession) -> str:
    credentials = _credentials(connector)
    refresh_token = str(credentials.get("refresh_token") or "")
    if not refresh_token:
        raise ValueError("Google access token expired and no refresh token is stored.")

    client_id = _get_google_client_id()
    client_secret = _get_env("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("Google OAuth is not configured on this server.")

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    _raise_google_error(resp, "Google token refresh")
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Google token refresh did not return an access token.")

    credentials["access_token"] = access_token
    credentials["expires_in"] = data.get("expires_in")
    connector.credentials_json = json.dumps(credentials)
    await session.commit()
    return access_token


def _credentials(connector: Connector) -> dict[str, object]:
    try:
        data = json.loads(connector.credentials_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


async def _document_exists(external_id: str, session: AsyncSession) -> bool:
    existing = await session.scalar(
        select(SourceDocument).where(SourceDocument.external_id == external_id)
    )
    return existing is not None


def _raise_google_error(response: httpx.Response, operation: str) -> None:
    if response.status_code < 400:
        return
    try:
        data = response.json()
    except Exception:
        data = {}
    detail = data.get("error", data)
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("error_description") or str(detail)
    else:
        message = str(detail)
    raise ValueError(f"{operation} failed ({response.status_code}): {message}")


def _gmail_metadata(message: dict[str, object], connector: Connector) -> dict[str, object]:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    header_map = {
        str(header.get("name", "")).lower(): header.get("value", "")
        for header in headers
        if isinstance(header, dict)
    }
    return {
        "workspace_id": str(connector.workspace_id),
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "snippet": message.get("snippet"),
        "subject": header_map.get("subject", ""),
        "from": header_map.get("from", ""),
        "to": header_map.get("to", ""),
        "date": header_map.get("date", ""),
        "label_ids": message.get("labelIds", []),
    }


def _gmail_content(message: dict[str, object], metadata: dict[str, object]) -> str:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    body = _gmail_payload_text(payload)
    if not body:
        body = str(message.get("snippet") or "")
    return (
        f"[Gmail] {metadata.get('subject') or '(no subject)'}\n"
        f"From: {metadata.get('from') or 'unknown'}\n"
        f"To: {metadata.get('to') or 'unknown'}\n"
        f"Date: {metadata.get('date') or 'unknown'}\n\n"
        f"{body[:20000]}"
    )


def _gmail_payload_text(payload: dict[str, object]) -> str:
    parts = payload.get("parts")
    mime_type = str(payload.get("mimeType") or "")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}

    if mime_type in {"text/plain", "text/html"} and body.get("data"):
        decoded = _decode_base64url(str(body["data"]))
        return _html_to_text(decoded) if mime_type == "text/html" else decoded

    if isinstance(parts, list):
        html_fallback = ""
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_text = _gmail_payload_text(part)
            part_mime = str(part.get("mimeType") or "")
            if part_mime == "text/plain" and part_text:
                chunks.append(part_text)
            elif part_mime == "text/html" and part_text and not html_fallback:
                html_fallback = part_text
            elif part_text:
                chunks.append(part_text)
        return "\n\n".join(chunks) or html_fallback

    return ""


def _decode_base64url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode()).decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    text = sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = sub(r"(?s)<br\s*/?>", "\n", text)
    text = sub(r"(?s)</p\s*>", "\n", text)
    text = sub(r"(?s)<.*?>", " ", text)
    text = unescape(text)
    return sub(r"[ \t]+", " ", text).strip()


async def _download_drive_text(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    file_id: str,
    mime_type: str,
) -> str:
    export_mime = _drive_export_mime_type(mime_type)
    if export_mime:
        resp = await http.get(
            f"{DRIVE_BASE_URL}/files/{file_id}/export",
            headers=headers,
            params={"mimeType": export_mime},
        )
    else:
        resp = await http.get(
            f"{DRIVE_BASE_URL}/files/{file_id}",
            headers=headers,
            params={"alt": "media"},
        )
    _raise_google_error(resp, f"Drive file download {file_id}")
    return resp.text


def _drive_export_mime_type(mime_type: str) -> str | None:
    if mime_type == "application/vnd.google-apps.document":
        return "text/plain"
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return "text/csv"
    if mime_type == "application/vnd.google-apps.presentation":
        return "text/plain"
    return None
