#!/usr/bin/env python3
"""Load production secrets, validate invariants, then exec the requested process."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit


SECRET_ENVIRONMENTS = {
    "SERVER_API_KEY": Path("/run/secrets/server_api_key"),
    "ENCRYPTION_KEY": Path("/run/secrets/encryption_key"),
    "METRICS_BEARER_TOKEN": Path("/run/secrets/metrics_bearer_token"),
    "PREVIOUS_ENCRYPTION_KEYS": Path("/run/secrets/previous_encryption_keys"),
    "PRINCIPAL_API_KEYS": Path("/run/secrets/principal_api_keys"),
    "LITELLM_API_KEY": Path("/run/secrets/litellm_api_key"),
    "GOOGLE_CLIENT_SECRET": Path("/run/secrets/google_client_secret"),
    "SLACK_CLIENT_SECRET": Path("/run/secrets/slack_client_secret"),
    "ZOOM_CLIENT_SECRET": Path("/run/secrets/zoom_client_secret"),
}
APP_PASSWORD_FILE = Path("/run/secrets/postgres_app_password")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RUNTIME_UID = 10001
RUNTIME_GID = 10001


class ConfigurationError(ValueError):
    """Raised when a production invariant is not satisfied."""


def _read_secret(path: Path, *, required: bool = False) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except FileNotFoundError:
        if required:
            raise ConfigurationError(f"required secret is not mounted: {path.name}") from None
        return None
    except OSError as exc:
        raise ConfigurationError(f"cannot read secret {path.name}: {exc.strerror}") from None
    if not value:
        if required:
            raise ConfigurationError(f"required secret is empty: {path.name}")
        return None
    if "\x00" in value:
        raise ConfigurationError(f"secret contains a NUL byte: {path.name}")
    return value


def _require_identifier(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    if not IDENTIFIER.fullmatch(value):
        raise ConfigurationError(f"{name} must be a PostgreSQL identifier")
    return value


def _validate_fernet_key(value: str, name: str) -> None:
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ConfigurationError(f"{name} is not a valid URL-safe base64 key") from exc
    if len(decoded) != 32:
        raise ConfigurationError(f"{name} must encode exactly 32 bytes")


def _validate_principal_keys(raw: str | None) -> None:
    if not raw:
        return
    try:
        bindings = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("principal_api_keys must contain valid JSON") from exc
    if not isinstance(bindings, dict) or not bindings:
        raise ConfigurationError("principal_api_keys must be a non-empty JSON object")
    for token, binding in bindings.items():
        if not isinstance(token, str) or len(token) < 32:
            raise ConfigurationError("each principal API token must be at least 32 characters")
        if not isinstance(binding, dict) or not str(binding.get("principal_id") or "").strip():
            raise ConfigurationError("each principal API token needs a principal_id")
        workspace_ids = binding.get("workspace_ids", [])
        if not isinstance(workspace_ids, list):
            raise ConfigurationError("principal workspace_ids must be a JSON list")


def _validate_https_url(name: str, *, required: bool = False) -> None:
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            raise ConfigurationError(f"{name} is required")
        return
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ConfigurationError(f"{name} must be an HTTPS URL without embedded credentials")


def _validate_provider(prefix: str) -> None:
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "").strip()
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get(f"{prefix}_REDIRECT_URI", "").strip()
    if any((client_id, client_secret, redirect_uri)) and not all(
        (client_id, client_secret, redirect_uri)
    ):
        raise ConfigurationError(
            f"{prefix}_CLIENT_ID, {prefix}_CLIENT_SECRET, and {prefix}_REDIRECT_URI "
            "must be configured together"
        )
    if redirect_uri:
        _validate_https_url(f"{prefix}_REDIRECT_URI", required=True)


def _load_environment() -> None:
    password = _read_secret(APP_PASSWORD_FILE, required=True)
    assert password is not None
    if len(password) < 20:
        raise ConfigurationError("postgres_app_password must be at least 20 characters")

    host = os.environ.get("POSTGRES_HOST", "db").strip()
    if not host or any(character.isspace() for character in host):
        raise ConfigurationError("POSTGRES_HOST is invalid")
    try:
        port = int(os.environ.get("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise ConfigurationError("POSTGRES_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("POSTGRES_PORT must be between 1 and 65535")

    database = _require_identifier("POSTGRES_DB", "context_engine")
    username = _require_identifier("POSTGRES_APP_USER", "ce_app")
    os.environ["DATABASE_URL"] = (
        f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )

    for environment, path in SECRET_ENVIRONMENTS.items():
        os.environ.pop(environment, None)
        value = _read_secret(
            path,
            required=environment in {
                "SERVER_API_KEY",
                "ENCRYPTION_KEY",
                "METRICS_BEARER_TOKEN",
            },
        )
        if value is not None:
            os.environ[environment] = value

    server_api_key = os.environ["SERVER_API_KEY"]
    if len(server_api_key) < 32:
        raise ConfigurationError("server_api_key must be at least 32 characters")
    metrics_token = os.environ["METRICS_BEARER_TOKEN"]
    if len(metrics_token) < 32:
        raise ConfigurationError("metrics_bearer_token must be at least 32 characters")

    encryption_key = os.environ["ENCRYPTION_KEY"]
    _validate_fernet_key(encryption_key, "encryption_key")
    previous_keys = os.environ.get("PREVIOUS_ENCRYPTION_KEYS", "")
    for index, key in enumerate(previous_keys.split(","), start=1):
        if key.strip():
            _validate_fernet_key(key.strip(), f"previous_encryption_keys[{index}]")

    _validate_principal_keys(os.environ.get("PRINCIPAL_API_KEYS"))
    if os.environ.get("PRINCIPAL_API_KEYS"):
        raise ConfigurationError(
            "principal_api_keys are disabled in the production single-tenant baseline"
        )
    _validate_https_url("PUBLIC_BASE_URL", required=True)
    _validate_https_url("SLACK_MANAGED_INSTALL_URL")
    for provider in ("GOOGLE", "SLACK", "ZOOM"):
        _validate_provider(provider)

    try:
        rate_limit = int(os.environ.get("API_RATE_LIMIT_PER_MINUTE", "0"))
    except ValueError as exc:
        raise ConfigurationError("API_RATE_LIMIT_PER_MINUTE must be an integer") from exc
    if rate_limit <= 0:
        raise ConfigurationError("API_RATE_LIMIT_PER_MINUTE must be greater than zero")
    try:
        auth_failure_limit = int(
            os.environ.get("AUTH_FAILURE_RATE_LIMIT_PER_MINUTE", "0")
        )
    except ValueError as exc:
        raise ConfigurationError(
            "AUTH_FAILURE_RATE_LIMIT_PER_MINUTE must be an integer"
        ) from exc
    if auth_failure_limit <= 0:
        raise ConfigurationError(
            "AUTH_FAILURE_RATE_LIMIT_PER_MINUTE must be greater than zero"
        )
    try:
        app_workers = int(os.environ.get("APP_WORKERS", "1"))
    except ValueError as exc:
        raise ConfigurationError("APP_WORKERS must be an integer") from exc
    if app_workers != 1:
        raise ConfigurationError(
            "APP_WORKERS must be 1 until Prometheus multiprocess collection is configured"
        )


def _drop_privileges() -> None:
    if os.geteuid() != 0:
        raise ConfigurationError("production entrypoint must start as root to load file secrets")
    try:
        os.setgroups([])
        os.setresgid(RUNTIME_GID, RUNTIME_GID, RUNTIME_GID)
        os.setresuid(RUNTIME_UID, RUNTIME_UID, RUNTIME_UID)
    except OSError as exc:
        raise ConfigurationError("could not drop production process privileges") from exc
    if os.geteuid() != RUNTIME_UID or os.getegid() != RUNTIME_GID:
        raise ConfigurationError("production process privilege drop did not take effect")
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    effective_capabilities = next(
        (
            int(line.split(":", 1)[1].strip(), 16)
            for line in status.splitlines()
            if line.startswith("CapEff:")
        ),
        -1,
    )
    if effective_capabilities != 0:
        raise ConfigurationError("production process retained Linux capabilities")
    os.umask(0o027)


def main() -> int:
    if len(sys.argv) < 2:
        print("production entrypoint: no command provided", file=sys.stderr)
        return 64
    try:
        _load_environment()
        _drop_privileges()
    except ConfigurationError as exc:
        print(f"production configuration error: {exc}", file=sys.stderr)
        return 78

    os.execvp(sys.argv[1], sys.argv[1:])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
