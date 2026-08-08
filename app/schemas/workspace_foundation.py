"""Strict contracts for an objective-independent workspace foundation.

The models in this module describe compiler output, not instructions for an
agent to execute.  Evidence is centralized and referenced by identifier so a
consumer can audit every product, architecture, command, and durable-knowledge
statement without accepting duplicated or partially different provenance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


LEGACY_WORKSPACE_FOUNDATION_SCHEMA_VERSION = "workspace_foundation.v1"
WORKSPACE_FOUNDATION_SCHEMA_VERSION = "workspace_foundation.v2"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _repository_path(value: str) -> str:
    """Return a canonical POSIX repository-relative file path."""

    if not value or value != value.strip():
        raise ValueError("repository paths must contain visible, stripped text")
    if "\x00" in value or "\\" in value:
        raise ValueError("repository paths must use POSIX separators")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("repository paths must be relative to the repository root")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("repository paths must be normalized and may not traverse")
    return value


def _repository_directory(value: str) -> str:
    if value == ".":
        return value
    return _repository_path(value)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
EntityId = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$"),
]
RepositoryPath = Annotated[str, Field(max_length=4096), AfterValidator(_repository_path)]
RepositoryDirectory = Annotated[
    str,
    Field(max_length=4096),
    AfterValidator(_repository_directory),
]
UtcDatetime = Annotated[datetime, AfterValidator(_utc_datetime)]


class _FrozenFoundationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class EvidenceTier(StrEnum):
    """Strength and lifecycle of evidence; values are intentionally not merged."""

    RUNTIME_VERIFIED = "runtime_verified"
    TEST_VERIFIED = "test_verified"
    CODE_OBSERVED = "code_observed"
    SYSTEM_VERIFIED = "system_verified"
    DOCUMENTATION_STATED = "documentation_stated"
    HUMAN_CONFIRMED = "human_confirmed"
    CORROBORATED = "corroborated"
    HISTORICAL_PROVISIONAL = "historical_provisional"
    CONFLICTING_SUPERSEDED = "conflicting_superseded"

    @property
    def is_current(self) -> bool:
        return self not in {
            EvidenceTier.HISTORICAL_PROVISIONAL,
            EvidenceTier.CONFLICTING_SUPERSEDED,
        }

    @property
    def is_durable(self) -> bool:
        return self in {
            EvidenceTier.RUNTIME_VERIFIED,
            EvidenceTier.TEST_VERIFIED,
            EvidenceTier.CODE_OBSERVED,
            EvidenceTier.SYSTEM_VERIFIED,
            EvidenceTier.HUMAN_CONFIRMED,
            EvidenceTier.CORROBORATED,
        }


class EvidenceReference(_FrozenFoundationModel):
    """A hash-bound source locator supporting one or more foundation records."""

    id: EntityId
    tier: EvidenceTier
    source_sha256: Sha256
    path: RepositoryPath | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = Field(default=None, min_length=1, max_length=500)
    heading: str | None = Field(default=None, min_length=1, max_length=500)
    rule: str | None = Field(default=None, min_length=1, max_length=240)
    note: str | None = Field(default=None, min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_locator(self) -> Self:
        has_start = self.start_line is not None
        has_end = self.end_line is not None
        if has_start != has_end:
            raise ValueError("evidence line ranges require both start_line and end_line")
        if has_start and self.end_line < self.start_line:  # type: ignore[operator]
            raise ValueError("evidence line range is reversed")
        if (has_start or self.symbol is not None or self.heading is not None) and self.path is None:
            raise ValueError("line, symbol, and heading locators require a repository path")
        if self.path is None and self.rule is None:
            raise ValueError("evidence requires a repository path or compiler rule")
        return self


class ProductClaimKind(StrEnum):
    PURPOSE = "purpose"
    AUDIENCE = "audience"
    MATURITY = "maturity"
    DEPLOYMENT = "deployment"
    BOUNDARY = "boundary"


class ProductClaim(_FrozenFoundationModel):
    """One product-profile statement with field-level provenance."""

    kind: ProductClaimKind
    value: str = Field(min_length=1, max_length=2_000)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)


class ProductProfile(_FrozenFoundationModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    maturity: str | None = Field(default=None, min_length=1, max_length=120)
    primary_value: str | None = Field(default=None, min_length=1, max_length=1_000)
    intended_users: tuple[str, ...] = Field(default=(), max_length=32)
    deployment_models: tuple[str, ...] = Field(default=(), max_length=24)
    non_goals: tuple[str, ...] = Field(default=(), max_length=32)
    claims: tuple[ProductClaim, ...] = Field(default=(), max_length=128)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_claim_uniqueness(self) -> Self:
        identities = [(claim.kind.value, claim.value.casefold()) for claim in self.claims]
        if len(identities) != len(set(identities)):
            raise ValueError("product profile contains duplicate sourced claims")
        return self


class Concept(_FrozenFoundationModel):
    id: EntityId
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=1_500)
    aliases: tuple[str, ...] = Field(default=(), max_length=24)
    distinguished_from: tuple[EntityId, ...] = Field(default=(), max_length=24)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=24)


class WorkflowStep(_FrozenFoundationModel):
    """One repository-stated workflow step with its own exact provenance."""

    position: int = Field(ge=1, le=64)
    description: str = Field(min_length=1, max_length=1_000)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)


class DocumentedSystemFlow(_FrozenFoundationModel):
    """A repository-stated system or data flow, never implementation proof."""

    id: EntityId
    name: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=1_000)
    steps: tuple[WorkflowStep, ...] = Field(min_length=2, max_length=32)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=16)


class SurfaceKind(StrEnum):
    WEB_UI = "web_ui"
    DESKTOP_UI = "desktop_ui"
    MOBILE_UI = "mobile_ui"
    API = "api"
    CLI = "cli"
    SDK = "sdk"
    LIBRARY = "library"
    EVENT = "event"
    JOB = "job"
    FILE = "file"
    DATABASE = "database"
    OPERATIONS = "operations"
    EXTERNAL_INTEGRATION = "external_integration"
    OTHER = "other"


class SurfaceRole(StrEnum):
    ENTRYPOINT = "entrypoint"
    IMPLEMENTATION = "implementation"
    DATA = "data"
    VERIFICATION = "verification"
    OPERATIONS = "operations"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class SurfaceDerivation(StrEnum):
    EXACT_ROUTE = "exact_route"
    SYMBOL_MATCH = "symbol_match"
    EXACT_EDGE = "exact_edge"
    PATH_HEURISTIC = "path_heuristic"


class CapabilitySurface(_FrozenFoundationModel):
    id: EntityId
    kind: SurfaceKind
    role: SurfaceRole = SurfaceRole.OTHER
    derivation: SurfaceDerivation
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1_500)
    locator: str = Field(min_length=1, max_length=1_000)
    repository_path: RepositoryPath | None = None
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=24)


class CapabilityState(StrEnum):
    VERIFIED = "verified"
    OBSERVED = "observed"
    PARTIAL = "partial"
    DOCUMENTED_ONLY = "documented_only"
    PLANNED = "planned"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CapabilityDeclarationStatus(StrEnum):
    DECLARED = "declared"
    UNDECLARED = "undeclared"


class ImplementationCoverage(StrEnum):
    NONE = "none"
    CANDIDATE_ONLY = "candidate_only"
    ENTRYPOINT_ONLY = "entrypoint_only"
    PARTIAL_TRACE = "partial_trace"
    MULTI_LAYER_TRACE = "multi_layer_trace"


class CapabilityVerificationStatus(StrEnum):
    ABSENT = "absent"
    TEST_PRESENT = "test_present"
    PASSED = "passed"
    FAILED = "failed"
    STALE = "stale"
    RUNTIME_VERIFIED = "runtime_verified"


class CapabilityAssessment(_FrozenFoundationModel):
    """Orthogonal maturity signals; none is allowed to imply another."""

    declaration_status: CapabilityDeclarationStatus
    implementation_coverage: ImplementationCoverage
    verification_status: CapabilityVerificationStatus
    production_surface_count: int = Field(default=0, ge=0)
    candidate_surface_count: int = Field(default=0, ge=0)
    verification_surface_count: int = Field(default=0, ge=0)
    exact_production_edge_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_coverage_counts(self) -> Self:
        if self.implementation_coverage is ImplementationCoverage.NONE and (
            self.production_surface_count or self.candidate_surface_count
        ):
            raise ValueError("no implementation coverage may not contain mapped surfaces")
        if self.implementation_coverage is ImplementationCoverage.CANDIDATE_ONLY and (
            self.production_surface_count or not self.candidate_surface_count
        ):
            raise ValueError(
                "candidate-only coverage requires heuristic candidates and no established surface"
            )
        if (
            self.implementation_coverage
            not in {ImplementationCoverage.NONE, ImplementationCoverage.CANDIDATE_ONLY}
            and not self.production_surface_count
        ):
            raise ValueError("implementation coverage requires a production surface")
        if (
            self.verification_status is CapabilityVerificationStatus.ABSENT
            and self.verification_surface_count
        ):
            raise ValueError("absent verification may not contain verification surfaces")
        if (
            self.verification_status is CapabilityVerificationStatus.TEST_PRESENT
            and not self.verification_surface_count
        ):
            raise ValueError("test-present verification requires a verification surface")
        return self


class Capability(_FrozenFoundationModel):
    id: EntityId
    name: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=2_000)
    state: CapabilityState
    workflow: tuple[WorkflowStep, ...] = Field(default=(), max_length=32)
    assessment: CapabilityAssessment
    concept_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    surface_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    component_ids: tuple[EntityId, ...] = Field(default=(), max_length=64)
    depends_on_capability_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=32)


class ArchitectureComponentKind(StrEnum):
    APPLICATION = "application"
    FRONTEND = "frontend"
    BACKEND = "backend"
    API = "api"
    CLI = "cli"
    SDK = "sdk"
    SERVICE = "service"
    WORKER = "worker"
    MODULE = "module"
    PACKAGE = "package"
    DATASTORE = "datastore"
    CACHE = "cache"
    QUEUE = "queue"
    EXTERNAL_SYSTEM = "external_system"
    INFRASTRUCTURE = "infrastructure"
    DEPLOYMENT = "deployment"
    TEST_SUITE = "test_suite"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class ArchitectureComponent(_FrozenFoundationModel):
    id: EntityId
    kind: ArchitectureComponentKind
    name: str = Field(min_length=1, max_length=240)
    responsibility: str = Field(min_length=1, max_length=2_000)
    repository_paths: tuple[RepositoryPath, ...] = Field(default=(), max_length=64)
    technologies: tuple[str, ...] = Field(default=(), max_length=48)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=32)


class StructuralRelation(StrEnum):
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    CALLS = "calls"
    ROUTES_TO = "routes_to"
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    PUBLISHES_TO = "publishes_to"
    CONSUMES_FROM = "consumes_from"
    RENDERS = "renders"
    EXPOSES = "exposes"
    INVOKES = "invokes"
    OWNS = "owns"
    TESTS = "tests"
    DEPLOYS = "deploys"
    SYNCHRONIZES_WITH = "synchronizes_with"
    OTHER = "other"


class StructuralEdge(_FrozenFoundationModel):
    id: EntityId
    source_component_id: EntityId
    target_component_id: EntityId
    relation: StructuralRelation
    description: str | None = Field(default=None, min_length=1, max_length=1_000)
    capability_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def reject_self_edge(self) -> Self:
        if self.source_component_id == self.target_component_id:
            raise ValueError("structural edges must connect two distinct components")
        return self


class ImplementationTraceCoverage(StrEnum):
    PARTIAL = "partial"
    COMPLETE = "complete"


class ImplementationTraceKind(StrEnum):
    PRODUCTION_CALL_FLOW = "production_call_flow"
    INTERNAL_CALL_CHAIN = "internal_call_chain"
    STRUCTURAL_DEPENDENCY = "structural_dependency"


class ImplementationTraceHop(_FrozenFoundationModel):
    """One exact syntax-level link with optional symbol endpoints."""

    source_path: RepositoryPath
    target_path: RepositoryPath
    relation: StructuralRelation
    source_symbol: str | None = Field(default=None, min_length=1, max_length=500)
    target_symbol: str | None = Field(default=None, min_length=1, max_length=500)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def reject_self_hop(self) -> Self:
        if self.source_path == self.target_path and self.relation not in {
            StructuralRelation.OWNS,
            StructuralRelation.CALLS,
        }:
            raise ValueError("same-file implementation trace hops require an exact symbol relation")
        if self.source_path == self.target_path and (
            self.source_symbol is None
            or self.target_symbol is None
            or self.source_symbol == self.target_symbol
        ):
            raise ValueError(
                "same-file implementation trace hops require distinct symbol endpoints"
            )
        return self


class ImplementationTrace(_FrozenFoundationModel):
    """A bounded, contiguous code-observed path for one or more capabilities."""

    id: EntityId
    name: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=1_000)
    kind: ImplementationTraceKind = ImplementationTraceKind.STRUCTURAL_DEPENDENCY
    coverage: ImplementationTraceCoverage = ImplementationTraceCoverage.PARTIAL
    capability_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=16)
    hops: tuple[ImplementationTraceHop, ...] = Field(min_length=1, max_length=8)
    gaps: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_contiguous_hops(self) -> Self:
        for current, following in zip(self.hops, self.hops[1:]):
            if current.target_path != following.source_path:
                raise ValueError("implementation trace hops must form a contiguous path")
            if (
                current.target_symbol is not None
                and following.source_symbol is not None
                and current.target_symbol != following.source_symbol
            ):
                raise ValueError(
                    "symbol-level implementation trace hops must form a contiguous path"
                )
        relations = tuple(hop.relation for hop in self.hops)
        if self.kind is ImplementationTraceKind.PRODUCTION_CALL_FLOW:
            valid_entrypoint_prefix = (
                relations[:1] == (StructuralRelation.OWNS,)
                and all(item is StructuralRelation.CALLS for item in relations[1:])
            ) or (
                relations[:2] == (StructuralRelation.ROUTES_TO, StructuralRelation.OWNS)
                and all(item is StructuralRelation.CALLS for item in relations[2:])
            )
            if not valid_entrypoint_prefix or not any(
                item is StructuralRelation.CALLS for item in relations
            ):
                raise ValueError(
                    "production call flows require an exact owns/calls or "
                    "routes_to/owns/calls entrypoint prefix"
                )
        if self.kind is ImplementationTraceKind.INTERNAL_CALL_CHAIN and any(
            relation is not StructuralRelation.CALLS for relation in relations
        ):
            raise ValueError("internal call chains may contain only call hops")
        if self.kind is ImplementationTraceKind.STRUCTURAL_DEPENDENCY and any(
            relation is not StructuralRelation.DEPENDS_ON for relation in relations
        ):
            raise ValueError("structural dependency traces may contain only dependency hops")
        if self.coverage is ImplementationTraceCoverage.COMPLETE and self.gaps:
            raise ValueError("complete implementation traces may not declare gaps")
        return self


class ProductionFlowProof(StrEnum):
    """Strongest evidence supporting an ordered request-to-output flow."""

    CODE_OBSERVED = "code_observed"
    TEST_VERIFIED = "test_verified"
    RUNTIME_VERIFIED = "runtime_verified"


class ProductionFlowStageKind(StrEnum):
    ENTRYPOINT = "entrypoint"
    SERVICE = "service"
    PERSISTENCE = "persistence"
    COMPILER = "compiler"
    OUTPUT = "output"


class ProductionFlowStage(_FrozenFoundationModel):
    """One typed, evidence-backed stage in a production path."""

    kind: ProductionFlowStageKind
    path: RepositoryPath
    symbol: str | None = Field(default=None, min_length=1, max_length=500)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=16)


class ProductionFlow(_FrozenFoundationModel):
    """A normalized production-flow record.

    Missing stages remain explicit. Static call syntax may support a partial
    record, but only execution evidence may upgrade ``proof`` beyond
    ``code_observed``.
    """

    id: EntityId
    name: str = Field(min_length=1, max_length=240)
    capability_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=16)
    snapshot: Sha256
    entrypoint: ProductionFlowStage
    service: tuple[ProductionFlowStage, ...] = Field(default=(), max_length=8)
    persistence: tuple[ProductionFlowStage, ...] = Field(default=(), max_length=8)
    compiler: tuple[ProductionFlowStage, ...] = Field(default=(), max_length=8)
    output: ProductionFlowStage | None = None
    proof: ProductionFlowProof = ProductionFlowProof.CODE_OBSERVED
    complete: bool = False
    gaps: tuple[str, ...] = Field(default=(), max_length=16)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=48)

    @model_validator(mode="after")
    def validate_stages(self) -> Self:
        if self.entrypoint.kind is not ProductionFlowStageKind.ENTRYPOINT:
            raise ValueError("production-flow entrypoint must use the entrypoint stage kind")
        for label, stages, expected in (
            ("service", self.service, ProductionFlowStageKind.SERVICE),
            ("persistence", self.persistence, ProductionFlowStageKind.PERSISTENCE),
            ("compiler", self.compiler, ProductionFlowStageKind.COMPILER),
        ):
            if any(stage.kind is not expected for stage in stages):
                raise ValueError(f"production-flow {label} stages use the wrong kind")
        if self.output is not None and self.output.kind is not ProductionFlowStageKind.OUTPUT:
            raise ValueError("production-flow output must use the output stage kind")
        has_canonical_path = bool(
            self.service and self.persistence and self.compiler and self.output is not None
        )
        if self.complete != has_canonical_path:
            raise ValueError(
                "complete production flows require entrypoint, service, persistence, "
                "compiler, and output stages"
            )
        if self.complete and self.gaps:
            raise ValueError("complete production flows may not declare gaps")
        if not self.complete and not self.gaps:
            raise ValueError("partial production flows require explicit gaps")
        return self


class CommandKind(StrEnum):
    SETUP = "setup"
    DOCTOR = "doctor"
    DEVELOP = "develop"
    RUN = "run"
    TEST = "test"
    SMOKE_TEST = "smoke_test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    FORMAT = "format"
    BUILD = "build"
    MIGRATE = "migrate"
    SEED = "seed"
    DEPLOY = "deploy"
    OTHER = "other"


class CommandOrigin(StrEnum):
    DECLARED = "declared"
    INFERRED = "inferred"
    OBSERVED = "observed"


class CommandVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    STALE = "stale"


class CommandVerification(_FrozenFoundationModel):
    status: CommandVerificationStatus = CommandVerificationStatus.UNVERIFIED
    verified_at: UtcDatetime | None = None
    exit_code: int | None = None
    output_sha256: Sha256 | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=1_000)
    evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_status_evidence(self) -> Self:
        if self.status is CommandVerificationStatus.UNVERIFIED:
            if (
                any(
                    value is not None
                    for value in (
                        self.verified_at,
                        self.exit_code,
                        self.output_sha256,
                        self.summary,
                    )
                )
                or self.evidence_ref_ids
            ):
                raise ValueError("unverified commands may not carry verification results")
            return self
        if self.verified_at is None:
            raise ValueError("verified, stale, or attempted commands require verified_at")
        if not self.evidence_ref_ids:
            raise ValueError("command verification requires evidence references")
        if self.status is CommandVerificationStatus.PASSED and self.exit_code != 0:
            raise ValueError("passed command verification requires exit_code 0")
        if self.status is CommandVerificationStatus.FAILED and (
            self.exit_code is None or self.exit_code == 0
        ):
            raise ValueError("failed command verification requires a non-zero exit_code")
        return self


class WorkspaceCommand(_FrozenFoundationModel):
    id: EntityId
    name: str = Field(min_length=1, max_length=240)
    purpose: str = Field(min_length=1, max_length=1_000)
    kind: CommandKind
    origin: CommandOrigin
    command: str = Field(min_length=1, max_length=4_000)
    working_directory: RepositoryDirectory = "."
    prerequisites: tuple[str, ...] = Field(default=(), max_length=32)
    verification: CommandVerification = Field(default_factory=CommandVerification)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=24)


class VerificationRunResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class VerificationRun(_FrozenFoundationModel):
    """One executed command bound to the exact compiled repository snapshot."""

    id: EntityId
    command: str = Field(min_length=1, max_length=4_000)
    working_directory: RepositoryDirectory = "."
    snapshot: Sha256
    exit_code: int
    result: VerificationRunResult
    failures: tuple[str, ...] = Field(default=(), max_length=8)
    observed_at: UtcDatetime
    output_sha256: Sha256
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.result is VerificationRunResult.PASSED:
            if self.exit_code != 0 or self.failures:
                raise ValueError("passing verification runs require exit code 0 and no failures")
        elif self.result is VerificationRunResult.FAILED:
            if self.exit_code == 0 or not self.failures:
                raise ValueError(
                    "failed verification runs require a non-zero exit code and failure details"
                )
        elif not self.failures:
            raise ValueError("blocked verification runs require a failure reason")
        return self


class VerificationPolicySource(StrEnum):
    """Repository mechanism from which an authoritative check policy was read."""

    GITHUB_ACTIONS = "github_actions"


class RequiredCommandKey(_FrozenFoundationModel):
    """The exact identity used to match a required check to an observation."""

    command: str = Field(min_length=1, max_length=4_000)
    working_directory: RepositoryDirectory = "."


class RequiredVerificationCommand(_FrozenFoundationModel):
    """One unconditionally required repository check with source provenance."""

    key: RequiredCommandKey
    name: str = Field(min_length=1, max_length=240)
    kind: CommandKind
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)


class VerificationPolicy(_FrozenFoundationModel):
    """Snapshot-bound required checks; this model never reports repository health.

    An incomplete discovery may retain checks proved by exact workflow sources,
    but ``discovery_complete`` remains false so those checks cannot establish a
    passing whole-repository health state.
    """

    source: VerificationPolicySource = VerificationPolicySource.GITHUB_ACTIONS
    discovery_complete: bool = False
    required_commands: tuple[RequiredVerificationCommand, ...] = Field(default=(), max_length=128)
    incomplete_reasons: tuple[str, ...] = Field(
        default=("required-check policy was not compiled",),
        max_length=32,
    )
    evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        keys = [(item.key.command, item.key.working_directory) for item in self.required_commands]
        if len(keys) != len(set(keys)):
            raise ValueError("verification policy contains duplicate command keys")
        if self.discovery_complete:
            if self.incomplete_reasons:
                raise ValueError("complete verification policy may not carry incomplete reasons")
        else:
            if not self.incomplete_reasons:
                raise ValueError("incomplete verification policy requires an explicit reason")
        policy_evidence = set(self.evidence_ref_ids)
        missing_policy_evidence = sorted(
            {
                reference_id
                for item in self.required_commands
                for reference_id in item.evidence_ref_ids
            }
            - policy_evidence
        )
        if missing_policy_evidence:
            raise ValueError(
                "required commands use evidence absent from their verification policy: "
                + ", ".join(missing_policy_evidence)
            )
        return self


def _uncompiled_verification_policy() -> VerificationPolicy:
    return VerificationPolicy()


class RepositoryChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    UNTRACKED = "untracked"
    TYPE_CHANGED = "type_changed"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class RepositoryChangeScope(StrEnum):
    INDEX = "index"
    WORKTREE = "worktree"
    BOTH = "both"
    UNTRACKED = "untracked"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class RepositoryChangeRole(StrEnum):
    IMPLEMENTATION = "implementation"
    SCHEMA = "schema"
    TEST = "test"
    MIGRATION = "migration"
    DOCUMENTATION = "documentation"
    OPERATIONS = "operations"
    CONFIGURATION = "configuration"
    OTHER = "other"


class RepositorySemanticParserCoverage(StrEnum):
    PARSED = "parsed"
    LINE_ONLY = "line_only"
    NOT_OBSERVED = "not_observed"


class RepositoryChangeCompletionStatus(StrEnum):
    """Explicitly sourced completion state; never derived from a diff."""

    UNKNOWN = "unknown"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class RepositoryChangeRemainingWorkStatus(StrEnum):
    """Whether an explicit source identifies work that remains."""

    UNKNOWN = "unknown"
    IDENTIFIED = "identified"
    NONE_STATED = "none_stated"


class RepositoryChangeStatement(_FrozenFoundationModel):
    """One explicit change-purpose statement with field-level provenance."""

    statement: str = Field(min_length=1, max_length=1_500)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)


class RepositorySemanticDelta(_FrozenFoundationModel):
    """Bounded HEAD-vs-working-tree syntax observations for one changed path.

    The record describes an observed delta only. It does not express author
    intent, behavioral completeness, or remaining work.
    """

    observer: Literal["head_vs_worktree_syntax.v1"]
    status: Literal["observed", "partial", "not_observed"]
    parser_coverage: RepositorySemanticParserCoverage
    parser_languages: tuple[str, ...] = Field(default=(), max_length=8)
    base: Literal["HEAD"] | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=240)
    lines_added: int | None = Field(default=None, ge=0)
    lines_removed: int | None = Field(default=None, ge=0)
    symbols_added: tuple[str, ...] = Field(default=(), max_length=32)
    symbols_removed: tuple[str, ...] = Field(default=(), max_length=32)
    symbols_modified: tuple[str, ...] = Field(default=(), max_length=32)
    routes_added: tuple[str, ...] = Field(default=(), max_length=32)
    routes_removed: tuple[str, ...] = Field(default=(), max_length=32)
    imports_added: tuple[str, ...] = Field(default=(), max_length=32)
    imports_removed: tuple[str, ...] = Field(default=(), max_length=32)
    headings_added: tuple[str, ...] = Field(default=(), max_length=32)
    headings_removed: tuple[str, ...] = Field(default=(), max_length=32)
    items_truncated: bool = False
    complete: bool = False

    @model_validator(mode="after")
    def validate_observation_state(self) -> Self:
        observed_values = (
            self.lines_added,
            self.lines_removed,
            self.symbols_added,
            self.symbols_removed,
            self.symbols_modified,
            self.routes_added,
            self.routes_removed,
            self.imports_added,
            self.imports_removed,
            self.headings_added,
            self.headings_removed,
        )
        if self.status == "not_observed" and any(observed_values):
            raise ValueError("not-observed semantic deltas may not contain observations")
        if self.status == "not_observed" and self.complete:
            raise ValueError("not-observed semantic deltas cannot be complete")
        if self.status == "not_observed" and (
            self.parser_coverage is not RepositorySemanticParserCoverage.NOT_OBSERVED
            or self.parser_languages
        ):
            raise ValueError("not-observed semantic deltas require not-observed parser coverage")
        if (
            self.parser_coverage is RepositorySemanticParserCoverage.NOT_OBSERVED
            and self.status != "not_observed"
        ):
            raise ValueError("observed semantic deltas require explicit parser coverage")
        if self.parser_coverage is RepositorySemanticParserCoverage.LINE_ONLY:
            if self.status != "partial" or self.complete:
                raise ValueError("line-only semantic deltas must remain partial")
            if not self.parser_languages:
                raise ValueError("line-only semantic deltas must name their language")
        if self.complete and (self.status != "observed" or self.items_truncated):
            raise ValueError("complete semantic deltas must be observed and untruncated")
        if self.complete and self.parser_coverage is not RepositorySemanticParserCoverage.PARSED:
            raise ValueError("complete semantic deltas require parsed syntax coverage")
        if self.status != "not_observed" and self.base is None:
            raise ValueError("observed semantic deltas require a comparison base")
        return self


class RepositoryChange(_FrozenFoundationModel):
    path: RepositoryPath
    kind: RepositoryChangeKind
    scope: RepositoryChangeScope = RepositoryChangeScope.UNKNOWN
    previous_path: RepositoryPath | None = None
    content_sha256: Sha256 | None = None
    role: RepositoryChangeRole = RepositoryChangeRole.OTHER
    capability_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    component_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    related_test_paths: tuple[RepositoryPath, ...] = Field(default=(), max_length=32)
    semantic_delta: RepositorySemanticDelta | None = None
    intended_behavior: RepositoryChangeStatement | None = None
    completion_status: RepositoryChangeCompletionStatus = RepositoryChangeCompletionStatus.UNKNOWN
    completion_evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=8)
    remaining_work_status: RepositoryChangeRemainingWorkStatus = (
        RepositoryChangeRemainingWorkStatus.UNKNOWN
    )
    remaining_work: tuple[RepositoryChangeStatement, ...] = Field(default=(), max_length=8)
    remaining_work_evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=8)
    evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_change_contract(self) -> Self:
        requires_previous = self.kind in {
            RepositoryChangeKind.RENAMED,
            RepositoryChangeKind.COPIED,
        }
        if requires_previous != (self.previous_path is not None):
            raise ValueError("only renamed or copied changes require previous_path")
        completion_is_unknown = self.completion_status is RepositoryChangeCompletionStatus.UNKNOWN
        if completion_is_unknown == bool(self.completion_evidence_ref_ids):
            raise ValueError(
                "known completion status requires evidence and unknown completion "
                "status forbids evidence"
            )

        if self.remaining_work_status is RepositoryChangeRemainingWorkStatus.UNKNOWN:
            if self.remaining_work or self.remaining_work_evidence_ref_ids:
                raise ValueError("unknown remaining-work status forbids work items and evidence")
        elif self.remaining_work_status is RepositoryChangeRemainingWorkStatus.IDENTIFIED:
            if not self.remaining_work or not self.remaining_work_evidence_ref_ids:
                raise ValueError(
                    "identified remaining work requires work items and status evidence"
                )
        elif self.remaining_work or not self.remaining_work_evidence_ref_ids:
            raise ValueError("none-stated remaining work requires evidence and forbids work items")
        return self


class ChangeIntent(_FrozenFoundationModel):
    """Capability-level intent for the exact dirty snapshot.

    Git and syntax may establish changed paths and affected tests, but the
    behavior and completion fields require an explicit trusted source.
    """

    id: EntityId
    capability: str = Field(min_length=1, max_length=240)
    capability_ids: tuple[EntityId, ...] = Field(default=(), max_length=16)
    snapshot: Sha256
    changed_paths: tuple[RepositoryPath, ...] = Field(min_length=1, max_length=128)
    before_behavior: RepositoryChangeStatement | None = None
    after_behavior: RepositoryChangeStatement | None = None
    completed: RepositoryChangeCompletionStatus = RepositoryChangeCompletionStatus.UNKNOWN
    completion_evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=16)
    remaining_status: RepositoryChangeRemainingWorkStatus = (
        RepositoryChangeRemainingWorkStatus.UNKNOWN
    )
    remaining: tuple[RepositoryChangeStatement, ...] = Field(default=(), max_length=16)
    remaining_evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=16)
    affected_tests: tuple[RepositoryPath, ...] = Field(default=(), max_length=64)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_intent_contract(self) -> Self:
        if len(self.changed_paths) != len(set(self.changed_paths)):
            raise ValueError("change intent contains duplicate changed paths")
        if len(self.affected_tests) != len(set(self.affected_tests)):
            raise ValueError("change intent contains duplicate affected tests")
        completion_unknown = self.completed is RepositoryChangeCompletionStatus.UNKNOWN
        if completion_unknown == bool(self.completion_evidence_ref_ids):
            raise ValueError(
                "known change-intent completion requires evidence and unknown completion "
                "forbids evidence"
            )
        if self.remaining_status is RepositoryChangeRemainingWorkStatus.UNKNOWN:
            if self.remaining or self.remaining_evidence_ref_ids:
                raise ValueError("unknown change-intent remaining work forbids details")
        elif self.remaining_status is RepositoryChangeRemainingWorkStatus.IDENTIFIED:
            if not self.remaining or not self.remaining_evidence_ref_ids:
                raise ValueError("identified change-intent remaining work requires evidence")
        elif self.remaining or not self.remaining_evidence_ref_ids:
            raise ValueError("none-stated change-intent remaining work forbids items")
        if (
            self.completed is RepositoryChangeCompletionStatus.COMPLETE
            and self.remaining_status is RepositoryChangeRemainingWorkStatus.IDENTIFIED
        ):
            raise ValueError("complete change intent cannot also identify remaining work")
        return self


class RepositoryState(_FrozenFoundationModel):
    repository_name: str = Field(min_length=1, max_length=240)
    branch: str | None = Field(default=None, min_length=1, max_length=500)
    head_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40,64}$")
    detached_head: bool = False
    dirty: bool
    captured_at: UtcDatetime
    snapshot_fingerprint: Sha256
    status_sha256: Sha256 | None = None
    changed_path_count: int = Field(default=0, ge=0)
    changes_truncated: bool = False
    changes: tuple[RepositoryChange, ...] = Field(default=(), max_length=2_000)
    evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_change_summary(self) -> Self:
        if self.detached_head and self.branch is not None:
            raise ValueError("detached repositories may not declare a branch")
        if self.changed_path_count < len(self.changes):
            raise ValueError("changed_path_count is smaller than the included changes")
        if not self.changes_truncated and self.changed_path_count != len(self.changes):
            raise ValueError("complete change lists must match changed_path_count")
        if not self.dirty and self.changed_path_count:
            raise ValueError("clean repositories may not contain changes")
        paths = [change.path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("repository changes contain duplicate paths")
        return self


class DurableFactKind(StrEnum):
    CONTEXT = "context"
    DECISION = "decision"
    INVARIANT = "invariant"
    CONSTRAINT = "constraint"
    CONVENTION = "convention"
    OPERATIONAL_REQUIREMENT = "operational_requirement"
    LIMITATION = "limitation"
    KNOWN_FAILURE = "known_failure"
    LESSON = "lesson"
    RISK = "risk"
    DIRECTION = "direction"


class DurablePromotionReason(StrEnum):
    LEGACY_PROMOTED = "legacy_promoted"
    MECHANICALLY_VERIFIED = "mechanically_verified"
    HUMAN_CONFIRMED = "human_confirmed"
    INDEPENDENT_CORROBORATION = "independent_corroboration"


class DurableKnowledgeFact(_FrozenFoundationModel):
    id: EntityId
    identity_key: str = Field(min_length=1, max_length=500)
    kind: DurableFactKind
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_tier: EvidenceTier
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    promotion_reason: DurablePromotionReason = DurablePromotionReason.LEGACY_PROMOTED
    corroboration_count: int = Field(default=1, ge=1)
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=32)
    truth_state: Literal["current"] = "current"

    @model_validator(mode="after")
    def validate_promotion(self) -> Self:
        if not self.evidence_tier.is_durable:
            raise ValueError("durable knowledge requires a durable evidence tier")
        if self.evidence_tier is EvidenceTier.CORROBORATED and self.corroboration_count < 2:
            raise ValueError("corroborated durable knowledge requires at least two sources")
        if self.corroboration_count > len(self.evidence_ref_ids):
            raise ValueError("corroboration_count exceeds the referenced evidence")
        if (
            self.promotion_reason is DurablePromotionReason.INDEPENDENT_CORROBORATION
            and self.evidence_tier is not EvidenceTier.CORROBORATED
        ):
            raise ValueError("independent-corroboration promotion requires corroborated evidence")
        if (
            self.evidence_tier is EvidenceTier.CORROBORATED
            and self.promotion_reason
            not in {
                DurablePromotionReason.INDEPENDENT_CORROBORATION,
                DurablePromotionReason.LEGACY_PROMOTED,
            }
        ):
            raise ValueError("corroborated durable facts require a corroboration promotion reason")
        return self


DurableFact = DurableKnowledgeFact


class RepositoryEngineeringKnowledgeKind(StrEnum):
    DECISION = "decision"
    INVARIANT = "invariant"
    CONVENTION = "convention"
    CURRENT_LIMITATION = "current_limitation"
    KNOWN_FAILURE = "known_failure"
    LESSON = "lesson"


class RepositoryEngineeringKnowledgeFact(_FrozenFoundationModel):
    """One source-scoped repository statement, never durable or runtime proof."""

    id: EntityId
    kind: RepositoryEngineeringKnowledgeKind
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=2_000)
    scope: Literal["source_scoped"] = "source_scoped"
    currentness: Literal["unverified"] = "unverified"
    evidence_ref_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=8)


class FoundationSection(StrEnum):
    PRODUCT = "product"
    CONCEPTS = "concepts"
    CAPABILITIES = "capabilities"
    ARCHITECTURE = "architecture"
    COMMANDS = "commands"
    REPOSITORY = "repository"
    ENGINEERING_KNOWLEDGE = "engineering_knowledge"
    DURABLE_KNOWLEDGE = "durable_knowledge"
    EVIDENCE = "evidence"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityIssueKind(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    CONFLICT = "conflict"
    STALE_SOURCE = "stale_source"
    INCOMPLETE_MAPPING = "incomplete_mapping"
    UNVERIFIED_COMMAND = "unverified_command"
    TRUNCATED_SCAN = "truncated_scan"
    CODE_DOCUMENTATION_MISMATCH = "code_documentation_mismatch"
    INVALID_REFERENCE = "invalid_reference"
    OTHER = "other"


class QualityIssue(_FrozenFoundationModel):
    id: EntityId
    kind: QualityIssueKind
    severity: QualitySeverity
    section: FoundationSection
    message: str = Field(min_length=1, max_length=2_000)
    entity_ids: tuple[EntityId, ...] = Field(default=(), max_length=64)
    evidence_ref_ids: tuple[EntityId, ...] = Field(default=(), max_length=32)
    blocking: bool = False

    @model_validator(mode="after")
    def validate_blocking_severity(self) -> Self:
        if self.blocking and self.severity is not QualitySeverity.ERROR:
            raise ValueError("blocking quality issues must have error severity")
        return self


class QualityStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class SectionCoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class SectionCoverage(_FrozenFoundationModel):
    section: FoundationSection
    status: SectionCoverageStatus
    item_count: int = Field(default=0, ge=0)
    evidenced_item_count: int = Field(default=0, ge=0)
    note: str | None = Field(default=None, min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.evidenced_item_count > self.item_count:
            raise ValueError("evidenced_item_count exceeds item_count")
        if self.status is SectionCoverageStatus.COMPLETE and (
            self.item_count != self.evidenced_item_count
        ):
            raise ValueError("complete coverage requires every item to be evidenced")
        if self.status is SectionCoverageStatus.MISSING and self.evidenced_item_count:
            raise ValueError("missing coverage may not report evidenced items")
        if self.status is SectionCoverageStatus.NOT_APPLICABLE and self.item_count:
            raise ValueError("not-applicable coverage may not report items")
        return self


class QualityReport(_FrozenFoundationModel):
    status: QualityStatus
    publishable: bool
    copy_ready: bool
    score: float = Field(ge=0.0, le=100.0)
    issues: tuple[QualityIssue, ...] = Field(default=(), max_length=1_000)
    section_coverage: tuple[SectionCoverage, ...] = Field(default=(), max_length=32)
    excluded_historical_provisional_fact_count: int = Field(default=0, ge=0)
    excluded_conflicting_superseded_fact_count: int = Field(default=0, ge=0)
    semantic_coverage_score: float = Field(default=0.0, ge=0.0, le=100.0)
    repository_health: Literal["verified", "passing", "failing", "stale", "unknown"] = "unknown"
    projection_self_contained: bool = True

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.copy_ready != self.publishable:
            raise ValueError("copy_ready and publishable must agree")
        issue_ids = [issue.id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("quality report contains duplicate issue ids")
        sections = [coverage.section for coverage in self.section_coverage]
        if len(sections) != len(set(sections)):
            raise ValueError("quality report contains duplicate section coverage")
        has_blocker = any(issue.blocking for issue in self.issues)
        if has_blocker and (self.status is not QualityStatus.FAIL or self.publishable):
            raise ValueError("blocking quality issues require a non-publishable fail report")
        if self.status is QualityStatus.PASS and self.issues:
            raise ValueError("passing quality reports may not contain issues")
        if self.status is QualityStatus.FAIL and self.publishable:
            raise ValueError("failed quality reports may not be publishable")
        return self


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate)


class WorkspaceFoundationPayload(_FrozenFoundationModel):
    """Hashable payload shared by producers and the hash-bound artifact."""

    schema_version: Literal["workspace_foundation.v1", "workspace_foundation.v2"] = (
        WORKSPACE_FOUNDATION_SCHEMA_VERSION
    )
    scope: Literal["workspace"] = "workspace"
    objective_independent: Literal[True] = True
    compiled_at: UtcDatetime
    compiler_version: str = Field(min_length=1, max_length=120)
    product_profile: ProductProfile
    evidence_references: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=10_000)
    concepts: tuple[Concept, ...] = Field(default=(), max_length=1_000)
    documented_system_flows: tuple[DocumentedSystemFlow, ...] = Field(default=(), max_length=128)
    capability_surfaces: tuple[CapabilitySurface, ...] = Field(default=(), max_length=2_000)
    capabilities: tuple[Capability, ...] = Field(default=(), max_length=1_000)
    architecture_components: tuple[ArchitectureComponent, ...] = Field(default=(), max_length=2_000)
    structural_edges: tuple[StructuralEdge, ...] = Field(default=(), max_length=5_000)
    implementation_traces: tuple[ImplementationTrace, ...] = Field(default=(), max_length=1_000)
    production_flows: tuple[ProductionFlow, ...] = Field(default=(), max_length=256)
    verification_policy: VerificationPolicy = Field(default_factory=_uncompiled_verification_policy)
    commands: tuple[WorkspaceCommand, ...] = Field(default=(), max_length=500)
    verification_runs: tuple[VerificationRun, ...] = Field(default=(), max_length=256)
    repository_state: RepositoryState
    change_intents: tuple[ChangeIntent, ...] = Field(default=(), max_length=256)
    repository_engineering_knowledge: tuple[RepositoryEngineeringKnowledgeFact, ...] = Field(
        default=(), max_length=128
    )
    durable_knowledge: tuple[DurableKnowledgeFact, ...] = Field(default=(), max_length=2_000)
    durable_facts: tuple[DurableFact, ...] = Field(default=(), max_length=2_000)
    quality_report: QualityReport

    @model_validator(mode="after")
    def validate_graph_and_provenance(self) -> Self:
        groups: tuple[tuple[str, tuple[Any, ...]], ...] = (
            ("evidence", self.evidence_references),
            ("concept", self.concepts),
            ("documented system flow", self.documented_system_flows),
            ("surface", self.capability_surfaces),
            ("capability", self.capabilities),
            ("component", self.architecture_components),
            ("edge", self.structural_edges),
            ("implementation trace", self.implementation_traces),
            ("production flow", self.production_flows),
            ("command", self.commands),
            ("verification run", self.verification_runs),
            ("change intent", self.change_intents),
            (
                "repository engineering knowledge",
                self.repository_engineering_knowledge,
            ),
            ("durable knowledge", self.durable_knowledge),
            ("durable fact", self.durable_facts),
        )
        for label, records in groups:
            duplicate_ids = _duplicates([record.id for record in records])
            if duplicate_ids:
                raise ValueError(f"duplicate {label} ids: {', '.join(duplicate_ids)}")

        all_entity_ids: list[str] = []
        for _label, records in groups:
            all_entity_ids.extend(record.id for record in records)
        all_entity_ids.extend(issue.id for issue in self.quality_report.issues)
        duplicate_global_ids = _duplicates(all_entity_ids)
        if duplicate_global_ids:
            raise ValueError(
                "foundation ids must be globally unique: " + ", ".join(duplicate_global_ids)
            )

        evidence_by_id = {reference.id: reference for reference in self.evidence_references}
        concept_ids = {concept.id for concept in self.concepts}
        surface_ids = {surface.id for surface in self.capability_surfaces}
        capability_ids = {capability.id for capability in self.capabilities}
        component_ids = {component.id for component in self.architecture_components}

        current_evidence_owners: list[tuple[str, tuple[str, ...]]] = [
            ("product profile", self.product_profile.evidence_ref_ids),
            *(
                (
                    f"product claim {claim.kind.value}:{claim.value}",
                    claim.evidence_ref_ids,
                )
                for claim in self.product_profile.claims
            ),
            *((concept.id, concept.evidence_ref_ids) for concept in self.concepts),
            *((flow.id, flow.evidence_ref_ids) for flow in self.documented_system_flows),
            *(
                (
                    f"documented system flow {flow.id} step {step.position}",
                    step.evidence_ref_ids,
                )
                for flow in self.documented_system_flows
                for step in flow.steps
            ),
            *((surface.id, surface.evidence_ref_ids) for surface in self.capability_surfaces),
            *((capability.id, capability.evidence_ref_ids) for capability in self.capabilities),
            *(
                (
                    f"capability {capability.id} workflow step {step.position}",
                    step.evidence_ref_ids,
                )
                for capability in self.capabilities
                for step in capability.workflow
            ),
            *(
                (component.id, component.evidence_ref_ids)
                for component in self.architecture_components
            ),
            *((edge.id, edge.evidence_ref_ids) for edge in self.structural_edges),
            *(
                (
                    f"implementation trace {trace.id} hop {index}",
                    hop.evidence_ref_ids,
                )
                for trace in self.implementation_traces
                for index, hop in enumerate(trace.hops, start=1)
            ),
            *((flow.id, flow.evidence_ref_ids) for flow in self.production_flows),
            *(
                (
                    f"production flow {flow.id} {stage.kind.value}",
                    stage.evidence_ref_ids,
                )
                for flow in self.production_flows
                for stage in (
                    flow.entrypoint,
                    *flow.service,
                    *flow.persistence,
                    *flow.compiler,
                    *((flow.output,) if flow.output is not None else ()),
                )
            ),
            *((command.id, command.evidence_ref_ids) for command in self.commands),
            *((run.id, run.evidence_ref_ids) for run in self.verification_runs),
            ("verification policy", self.verification_policy.evidence_ref_ids),
            *(
                (
                    "required verification command "
                    f"{command.key.working_directory}:{command.key.command}",
                    command.evidence_ref_ids,
                )
                for command in self.verification_policy.required_commands
            ),
            *((fact.id, fact.evidence_ref_ids) for fact in self.repository_engineering_knowledge),
            *((fact.id, fact.evidence_ref_ids) for fact in self.durable_knowledge),
            *((fact.id, fact.evidence_ref_ids) for fact in self.durable_facts),
            ("repository state", self.repository_state.evidence_ref_ids),
            *(
                (f"repository change {change.path}", change.evidence_ref_ids)
                for change in self.repository_state.changes
            ),
            *(
                (
                    f"repository change {change.path} intended behavior",
                    change.intended_behavior.evidence_ref_ids,
                )
                for change in self.repository_state.changes
                if change.intended_behavior is not None
            ),
            *(
                (
                    f"repository change {change.path} completion status",
                    change.completion_evidence_ref_ids,
                )
                for change in self.repository_state.changes
            ),
            *(
                (
                    f"repository change {change.path} remaining-work status",
                    change.remaining_work_evidence_ref_ids,
                )
                for change in self.repository_state.changes
            ),
            *(
                (
                    f"repository change {change.path} remaining-work item {index}",
                    item.evidence_ref_ids,
                )
                for change in self.repository_state.changes
                for index, item in enumerate(change.remaining_work, start=1)
            ),
            *((intent.id, intent.evidence_ref_ids) for intent in self.change_intents),
            *(
                (
                    f"change intent {intent.id} before behavior",
                    intent.before_behavior.evidence_ref_ids,
                )
                for intent in self.change_intents
                if intent.before_behavior is not None
            ),
            *(
                (
                    f"change intent {intent.id} after behavior",
                    intent.after_behavior.evidence_ref_ids,
                )
                for intent in self.change_intents
                if intent.after_behavior is not None
            ),
            *(
                (f"change intent {intent.id} completion", intent.completion_evidence_ref_ids)
                for intent in self.change_intents
            ),
            *(
                (
                    f"change intent {intent.id} remaining status",
                    intent.remaining_evidence_ref_ids,
                )
                for intent in self.change_intents
            ),
            *(
                (
                    f"change intent {intent.id} remaining item {index}",
                    item.evidence_ref_ids,
                )
                for intent in self.change_intents
                for index, item in enumerate(intent.remaining, start=1)
            ),
        ]
        all_evidence_owners = [
            *current_evidence_owners,
            *(
                (f"command verification {command.id}", command.verification.evidence_ref_ids)
                for command in self.commands
            ),
            *(
                (f"quality issue {issue.id}", issue.evidence_ref_ids)
                for issue in self.quality_report.issues
            ),
        ]
        for owner, reference_ids in all_evidence_owners:
            duplicate_refs = _duplicates(list(reference_ids))
            if duplicate_refs:
                raise ValueError(f"{owner} repeats evidence ids: {', '.join(duplicate_refs)}")
            missing = sorted(set(reference_ids) - evidence_by_id.keys())
            if missing:
                raise ValueError(f"{owner} references unknown evidence: {', '.join(missing)}")

        for owner, reference_ids in current_evidence_owners:
            excluded = sorted(
                reference_id
                for reference_id in reference_ids
                if not evidence_by_id[reference_id].tier.is_current
            )
            if excluded:
                raise ValueError(
                    f"{owner} uses provisional or superseded evidence: {', '.join(excluded)}"
                )

        for fact in self.repository_engineering_knowledge:
            non_documentation = sorted(
                reference_id
                for reference_id in fact.evidence_ref_ids
                if evidence_by_id[reference_id].tier is not EvidenceTier.DOCUMENTATION_STATED
            )
            if non_documentation:
                raise ValueError(
                    "repository engineering knowledge requires documentation-stated "
                    f"evidence: {', '.join(non_documentation)}"
                )

        non_code_policy_evidence = sorted(
            reference_id
            for reference_id in self.verification_policy.evidence_ref_ids
            if evidence_by_id[reference_id].tier is not EvidenceTier.CODE_OBSERVED
        )
        if non_code_policy_evidence:
            raise ValueError(
                "verification policy requires code-observed workflow evidence: "
                + ", ".join(non_code_policy_evidence)
            )

        change_declaration_tiers = {
            EvidenceTier.DOCUMENTATION_STATED,
            EvidenceTier.HUMAN_CONFIRMED,
        }
        for change in self.repository_state.changes:
            declaration_owners = [
                *(
                    [
                        (
                            "intended behavior",
                            change.intended_behavior.evidence_ref_ids,
                        )
                    ]
                    if change.intended_behavior is not None
                    else []
                ),
                ("completion status", change.completion_evidence_ref_ids),
                ("remaining-work status", change.remaining_work_evidence_ref_ids),
                *(
                    (f"remaining-work item {index}", item.evidence_ref_ids)
                    for index, item in enumerate(change.remaining_work, start=1)
                ),
            ]
            for label, reference_ids in declaration_owners:
                inferred = sorted(
                    reference_id
                    for reference_id in reference_ids
                    if evidence_by_id[reference_id].tier not in change_declaration_tiers
                )
                if inferred:
                    raise ValueError(
                        f"repository change {change.path} {label} requires "
                        "documentation-stated or human-confirmed evidence: " + ", ".join(inferred)
                    )

        for concept in self.concepts:
            unknown = sorted(set(concept.distinguished_from) - concept_ids)
            if unknown:
                raise ValueError(
                    f"concept {concept.id} distinguishes unknown concepts: {', '.join(unknown)}"
                )
            if concept.id in concept.distinguished_from:
                raise ValueError(f"concept {concept.id} may not distinguish itself")

        for capability in self.capabilities:
            references = (
                ("concepts", capability.concept_ids, concept_ids),
                ("surfaces", capability.surface_ids, surface_ids),
                ("components", capability.component_ids, component_ids),
                ("dependencies", capability.depends_on_capability_ids, capability_ids),
            )
            for label, values, known in references:
                unknown = sorted(set(values) - known)
                if unknown:
                    raise ValueError(
                        f"capability {capability.id} references unknown {label}: "
                        + ", ".join(unknown)
                    )
            if capability.id in capability.depends_on_capability_ids:
                raise ValueError(f"capability {capability.id} may not depend on itself")
            mapped_production_surfaces = {
                surface_id
                for surface_id in capability.surface_ids
                if surface_id in surface_ids
                and next(
                    surface for surface in self.capability_surfaces if surface.id == surface_id
                ).role
                is not SurfaceRole.VERIFICATION
            }
            candidate_surfaces = {
                surface_id
                for surface_id in mapped_production_surfaces
                if next(
                    surface for surface in self.capability_surfaces if surface.id == surface_id
                ).derivation
                is SurfaceDerivation.PATH_HEURISTIC
            }
            production_surfaces = mapped_production_surfaces - candidate_surfaces
            verification_surfaces = set(capability.surface_ids) - mapped_production_surfaces
            if len(production_surfaces) != capability.assessment.production_surface_count:
                raise ValueError(
                    f"capability {capability.id} production surface count is inconsistent"
                )
            if len(candidate_surfaces) != capability.assessment.candidate_surface_count:
                raise ValueError(
                    f"capability {capability.id} candidate surface count is inconsistent"
                )
            if len(verification_surfaces) != capability.assessment.verification_surface_count:
                raise ValueError(
                    f"capability {capability.id} verification surface count is inconsistent"
                )

        for edge in self.structural_edges:
            missing_components = sorted(
                {edge.source_component_id, edge.target_component_id} - component_ids
            )
            if missing_components:
                raise ValueError(
                    f"edge {edge.id} references unknown components: "
                    + ", ".join(missing_components)
                )
            unknown_capabilities = sorted(set(edge.capability_ids) - capability_ids)
            if unknown_capabilities:
                raise ValueError(
                    f"edge {edge.id} references unknown capabilities: "
                    + ", ".join(unknown_capabilities)
                )

        for trace in self.implementation_traces:
            unknown_capabilities = sorted(set(trace.capability_ids) - capability_ids)
            if unknown_capabilities:
                raise ValueError(
                    f"implementation trace {trace.id} references unknown capabilities: "
                    + ", ".join(unknown_capabilities)
                )

        for change in self.repository_state.changes:
            unknown_capabilities = sorted(set(change.capability_ids) - capability_ids)
            if unknown_capabilities:
                raise ValueError(
                    f"repository change {change.path} references unknown capabilities: "
                    + ", ".join(unknown_capabilities)
                )
            unknown_components = sorted(set(change.component_ids) - component_ids)
            if unknown_components:
                raise ValueError(
                    f"repository change {change.path} references unknown components: "
                    + ", ".join(unknown_components)
                )

        for fact in self.durable_knowledge:
            referenced_tiers = {
                evidence_by_id[reference_id].tier for reference_id in fact.evidence_ref_ids
            }
            if fact.evidence_tier not in referenced_tiers:
                raise ValueError(
                    f"durable fact {fact.id} declares {fact.evidence_tier.value} "
                    "without evidence from that tier"
                )

        for capability in self.capabilities:
            if capability.state is not CapabilityState.VERIFIED:
                continue
            if not any(
                evidence_by_id[reference_id].tier
                in {EvidenceTier.RUNTIME_VERIFIED, EvidenceTier.TEST_VERIFIED}
                for reference_id in capability.evidence_ref_ids
            ):
                raise ValueError(f"verified capability {capability.id} lacks executed evidence")

        current_entity_ids = set(all_entity_ids)
        for issue in self.quality_report.issues:
            unknown = sorted(set(issue.entity_ids) - current_entity_ids)
            if unknown:
                raise ValueError(
                    f"quality issue {issue.id} references unknown entities: " + ", ".join(unknown)
                )

        runtime_tiers = {EvidenceTier.RUNTIME_VERIFIED, EvidenceTier.TEST_VERIFIED}
        for command in self.commands:
            if command.verification.status in {
                CommandVerificationStatus.PASSED,
                CommandVerificationStatus.FAILED,
                CommandVerificationStatus.PARTIAL,
                CommandVerificationStatus.BLOCKED,
            } and not any(
                evidence_by_id[reference_id].tier in runtime_tiers
                for reference_id in command.verification.evidence_ref_ids
            ):
                raise ValueError(
                    f"command {command.id} claims an executed result without runtime evidence"
                )
        if self.quality_report.repository_health in {"passing", "verified"}:
            if not self.verification_policy.discovery_complete:
                raise ValueError(
                    "passing repository health requires complete required-check discovery"
                )
            if not self.verification_policy.required_commands:
                raise ValueError("passing repository health requires at least one required check")
            commands_by_key: dict[tuple[str, str], list[WorkspaceCommand]] = {}
            for command in self.commands:
                commands_by_key.setdefault(
                    (command.command, command.working_directory),
                    [],
                ).append(command)
            not_passing = [
                f"{required.key.working_directory}:{required.key.command}"
                for required in self.verification_policy.required_commands
                if not any(
                    command.verification.status is CommandVerificationStatus.PASSED
                    for command in commands_by_key.get(
                        (
                            required.key.command,
                            required.key.working_directory,
                        ),
                        (),
                    )
                )
            ]
            if not_passing:
                raise ValueError(
                    "passing repository health requires a passing exact observation for "
                    "every required check: " + ", ".join(not_passing)
                )
        return self


class WorkspaceFoundationArtifact(WorkspaceFoundationPayload):
    """A complete ``workspace_foundation.v2`` payload bound to its SHA-256."""

    semantic_sha256: Sha256
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def validate_artifact_hash(self) -> Self:
        expected_semantic = compute_workspace_foundation_semantic_sha256(self)
        if not hmac.compare_digest(self.semantic_sha256, expected_semantic):
            raise ValueError("semantic_sha256 does not match the canonical semantic payload")
        expected = compute_workspace_foundation_sha256(self)
        if not hmac.compare_digest(self.artifact_sha256, expected):
            raise ValueError("artifact_sha256 does not match the canonical payload")
        return self

    @classmethod
    def from_payload(
        cls,
        payload: WorkspaceFoundationPayload | Mapping[str, Any],
    ) -> Self:
        """Validate a payload, compute its digest, and return a bound artifact."""

        validated = _foundation_payload(payload)
        values = validated.model_dump(mode="python")
        semantic_sha256 = compute_workspace_foundation_semantic_sha256(validated)
        return cls(
            **values,
            semantic_sha256=semantic_sha256,
            artifact_sha256=compute_workspace_foundation_sha256(validated),
        )

    def verify_sha256(self) -> bool:
        return verify_workspace_foundation_sha256(self)


WorkspaceFoundation = WorkspaceFoundationArtifact


def _foundation_payload(
    value: WorkspaceFoundationPayload | Mapping[str, Any],
) -> WorkspaceFoundationPayload:
    if isinstance(value, WorkspaceFoundationPayload):
        if isinstance(value, WorkspaceFoundationArtifact):
            return WorkspaceFoundationPayload.model_validate(
                value.model_dump(
                    mode="python",
                    exclude={"artifact_sha256", "semantic_sha256"},
                )
            )
        return value
    if not isinstance(value, Mapping):
        raise TypeError("workspace foundation payload must be a model or mapping")
    raw = dict(value)
    raw.pop("artifact_sha256", None)
    raw.pop("semantic_sha256", None)
    return WorkspaceFoundationPayload.model_validate(raw)


def _canonical_json(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_workspace_foundation_semantic_json(
    value: WorkspaceFoundationPayload | Mapping[str, Any],
) -> str:
    """Serialize stable semantic state while excluding capture-time metadata."""

    payload = _foundation_payload(value)
    semantic_payload = payload.model_dump(mode="json")
    semantic_payload.pop("compiled_at", None)
    repository_state = semantic_payload.get("repository_state")
    if isinstance(repository_state, dict):
        repository_state.pop("captured_at", None)
    return _canonical_json(semantic_payload)


def compute_workspace_foundation_semantic_sha256(
    value: WorkspaceFoundationPayload | Mapping[str, Any],
) -> str:
    canonical = canonical_workspace_foundation_semantic_json(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_workspace_foundation_json(
    value: WorkspaceFoundationPayload | Mapping[str, Any],
) -> str:
    """Serialize the full timestamped artifact envelope for integrity checks."""

    payload = _foundation_payload(value)
    envelope = payload.model_dump(mode="json")
    envelope["semantic_sha256"] = compute_workspace_foundation_semantic_sha256(payload)
    return _canonical_json(envelope)


def compute_workspace_foundation_sha256(
    value: WorkspaceFoundationPayload | Mapping[str, Any],
) -> str:
    canonical = canonical_workspace_foundation_json(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_workspace_foundation_sha256(
    value: WorkspaceFoundationArtifact | Mapping[str, Any],
) -> bool:
    """Return whether a supplied artifact digest matches its canonical payload."""

    if isinstance(value, WorkspaceFoundationArtifact):
        actual = value.artifact_sha256
    elif isinstance(value, Mapping):
        actual = value.get("artifact_sha256")
    else:
        raise TypeError("workspace foundation artifact must be a model or mapping")
    if not isinstance(actual, str) or not _SHA256_RE.fullmatch(actual):
        return False
    if isinstance(value, WorkspaceFoundationArtifact):
        actual_semantic = value.semantic_sha256
    else:
        actual_semantic = value.get("semantic_sha256")
    expected_semantic = compute_workspace_foundation_semantic_sha256(value)
    if (
        not isinstance(actual_semantic, str)
        or not _SHA256_RE.fullmatch(actual_semantic)
        or not hmac.compare_digest(actual_semantic, expected_semantic)
    ):
        return False
    expected = compute_workspace_foundation_sha256(value)
    return hmac.compare_digest(actual, expected)


__all__ = [
    "WORKSPACE_FOUNDATION_SCHEMA_VERSION",
    "ArchitectureComponent",
    "ArchitectureComponentKind",
    "Capability",
    "CapabilityAssessment",
    "CapabilityDeclarationStatus",
    "CapabilityState",
    "CapabilitySurface",
    "CapabilityVerificationStatus",
    "CommandKind",
    "CommandOrigin",
    "CommandVerification",
    "CommandVerificationStatus",
    "Concept",
    "DurableFactKind",
    "DurableKnowledgeFact",
    "DocumentedSystemFlow",
    "EvidenceReference",
    "EvidenceTier",
    "FoundationSection",
    "ImplementationCoverage",
    "ImplementationTrace",
    "ImplementationTraceCoverage",
    "ImplementationTraceHop",
    "ImplementationTraceKind",
    "ProductProfile",
    "ProductClaim",
    "ProductClaimKind",
    "QualityIssue",
    "QualityIssueKind",
    "QualityReport",
    "QualitySeverity",
    "QualityStatus",
    "RequiredCommandKey",
    "RequiredVerificationCommand",
    "RepositoryChange",
    "RepositoryChangeCompletionStatus",
    "RepositoryChangeKind",
    "RepositoryChangeRemainingWorkStatus",
    "RepositoryChangeRole",
    "RepositoryChangeScope",
    "RepositoryChangeStatement",
    "RepositorySemanticDelta",
    "RepositorySemanticParserCoverage",
    "RepositoryEngineeringKnowledgeFact",
    "RepositoryEngineeringKnowledgeKind",
    "RepositoryState",
    "SectionCoverage",
    "SectionCoverageStatus",
    "StructuralEdge",
    "StructuralRelation",
    "SurfaceKind",
    "SurfaceDerivation",
    "SurfaceRole",
    "WorkflowStep",
    "VerificationPolicy",
    "VerificationPolicySource",
    "WorkspaceCommand",
    "WorkspaceFoundation",
    "WorkspaceFoundationArtifact",
    "WorkspaceFoundationPayload",
    "canonical_workspace_foundation_json",
    "canonical_workspace_foundation_semantic_json",
    "compute_workspace_foundation_sha256",
    "compute_workspace_foundation_semantic_sha256",
    "verify_workspace_foundation_sha256",
]
