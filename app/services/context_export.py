"""Build a digest-bound export of the public Session Context's allowed details."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.schemas.context_quality import canonical_json


SESSION_CONTEXT_DETAILS_SCHEMA_VERSION = "session_context_details.v1"
_ATTACHMENT_REFERENCE_FIELDS = frozenset({
    "id", "kind", "name", "portable_reference", "required", "dependency_role",
    "available", "available_at_capture", "source_binding_valid", "source_identity_complete",
    "source_bytes_available", "source_attachment_ordinal", "source_event_id",
    "sha256", "content_hash", "mime_type", "media_type", "capture_status",
    "integrity_status", "receiver_availability", "receiver_local_reference",
    "unavailable_reason",
})


def build_session_context_details(artifact: Mapping[str, Any]) -> dict[str, str]:
    """Do not resurrect content excluded from the public background contract.

    The only excluded claims eligible for the detailed file are file paths hidden
    by the overview inventory bound. Excluded instructions and references stay
    excluded, including when raw supporting context is retained for inspection.
    """
    claims = [
        dict(claim)
        for claim in artifact.get("claim_manifest") or []
        if claim.get("selection") == "included"
        or (
            claim.get("selection") == "excluded"
            and claim.get("kind") == "relevant_file"
            and claim.get("exclusion_reason") == "bounded_inventory"
        )
    ]
    payload = {
        "schema_version": SESSION_CONTEXT_DETAILS_SCHEMA_VERSION,
        "context_role": "background_only",
        "provider": artifact.get("provider"),
        "session_id": artifact.get("session_id"),
        "checkpoint_id": artifact.get("checkpoint_id"),
        "source_document_id": artifact.get("source_document_id"),
        "boundary": artifact.get("boundary"),
        "captured_at": artifact.get("captured_at"),
        "overview_sha256": artifact.get("sha256"),
        "claim_manifest": claims,
        "retrieval_context": {
            **{key: value for key, value in artifact["retrieval_context"].items() if key != "spans"},
            "spans": [span for span in artifact["retrieval_context"].get("spans") or []
                      if f"session.{span['id']}" in {
                          claim["stable_id"] for claim in claims
                          if claim.get("kind") == "historical_excerpt" and claim.get("selection") == "included"
                      }],
        } if isinstance(artifact.get("retrieval_context"), Mapping) else None,
        "repository": artifact.get("repository") or {},
        "attachment_dependencies": [
            {key: value for key, value in item.items() if key in _ATTACHMENT_REFERENCE_FIELDS}
            for item in artifact.get("attachment_dependencies") or []
        ],
        "unresolved_dependencies": artifact.get("unresolved_dependencies") or [],
        "source_projection": artifact.get("source_projection"),
    }
    # Match the public API's datetime/UUID representation before freezing the
    # bytes; receivers hash this string directly rather than canonicalizing it.
    content = canonical_json(jsonable_encoder(payload, custom_encoder={
        datetime: lambda value: value.isoformat() + ("Z" if value.tzinfo is None else ""),
    }))
    return {
        "schema_version": SESSION_CONTEXT_DETAILS_SCHEMA_VERSION,
        "content": content,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
