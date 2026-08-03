from __future__ import annotations

from enum import StrEnum


class ContinuationBriefVariant(StrEnum):
    """Model-facing continuation projection used by the A/B experiment."""

    LEGACY_V1 = "legacy_v1"
    COMPACT_V2 = "compact_v2"


def resolve_continuation_brief_variant(
    value: ContinuationBriefVariant | str,
) -> ContinuationBriefVariant:
    return (
        value
        if isinstance(value, ContinuationBriefVariant)
        else ContinuationBriefVariant(str(value).strip().lower())
    )
