from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTEXT_QUALITY_POLICY_VERSION = "context_quality_policy.v1"
CONTEXT_QUALITY_ACTIVATION_SCHEMA_VERSION = "context_quality_activation.v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextKind(StrEnum):
    SESSION = "session"
    WORKSPACE = "workspace"


class ContextDecision(StrEnum):
    REJECT = "reject"
    REVIEW = "review"
    PROMOTE = "promote"
    NO_CHANGE = "no_change"


class ClaimSelection(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


class ClaimCriticality(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ContextClaimEnvelope(_FrozenModel):
    stable_id: str = Field(min_length=1, max_length=512)
    section: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1)
    scope: ContextKind
    authority: Literal[
        "direct_user",
        "repository_observation",
        "verification_observation",
        "human_confirmed",
        "documentation",
        "agent_report",
        "compiler_inference",
    ]
    truth_state: Literal[
        "current",
        "historical",
        "verified",
        "reported",
        "unknown",
        "contested",
    ]
    criticality: ClaimCriticality = ClaimCriticality.NORMAL
    selection: ClaimSelection = ClaimSelection.INCLUDED
    exclusion_reason: str | None = Field(default=None, max_length=120)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=256)
    repository_snapshot_sha256: str | None = Field(default=None, max_length=64)
    session_boundary_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_selection(self) -> "ContextClaimEnvelope":
        if self.selection is ClaimSelection.EXCLUDED and not self.exclusion_reason:
            raise ValueError("excluded claims require an exclusion_reason")
        if self.selection is ClaimSelection.INCLUDED and self.exclusion_reason:
            raise ValueError("included claims cannot have an exclusion_reason")
        return self

    @property
    def statement_sha256(self) -> str:
        return hashlib.sha256(self.statement.encode("utf-8")).hexdigest()

    @property
    def evidence_sha256(self) -> str:
        return canonical_sha256(list(self.evidence_refs))


class ContextSemanticDiff(_FrozenModel):
    added: tuple[str, ...] = ()
    retained: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    weakened: tuple[str, ...] = ()
    strengthened: tuple[str, ...] = ()
    not_observed: tuple[str, ...] = ()
    exclusion_changed: tuple[str, ...] = ()
    details: tuple[dict[str, Any], ...] = ()
    sha256: str


class ContextQualityEvaluation(_FrozenModel):
    policy_version: str = CONTEXT_QUALITY_POLICY_VERSION
    decision: ContextDecision
    hard_failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    quality_vector: dict[str, float] = Field(default_factory=dict)
    diff: ContextSemanticDiff
    sha256: str


class ContextQualityActivation(_FrozenModel):
    schema_version: Literal["context_quality_activation.v1"] = (
        CONTEXT_QUALITY_ACTIVATION_SCHEMA_VERSION
    )
    status: Literal[
        "active",
        "review_required",
        "rejected",
        "quarantined",
        "inactive",
    ]
    copy_allowed: bool
    candidate_id: str = Field(min_length=1)
    active_candidate_id: str | None = None
    observation_sha256: str = Field(min_length=64, max_length=64)
    artifact_sha256: str = Field(min_length=64, max_length=64)
    semantic_sha256: str = Field(min_length=64, max_length=64)
    evaluation_id: str | None = None
    pointer_generation: int = Field(default=0, ge=0)
    decision: ContextDecision
    policy_version: str = CONTEXT_QUALITY_POLICY_VERSION

    @model_validator(mode="after")
    def validate_copy_binding(self) -> "ContextQualityActivation":
        if self.copy_allowed:
            if self.status != "active":
                raise ValueError("copy_allowed requires active status")
            if not self.active_candidate_id:
                raise ValueError("copy_allowed requires an active_candidate_id")
            if self.active_candidate_id != self.candidate_id:
                raise ValueError("copy_allowed candidate must match the active pointer")
        return self


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

