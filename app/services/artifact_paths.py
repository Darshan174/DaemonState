from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def artifact_bundle_relative_path(
    artifact: Any,
    *,
    ordinal: int,
) -> str:
    """Return a deterministic, collision-proof path within one contract.

    Artifact IDs are human labels and different IDs can normalize to the same
    filename (for example ``screen:a`` and ``screen-a``). The contract order is
    stable and artifact IDs are unique, so including the one-based ordinal
    makes bundle paths unique without trusting or leaking source paths.
    """

    if ordinal < 1:
        raise ValueError("artifact ordinal must be positive")
    artifact_id = str(_field(artifact, "id", "artifact"))
    source_path = str(
        _field(artifact, "path", _field(artifact, "local_path", ""))
    )
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", artifact_id).strip(".-")
    suffix = _safe_suffix(Path(source_path).suffix)
    return (
        f"attachments/{ordinal:02d}-"
        f"{safe_id[:80] or 'artifact'}{suffix}"
    )


def _safe_suffix(value: str) -> str:
    suffix = str(value or "")[:32]
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix):
        return ""
    return suffix.lower()


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
