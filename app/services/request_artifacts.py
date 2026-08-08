from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import stat
import struct
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.schemas.continuation_execution import (
    MAX_CONTINUATION_ARTIFACTS,
    ArtifactReference,
)
from app.services.session_summary import (
    extract_delegated_user_request,
    extract_user_authored_request,
)


MAX_TRUSTED_REQUEST_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TRUSTED_REQUEST_TURN_IMAGE_BYTES = 32 * 1024 * 1024
MAX_LEGACY_CODEX_TURN_BYTES = (
    (MAX_TRUSTED_REQUEST_TURN_IMAGE_BYTES + 2) // 3
) * 4 + 2 * 1024 * 1024
MAX_RASTER_DIMENSION = 32_768
MAX_RASTER_PIXELS = 100_000_000
_SOURCE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_RASTER_MIME_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)
_IMAGE_PATH_RE = re.compile(
    r"(?is)<image\b[^>]*\bpath\s*=\s*"
    r"(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))[^>]*>",
)


@dataclass(frozen=True)
class TrustedRequestImageDescriptor:
    """Provider-authenticated attachment metadata for one user turn."""

    path: str
    sha256: str | None = None
    mime_type: str | None = None
    resolved_path: str | None = None
    ordinal: int | None = None
    size_bytes: int | None = None
    binding_valid: bool = True
    binding_error: str | None = None
    visual_inspection: Mapping[str, Any] | None = None
    visual_inspection_attested: bool = False


_VISUAL_INSPECTION_OUTPUT_FIELDS = (
    "producer",
    "status",
    "inspected_sha256",
    "method",
    "inspector_model",
    "prompt_definition_sha256",
    "summary",
    "anchors",
    "suspected_surface",
    "candidate_route",
    "candidate_files",
)


