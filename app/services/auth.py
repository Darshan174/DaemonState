from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any
from uuid import UUID

from fastapi import Request

from app.config import settings
from app.services.access import AccessScope


API_KEY_HEADERS = (
    "x-context-engine-api-key",
    "x-api-key",
)
_RATE_LIMIT_BUCKETS: dict[str, tuple[int, float]] = {}
_redis_client: Any = None
_redis_client_url: str | None = None

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RateLimitBackendUnavailable(RuntimeError):
    pass


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


async def check_api_rate_limit_async(
    request: Request,
    *,
    limit: int | None = None,
    namespace: str = "api",
    key_by_ip: bool = False,
) -> tuple[bool, int, int]:
    effective_limit = int(
        settings.api_rate_limit_per_minute if limit is None else limit
    )
    if effective_limit <= 0:
        return True, 0, effective_limit

    if not settings.redis_url:
        allowed, retry_after = _check_memory_rate_limit(
            request,
            limit=effective_limit,
            namespace=namespace,
            key_by_ip=key_by_ip,
        )
        count, _ = _RATE_LIMIT_BUCKETS.get(
            _namespaced_rate_limit_key(request, namespace, key_by_ip), (0, 0.0)
        )
        return allowed, retry_after, max(0, effective_limit - count)

    try:
        client = await _get_redis_client()
        window_seconds = 60
        window = int(time.time() // window_seconds)
        identity = _rate_limit_identity(request, key_by_ip=key_by_ip)
        redis_key = f"context-engine:rate-limit:{namespace}:{identity}:{window}"
        current, ttl = await client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            redis_key,
            window_seconds + 1,
        )
        current_count = int(current)
        retry_after = max(1, int(ttl))
        return (
            current_count <= effective_limit,
            retry_after,
            max(0, effective_limit - current_count),
        )
    except Exception as exc:
        if settings.rate_limit_fail_open:
            allowed, retry_after = _check_memory_rate_limit(
                request,
                limit=effective_limit,
                namespace=namespace,
                key_by_ip=key_by_ip,
            )
            count, _ = _RATE_LIMIT_BUCKETS.get(
                _namespaced_rate_limit_key(request, namespace, key_by_ip), (0, 0.0)
            )
            return allowed, retry_after, max(0, effective_limit - count)
        raise RateLimitBackendUnavailable(
            "The distributed rate-limit backend is unavailable."
        ) from exc


def reset_api_rate_limits() -> None:
    _RATE_LIMIT_BUCKETS.clear()


async def close_rate_limit_backend() -> None:
    global _redis_client, _redis_client_url
    client = _redis_client
    _redis_client = None
    _redis_client_url = None
    if client is not None:
        await client.aclose()


async def rate_limit_backend_ready() -> bool:
    if not settings.redis_url:
        return not (
            settings.environment.strip().lower() == "production"
            and settings.api_rate_limit_per_minute > 0
        )
    try:
        client = await _get_redis_client()
        # PING succeeds even when noeviction Redis refuses writes at the
        # memory ceiling. Probe the operation the API actually depends on.
        import secrets

        key = f"context-engine:readiness:{secrets.token_hex(16)}"
        if not await client.set(key, "1", ex=5, nx=True):
            return False
        await client.delete(key)
        return True
    except Exception:
        return False


async def _get_redis_client():
    global _redis_client, _redis_client_url
    configured_url = settings.redis_url
    if not configured_url:
        raise RateLimitBackendUnavailable("REDIS_URL is not configured.")
    if _redis_client is None or _redis_client_url != configured_url:
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
        _redis_client_url = configured_url
    return _redis_client


def _check_memory_rate_limit(
    request: Request,
    *,
    limit: int,
    namespace: str,
    key_by_ip: bool,
) -> tuple[bool, int]:
    now = time.monotonic()
    window_seconds = 60.0
    key = _namespaced_rate_limit_key(request, namespace, key_by_ip)
    count, reset_at = _RATE_LIMIT_BUCKETS.get(key, (0, now + window_seconds))
    if reset_at <= now:
        count = 0
        reset_at = now + window_seconds
    if count >= limit:
        _RATE_LIMIT_BUCKETS[key] = (count, reset_at)
        return False, max(1, int(reset_at - now))
    _RATE_LIMIT_BUCKETS[key] = (count + 1, reset_at)
    return True, max(1, int(reset_at - now))


def _namespaced_rate_limit_key(
    request: Request,
    namespace: str,
    key_by_ip: bool,
) -> str:
    return f"{namespace}:{_rate_limit_identity(request, key_by_ip=key_by_ip)}"


def _rate_limit_identity(request: Request, *, key_by_ip: bool) -> str:
    if key_by_ip:
        return f"ip:{_client_host_digest(request)}"
    api_key = _api_key_from_request(request)
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:32]
        return f"key:{digest}"
    return f"ip:{_client_host_digest(request)}"


def _client_host_digest(request: Request) -> str:
    # Uvicorn's trusted proxy middleware normalizes request.client when proxy
    # handling is explicitly enabled. Never trust X-Forwarded-For directly.
    client_host = request.client.host if request.client else "unknown"
    return hashlib.sha256(client_host.encode("utf-8")).hexdigest()[:32]


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
    return _rate_limit_identity(request, key_by_ip=False)
