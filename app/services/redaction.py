from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REDACTED_VALUE = "[redacted]"

_DIRECT_SENSITIVE_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
}
_SENSITIVE_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_apikey",
    "_authorization",
    "_client_secret",
    "_credential",
    "_credentials",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_secret_key",
    "_token",
)
_SENSITIVE_PREFIXES = (
    "access_token_",
    "api_key_",
    "authorization_",
    "client_secret_",
    "credential_",
    "password_",
    "private_key_",
    "refresh_token_",
    "secret_",
    "token_",
)
_KEY_VALUE_PATTERNS = (
    re.compile(
        r"(?i)([\"'](?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|password|secret|authorization)[\"']\s*:\s*[\"'])[^\"']+([\"'])"
    ),
    re.compile(r"(?i)(\bauthorization\s*[:=]\s*bearer\s+)[^\s,;}]+"),
    re.compile(
        r"(?i)(\bauthorization\s*[:=]\s*)([\"']?)[^\"'\s,;}]+(\2)"
    ),
    re.compile(
        r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|password|secret)\b\s*[:=]\s*)([\"']?)[^\"'\s,;}]+(\2)"
    ),
)


def is_sensitive_key(key: object) -> bool:
    normalized = _normalize_key(key)
    if not normalized:
        return False
    if normalized.endswith("_count") or normalized.endswith("_total"):
        return False
    return (
        normalized in _DIRECT_SENSITIVE_KEYS
        or normalized.endswith(_SENSITIVE_SUFFIXES)
        or normalized.startswith(_SENSITIVE_PREFIXES)
    )


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED_VALUE if is_sensitive_key(key) else redact_sensitive(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(child) for child in value]
    if isinstance(value, tuple):
        return [redact_sensitive(child) for child in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_sensitive_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = value
    for pattern in _KEY_VALUE_PATTERNS:
        redacted = pattern.sub(_replace_secret_match, redacted)
    return redacted


def _replace_secret_match(match: re.Match[str]) -> str:
    group_count = match.lastindex or 0
    if group_count >= 3:
        return f"{match.group(1)}{match.group(2)}{REDACTED_VALUE}{match.group(3)}"
    if group_count == 2:
        return f"{match.group(1)}{REDACTED_VALUE}{match.group(2)}"
    return f"{match.group(1)}{REDACTED_VALUE}"


def _normalize_key(key: object) -> str:
    raw = str(key or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return re.sub(r"[^a-zA-Z0-9]+", "_", raw).lower().strip("_")
