from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path

from app.services.request_artifacts import (
    MAX_LEGACY_CODEX_TURN_BYTES,
    MAX_TRUSTED_REQUEST_IMAGE_BYTES,
    TrustedRequestImageDescriptor,
    materialize_trusted_request_image_descriptor,
    recover_codex_request_image_descriptors,
    resolve_trusted_request_image_artifacts,
    structured_input_image_metadata,
    trusted_request_image_descriptors_from_payload,
)


def test_structured_provider_images_are_hash_bound_and_markup_alone_is_not(
    tmp_path,
) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(_test_png((7, 14, 21)))
    request = f'Implement the visual.\n<image path="{image}"></image>'
    digest = hashlib.sha256(image.read_bytes()).hexdigest()

    trusted = resolve_trusted_request_image_artifacts(
        request,
        trusted_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image),
                sha256=digest,
                mime_type="image/png",
            ),
        ),
        allow_local_files=True,
    )
    markup_only = resolve_trusted_request_image_artifacts(
        request,
        trusted_descriptors=(),
        allow_local_files=True,
    )

    assert trusted[0].available is True
    assert trusted[0].sha256 == digest
    assert markup_only[0].available is False
    assert markup_only[0].sha256 is None
    assert "structured source event" in (markup_only[0].visual_summary or "")


def test_explicitly_edited_lead_does_not_inherit_unreferenced_source_image(
    tmp_path,
) -> None:
    image = tmp_path / "old-reference.png"
    image.write_bytes(b"old-image")

    artifacts = resolve_trusted_request_image_artifacts(
        "Implement the newly edited lead without the old visual.",
        trusted_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image),
                sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                mime_type="image/png",
            ),
        ),
        allow_local_files=True,
        include_unreferenced_trusted_descriptors=False,
    )

    assert artifacts == ()


def test_trusted_image_resolver_rejects_symlinks_and_oversized_files(
    tmp_path,
) -> None:
    target = tmp_path / "target.png"
    target.write_bytes(b"private")
    symlink = tmp_path / "link.png"
    symlink.symlink_to(target)
    oversized = tmp_path / "oversized.png"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_TRUSTED_REQUEST_IMAGE_BYTES + 1)
    request = (
        f'<image path="{symlink}"></image>\n'
        f'<image path="{oversized}"></image>'
    )

    artifacts = resolve_trusted_request_image_artifacts(
        request,
        trusted_descriptors=(
            TrustedRequestImageDescriptor(path=str(symlink)),
            TrustedRequestImageDescriptor(path=str(oversized)),
        ),
        allow_local_files=True,
    )

    assert [artifact.available for artifact in artifacts] == [False, False]
    assert [artifact.sha256 for artifact in artifacts] == [None, None]


def test_legacy_codex_turn_recovers_only_matching_structured_local_images(
    tmp_path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    image_paths = []
    content_items = []
    image_contents = (
        _test_png((255, 0, 0)),
        _test_png((0, 255, 0)),
        _test_png((0, 0, 255)),
    )
    for index, content in enumerate(image_contents, start=1):
        path = tmp_path / f"reference-{index}.png"
        path.write_bytes(content)
        image_paths.append(str(path))
        content_items.append({
            "type": "input_image",
            "image_url": (
                "data:image/png;base64,"
                + base64.b64encode(content).decode("ascii")
            ),
        })
    request = (
        "WORK ON THIS AND GET THIS DONE.\n"
        + "\n".join(
            f'<image path="{path}"></image>' for path in image_paths
        )
    )
    raw_request = (
        "## My request for Codex:\n"
        + request
    )
    rollout = sessions / "rollout.jsonl"
    response = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": raw_request},
                *content_items,
            ],
        },
    }
    event = {
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": (
                "## My request for Codex:\n"
                "WORK ON THIS AND GET THIS DONE."
            ),
            "local_images": image_paths,
        },
    }
    rollout.write_text(
        json.dumps(response) + "\n" + json.dumps(event) + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    descriptors = recover_codex_request_image_descriptors(
        source_path=str(rollout),
        source_sequence_number=1,
        request_verbatim=request,
        codex_sessions_root=sessions,
        artifact_data_dir=Path("data"),
    )

    assert [descriptor.path for descriptor in descriptors] == image_paths
    assert [descriptor.sha256 for descriptor in descriptors] == [
        hashlib.sha256(content).hexdigest()
        for content in image_contents
    ]
    stored = [
        descriptor.resolved_path for descriptor in descriptors
    ]
    assert all(path is not None for path in stored)
    assert all(Path(path).is_absolute() for path in stored)
    assert all((tmp_path / "data") in Path(path).parents for path in stored)
    assert all(
        (Path(path).stat().st_mode & 0o777) == 0o600
        for path in stored
    )


def test_attachment_without_source_time_digest_is_never_available(
    tmp_path,
) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(_test_png((4, 5, 6)))

    artifact = resolve_trusted_request_image_artifacts(
        f'<image path="{image}"></image>',
        trusted_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(image),
                mime_type="image/png",
            ),
        ),
        allow_local_files=True,
    )[0]

    assert artifact.available is False
    assert artifact.sha256 is None
    assert "source-time SHA-256" in (artifact.visual_summary or "")


