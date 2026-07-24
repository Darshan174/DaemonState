from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import settings
from app.models import Connector


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

    try:
        token = Fernet(key.encode()).encrypt(payload.encode("utf-8")).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CredentialStoreError("ENCRYPTION_KEY is not a valid Fernet key.") from exc
    return _json_dumps({
        "_encrypted": True,
        "scheme": FERNET_CREDENTIAL_SCHEME,
        "ciphertext": token,
    })


def load_credentials(raw: str | None) -> dict[str, Any]:
    data = _loads_json_dict(raw, strict=True)
    if not data:
        return {}
    if not _is_encrypted_envelope(data):
        if _looks_like_encrypted_envelope(data):
            raise CredentialStoreError(
                "Stored connector credentials contain a malformed envelope."
            )
        return data

    return _decrypt_envelope(data)


def _decrypt_envelope(data: dict[str, Any]) -> dict[str, Any]:
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
            return _loads_json_dict(decrypted, strict=True)
        except (CredentialStoreError, InvalidToken, TypeError, ValueError) as exc:
            last_error = exc
            continue
    raise CredentialStoreError("Encrypted connector credentials could not be decrypted.") from last_error


def clear_credentials() -> str:
    return "{}"


def credentials_are_encrypted(raw: str | None) -> bool:
    return _is_encrypted_envelope(_loads_json_dict(raw, strict=True))


def credentials_are_empty(raw: str | None) -> bool:
    """Return whether a stored value contains no connector credentials."""
    return not _loads_json_dict(raw, strict=True)


def rotate_credentials(raw: str | None) -> str:
    """Decrypt with any configured key and re-dump with the primary key.

    This is the key-rotation escape hatch: deploy with
    ENCRYPTION_KEY=<new> and PREVIOUS_ENCRYPTION_KEYS=<old>, then rewrite
    stored payloads through this function.
    """
    data = _loads_json_dict(raw, strict=True)
    if not data:
        return clear_credentials()
    if not settings.encryption_key:
        raise CredentialStoreError("ENCRYPTION_KEY is required to rotate encrypted credentials.")
    if _looks_like_encrypted_envelope(data) and not _is_encrypted_envelope(data):
        raise CredentialStoreError("Stored connector credentials contain a malformed envelope.")
    credentials = _decrypt_envelope(data) if _is_encrypted_envelope(data) else data
    return dump_credentials(credentials)


def validate_encrypted_credentials(raw: str | None) -> None:
    """Require a non-empty stored value to be a decryptable Fernet envelope."""
    data = _loads_json_dict(raw, strict=True)
    if not data:
        return
    if not _is_encrypted_envelope(data):
        raise CredentialStoreError(
            "Stored connector credentials are not an encrypted Fernet envelope."
        )
    _decrypt_envelope(data)


def credentials_use_primary_key(raw: str | None) -> bool:
    """Return whether an envelope decrypts with the current key specifically."""
    data = _loads_json_dict(raw, strict=True)
    if not data or not _is_encrypted_envelope(data):
        return False
    key = settings.encryption_key
    if not key:
        raise CredentialStoreError(
            "ENCRYPTION_KEY is required to validate connector credentials."
        )
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise CredentialStoreError(
            "cryptography is required to decrypt connector credentials."
        ) from exc

    try:
        decrypted = Fernet(key.encode()).decrypt(
            data["ciphertext"].encode("utf-8")
        ).decode("utf-8")
    except InvalidToken:
        return False
    except (TypeError, ValueError) as exc:
        raise CredentialStoreError(
            "ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc
    _loads_json_dict(decrypted, strict=True)
    return True


async def rotate_connector_credentials(
    conn: AsyncConnection,
) -> dict[str, int]:
    """Rotate populated connector credentials inside the caller's transaction."""
    rows = (
        await conn.execute(
            select(Connector.id, Connector.credentials_json).order_by(Connector.id)
        )
    ).all()
    updated = 0
    populated = 0
    for connector_id, raw in rows:
        try:
            if credentials_are_empty(raw):
                continue
            populated += 1
            if credentials_use_primary_key(raw):
                validate_encrypted_credentials(raw)
                continue
            rotated = rotate_credentials(raw)
            validate_encrypted_credentials(rotated)
        except CredentialStoreError as exc:
            raise CredentialStoreError(
                f"Connector credential record {connector_id} is invalid: {exc}"
            ) from exc
        if rotated != raw:
            await conn.execute(
                update(Connector)
                .where(Connector.id == connector_id)
                .values(credentials_json=rotated)
            )
            updated += 1
    return {"scanned": len(rows), "populated": populated, "updated": updated}


async def validate_connector_credentials(
    conn: AsyncConnection,
) -> dict[str, int]:
    """Audit the production credential invariant without returning secret data."""
    rows = (
        await conn.execute(
            select(Connector.id, Connector.credentials_json).order_by(Connector.id)
        )
    ).all()
    populated = 0
    for connector_id, raw in rows:
        try:
            if credentials_are_empty(raw):
                continue
            populated += 1
            validate_encrypted_credentials(raw)
        except CredentialStoreError as exc:
            raise CredentialStoreError(
                f"Connector credential record {connector_id} is invalid: {exc}"
            ) from exc
    return {"scanned": len(rows), "populated": populated}


def _is_encrypted_envelope(data: dict[str, Any]) -> bool:
    return (
        data.get("_encrypted") is True
        and data.get("scheme") == FERNET_CREDENTIAL_SCHEME
        and isinstance(data.get("ciphertext"), str)
        and bool(data["ciphertext"])
    )


def _looks_like_encrypted_envelope(data: dict[str, Any]) -> bool:
    return "_encrypted" in data or data.get("scheme") == FERNET_CREDENTIAL_SCHEME


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


def _loads_json_dict(
    raw: str | None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        if strict:
            raise CredentialStoreError(
                "Stored connector credentials are not valid JSON."
            ) from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise CredentialStoreError(
                "Stored connector credentials must be a JSON object."
            )
        return {}
    return data


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
