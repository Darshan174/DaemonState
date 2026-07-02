from __future__ import annotations

import json
from typing import Any

from app.config import settings


FERNET_CREDENTIAL_SCHEME = "fernet.v1"


class CredentialStoreError(ValueError):
    pass


def dump_credentials(credentials: dict[str, Any]) -> str:
    payload = _json_dumps(credentials)
    key = settings.encryption_key
    if not key:
        return payload

    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise CredentialStoreError("cryptography is required when ENCRYPTION_KEY is configured.") from exc

    token = Fernet(key.encode()).encrypt(payload.encode("utf-8")).decode("utf-8")
    return _json_dumps({
        "_encrypted": True,
        "scheme": FERNET_CREDENTIAL_SCHEME,
        "ciphertext": token,
    })


def load_credentials(raw: str | None) -> dict[str, Any]:
    data = _loads_json_dict(raw)
    if not data:
        return {}
    if not _is_encrypted_envelope(data):
        return data

    keys = _credential_decryption_keys()
    if not keys:
        raise CredentialStoreError("ENCRYPTION_KEY is required to decrypt connector credentials.")

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise CredentialStoreError("cryptography is required to decrypt connector credentials.") from exc

    ciphertext = str(data.get("ciphertext") or "")
    if not ciphertext:
        raise CredentialStoreError("Encrypted connector credentials are missing ciphertext.")

    last_error: Exception | None = None
    for key in keys:
        try:
            decrypted = Fernet(key.encode()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
            return _loads_json_dict(decrypted)
        except (InvalidToken, ValueError) as exc:
            last_error = exc
            continue
    raise CredentialStoreError("Encrypted connector credentials could not be decrypted.") from last_error


def clear_credentials() -> str:
    return "{}"


def credentials_are_encrypted(raw: str | None) -> bool:
    return _is_encrypted_envelope(_loads_json_dict(raw))


def rotate_credentials(raw: str | None) -> str:
    """Decrypt with any configured key and re-dump with the primary key.

    This is the key-rotation escape hatch: deploy with
    ENCRYPTION_KEY=<new> and PREVIOUS_ENCRYPTION_KEYS=<old>, then rewrite
    stored payloads through this function.
    """
    if credentials_are_encrypted(raw) and not settings.encryption_key:
        raise CredentialStoreError("ENCRYPTION_KEY is required to rotate encrypted credentials.")
    return dump_credentials(load_credentials(raw))


def _is_encrypted_envelope(data: dict[str, Any]) -> bool:
    return data.get("_encrypted") is True and data.get("scheme") == FERNET_CREDENTIAL_SCHEME


def _credential_decryption_keys() -> list[str]:
    keys: list[str] = []
    if settings.encryption_key:
        keys.append(settings.encryption_key)
    previous = settings.previous_encryption_keys or ""
    for item in previous.split(","):
        key = item.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _loads_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
