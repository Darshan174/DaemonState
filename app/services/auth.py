from __future__ import annotations

import hashlib
import json
import secrets
import time
from uuid import UUID

from fastapi import Request

from app.config import settings
from app.services.access import AccessScope


API_KEY_HEADERS = (
    "x-context-engine-api-key",
    "x-api-key",
)
_RATE_LIMIT_BUCKETS: dict[str, tuple[int, float]] = {}


def api_auth_enabled() -> bool:
    return bool(settings.server_api_key or _principal_key_bindings())


def request_has_valid_api_key(request: Request) -> bool:
    return request_access_scope(request) is not None


def request_access_scope(request: Request) -> AccessScope | None:
    provided = _api_key_from_request(request)
    expected = settings.server_api_key
    if expected and provided and secrets.compare_digest(provided, expected):
        return AccessScope.admin()
    for token, binding in _principal_key_bindings().items():
        if not provided or not secrets.compare_digest(provided, token):
            continue
        principal_id = str(binding.get("principal_id") or "").strip()
        if not principal_id:
            return None
        workspace_ids: set[UUID] = set()
        for value in binding.get("workspace_ids") or []:
            try:
                workspace_ids.add(UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                return None
        return AccessScope(
            principal_id=principal_id,
            workspace_ids=frozenset(workspace_ids),
            unrestricted=False,
        )
    if not expected and not _principal_key_bindings():
        return AccessScope.local()
    return None


def _principal_key_bindings() -> dict[str, dict]:
    raw = settings.principal_api_keys
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(token): binding
        for token, binding in parsed.items()
        if token and isinstance(binding, dict)
    }


def api_rate_limit_enabled() -> bool:
    return int(settings.api_rate_limit_per_minute or 0) > 0


def check_api_rate_limit(request: Request) -> tuple[bool, int]:
    limit = int(settings.api_rate_limit_per_minute or 0)
    if limit <= 0:
        return True, 0

    now = time.monotonic()
    window_seconds = 60.0
    key = _rate_limit_key(request)
    count, reset_at = _RATE_LIMIT_BUCKETS.get(key, (0, now + window_seconds))
    if reset_at <= now:
        count = 0
        reset_at = now + window_seconds

    if count >= limit:
        retry_after = max(1, int(reset_at - now))
        _RATE_LIMIT_BUCKETS[key] = (count, reset_at)
        return False, retry_after

    _RATE_LIMIT_BUCKETS[key] = (count + 1, reset_at)
    return True, max(1, int(reset_at - now))


def reset_api_rate_limits() -> None:
    _RATE_LIMIT_BUCKETS.clear()


def _api_key_from_request(request: Request) -> str | None:
    for header in API_KEY_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()

    auth = request.headers.get("authorization", "").strip()
    prefix = "bearer "
    if auth.lower().startswith(prefix):
        return auth[len(prefix):].strip()
    return None


def _rate_limit_key(request: Request) -> str:
    api_key = _api_key_from_request(request)
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        return f"key:{digest}"
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    client_host = forwarded_for or (request.client.host if request.client else "unknown")
    return f"ip:{client_host}"
