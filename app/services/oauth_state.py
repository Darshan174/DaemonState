from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import secrets
import time
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class OAuthStateError(ValueError):
    pass


@dataclass(frozen=True)
class OAuthState:
    workspace_id: UUID
    connector_type: str
    principal_id: str
    code_verifier: str | None = None


_local_states: dict[str, float] = {}
_local_key = Fernet.generate_key()
_redis_client: Any = None
_redis_url: str | None = None


async def issue_oauth_state(
    *,
    workspace_id: UUID,
    connector_type: str,
    principal_id: str,
    use_pkce: bool = False,
) -> tuple[str, str | None]:
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64) if use_pkce else None
    ttl = max(60, int(settings.oauth_state_ttl_seconds))
    payload = {
        "v": 1,
        "nonce": nonce,
        "workspace_id": str(workspace_id),
        "connector_type": connector_type,
        "principal_id": principal_id,
        "code_verifier": code_verifier,
        "issued_at": int(time.time()),
    }
    token = _fernet().encrypt(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    await _store_nonce(nonce, ttl)
    return token, code_verifier


async def consume_oauth_state(
    token: str,
    *,
    connector_type: str | None,
) -> OAuthState:
    if not token:
        raise OAuthStateError("OAuth state is missing")
    ttl = max(60, int(settings.oauth_state_ttl_seconds))
    try:
        raw = _fernet().decrypt(token.encode("utf-8"), ttl=ttl)
        payload = json.loads(raw)
        workspace_id = UUID(str(payload["workspace_id"]))
        nonce = str(payload["nonce"])
        stored_connector = str(payload["connector_type"])
        principal_id = str(payload["principal_id"])
    except (InvalidToken, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise OAuthStateError("OAuth state is invalid or expired") from exc
    if (connector_type is not None and stored_connector != connector_type) or not principal_id:
        raise OAuthStateError("OAuth state does not match this connector")
    if not await _consume_nonce(nonce):
        raise OAuthStateError("OAuth state was already used or expired")
    return OAuthState(
        workspace_id=workspace_id,
        connector_type=stored_connector,
        principal_id=principal_id,
        code_verifier=str(payload.get("code_verifier") or "") or None,
    )


def pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def close_oauth_state_backend() -> None:
    global _redis_client, _redis_url
    client = _redis_client
    _redis_client = None
    _redis_url = None
    if client is not None:
        await client.aclose()


def reset_local_oauth_states() -> None:
    _local_states.clear()


def _fernet() -> Fernet:
    if settings.encryption_key:
        try:
            return Fernet(settings.encryption_key.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise OAuthStateError("OAuth state encryption is misconfigured") from exc
    if settings.environment.strip().lower() == "production":
        raise OAuthStateError("OAuth state encryption is unavailable")
    return Fernet(_local_key)


async def _store_nonce(nonce: str, ttl: int) -> None:
    if settings.redis_url:
        try:
            client = await _get_redis_client()
            stored = await client.set(_nonce_key(nonce), "1", ex=ttl, nx=True)
        except Exception as exc:
            raise OAuthStateError("OAuth state storage is unavailable") from exc
        if not stored:
            raise OAuthStateError("Could not create unique OAuth state")
        return
    if settings.environment.strip().lower() == "production":
        raise OAuthStateError("OAuth state storage is unavailable")
    _purge_local_states()
    _local_states[nonce] = time.monotonic() + ttl


async def _consume_nonce(nonce: str) -> bool:
    if settings.redis_url:
        try:
            client = await _get_redis_client()
            return bool(await client.getdel(_nonce_key(nonce)))
        except Exception as exc:
            raise OAuthStateError("OAuth state storage is unavailable") from exc
    _purge_local_states()
    expires_at = _local_states.pop(nonce, 0.0)
    return expires_at > time.monotonic()


async def _get_redis_client():
    global _redis_client, _redis_url
    configured_url = settings.redis_url
    if not configured_url:
        raise OAuthStateError("REDIS_URL is not configured")
    if _redis_client is None or _redis_url != configured_url:
        from redis.asyncio import Redis

        if _redis_client is not None:
            await _redis_client.aclose()
        _redis_client = Redis.from_url(
            configured_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=max(1.0, settings.database_connect_timeout_seconds),
            socket_timeout=max(1.0, settings.database_connect_timeout_seconds),
            health_check_interval=30,
        )
        _redis_url = configured_url
    return _redis_client


def _nonce_key(nonce: str) -> str:
    digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    return f"context-engine:oauth-state:{digest}"


def _purge_local_states() -> None:
    now = time.monotonic()
    expired = [nonce for nonce, expiry in _local_states.items() if expiry <= now]
    for nonce in expired:
        _local_states.pop(nonce, None)