def trusted_image_inspection_output_sha256(value: Mapping[str, Any]) -> str:
    """Hash the canonical infrastructure observation payload, excluding its signature field."""

    payload = {field: value.get(field) for field in _VISUAL_INSPECTION_OUTPUT_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def validated_trusted_image_inspection(
    descriptor: TrustedRequestImageDescriptor,
) -> dict[str, Any] | None:
    """Return bounded, digest-bound visual observations or fail closed."""

    raw = descriptor.visual_inspection
    expected_sha256 = str(descriptor.sha256 or "").casefold()
    if (
        descriptor.binding_valid is not True
        or str(descriptor.mime_type or "").casefold() not in _SUPPORTED_RASTER_MIME_TYPES
        or descriptor.visual_inspection_attested is not True
        or not isinstance(raw, Mapping)
        or str(raw.get("producer") or "") != "daemonstate_visual_inspection.v1"
        or str(raw.get("status") or "") != "succeeded"
        or str(raw.get("inspected_sha256") or "").casefold() != expected_sha256
        or _SOURCE_SHA256_RE.fullmatch(expected_sha256) is None
    ):
        return None
    prompt_sha256 = str(raw.get("prompt_definition_sha256") or "").casefold()
    output_sha256 = str(raw.get("output_sha256") or "").casefold()
    try:
        computed_output_sha256 = trusted_image_inspection_output_sha256(raw)
    except (TypeError, ValueError):
        return None
    if (
        _SOURCE_SHA256_RE.fullmatch(prompt_sha256) is None
        or _SOURCE_SHA256_RE.fullmatch(output_sha256) is None
        or output_sha256 != computed_output_sha256
        or not str(raw.get("method") or "").strip()
        or not str(raw.get("inspector_model") or "").strip()
    ):
        return None
    raw_anchors = raw.get("anchors")
    if not isinstance(raw_anchors, (list, tuple)) or not 1 <= len(raw_anchors) <= 12:
        return None
    anchors: list[dict[str, Any]] = []
    for value in raw_anchors:
        if not isinstance(value, Mapping):
            return None
        text = " ".join(str(value.get("text") or "").split())[:300]
        if not text:
            return None
        confidence = value.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            confidence = None
        anchors.append(
            {
                "kind": " ".join(str(value.get("kind") or "visual_cue").split())[:50],
                "text": text,
                "region": " ".join(str(value.get("region") or "unknown").split())[:50],
                "confidence": (
                    max(0.0, min(1.0, float(confidence))) if confidence is not None else None
                ),
            }
        )
    candidate_files: list[dict[str, str]] = []
    raw_candidates = raw.get("candidate_files")
    if isinstance(raw_candidates, (list, tuple)) and len(raw_candidates) <= 8:
        for value in raw_candidates:
            if not isinstance(value, Mapping):
                continue
            path = " ".join(str(value.get("path") or "").split())[:500]
            reason = " ".join(str(value.get("reason") or "").split())[:500]
            if path and reason:
                candidate_files.append({"path": path, "reason": reason})
    validated = {
        "producer": "daemonstate_visual_inspection.v1",
        "status": "succeeded",
        "inspected_sha256": expected_sha256,
        "method": " ".join(str(raw.get("method") or "vision_model").split())[:80],
        "inspector_model": " ".join(str(raw.get("inspector_model") or "").split())[:160] or None,
        "prompt_definition_sha256": prompt_sha256 or None,
        "output_sha256": output_sha256 or None,
        "summary": " ".join(str(raw.get("summary") or "").split())[:1_000] or None,
        "anchors": anchors,
        "suspected_surface": " ".join(str(raw.get("suspected_surface") or "").split())[:160]
        or None,
        "candidate_route": " ".join(str(raw.get("candidate_route") or "").split())[:160] or None,
        "candidate_files": (candidate_files if raw_candidates is not None else None),
        "trust": "infrastructure_attested_hash_bound_observation",
    }
    # The persisted record rendered into a receiving session must itself be a
    # canonical attested payload.  Reject producer output that only becomes
    # valid after truncation, whitespace normalization, or field dropping so a
    # later renderer can independently recompute this exact hash.
    if trusted_image_inspection_output_sha256(validated) != output_sha256:
        return None
    return validated


def materialize_trusted_request_image_descriptor(
    descriptor: TrustedRequestImageDescriptor,
    *,
    data_dir: str | Path,
) -> TrustedRequestImageDescriptor:
    """Copy one hash-bound exact-turn raster into durable content storage."""

    if (
        not descriptor.binding_valid
        or descriptor.sha256 is None
        or _SOURCE_SHA256_RE.fullmatch(descriptor.sha256.casefold()) is None
        or descriptor.mime_type is None
        or descriptor.mime_type.casefold() not in _SUPPORTED_RASTER_MIME_TYPES
    ):
        return descriptor
    if (
        descriptor.resolved_path
        and _is_content_addressed_artifact_path(
            descriptor.resolved_path,
            sha256=descriptor.sha256,
            mime_type=descriptor.mime_type,
            data_dir=data_dir,
        )
        and _hash_bounded_raster_file(
            Path(descriptor.resolved_path),
            mime_type=descriptor.mime_type,
        )
        == descriptor.sha256.casefold()
    ):
        return descriptor
    descriptor = replace(descriptor, resolved_path=None)
    source = Path(descriptor.path)
    content = _read_bounded_raster_file(
        source,
        mime_type=descriptor.mime_type,
    )
    if content is None or hashlib.sha256(content).hexdigest() != descriptor.sha256.casefold():
        return replace(
            descriptor,
            binding_valid=False,
            binding_error=(
                "The provider image could not be durably materialized from its source-time digest."
            ),
        )
    stored = _materialize_content_addressed_image(
        content,
        mime_type=descriptor.mime_type,
        data_dir=Path(data_dir).expanduser().resolve(),
    )
    if stored is None:
        return replace(
            descriptor,
            binding_valid=False,
            binding_error=("The provider image could not be durably materialized."),
        )
    return replace(
        descriptor,
        resolved_path=str(stored),
        size_bytes=len(content),
    )


def _is_content_addressed_artifact_path(
    value: str,
    *,
    sha256: str,
    mime_type: str,
    data_dir: str | Path,
) -> bool:
    suffixes = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    suffix = suffixes.get(mime_type.casefold())
    if suffix is None:
        return False
    try:
        root = Path(data_dir).expanduser().resolve() / "request-artifacts" / sha256[:2]
        candidate = Path(value).expanduser()
        if candidate.name != f"{sha256}{suffix}":
            return False
        return candidate.parent.resolve(strict=True) == root.resolve(strict=True)
    except (OSError, ValueError):
        return False


def resolve_trusted_request_image_artifacts(
    request_verbatim: str,
    *,
    trusted_descriptors: Iterable[TrustedRequestImageDescriptor | Mapping[str, Any]],
    allow_local_files: bool,
    include_unreferenced_trusted_descriptors: bool = True,
) -> tuple[ArtifactReference, ...]:
    """Resolve only image tags corroborated by structured provider transport.

    ``request_verbatim`` remains the lossless task, but its markup is never file
    read authority. Callers must supply descriptors recovered from the exact
    same-session provider event or immutable source boundary. Every request
    reference is retained; uncorroborated, unsafe, missing, or digest-mismatched
    paths remain explicit unavailable artifacts so continuation fails closed.
    """

    paths: list[str] = []
    seen: set[str] = set()
    for match in _IMAGE_PATH_RE.finditer(str(request_verbatim or "")):
        path = next(
            (group for group in match.groups() if group is not None),
            "",
        ).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    trusted: dict[str, TrustedRequestImageDescriptor] = {}
    for raw in trusted_descriptors:
        descriptor = (
            raw
            if isinstance(raw, TrustedRequestImageDescriptor)
            else TrustedRequestImageDescriptor(
                path=str(raw.get("path") or "").strip(),
                sha256=str(raw.get("sha256") or "").strip() or None,
                mime_type=str(raw.get("mime_type") or "").strip() or None,
                resolved_path=(
                    str(raw.get("resolved_path") or raw.get("stored_path") or "").strip() or None
                ),
                ordinal=(
                    int(raw["ordinal"])
                    if isinstance(raw.get("ordinal"), int)
                    and not isinstance(raw.get("ordinal"), bool)
                    else None
                ),
                size_bytes=(
                    int(raw["size_bytes"])
                    if isinstance(raw.get("size_bytes"), int)
                    and not isinstance(raw.get("size_bytes"), bool)
                    else None
                ),
                binding_valid=raw.get("binding_valid") is not False,
                binding_error=(str(raw.get("binding_error") or "").strip() or None),
            )
        )
        if descriptor.path and descriptor.path not in trusted:
            trusted[descriptor.path] = descriptor
    if include_unreferenced_trusted_descriptors:
        # Structured provider attachments remain part of the original user
        # turn even when the provider omits transport tags from normalized
        # request text. An explicitly edited lead opts out unless it still
        # references the attachment; otherwise stale source images would be
        # silently carried into a new task.
        for path in trusted:
            if path not in seen:
                seen.add(path)
                paths.append(path)
    if len(paths) > MAX_CONTINUATION_ARTIFACTS:
        raise ValueError(
            "trusted request image references exceed the supported limit of "
            f"{MAX_CONTINUATION_ARTIFACTS}"
        )

    return tuple(
        _resolve_image_path(
            path,
            index=index,
            descriptor=trusted.get(path),
            allow_local_files=allow_local_files,
        )
        for index, path in enumerate(paths, start=1)
    )


def trusted_request_image_descriptors_from_payload(
    payload: Mapping[str, Any] | None,
) -> tuple[TrustedRequestImageDescriptor, ...]:
    """Read bounded structured image descriptors persisted for a user event."""

    value = payload if isinstance(payload, Mapping) else {}
    raw_paths = value.get("local_images")
    if not isinstance(raw_paths, (list, tuple)) or len(raw_paths) > MAX_CONTINUATION_ARTIFACTS:
        return ()
    paths = list(raw_paths)
    raw_inputs = value.get("input_images")
    inputs = (
        list(raw_inputs)
        if isinstance(raw_inputs, (list, tuple)) and len(raw_inputs) <= MAX_CONTINUATION_ARTIFACTS
        else []
    )
    cardinality_valid = len(paths) == len(inputs)
    inputs_by_ordinal: dict[int, Mapping[str, Any]] = {}
    ordinal_binding_valid = True
    for position, raw_input in enumerate(inputs, start=1):
        image = raw_input if isinstance(raw_input, Mapping) else {}
        raw_ordinal = image.get("ordinal", position)
        if (
            not isinstance(raw_ordinal, int)
            or isinstance(raw_ordinal, bool)
            or raw_ordinal < 1
            or raw_ordinal > len(inputs)
            or raw_ordinal in inputs_by_ordinal
        ):
            ordinal_binding_valid = False
            continue
        inputs_by_ordinal[raw_ordinal] = image
    ordinal_binding_valid = ordinal_binding_valid and set(inputs_by_ordinal) == set(
        range(1, len(inputs) + 1)
    )
    descriptors: list[TrustedRequestImageDescriptor] = []
    for ordinal, raw_path in enumerate(paths, start=1):
        path = (
            str(raw_path.get("path") or "").strip()
            if isinstance(raw_path, Mapping)
            else str(raw_path or "").strip()
        )
        if not path:
            continue
        image = inputs_by_ordinal.get(ordinal, {})
        source_sha256 = str(image.get("sha256") or "").strip().casefold()
        image_valid = image.get("valid") is not False and bool(
            _SOURCE_SHA256_RE.fullmatch(source_sha256)
        )
        binding_valid = cardinality_valid and ordinal_binding_valid and image_valid
        binding_error = None
        if not cardinality_valid:
            binding_error = "The provider image metadata and local path counts differ."
        elif not ordinal_binding_valid:
            binding_error = "The provider image metadata ordinals are missing or ambiguous."
        elif not image_valid:
            binding_error = str(
                image.get("error") or "The provider image has no valid source-time SHA-256."
            )
        descriptors.append(
            TrustedRequestImageDescriptor(
                path=path,
                sha256=source_sha256 or None,
                mime_type=str(image.get("mime_type") or "").strip() or None,
                resolved_path=(str(image.get("stored_path") or "").strip() or None),
                ordinal=ordinal,
                size_bytes=(
                    int(image["size_bytes"])
                    if isinstance(image.get("size_bytes"), int)
                    and not isinstance(image.get("size_bytes"), bool)
                    else None
                ),
                binding_valid=binding_valid,
                binding_error=binding_error,
            )
        )
    return tuple(descriptors)


def recover_codex_request_image_descriptors(
    *,
    source_path: str,
    source_sequence_number: int,
    request_verbatim: str,
    codex_sessions_root: str | Path,
    artifact_data_dir: str | Path | None = None,
) -> tuple[TrustedRequestImageDescriptor, ...]:
    """Recover structured images from an exact legacy Codex JSONL turn.

    Old normalized events retained only ``message_id``. This reads a small
    window at the exact provider line and accepts ``local_images`` only when
    both the response item and adjacent event message match the authoritative
    user request. The rollout path must be a regular, non-symlink file inside
    the configured Codex sessions directory.
    """

    path = Path(source_path)
    root = Path(codex_sessions_root)
    try:
        resolved_root = root.resolve(strict=True)
        resolved_parent = path.parent.resolve(strict=True)
        if not resolved_parent.is_relative_to(resolved_root):
            return ()
    except (OSError, ValueError):
        return ()
    rows = _bounded_jsonl_window(path, source_sequence_number)
    if not rows:
        return ()
    expected = normalize_request_without_image_transport(request_verbatim)
    rows_by_number = dict(rows)
    response = rows_by_number.get(source_sequence_number)
    event = rows_by_number.get(source_sequence_number + 1)
    if not isinstance(response, Mapping) or not isinstance(event, Mapping):
        return ()
    response_payload = response.get("payload")
    event_payload = event.get("payload")
    if (
        response.get("type") != "response_item"
        or not isinstance(response_payload, Mapping)
        or response_payload.get("type") != "message"
        or str(response_payload.get("role") or "").strip().casefold() != "user"
        or event.get("type") != "event_msg"
        or not isinstance(event_payload, Mapping)
        or event_payload.get("type") != "user_message"
    ):
        return ()
    response_text = _provider_content_text(response_payload.get("content"))
    event_text = _provider_content_text(
        event_payload.get("message") or event_payload.get("content")
    )
    if (
        normalize_request_without_image_transport(response_text) != expected
        or normalize_request_without_image_transport(event_text) != expected
    ):
        return ()
    input_images = structured_input_image_metadata(
        response_payload.get("content"),
        data_dir=artifact_data_dir,
    )
    local_images = structured_local_image_paths(event_payload.get("local_images"))
    return _bind_image_descriptors(local_images, input_images)


def _resolve_image_path(
    path_text: str,
    *,
    index: int,
    descriptor: TrustedRequestImageDescriptor | None,
    allow_local_files: bool,
) -> ArtifactReference:
    mime_type = (
        descriptor.mime_type
        if descriptor is not None and descriptor.mime_type
        else mimetypes.guess_type(path_text)[0]
    )
    if descriptor is None:
        unavailable_reason = (
            "The image path was not corroborated by the structured source "
            "event for this exact user turn."
        )
    elif not descriptor.binding_valid:
        unavailable_reason = (
            descriptor.binding_error
            or "The provider image could not be bound to this attachment ordinal."
        )
    elif (
        descriptor.sha256 is None
        or _SOURCE_SHA256_RE.fullmatch(descriptor.sha256.casefold()) is None
    ):
        unavailable_reason = "The provider attachment has no valid source-time SHA-256."
    elif not allow_local_files:
        unavailable_reason = "Local artifact access is unavailable for this request."
    else:
        unavailable_reason = "The provider-attached image is not a safe readable local image."
    digest: str | None = None
    readable_path = (
        descriptor.resolved_path
        if descriptor is not None and descriptor.resolved_path
        else path_text
    )
    if (
        descriptor is not None
        and descriptor.binding_valid
        and descriptor.sha256 is not None
        and _SOURCE_SHA256_RE.fullmatch(descriptor.sha256.casefold()) is not None
        and allow_local_files
        and Path(readable_path).is_absolute()
        and mime_type is not None
        and mime_type.casefold() in _SUPPORTED_RASTER_MIME_TYPES
    ):
        digest = _hash_bounded_raster_file(
            Path(readable_path),
            mime_type=mime_type,
        )
        if digest is not None and digest != descriptor.sha256.casefold():
            digest = None
            unavailable_reason = "The provider-attached image no longer matches its source digest."
        elif digest is None:
            unavailable_reason = (
                "The provider-attached image is not a supported, safely bounded raster image."
            )
    available = digest is not None
    return ArtifactReference(
        id=f"A{index}",
        kind="screenshot",
        path=readable_path,
        source_path=(path_text if readable_path != path_text else None),
        sha256=digest,
        mime_type=mime_type,
        required=True,
        available=available,
        visual_summary=None if available else unavailable_reason,
    )


def _hash_bounded_regular_file(path: Path) -> str | None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_TRUSTED_REQUEST_IMAGE_BYTES:
            return None
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _hash_bounded_raster_file(
    path: Path,
    *,
    mime_type: str,
) -> str | None:
    content = _read_bounded_raster_file(path, mime_type=mime_type)
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _read_bounded_raster_file(
    path: Path,
    *,
    mime_type: str,
) -> bytes | None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > MAX_TRUSTED_REQUEST_IMAGE_BYTES
        ):
            return None
        content = bytearray()
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            while chunk := handle.read(1024 * 1024):
                content.extend(chunk)
        if not _safe_raster_dimensions(bytes(content), mime_type=mime_type):
            return None
        return bytes(content)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _bounded_jsonl_window(
    path: Path,
    source_sequence_number: int,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    if source_sequence_number < 1:
        return ()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return ()
        result: list[tuple[int, dict[str, Any]]] = []
        bytes_read = 0
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            for _ in range(source_sequence_number - 1):
                if not _skip_bounded_binary_line(handle):
                    return ()
            for line_number in (
                source_sequence_number,
                source_sequence_number + 1,
            ):
                remaining = MAX_LEGACY_CODEX_TURN_BYTES - bytes_read
                if remaining <= 0:
                    return ()
                raw = handle.readline(remaining + 1)
                if not raw or len(raw) > remaining:
                    return ()
                bytes_read += len(raw)
                try:
                    value = json.loads(raw.decode("utf-8", errors="replace"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    result.append((line_number, value))
        return tuple(result)
    except OSError:
        return ()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _skip_bounded_binary_line(handle: Any) -> bool:
    consumed = 0
    while consumed <= MAX_LEGACY_CODEX_TURN_BYTES:
        chunk = handle.readline(min(64 * 1024, MAX_LEGACY_CODEX_TURN_BYTES - consumed + 1))
        if not chunk:
            return False
        consumed += len(chunk)
        if consumed > MAX_LEGACY_CODEX_TURN_BYTES:
            return False
        if chunk.endswith(b"\n"):
            return True
    return False


def _provider_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        if value.get("type") in {"text", "input_text"}:
            return str(value.get("text") or "").strip()
        parts = [_provider_content_text(value.get(key)) for key in ("text", "content")]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, (list, tuple)):
        parts = [_provider_content_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return ""


def normalize_request_without_image_transport(value: str) -> str:
    raw = str(value or "")
    extracted = extract_user_authored_request(raw) or extract_delegated_user_request(raw) or raw
    without_image_transport = re.sub(
        r"(?is)</?image\b[^>]*>",
        " ",
        extracted,
    )
    return " ".join(without_image_transport.split())


def structured_local_image_paths(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_CONTINUATION_ARTIFACTS:
        return []
    result: list[str] = []
    for raw in value:
        path = (
            str(raw.get("path") or "").strip()
            if isinstance(raw, Mapping)
            else str(raw or "").strip()
        )
        # Empty values deliberately retain their ordinal. Compressing them
        # would bind every later local path to the wrong input_image digest.
        result.append(path)
    return result


def structured_input_image_metadata(
    value: Any,
    *,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    image_urls: list[str] = []
    total_size = 0
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").strip() not in {
            "input_image",
            "image",
        }:
            continue
        ordinal = len(result) + 1
        if ordinal > MAX_CONTINUATION_ARTIFACTS:
            return []
        raw_url = str(item.get("image_url") or item.get("url") or "")
        image_urls.append(raw_url)
        metadata = _data_url_metadata(raw_url, data_dir=None)
        if metadata is None:
            metadata = {
                "mime_type": _declared_data_url_mime(raw_url),
                "valid": False,
                "error": (
                    "The provider input image is not a valid supported bounded raster data URL."
                ),
            }
        metadata["ordinal"] = ordinal
        size_bytes = metadata.get("size_bytes")
        if (
            isinstance(size_bytes, int)
            and not isinstance(size_bytes, bool)
            and metadata.get("valid") is not False
        ):
            total_size += size_bytes
        result.append(metadata)
    if total_size > MAX_TRUSTED_REQUEST_TURN_IMAGE_BYTES:
        for metadata in result:
            metadata["valid"] = False
            metadata["error"] = "The provider turn exceeds the aggregate trusted image limit."
            metadata.pop("stored_path", None)
    elif data_dir is not None:
        for metadata, raw_url in zip(result, image_urls, strict=True):
            if metadata.get("valid") is False:
                continue
            durable = _data_url_metadata(raw_url, data_dir=data_dir)
            if durable is None or not durable.get("stored_path"):
                metadata["valid"] = False
                metadata["error"] = "The provider input image could not be durably stored."
                metadata.pop("stored_path", None)
                continue
            metadata["stored_path"] = durable["stored_path"]
    return result


def _data_url_metadata(
    value: str,
    *,
    data_dir: str | Path | None,
) -> dict[str, Any] | None:
    match = re.fullmatch(
        r"data:([^;,]+);base64,([A-Za-z0-9+/=\r\n]+)",
        value,
    )
    if match is None:
        return None
    import base64

    encoded = re.sub(r"\s+", "", match.group(2))
    if len(encoded) > ((MAX_TRUSTED_REQUEST_IMAGE_BYTES + 2) // 3) * 4:
        return None
    try:
        content = base64.b64decode(
            encoded,
            validate=True,
        )
    except (ValueError, TypeError):
        return None
    mime_type = match.group(1).casefold()
    if (
        not content
        or len(content) > MAX_TRUSTED_REQUEST_IMAGE_BYTES
        or mime_type not in _SUPPORTED_RASTER_MIME_TYPES
        or not _safe_raster_dimensions(content, mime_type=mime_type)
    ):
        return None
    metadata: dict[str, Any] = {
        "mime_type": mime_type,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "valid": True,
    }
    if data_dir is not None:
        stored_path = _materialize_content_addressed_image(
            content,
            mime_type=mime_type,
            data_dir=Path(data_dir).expanduser().resolve(),
        )
        if stored_path is not None:
            metadata["stored_path"] = str(stored_path)
    return metadata


def _bind_image_descriptors(
    local_images: list[str],
    input_images: list[dict[str, Any]],
) -> tuple[TrustedRequestImageDescriptor, ...]:
    return trusted_request_image_descriptors_from_payload(
        {
            "local_images": local_images,
            "input_images": input_images,
        }
    )


def _declared_data_url_mime(value: str) -> str | None:
    match = re.match(r"data:([^;,]+)", value)
    return match.group(1).casefold() if match is not None else None


def _safe_raster_dimensions(content: bytes, *, mime_type: str) -> bool:
    dimensions: tuple[int, int] | None
    normalized_mime = mime_type.casefold()
    if normalized_mime == "image/png":
        dimensions = _png_dimensions(content)
    elif normalized_mime == "image/jpeg":
        dimensions = _jpeg_dimensions(content)
    elif normalized_mime == "image/gif":
        dimensions = _gif_dimensions(content)
    elif normalized_mime == "image/webp":
        dimensions = _webp_dimensions(content)
    else:
        return False
    if dimensions is None:
        return False
    width, height = dimensions
    return (
        0 < width <= MAX_RASTER_DIMENSION
        and 0 < height <= MAX_RASTER_DIMENSION
        and width * height <= MAX_RASTER_PIXELS
    )


def _png_dimensions(content: bytes) -> tuple[int, int] | None:
    if (
        len(content) < 45
        or content[:8] != b"\x89PNG\r\n\x1a\n"
        or content[8:12] != b"\x00\x00\x00\r"
        or content[12:16] != b"IHDR"
    ):
        return None
    ihdr = content[12:29]
    expected_crc = int.from_bytes(content[29:33], "big")
    if zlib.crc32(ihdr) & 0xFFFFFFFF != expected_crc:
        return None
    width, height = struct.unpack(">II", content[16:24])
    bit_depth, color_type, compression, filtering, interlace = content[24:29]
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        bit_depth not in valid_depths.get(color_type, set())
        or compression != 0
        or filtering != 0
        or interlace not in {0, 1}
    ):
        return None
    # A bounded structural walk catches truncation and forged signatures
    # without importing an undeclared image-decoder dependency.
    offset = 8
    saw_idat = False
    saw_iend = False
    while offset + 12 <= len(content):
        chunk_length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(content):
            return None
        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + chunk_length]
        chunk_crc = int.from_bytes(
            content[offset + 8 + chunk_length : chunk_end],
            "big",
        )
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != chunk_crc:
            return None
        saw_idat = saw_idat or chunk_type == b"IDAT"
        if chunk_type == b"IEND":
            saw_iend = chunk_length == 0
            break
        offset = chunk_end
    return (width, height) if saw_idat and saw_iend else None


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 4 or content[:2] != b"\xff\xd8" or content[-2:] != b"\xff\xd9":
        return None
    offset = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 1 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(content):
            return None
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            return None
        if marker in start_of_frame:
            if segment_length < 7:
                return None
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    return None


def _gif_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 14 or content[:6] not in {b"GIF87a", b"GIF89a"} or content[-1:] != b";":
        return None
    return struct.unpack("<HH", content[6:10])


def _webp_dimensions(content: bytes) -> tuple[int, int] | None:
    if (
        len(content) < 30
        or content[:4] != b"RIFF"
        or content[8:12] != b"WEBP"
        or int.from_bytes(content[4:8], "little") + 8 > len(content)
    ):
        return None
    chunk_type = content[12:16]
    data = content[20:]
    if chunk_type == b"VP8X" and len(data) >= 10:
        width = int.from_bytes(data[4:7], "little") + 1
        height = int.from_bytes(data[7:10], "little") + 1
        return width, height
    if chunk_type == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
        bits = int.from_bytes(data[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk_type == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[6:8], "little") & 0x3FFF
        height = int.from_bytes(data[8:10], "little") & 0x3FFF
        return width, height
    return None


def _materialize_content_addressed_image(
    content: bytes,
    *,
    mime_type: str,
    data_dir: Path,
) -> Path | None:
    suffixes = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    suffix = suffixes.get(mime_type.casefold())
    if suffix is None or len(content) > MAX_TRUSTED_REQUEST_IMAGE_BYTES:
        return None
    digest = hashlib.sha256(content).hexdigest()
    request_root = data_dir / "request-artifacts"
    directory = request_root / digest[:2]
    try:
        request_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if request_root.is_symlink():
            return None
        directory.mkdir(exist_ok=True, mode=0o700)
        if directory.is_symlink():
            return None
        target = directory / f"{digest}{suffix}"
        if target.exists():
            return target if _hash_bounded_regular_file(target) == digest else None
        temporary = directory / (f".{digest}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)
        if _hash_bounded_regular_file(target) != digest:
            return None
        os.chmod(target, 0o600)
        return target
    except OSError:
        return None
