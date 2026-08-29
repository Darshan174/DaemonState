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
    DesktopStageAttachmentBundle,
    _desktop_stage_delivery_receipt,
    _materialize_desktop_stage_attachments,
    _desktop_stage_target_capability_profile,
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
            "portable_reference": (
                f"handoff://repository-snapshots/{manifest_id}"
            ),
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


def test_desktop_stage_receipt_stops_at_the_observed_delivery_boundary(
    tmp_path: Path,
) -> None:
    bundle = DesktopStageAttachmentBundle(
        root=tmp_path / "bundle",
        deliveries={
            "A2": {
                "receiver_local_reference": str(tmp_path / "A2.png"),
                "sha256": "2" * 64,
                "media_type": "image/png",
            },
            "A1": {
                "receiver_local_reference": str(tmp_path / "A1.png"),
                "sha256": "1" * 64,
                "media_type": "image/png",
            },
        },
        baseline_delivery={
            "id": "PB-exact",
            "receiver_local_reference": str(tmp_path / "baseline.json"),
            "manifest_sha256": "b" * 64,
        },
    )

    receipt = _desktop_stage_delivery_receipt(
        bundle,
        provider="codex",
        context_sha256="c" * 64,
        paste_verified=True,
        context_loaded=True,
    )

    assert receipt["status"] == "staged_awaiting_user_submission"
    assert receipt["verified_delivery_ready"] is False
    assert receipt["blocking_issue_codes"] == [
        "receiver_submission_unobserved",
        "receiver_consumption_unacknowledged",
        "native_image_attachment_unavailable",
    ]
    assert receipt["submission_observed"] is False
    assert receipt["receiver_acknowledged"] is False
    assert receipt["text"] == {
        "status": "composer_insert_verified",
        "sha256": "c" * 64,
        "composer_insert_verified": True,
        "receiver_acknowledged": False,
    }
    assert receipt["evidence"]["required_count"] == 3
    assert receipt["evidence"]["staged_count"] == 3
    assert receipt["evidence"]["attachment_ids"] == ["A1", "A2"]
    assert receipt["evidence"]["protected_baseline_id"] == "PB-exact"
    assert receipt["evidence"]["receiver_acknowledged_ids"] == []
    assert receipt["evidence"]["receiver_acknowledged"] is False
    assert receipt["failure_state"] == {
        "schema_version": "continuation.delivery_failure_state.v1",
        "submission": {
            "status": "unobserved",
            "code": "receiver_submission_unobserved",
            "blocks_verified_delivery": True,
        },
        "receiver_consumption": {
            "status": "unacknowledged",
            "code": "receiver_consumption_unacknowledged",
            "blocks_verified_delivery": True,
        },
        "native_image_attachment": {
            "status": "unsupported",
            "code": "native_image_attachment_unavailable",
            "attachment_ids": ["A1", "A2"],
            "blocks_verified_delivery": True,
        },
    }
    assert "receiver consumption have not been observed" in receipt["claim_boundary"]


def test_desktop_capability_profile_does_not_promote_provider_image_support() -> None:
    profile = _desktop_stage_target_capability_profile("codex")
    capabilities = profile["capabilities"]

    assert capabilities["native_image_attachment"]["provider_supported"] is True
    assert capabilities["native_image_attachment"]["adapter_supported"] is False
    assert capabilities["native_image_attachment"]["effective"] is False
    assert capabilities["receiver_consumption_acknowledgement"]["effective"] is False
    assert capabilities["automatic_execution"]["effective"] is False


def test_desktop_stage_receipt_does_not_promote_unverified_paste_dispatch() -> None:
    receipt = _desktop_stage_delivery_receipt(
        None,
        provider="codex",
        context_sha256="d" * 64,
        paste_verified=False,
        context_loaded=False,
    )

    assert receipt["text"]["status"] == "paste_dispatched_unverified"
    assert receipt["text"]["composer_insert_verified"] is False
    assert receipt["text"]["receiver_acknowledged"] is False
    assert receipt["evidence"]["status"] == "not_required"
    assert receipt["evidence"]["required_count"] == 0
    assert receipt["submission_observed"] is False
    assert receipt["verified_delivery_ready"] is False
    assert receipt["blocking_issue_codes"] == [
        "receiver_submission_unobserved",
        "receiver_consumption_unacknowledged",
    ]
    assert receipt["failure_state"]["native_image_attachment"] == {
        "status": "not_required",
        "code": None,
        "attachment_ids": [],
        "blocks_verified_delivery": False,
    }


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
