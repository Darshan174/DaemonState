from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services.credentials import (
    CredentialStoreError,
    credentials_are_encrypted,
    dump_credentials,
    load_credentials,
    rotate_credentials,
)


def test_credentials_default_to_legacy_plaintext_when_no_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.encryption_key", None, raising=False)

    raw = dump_credentials({"access_token": "legacy-token"})

    assert "legacy-token" in raw
    assert credentials_are_encrypted(raw) is False
    assert load_credentials(raw) == {"access_token": "legacy-token"}


def test_credentials_encrypt_when_key_is_configured(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.encryption_key", key, raising=False)

    raw = dump_credentials({"access_token": "secret-token", "refresh_token": "refresh-token"})

    assert "secret-token" not in raw
    assert "refresh-token" not in raw
    assert credentials_are_encrypted(raw) is True
    assert load_credentials(raw) == {
        "access_token": "secret-token",
        "refresh_token": "refresh-token",
    }


def test_encrypted_credentials_require_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.encryption_key", key, raising=False)
    raw = dump_credentials({"access_token": "secret-token"})

    monkeypatch.setattr("app.config.settings.encryption_key", None, raising=False)

    with pytest.raises(CredentialStoreError, match="ENCRYPTION_KEY"):
        load_credentials(raw)


def test_credentials_decrypt_with_previous_key_and_rotate_to_primary(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.encryption_key", old_key, raising=False)
    monkeypatch.setattr("app.config.settings.previous_encryption_keys", None, raising=False)
    old_payload = dump_credentials({"access_token": "rotating-token"})

    monkeypatch.setattr("app.config.settings.encryption_key", new_key, raising=False)
    monkeypatch.setattr("app.config.settings.previous_encryption_keys", old_key, raising=False)

    assert load_credentials(old_payload) == {"access_token": "rotating-token"}
    rotated = rotate_credentials(old_payload)
    assert rotated != old_payload
    assert load_credentials(rotated) == {"access_token": "rotating-token"}

    monkeypatch.setattr("app.config.settings.previous_encryption_keys", None, raising=False)
    assert load_credentials(rotated) == {"access_token": "rotating-token"}
    with pytest.raises(CredentialStoreError):
        load_credentials(old_payload)


def test_rotate_encrypted_credentials_requires_primary_key(monkeypatch):
    old_key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.encryption_key", old_key, raising=False)
    payload = dump_credentials({"access_token": "secret-token"})

    monkeypatch.setattr("app.config.settings.encryption_key", None, raising=False)
    monkeypatch.setattr("app.config.settings.previous_encryption_keys", old_key, raising=False)

    with pytest.raises(CredentialStoreError, match="rotate encrypted credentials"):
        rotate_credentials(payload)
