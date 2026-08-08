from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import settings
from app.services.access import AccessScope
from app.services.continuation_runtime import (
    ContinuationRunError,
    _materialize_desktop_stage_attachments,
)


def _tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return b"\x89PNG\r\n\x1a\n" + b"".join(
        (
            chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")),
            chunk(b"IEND", b""),
        )
    )


def _exact_baseline() -> tuple[dict[str, object], bytes]:
    payload: dict[str, object] = {
        "schema_version": "protected_baseline.v1",
        "complete": True,
        "entry_count": 0,
        "git_object_format": "sha1",
        "head_commit": "c" * 40,
        "entries": [],
    }
    payload_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    digest = hashlib.sha256(payload_bytes).hexdigest()
    manifest_id = f"PB-{digest[:12]}"
    return (
        {
            **payload,
            "id": manifest_id,
            "manifest_sha256": digest,
            "portable_reference": (f"handoff://repository-snapshots/{manifest_id}"),
            "integrity_valid": True,
        },
        payload_bytes,
    )


def _session_context(
    *,
    attachments: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], bytes]:
    baseline, baseline_bytes = _exact_baseline()
    return (
        {
            "task_mode": "change",
            "repository": {"protected_baseline_manifest": baseline},
            "attachment_dependencies": attachments or [],
        },
        baseline_bytes,
    )


def test_stage_bundle_materializes_exact_baseline_without_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    session_context, baseline_bytes = _session_context()
    bundle_id = str(uuid4())

    first = _materialize_desktop_stage_attachments(
        SimpleNamespace(),
        request_verbatim="Make cards opaque.",
        session_context=session_context,
        access_scope=AccessScope.local(),
        bundle_id=bundle_id,
    )
    second = _materialize_desktop_stage_attachments(
        SimpleNamespace(),
        request_verbatim="Make cards opaque.",
        session_context=session_context,
        access_scope=AccessScope.local(),
        bundle_id=bundle_id,
    )

    assert first is not None
    assert second is not None
    assert second.root == first.root
    assert first.deliveries == {}
    assert first.baseline_delivery is not None
    baseline_path = Path(first.baseline_delivery["receiver_local_reference"])
    assert baseline_path.read_bytes() == baseline_bytes
    assert (
        hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        == first.baseline_delivery["manifest_sha256"]
    )
    bundle_manifest = json.loads((first.root / "attachments.json").read_text())
    assert bundle_manifest["protected_baseline"] == first.baseline_delivery
    assert bundle_manifest["retention_policy"] == (
        "retain_for_idempotent_retry_and_late_desktop_open"
    )


def test_stage_bundle_reuses_only_exact_attachment_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source_path = tmp_path / "cards.png"
    source_bytes = _tiny_png()
    source_path.write_bytes(source_bytes)
    digest = hashlib.sha256(source_bytes).hexdigest()
    attachments = [
        {
            "id": "A1",
            "portable_reference": "handoff://attachments/A1",
            "required": True,
            "content_hash": digest,
            "media_type": "image/png",
        }
    ]
    session_context, _baseline_bytes = _session_context(attachments=attachments)
    resolve_calls: list[dict[str, object]] = []

    def fake_resolve(*_args, **kwargs):
        resolve_calls.append(kwargs)
        assert kwargs["portable_reference"] == "handoff://attachments/A1"
        assert kwargs["expected_sha256"] == digest
        assert kwargs["expected_media_type"] == "image/png"
        return SimpleNamespace(path=str(source_path))

    monkeypatch.setattr(
        "app.services.continuation_runtime.resolve_handoff_attachment_reference",
        fake_resolve,
    )
    bundle_id = str(uuid4())
    first = _materialize_desktop_stage_attachments(
        SimpleNamespace(),
        request_verbatim="Don't let cards be transparent.",
        session_context=session_context,
        access_scope=AccessScope.local(),
        bundle_id=bundle_id,
    )
    second = _materialize_desktop_stage_attachments(
        SimpleNamespace(),
        request_verbatim="Don't let cards be transparent.",
        session_context=session_context,
        access_scope=AccessScope.local(),
        bundle_id=bundle_id,
    )

    assert first is not None
    assert second is not None
    assert len(resolve_calls) == 1
    delivered = Path(first.deliveries["A1"]["receiver_local_reference"])
    assert delivered.read_bytes() == source_bytes
    assert second.deliveries == first.deliveries

    delivered.chmod(0o600)
    delivered.write_bytes(b"corrupted")
    delivered.chmod(0o400)
    with pytest.raises(ContinuationRunError) as error:
        _materialize_desktop_stage_attachments(
            SimpleNamespace(),
            request_verbatim="Don't let cards be transparent.",
            session_context=session_context,
            access_scope=AccessScope.local(),
            bundle_id=bundle_id,
        )
    assert error.value.code == "required_stage_evidence_delivery_failed"
    assert len(resolve_calls) == 1


def test_change_stage_fails_closed_without_an_exact_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    session_context = {
        "task_mode": "change",
        "repository": {
            "protected_baseline_manifest": {
                "complete": False,
                "integrity_valid": False,
            }
        },
        "attachment_dependencies": [],
    }

    with pytest.raises(ContinuationRunError) as error:
        _materialize_desktop_stage_attachments(
            SimpleNamespace(),
            request_verbatim="Make cards opaque.",
            session_context=session_context,
            access_scope=AccessScope.local(),
            bundle_id=str(uuid4()),
        )

    assert error.value.code == "required_stage_evidence_delivery_failed"
    assert "No desktop app was opened" in str(error.value)
