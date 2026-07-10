from __future__ import annotations

import hashlib
import json
from uuid import UUID


GLOBAL_WORKSPACE_SCOPE = "__global__"


def canonical_source_identity_sha256(
    workspace_id: object,
    source_type: str,
    external_id: str,
) -> str:
    payload = json.dumps(
        [_workspace_scope(workspace_id), source_type, external_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _workspace_scope(value: object) -> str:
    if value in (None, ""):
        return GLOBAL_WORKSPACE_SCOPE
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value))).lower()
    except (TypeError, ValueError):
        return str(value).strip().lower()