def test_invalid_input_image_retains_ordinal_without_shifting_later_hash(
    tmp_path,
) -> None:
    first = tmp_path / "invalid-first.png"
    second = tmp_path / "valid-second.png"
    second_content = _test_png((7, 8, 9))
    first.write_bytes(b"not-a-raster")
    second.write_bytes(second_content)
    metadata = structured_input_image_metadata([
        {
            "type": "input_image",
            "image_url": "data:image/png;base64,not-valid-base64",
        },
        {
            "type": "input_image",
            "image_url": (
                "data:image/png;base64,"
                + base64.b64encode(second_content).decode("ascii")
            ),
        },
    ])

    assert [item["ordinal"] for item in metadata] == [1, 2]
    assert metadata[0]["valid"] is False
    descriptors = trusted_request_image_descriptors_from_payload({
        "local_images": [str(first), str(second)],
        "input_images": metadata,
    })
    artifacts = resolve_trusted_request_image_artifacts(
        "",
        trusted_descriptors=descriptors,
        allow_local_files=True,
    )

    assert descriptors[0].binding_valid is False
    assert descriptors[1].ordinal == 2
    assert descriptors[1].sha256 == hashlib.sha256(
        second_content
    ).hexdigest()
    assert [artifact.available for artifact in artifacts] == [False, True]


def test_cardinality_mismatch_blocks_every_positional_binding(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    content = _test_png((10, 11, 12))
    first.write_bytes(content)
    second.write_bytes(content)

    descriptors = trusted_request_image_descriptors_from_payload({
        "local_images": [str(first), str(second)],
        "input_images": [{
            "ordinal": 1,
            "valid": True,
            "sha256": hashlib.sha256(content).hexdigest(),
            "mime_type": "image/png",
        }],
    })

    assert len(descriptors) == 2
    assert all(not descriptor.binding_valid for descriptor in descriptors)
    assert all(
        "counts differ" in (descriptor.binding_error or "")
        for descriptor in descriptors
    )


def test_legacy_recovery_requires_the_exact_adjacent_turn_pair(
    tmp_path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    content = _test_png((13, 14, 15))
    image_path = tmp_path / "reference.png"
    image_path.write_bytes(content)
    request = "Implement the exact attached reference."
    rollout = sessions / "rollout.jsonl"
    rollout.write_text("\n".join((
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": request},
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/png;base64,"
                            + base64.b64encode(content).decode("ascii")
                        ),
                    },
                ],
            },
        }),
        json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}),
        json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": request,
                "local_images": [str(image_path)],
            },
        }),
    )), encoding="utf-8")

    assert recover_codex_request_image_descriptors(
        source_path=str(rollout),
        source_sequence_number=1,
        request_verbatim=request,
        codex_sessions_root=sessions,
        artifact_data_dir=tmp_path / "data",
    ) == ()
    assert not (tmp_path / "data").exists()


def test_legacy_recovery_rejects_an_oversized_target_line(tmp_path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    rollout = sessions / "rollout.jsonl"
    with rollout.open("wb") as handle:
        handle.write(b" " * (MAX_LEGACY_CODEX_TURN_BYTES + 1))
        handle.write(b"\n{}\n")

    assert recover_codex_request_image_descriptors(
        source_path=str(rollout),
        source_sequence_number=1,
        request_verbatim="Implement the attached image.",
        codex_sessions_root=sessions,
    ) == ()


def test_forged_png_signature_and_unsafe_dimensions_are_rejected(
    tmp_path,
) -> None:
    forged = tmp_path / "forged.png"
    forged.write_bytes(b"\x89PNG\r\n\x1a\n" + b"forged")
    huge = tmp_path / "huge.png"
    huge.write_bytes(_test_png((1, 1, 1), width=32_769))

    artifacts = resolve_trusted_request_image_artifacts(
        (
            f'<image path="{forged}"></image>\n'
            f'<image path="{huge}"></image>'
        ),
        trusted_descriptors=(
            TrustedRequestImageDescriptor(
                path=str(forged),
                sha256=hashlib.sha256(forged.read_bytes()).hexdigest(),
                mime_type="image/png",
            ),
            TrustedRequestImageDescriptor(
                path=str(huge),
                sha256=hashlib.sha256(huge.read_bytes()).hexdigest(),
                mime_type="image/png",
            ),
        ),
        allow_local_files=True,
    )

    assert [artifact.available for artifact in artifacts] == [False, False]


def test_claimed_stored_path_is_rehomed_into_content_addressed_storage(
    tmp_path,
) -> None:
    source = tmp_path / "temporary-reference.png"
    source.write_bytes(_test_png((16, 17, 18)))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    descriptor = materialize_trusted_request_image_descriptor(
        TrustedRequestImageDescriptor(
            path=str(source),
            resolved_path=str(source),
            sha256=digest,
            mime_type="image/png",
            ordinal=1,
        ),
        data_dir=tmp_path / "durable",
    )

    assert descriptor.binding_valid is True
    assert descriptor.resolved_path != str(source)
    assert Path(descriptor.resolved_path or "").read_bytes() == (
        source.read_bytes()
    )
    assert (
        tmp_path / "durable" / "request-artifacts"
    ) in Path(descriptor.resolved_path or "").parents


def _test_png(
    rgb: tuple[int, int, int],
    *,
    width: int = 1,
    height: int = 1,
) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            len(content).to_bytes(4, "big")
            + kind
            + content
            + (zlib.crc32(kind + content) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
        + chunk(b"IEND", b"")
    )
