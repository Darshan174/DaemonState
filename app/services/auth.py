from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import Request

from app.config import settings


API_KEY_HEADERS = (
    "x-context-engine-api-key",
    "x-api-key",
)
_RATE_LIMIT_BUCKETS: dict[str, tuple[int, float]] = {}


def api_auth_enabled() -> bool:
    return bool(settings.server_api_key)


def request_has_valid_api_key(request: Request) -> bool:
    expected = settings.server_api_key
    if not expected:
        return True
    provided = _api_key_from_request(request)
    return bool(provided) and secrets.compare_digest(provided, expected)


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
