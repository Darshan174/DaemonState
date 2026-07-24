from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.cli.main import _deploy_database
from app.config import Settings, production_configuration_errors, settings
from app.models import Connector, Workspace
from app.services.credentials import (
    CredentialStoreError,
    credentials_are_encrypted,
    dump_credentials,
    load_credentials,
)


def test_production_configuration_rejects_invalid_previous_encryption_keys():
    configured = Settings(
        _env_file=None,
        environment="production",
        encryption_key=Fernet.generate_key().decode(),
        previous_encryption_keys="not-a-fernet-key",
    )

    assert (
        "PREVIOUS_ENCRYPTION_KEYS must contain only valid Fernet keys"
        in production_configuration_errors(configured)
    )


async def _bootstrap_database(database_url: str, monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "encryption_key",
        Fernet.generate_key().decode(),
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "previous_encryption_keys",
        None,
        raising=False,
    )
    await _deploy_database(database_url)


async def test_db_deploy_rotates_plaintext_and_previous_key_credentials(
    tmp_path,
    monkeypatch,
):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'credential-cutover.db'}"
    await _bootstrap_database(database_url, monkeypatch)
    database = create_async_engine(database_url)
    workspace_id = uuid4()
    old_key = Fernet.generate_key().decode()
    current_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "encryption_key", old_key, raising=False)
    previous_key_payload = dump_credentials({"access_token": "old-key-secret"})

    async with AsyncSession(database, expire_on_commit=False) as session:
        session.add(Workspace(id=workspace_id, name="Cutover", slug=f"cutover-{uuid4()}"))
        session.add_all([
            Connector(
                workspace_id=workspace_id,
                connector_type="github",
                credentials_json=json.dumps({"access_token": "plaintext-secret"}),
            ),
            Connector(
                workspace_id=workspace_id,
                connector_type="slack",
                credentials_json=previous_key_payload,
            ),
            Connector(
                workspace_id=workspace_id,
                connector_type="gdrive",
                credentials_json="{}",
            ),
        ])
        await session.commit()

    monkeypatch.setattr(settings, "encryption_key", current_key, raising=False)
    monkeypatch.setattr(settings, "previous_encryption_keys", old_key, raising=False)
    result = await _deploy_database(database_url)

    assert result["credentials"]["populated"] == 2
    assert result["credentials"]["updated"] == 2
    repeated = await _deploy_database(database_url)
    assert repeated["credentials"]["populated"] == 2
    assert repeated["credentials"]["updated"] == 0
    monkeypatch.setattr(settings, "previous_encryption_keys", None, raising=False)
    async with AsyncSession(database) as session:
        rows = list(
            await session.scalars(
                select(Connector).order_by(Connector.connector_type)
            )
        )

    by_type = {row.connector_type: row.credentials_json for row in rows}
    assert by_type["gdrive"] == "{}"
    assert credentials_are_encrypted(by_type["github"]) is True
    assert credentials_are_encrypted(by_type["slack"]) is True
    assert load_credentials(by_type["github"]) == {
        "access_token": "plaintext-secret"
    }
    assert load_credentials(by_type["slack"]) == {
        "access_token": "old-key-secret"
    }
    assert "plaintext-secret" not in by_type["github"]
    assert "old-key-secret" not in by_type["slack"]
    await database.dispose()


async def test_db_deploy_rolls_back_all_rotation_when_one_row_is_malformed(
    tmp_path,
    monkeypatch,
):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'credential-rollback.db'}"
    await _bootstrap_database(database_url, monkeypatch)
    database = create_async_engine(database_url)
    workspace_id = uuid4()
    plaintext = '{"access_token":"must-not-leak"}'

    async with AsyncSession(database, expire_on_commit=False) as session:
        session.add(Workspace(id=workspace_id, name="Rollback", slug=f"rollback-{uuid4()}"))
        session.add_all([
            Connector(
                id=UUID(int=1),
                workspace_id=workspace_id,
                connector_type="github",
                credentials_json=plaintext,
            ),
            Connector(
                id=UUID(int=2),
                workspace_id=workspace_id,
                connector_type="slack",
                credentials_json="malformed-secret-value",
            ),
        ])
        await session.commit()

    with pytest.raises(CredentialStoreError) as raised:
        await _deploy_database(database_url)

    assert "must-not-leak" not in str(raised.value)
    assert "malformed-secret-value" not in str(raised.value)
    async with AsyncSession(database) as session:
        stored = dict(
            (
                str(connector_id),
                credentials_json,
            )
            for connector_id, credentials_json in (
                await session.execute(
                    select(Connector.id, Connector.credentials_json)
                )
            ).all()
        )

    assert stored[str(UUID(int=1))] == plaintext
    assert stored[str(UUID(int=2))] == "malformed-secret-value"
    await database.dispose()


async def test_production_readiness_fails_closed_for_invalid_credential_store(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    monkeypatch.setattr(settings, "auto_migrate", True, raising=False)
    monkeypatch.setattr(
        "app.main.validate_connector_credentials",
        AsyncMock(
            side_effect=CredentialStoreError(
                "Connector credential record is invalid."
            )
        ),
    )
    monkeypatch.setattr(
        "app.main.rate_limit_backend_ready",
        AsyncMock(return_value=True),
    )

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "ready",
        "rate_limit_backend": "ready",
        "credential_store": "invalid",
    }
