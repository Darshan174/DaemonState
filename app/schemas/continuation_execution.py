from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTINUATION_EXECUTION_SCHEMA_VERSION = "continuation_execution.v1"
MAX_DISPLAY_TITLE = 180
MAX_CONTINUATION_ARTIFACTS = 12
MAX_PROJECT_CONTEXT_ITEMS = 48
MAX_REPOSITORY_EVIDENCE_ITEMS = 24
MAX_SUPPORTING_CONTEXT_ITEMS = 4
MAX_SUPPORTING_CONTEXT_CHARS = 30_000
_HISTORICAL_SPEECH_RE = re.compile(
    r"^(?:the\s+)?(?:prior|previous|historical)\s+"
    r"(?:agent|assistant|user|transcript|message)\s+"
    r"(?:said|says|wrote|asked|claimed|reported)\b",
    re.IGNORECASE,
)
_NON_AUTHORITATIVE_HEADING_RE = re.compile(
    r"\b(?:background|context|histor(?:y|ical)|example|quoted|transcript|"
    r"for reference|untrusted)\b",
    re.IGNORECASE,
)
_CURRENT_USER_REQUEST_MARKER_RE = re.compile(
    r"(?<!\S)#{1,6}\s*My request(?: for Codex)?:\s*",
    re.IGNORECASE,
)
_IMAGE_TRANSPORT_TAG_RE = re.compile(
    r"(?is)</?image\b[^>]*>",
)
_CONCRETE_OUTCOME_ACTION_RE = re.compile(
    r"\b(?:accomplish|add|allow|build|carry|change|copy|create|debug|"
    r"diagnose|disable|display|divide|document|enable|ensure|expose|finish|"
    r"fix|hide|honou?r|implement|inspect|investigate|make|match|move|paste|"
    r"prevent|reject|remove|rename|repair|replace|respect|restore|retain|"
    r"review|route|run|send|ship|show|support|surface|test|update|verify|"
    r"wire|write)\b",
    re.IGNORECASE,
)
_EXPLICIT_QUALITY_OUTCOME_RE = re.compile(
    r"\b(?:pixel[- ]perfect|production[- ]ready|match(?:es|ed|ing)?\b.{0,80}"
    r"\bexact(?:ly)?\b|(?:screenshot|visual)\s+(?:comparison|parity)|"
    r"(?:tests?|checks?|build|lint)\s+(?:must\s+)?pass|"
    r"\bwcag\b|accessib(?:le|ility)|responsive|"
    r"(?:under|within|at most|no more than)\s+\d+(?:\.\d+)?\s*"
    r"(?:ms|milliseconds?|s|seconds?|kb|mb|%)\b|"
    r"(?:zero|no)\s+(?:regressions?|errors?|warnings?|failures?))\b",
    re.IGNORECASE,
)
_REFERENTIAL_WORK_STYLE_RE = re.compile(
    r"^(?:(?:i\s+)?(?:want|need)\s+(?:you|u)\s+to\s+|please\s+)?"
    r"(?:work|proceed|execute|iterate)\s+"
    r"(?:on\s+(?:this|it|that)\s+)?"
    r"(?:very\s+)?(?:aggressively|carefully|quickly|urgently|thoroughly|"
    r"diligently|meticulously)\b",
    re.IGNORECASE,
)
_REFERENTIAL_STYLE_DIRECTIVE_RE = re.compile(
    r"^(?:please\s+)?(?:do|get)\s+(?:this|it|that)\b.*\b"
    r"(?:aggressively|asap|as soon as possible|carefully|quickly|urgently|"
    r"thoroughly|diligently|meticulously)\b",
    re.IGNORECASE,
)
_QUALITY_PREFERENCE_RE = re.compile(
    r"^(?:please\s+)?(?:remember(?:\s+that|\s+to)?\s+)?"
    r"(?:(?:always\s+)?prioriti[sz]e\s+)?"
    r"(?:quality|correctness)\s+(?:over|before)\s+"
    r"(?:quantity|speed|haste)\b|"
    r"^(?:please\s+)?(?:do not|don't|never)\s+sacrifice\s+"
    r"(?:quality|correctness)\s+for\s+(?:quantity|speed|haste)\b",
    re.IGNORECASE,
)
_STANDALONE_EXECUTION_PREFERENCE_RE = re.compile(
    r"^(?:please\s+)?(?:asap|as soon as possible|urgently|move fast|"
    r"hurry(?:\s+up)?|be (?:careful|quick|thorough|diligent|meticulous)|"
    r"take (?:your|the) time|"
    r"(?:do not|don't|never)\s+stop\s+(?:until|before)\b)",
    re.IGNORECASE,
)
_TEST_ONLY_INTENT_RE = re.compile(
    r"\b(?:tests?[- ]only|only\s+(?:run|execute)\s+(?:the\s+)?tests?"
    r"(?=\b|/)|run\s+only\s+(?:the\s+)?tests?(?=\b|/)|"
    r"run\s+(?:the\s+)?tests?\s+only\b)",
    re.IGNORECASE,
)
_DIRECT_TEST_INTENT_RE = re.compile(
    r"^(?:(?:please|just|now)\s+|"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:(?:run|execute)\s+(?:the\s+)?"
    r"(?:[\w-]+\s+){0,3}"
    r"(?:tests?|test\s+suite|checks?|lint|typechecks?|build)\b|"
    r"test\b|(?:check|validate|verify)\b.{0,80}"
    r"\b(?:tests?|test\s+suite|checks?|lint|typechecks?|build)\b)",
    re.IGNORECASE,
)
_DIRECT_REQUEST_BOUNDARY = (
    r"(?:^|[.!?]\s+|\b(?:and|then|also)\s+|(?:&|\+)\s*)"
)
_DIRECT_REQUEST_PREFIX = (
    r"(?:(?:please|now|immediately)\s+|"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"i\s+(?:want|need)\s+you\s+to\s+|"
    r"let(?:'|’)s\s+|you\s+(?:must|should)\s+)?"
)
_DIRECT_MUTATION_INTENT_RE = re.compile(
    _DIRECT_REQUEST_BOUNDARY
    + _DIRECT_REQUEST_PREFIX
    + r"(?:add|address|allow|clean(?:\s+up)?|commit|configure|convert|copy|"
    r"correct|delete|deploy|disable|display|edit|enable|ensure|expose|fix|"
    r"harden|hide|implement|improve|install|integrate|merge|migrate|modify|"
    r"move|optimize|paste|patch|persist|prevent|push|refactor|reject|remove|"
    r"rename|reorganize|repair|replace|resolve|restore|retain|route|secure|"
    r"set|ship|show(?!\s+(?:me|us)\b)|simplify|split|support|surface|"
    r"tackle|turn\s+(?:on|off)|uninstall|update|upgrade|wire|"
    r"document(?!\s+(?:how|what|whether|why)\b)|"
    r"write(?!\s+(?:(?:an?|the)\s+)?"
    r"(?:(?:action|deployment|detailed|engineering|implementation|migration|"
    r"product|project|remediation|rollout|technical|test|testing|written)\s+){0,2}"
    r"(?:analysis|assessment|plan|report|summary)\b))\b",
    re.IGNORECASE,
)
_DIRECT_BUILD_INTENT_RE = re.compile(
    _DIRECT_REQUEST_BOUNDARY
    + _DIRECT_REQUEST_PREFIX
    + r"(?:build|change|create|engineer|make)\b"
    + r"(?!\s+(?:(?:an?|the)\s+)?"
    + r"(?:(?:action|deployment|detailed|engineering|implementation|migration|"
    + r"product|project|remediation|rollout|technical|test|testing|written)\s+){0,2}"
    + r"(?:analysis|assessment|plan|report|summary)\b)",
    re.IGNORECASE,
)
_DIRECT_COMPLETION_INTENT_RE = re.compile(
    _DIRECT_REQUEST_BOUNDARY
    + _DIRECT_REQUEST_PREFIX
    + r"(?:(?:carry|complete|continue|deliver|finish|resume|retry)\b"
    + r"(?!\s+(?:(?:an?|the)\s+)?(?:analysis|assessment|discussion|"
    + r"explanation|plan|report|review|summary|tests?|checks?|lint|build)\b)|"
    + r"work\s+on\s+(?:this|it)|get\s+(?:this|it)\s+done|ship\s+(?:this|it))",
    re.IGNORECASE,
)
_DIRECT_BEHAVIOR_CONSTRAINT_RE = re.compile(
    _DIRECT_REQUEST_BOUNDARY
    + r"(?:do\s+not|don't|never)\s+"
    + r"(?:expose|fallback|fall\s+back|hide|launch|leak|lose|pretend|skip)\b",
    re.IGNORECASE,
)
_DIRECT_REFERENTIAL_CHANGE_INTENT_RE = re.compile(
    r"(?:^|[.!?]\s+)(?:(?:yes|sure|okay|ok|alright|looks\s+good|"
    r"sounds\s+good)[,\s]+)?(?:please\s+)?"
    r"(?:(?:go\s+ahead|proceed)"
    r"(?!\s+(?:with|and|to)\s+(?:(?:an?|the)\s+)?"
    r"(?:analysis|assessment|discussion|explanation|plan|report|review|"
    r"summary|answer|describe|discuss|explain))|"
    r"do\s+(?:it|this|that|so)|apply\s+(?:it|this|that|the\s+fix|"
    r"these\s+changes|those\s+changes))\b",
    re.IGNORECASE,
)
_HYPOTHETICAL_CHANGE_INTENT_RE = re.compile(
    r"\b(?:how\s+(?:can|could|do|might|should|would)\s+"
    r"(?:i|we|you)\b.{0,100}\b(?:build|change|configure|create|delete|"
    r"disable|document|enable|engineer|fix|harden|implement|improve|install|"
    r"integrate|make|migrate|move|optimize|rename|repair|resolve|secure|set|"
    r"simplify|split|turn|update|upgrade)\b|"
    r"what\s+(?:would|will)\s+it\s+take\s+to\s+"
    r"(?:build|change|configure|create|delete|disable|document|enable|"
    r"engineer|fix|harden|implement|improve|install|integrate|make|migrate|"
    r"move|optimize|rename|repair|resolve|secure|set|simplify|split|turn|"
    r"update|upgrade)\b|"
    r"(?:could|should|would)\s+(?:i|we)\s+"
    r"(?:build|change|configure|create|delete|disable|document|enable|"
    r"engineer|fix|harden|implement|improve|install|integrate|make|migrate|"
    r"move|optimize|rename|repair|resolve|secure|set|simplify|split|turn|"
    r"update|upgrade)\b)",
    re.IGNORECASE,
)
_ADVISORY_CHANGE_FRAME_RE = re.compile(
    r"\b(?:how\s+(?:can|could|do|might|should|would)\b|"
    r"what\s+(?:could|should|would|will)\b|"
    r"(?:assess|brainstorm|discuss|explore|investigate|review)\s+"
    r"(?:how|if|what|whether|why)\b)",
    re.IGNORECASE,
)


class TaskMode(StrEnum):
    CHANGE = "change"
    DIAGNOSE = "diagnose"
    REVIEW = "review"
    REPORT = "report"
    PLAN = "plan"
    TEST_ONLY = "test_only"


    @property
    def allows_edits(self) -> bool:
        return self is TaskMode.CHANGE

    @property
    def allows_commands(self) -> bool:
        return self in {
            TaskMode.CHANGE,
            TaskMode.DIAGNOSE,
            TaskMode.REVIEW,
            TaskMode.TEST_ONLY,
        }


class SelectedTaskLifecycle(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    DROPPED = "dropped"
    UNKNOWN = "unknown"


class SourceSpanKind(StrEnum):
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    QUESTION = "question"
    BACKGROUND = "background"


class RequirementPriority(StrEnum):
    MUST = "must"
    CONTEXT = "context"


class VerifierType(StrEnum):
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    STATIC_ANALYSIS = "static_analysis"
    BROWSER_ASSERTION = "browser_assertion"
    SCREENSHOT_COMPARISON = "screenshot_comparison"
    EVENT_ASSERTION = "event_assertion"
    DATABASE_STATE_ASSERTION = "database_state_assertion"
    GIT_DIFF_ASSERTION = "git_diff_assertion"
    MODEL_RUBRIC = "model_rubric"
    HUMAN_REVIEW = "human_review"


class RequiredCapability(StrEnum):
    COMMAND_EXECUTION = "command_execution"
    FILE_CONTEXT = "file_context"
    FILESYSTEM_WRITE = "filesystem_write"
    IMAGE_INPUT = "image_input"
    STRUCTURED_EVENTS = "structured_events"
    BROWSER_VERIFICATION = "browser_verification"


class FilesystemMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class CommandMode(StrEnum):
    INSPECTION_ONLY = "inspection_only"
    EXECUTE = "execute"


class HandoffTruthState(StrEnum):
    CONFIRMED_REPO = "confirmed_repo"
    CONFIRMED_COMMAND = "confirmed_command"
    USER_ASSERTED = "user_asserted"
    AGENT_REPORTED = "agent_reported"
    STALE = "stale"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class RepositoryReconciliationState(StrEnum):
    MATCHES_CHECKPOINT = "matches_checkpoint"
    CHANGED_SINCE_CHECKPOINT = "changed_since_checkpoint"
    UNKNOWN = "unknown"


class ProjectContextKind(StrEnum):
    DECISION = "decision"
    INVARIANT = "invariant"
    BLOCKER = "blocker"
    RISK = "risk"
    LEARNING = "learning"
    VERIFICATION = "verification"
    TASK = "task"
    CONTEXT = "context"


class ProjectFoundationSection(StrEnum):
    IDENTITY = "identity"
    WORKFLOWS = "workflows"
    ARCHITECTURE = "architecture"
    DOMAIN = "domain"
    REPOSITORY = "repository"
    STACK = "stack"
    DECISIONS = "decisions"
    CONVENTIONS = "conventions"
    COMMANDS = "commands"
    CAPABILITIES = "capabilities"
    CONSTRAINTS = "constraints"
    DIRECTION = "direction"


class ProjectEvidenceLevel(StrEnum):
    MECHANICALLY_VERIFIED = "mechanically_verified"
    HUMAN_CONFIRMED = "human_confirmed"
    CORROBORATED = "corroborated"
    PROVISIONAL = "provisional"
    SUPERSEDED_CONFLICTING = "superseded_conflicting"

    @property
    def durable_current(self) -> bool:
        return self in {
            ProjectEvidenceLevel.MECHANICALLY_VERIFIED,
            ProjectEvidenceLevel.HUMAN_CONFIRMED,
            ProjectEvidenceLevel.CORROBORATED,
        }


class RepositoryEvidenceKind(StrEnum):
    SYMBOL_DECLARATION = "symbol_declaration"
    TEST_LINK = "test_link"
    MANIFEST_DEPENDENCY = "manifest_dependency"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthoritativeRequest(_FrozenContract):
    request_verbatim: str
    request_normalized: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_title: str = Field(min_length=1, max_length=MAX_DISPLAY_TITLE)

    @model_validator(mode="after")
    def validate_derivatives(self) -> "AuthoritativeRequest":
        if not self.request_verbatim.strip():
            raise ValueError("request_verbatim must contain visible characters")
        expected_normalized = normalize_request_for_matching(self.request_verbatim)
        if self.request_normalized != expected_normalized:
            raise ValueError("request_normalized does not match request_verbatim")
        expected_sha256 = sha256_text(self.request_verbatim)
        if self.request_sha256 != expected_sha256:
            raise ValueError("request_sha256 does not match request_verbatim")
        if self.display_title != display_title_for_request(self.request_verbatim):
            raise ValueError("display_title does not match request_verbatim")
        return self


class ContinuationTaskIdentity(_FrozenContract):
    schema_version: Literal["continuation_task_identity.v1"] = (
        "continuation_task_identity.v1"
    )
    id: str = Field(min_length=1, max_length=255)
    workspace_id: UUID
    selected_objective_key: str = Field(min_length=1)
    selected_objective_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritative_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_goal_id: UUID | None = None
    selected_component_id: UUID | None = None


class RequestSourceSpan(_FrozenContract):
    id: str = Field(pattern=r"^S[1-9][0-9]*$")
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: SourceSpanKind
    substantive: bool = True

    @model_validator(mode="after")
    def validate_bounds_and_hash(self) -> "RequestSourceSpan":
        if self.end_char <= self.start_char:
            raise ValueError("source span end_char must be after start_char")
        if self.text_sha256 != sha256_text(self.text):
            raise ValueError("source span hash does not match its text")
        return self


class AtomicRequirement(_FrozenContract):
    id: str = Field(pattern=r"^R[1-9][0-9]*$")
    text: str = Field(min_length=1)
    priority: RequirementPriority
    source_span_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_lineage_source(self) -> "AtomicRequirement":
        if not self.source_span_ids and not self.source_artifact_ids:
            raise ValueError(
                "requirement must be derived from a request span or artifact"
            )
        return self


class StructuredHandoffItem(_FrozenContract):
    id: str
    statement: str = Field(min_length=1)
    state: str = "active"
    truth_state: HandoffTruthState = HandoffTruthState.UNKNOWN
    evidence: tuple[dict[str, Any], ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)


class HandoffReconciliation(_FrozenContract):
    repository_state: RepositoryReconciliationState = (
        RepositoryReconciliationState.UNKNOWN
    )
    summary: str = (
        "The checkpoint could not be compared with the current repository."
    )


class StructuredHandoff(_FrozenContract):
    checkpoint_id: str | None = None
    schema_version: str | None = None
    completed: tuple[StructuredHandoffItem, ...] = ()
    in_progress: tuple[StructuredHandoffItem, ...] = ()
    remaining: tuple[StructuredHandoffItem, ...] = ()
    decisions: tuple[StructuredHandoffItem, ...] = ()
    failed_approaches: tuple[StructuredHandoffItem, ...] = ()
    discoveries: tuple[StructuredHandoffItem, ...] = ()
    useful_commands: tuple[StructuredHandoffItem, ...] = ()
    open_items: tuple[StructuredHandoffItem, ...] = ()
    blockers: tuple[StructuredHandoffItem, ...] = ()
    referenced_files: tuple[StructuredHandoffItem, ...] = ()
    prior_verification: tuple[StructuredHandoffItem, ...] = ()
    unknowns: tuple[StructuredHandoffItem, ...] = ()
    reconciliation: HandoffReconciliation = Field(
        default_factory=HandoffReconciliation
    )


class ProjectContextProvenance(_FrozenContract):
    """A hash-bound source that supports one durable foundation statement."""

    source_document_id: str = Field(min_length=1)
    evidence_span_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1, max_length=80)
    source_revision_number: int | None = Field(default=None, ge=1)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectContextItem(_FrozenContract):
    """One objective-independent, evidence-backed workspace foundation fact."""

    id: str = Field(pattern=r"^P[1-9][0-9]*$")
    kind: ProjectContextKind
    section: ProjectFoundationSection
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=1_200)
    identity_key: str = Field(min_length=1, max_length=500)
    evidence_level: ProjectEvidenceLevel
    provenance_refs: tuple[ProjectContextProvenance, ...] = Field(
        min_length=1,
        max_length=8,
    )
    corroboration_count: int = Field(default=1, ge=1)
    truth_state: Literal["current"] = "current"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("project context title must contain visible characters")
        return normalized

    @field_validator("statement")
    @classmethod
    def strip_statement(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(
                "project context statement must contain visible characters"
            )
        return normalized

    @model_validator(mode="after")
    def validate_evidence_level(self) -> "ProjectContextItem":
        if not self.evidence_level.durable_current:
            raise ValueError(
                "current Project Context may contain only durable evidence levels"
            )
        if (
            self.evidence_level is ProjectEvidenceLevel.CORROBORATED
            and self.corroboration_count < 2
        ):
            raise ValueError("corroborated Project Context requires two sources")
        return self


class ProjectFoundationSnapshot(_FrozenContract):
    """Compilation metadata proving workspace scope and repository freshness."""

    schema_version: Literal["project_foundation.v1"] = "project_foundation.v1"
    workspace_id: UUID
    compilation_scope: Literal["workspace"] = "workspace"
    objective_independent: Literal[True] = True
    repository_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    included_fact_count: int = Field(ge=0)
    provisional_fact_count: int = Field(default=0, ge=0)
    superseded_conflicting_fact_count: int = Field(default=0, ge=0)
    source_document_count: int = Field(default=0, ge=0)


class RepositoryEvidenceItem(_FrozenContract):
    """One syntax-level fact observed in the bound repository snapshot.

    This is intentionally separate from durable workspace knowledge. It may
    describe declarations and exact indexer edges, but it cannot claim code
    behavior, architectural intent, or user acceptance.
    """

    id: str = Field(pattern=r"^RE[1-9][0-9]*$")
    kind: RepositoryEvidenceKind
    path: str | None = Field(default=None, min_length=1)
    file_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    symbol_type: str | None = Field(default=None, min_length=1, max_length=80)
    symbol_name: str | None = Field(default=None, min_length=1, max_length=300)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    test_path: str | None = Field(default=None, min_length=1)
    test_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    target_path: str | None = Field(default=None, min_length=1)
    target_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    rule_id: str | None = Field(default=None, min_length=1, max_length=120)
    rule_version: str | None = Field(default=None, min_length=1, max_length=40)
    edge_key: str | None = Field(default=None, min_length=1, max_length=160)
    manifest_path: str | None = Field(default=None, min_length=1)
    manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    dependency_group: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    dependency_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
    )
    declaration: str | None = Field(default=None, min_length=1, max_length=500)
    truth_state: Literal["observed_at_snapshot"] = "observed_at_snapshot"
    provenance: Literal["repository_index"] = "repository_index"

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "RepositoryEvidenceItem":
        symbol_fields = {
            "path",
            "file_sha256",
            "symbol_type",
            "symbol_name",
            "start_line",
            "end_line",
        }
        test_link_fields = {
            "test_path",
            "test_sha256",
            "target_path",
            "target_sha256",
            "rule_id",
            "rule_version",
            "edge_key",
        }
        dependency_fields = {
            "manifest_path",
            "manifest_sha256",
            "dependency_group",
            "dependency_name",
            "declaration",
        }
        paths = (
            self.path,
            self.test_path,
            self.target_path,
            self.manifest_path,
        )
        if any(
            value is not None
            and (
                value.startswith(("/", "\\"))
                or ".." in value.replace("\\", "/").split("/")
            )
            for value in paths
        ):
            raise ValueError(
                "repository evidence paths must be repository-relative"
            )
        if self.kind is RepositoryEvidenceKind.SYMBOL_DECLARATION:
            allowed_fields = symbol_fields
            required = (
                self.path,
                self.file_sha256,
                self.symbol_type,
                self.symbol_name,
                self.start_line,
                self.end_line,
            )
        elif self.kind is RepositoryEvidenceKind.TEST_LINK:
            allowed_fields = test_link_fields
            required = (
                self.test_path,
                self.test_sha256,
                self.target_path,
                self.target_sha256,
                self.rule_id,
                self.rule_version,
                self.edge_key,
            )
        else:
            allowed_fields = dependency_fields
            required = (
                self.manifest_path,
                self.manifest_sha256,
                self.dependency_group,
                self.dependency_name,
                self.declaration,
            )
        all_kind_fields = symbol_fields | test_link_fields | dependency_fields
        unexpected_fields = sorted(
            field_name
            for field_name in all_kind_fields - allowed_fields
            if getattr(self, field_name) is not None
        )
        if unexpected_fields:
            raise ValueError(
                f"{self.kind.value} repository evidence includes fields from "
                "another evidence kind: "
                + ", ".join(unexpected_fields)
            )
        if any(value in (None, "") for value in required):
            raise ValueError(
                f"{self.kind.value} repository evidence is incomplete"
            )
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("repository evidence line range is reversed")
        return self


class SupportingContextItem(_FrozenContract):
    """Hash-bound historical material explicitly referenced by the user."""

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=MAX_SUPPORTING_CONTEXT_CHARS)
    source: Literal[
        "embedded_referenced_conversation",
        "prior_session_turn",
    ]
    truth_state: Literal["historical_data"] = "historical_data"
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_hash(self) -> "SupportingContextItem":
        if self.text != self.text.strip():
            raise ValueError("supporting context text must be stripped")
        if self.content_sha256 != sha256_text(self.text):
            raise ValueError("supporting context hash does not match its text")
        return self


class PreexistingChange(_FrozenContract):
    status: str = Field(min_length=1)
    path: str = Field(min_length=1)
    xy: str | None = Field(default=None, min_length=2, max_length=2)
    change_kind: str | None = Field(default=None, min_length=1)
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class RepositoryContract(_FrozenContract):
    root: str = Field(min_length=1)
    branch: str | None = None
    head_commit: str | None = None
    status_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    status_truncated: bool = False
    preexisting_changes: tuple[PreexistingChange, ...] = ()


class ArtifactReference(_FrozenContract):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    source_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mime_type: str | None = None
    required: bool = True
    available: bool = True
    visual_summary: str | None = None
    requirement_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> "ArtifactReference":
        if self.available and self.sha256 is None:
            raise ValueError("available artifact requires sha256")
        return self


class ContinuationArtifactInput(_FrozenContract):
    """Bounded local artifact descriptor accepted at API/service boundaries."""

    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    kind: str = Field(default="attachment", min_length=1, max_length=50)
    path: str = Field(min_length=1, max_length=4096)
    required: bool = True
    mime_type: str | None = Field(default=None, min_length=1, max_length=255)
    visual_summary: str | None = Field(
        default=None,
        min_length=1,
        max_length=4_000,
    )

    @field_validator("kind", "path", "mime_type", "visual_summary")
    @classmethod
    def strip_visible_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("artifact fields must contain visible characters")
        return normalized


class ReadPlanItem(_FrozenContract):
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    symbol: str | None = None
    priority: int = Field(default=0, ge=0)


class VerificationSpec(_FrozenContract):
    id: str = Field(min_length=1)
    verifier_type: VerifierType
    requirement_ids: tuple[str, ...] = ()
    command_argv: tuple[str, ...] = ()
    cwd: str = "."
    required: bool = True
    expected_exit_code: int | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    rubric: str | None = None

    @model_validator(mode="after")
    def validate_verifier_shape(self) -> "VerificationSpec":
        command_types = {
            VerifierType.UNIT_TEST,
            VerifierType.INTEGRATION_TEST,
            VerifierType.STATIC_ANALYSIS,
            VerifierType.DATABASE_STATE_ASSERTION,
            VerifierType.GIT_DIFF_ASSERTION,
        }
        if self.verifier_type in command_types and not self.command_argv:
            raise ValueError("command verifier requires command_argv")
        if self.command_argv and not self.command_argv[0].strip():
            raise ValueError("command_argv must contain an executable")
        if self.verifier_type is VerifierType.MODEL_RUBRIC and not self.rubric:
            raise ValueError("model_rubric verifier requires a rubric")
        if self.cwd.startswith("/") or ".." in self.cwd.replace("\\", "/").split("/"):
            raise ValueError("verification cwd must be repository-relative")
        return self


class ExecutionAuthority(_FrozenContract):
    filesystem_mode: FilesystemMode
    command_mode: CommandMode
    allow_product_edits: bool
    preserve_preexisting_changes: bool = True

    @classmethod
    def for_mode(cls, mode: TaskMode) -> "ExecutionAuthority":
        return cls(
            filesystem_mode=(
                FilesystemMode.WORKSPACE_WRITE
                if mode.allows_edits
                else FilesystemMode.READ_ONLY
            ),
            command_mode=(
                CommandMode.EXECUTE
                if mode in {TaskMode.CHANGE, TaskMode.DIAGNOSE, TaskMode.TEST_ONLY}
                else CommandMode.INSPECTION_ONLY
            ),
            allow_product_edits=mode.allows_edits,
        )


class ExecutionPolicy(_FrozenContract):
    max_repair_attempts: int = Field(default=2, ge=0, le=2)
    stop_on_no_progress: bool = True
    no_progress_rule: str = "same_unmet_requirements_and_repository_fingerprint"
    worker_timeout_seconds: float = Field(default=1800.0, gt=0)
    verification_timeout_seconds: float = Field(default=300.0, gt=0)


class ContinuationExecutionContract(_FrozenContract):
    schema_version: Literal["continuation_execution.v1"] = (
        CONTINUATION_EXECUTION_SCHEMA_VERSION
    )
    id: str
    context_pack_id: str
    checkpoint_id: str | None = None
    created_at: datetime
    task_mode: TaskMode
    task: AuthoritativeRequest
    selected_task_lifecycle: SelectedTaskLifecycle = Field(
        default=SelectedTaskLifecycle.ACTIVE,
        exclude_if=lambda value: value is SelectedTaskLifecycle.ACTIVE,
    )
    task_identity: ContinuationTaskIdentity | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    execution_focus: str | None = None
    source_spans: tuple[RequestSourceSpan, ...]
    requirements: tuple[AtomicRequirement, ...]
    definition_of_done: tuple[str, ...]
    repository: RepositoryContract
    handoff: StructuredHandoff = Field(default_factory=StructuredHandoff)
    project_foundation: ProjectFoundationSnapshot | None = None
    project_context: tuple[ProjectContextItem, ...] = Field(
        default=(),
        max_length=MAX_PROJECT_CONTEXT_ITEMS,
        exclude_if=lambda value: not value,
    )
    repository_evidence: tuple[RepositoryEvidenceItem, ...] = Field(
        default=(),
        max_length=MAX_REPOSITORY_EVIDENCE_ITEMS,
        exclude_if=lambda value: not value,
    )
    supporting_context: tuple[SupportingContextItem, ...] = Field(
        default=(),
        max_length=MAX_SUPPORTING_CONTEXT_ITEMS,
        exclude_if=lambda value: not value,
    )
    artifacts: tuple[ArtifactReference, ...] = ()
    read_plan: tuple[ReadPlanItem, ...] = ()
    verification: tuple[VerificationSpec, ...] = ()
    required_capabilities: tuple[RequiredCapability, ...] = ()
    authority: ExecutionAuthority
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @model_validator(mode="after")
    def validate_lineage_and_authority(self) -> "ContinuationExecutionContract":
        if (
            self.task_identity is not None
            and self.task_identity.authoritative_request_sha256
            != self.task.request_sha256
        ):
            raise ValueError(
                "task identity authoritative request hash does not match task"
            )
        if (
            self.task_mode.allows_edits
            and request_explicitly_forbids_edits(
                self.task.request_verbatim
            )
        ):
            raise ValueError(
                "explicit no-edit request cannot grant product edit authority"
            )
        span_ids = [span.id for span in self.source_spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("source span IDs must be unique")
        requirement_ids = [requirement.id for requirement in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement IDs must be unique")
        known_spans = set(span_ids)
        covered_spans: set[str] = set()
        for requirement in self.requirements:
            unknown = set(requirement.source_span_ids) - known_spans
            if unknown:
                raise ValueError(
                    "requirement references unknown source spans: "
                    + ", ".join(sorted(unknown))
                )
            covered_spans.update(requirement.source_span_ids)
        substantive = {
            span.id for span in self.source_spans if span.substantive
        }
        missing = substantive - covered_spans
        if missing:
            raise ValueError(
                "substantive request spans lack requirement coverage: "
                + ", ".join(sorted(missing))
            )
        known_requirements = set(requirement_ids)
        known_artifacts = {artifact.id for artifact in self.artifacts}
        for requirement in self.requirements:
            unknown = set(requirement.source_artifact_ids) - known_artifacts
            if unknown:
                raise ValueError(
                    "requirement references unknown artifacts: "
                    + ", ".join(sorted(unknown))
                )
        unknown_done = set(self.definition_of_done) - known_requirements
        if unknown_done:
            raise ValueError(
                "definition_of_done references unknown requirements: "
                + ", ".join(sorted(unknown_done))
            )
        mandatory = {
            requirement.id
            for requirement in self.requirements
            if requirement.priority is RequirementPriority.MUST
        }
        if set(self.definition_of_done) != mandatory:
            raise ValueError(
                "definition_of_done must contain every and only MUST requirement"
            )
        for span in self.source_spans:
            if self.task.request_verbatim[span.start_char:span.end_char] != span.text:
                raise ValueError(
                    f"source span {span.id} does not match request_verbatim offsets"
                )
        verifier_ids = [verifier.id for verifier in self.verification]
        if len(verifier_ids) != len(set(verifier_ids)):
            raise ValueError("verification IDs must be unique")
        known_verifiers = set(verifier_ids)
        links_from_requirements = {
            (requirement.id, verifier_id)
            for requirement in self.requirements
            for verifier_id in requirement.verification_ids
        }
        unknown_verifiers = {
            verifier_id
            for _, verifier_id in links_from_requirements
            if verifier_id not in known_verifiers
        }
        if unknown_verifiers:
            raise ValueError(
                "requirements reference unknown verifiers: "
                + ", ".join(sorted(unknown_verifiers))
            )
        links_from_verifiers = {
            (requirement_id, verifier.id)
            for verifier in self.verification
            for requirement_id in verifier.requirement_ids
        }
        unknown_requirement_links = {
            requirement_id
            for requirement_id, _ in links_from_verifiers
            if requirement_id not in known_requirements
        }
        if unknown_requirement_links:
            raise ValueError(
                "verifiers reference unknown requirements: "
                + ", ".join(sorted(unknown_requirement_links))
            )
        if links_from_requirements != links_from_verifiers:
            raise ValueError(
                "requirement and verifier lineage must be bidirectionally consistent"
            )
        required_verifier_ids = {
            verifier.id for verifier in self.verification if verifier.required
        }
        for requirement in self.requirements:
            if (
                requirement.priority is RequirementPriority.MUST
                and not (set(requirement.verification_ids) & required_verifier_ids)
            ):
                raise ValueError(
                    f"MUST requirement {requirement.id} has no required verifier"
                )
        artifact_ids = [artifact.id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact IDs must be unique")
        project_context_ids = [item.id for item in self.project_context]
        if len(project_context_ids) != len(set(project_context_ids)):
            raise ValueError("project context IDs must be unique")
        repository_evidence_ids = [
            item.id for item in self.repository_evidence
        ]
        if len(repository_evidence_ids) != len(
            set(repository_evidence_ids)
        ):
            raise ValueError("repository evidence IDs must be unique")
        for artifact in self.artifacts:
            unknown = set(artifact.requirement_ids) - known_requirements
            if unknown:
                raise ValueError(
                    "artifact references unknown requirements: "
                    + ", ".join(sorted(unknown))
                )
        artifact_links_from_requirements = {
            (artifact_id, requirement.id)
            for requirement in self.requirements
            for artifact_id in requirement.source_artifact_ids
        }
        artifact_links_from_artifacts = {
            (artifact.id, requirement_id)
            for artifact in self.artifacts
            for requirement_id in artifact.requirement_ids
        }
        if artifact_links_from_requirements != artifact_links_from_artifacts:
            raise ValueError(
                "artifact and requirement lineage must be bidirectionally "
                "consistent"
            )
        expected_filesystem_mode = (
            FilesystemMode.WORKSPACE_WRITE
            if self.task_mode.allows_edits
            else FilesystemMode.READ_ONLY
        )
        if self.authority.filesystem_mode is not expected_filesystem_mode:
            raise ValueError("execution authority does not match task mode")
        if self.authority.allow_product_edits is not self.task_mode.allows_edits:
            raise ValueError("product edit authority does not match task mode")
        return self


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_request_for_matching(value: str) -> str:
    return " ".join(value.split())


def is_non_verifiable_execution_guidance(value: str) -> bool:
    """Return whether a clause directs working style, not an observable result.

    These clauses remain source-backed constraints in the contract, but they
    must not create standalone completion gates. A clause that also names a
    concrete outcome stays a requirement so modifiers such as ``carefully`` are
    retained without losing the actual requested work.
    """

    normalized = normalize_request_for_matching(
        re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", str(value or ""))
    )
    normalized = re.sub(r"[*_~]+", "", normalized).strip(" \t\r\n.!?:;")
    if not normalized:
        return False
    if _EXPLICIT_QUALITY_OUTCOME_RE.search(normalized):
        return False
    if _CONCRETE_OUTCOME_ACTION_RE.search(normalized):
        return False
    return any(
        pattern.search(normalized) is not None
        for pattern in (
            _REFERENTIAL_WORK_STYLE_RE,
            _REFERENTIAL_STYLE_DIRECTIVE_RE,
            _QUALITY_PREFERENCE_RE,
            _STANDALONE_EXECUTION_PREFERENCE_RE,
        )
    )


def display_title_for_request(value: str) -> str:
    normalized = normalize_request_for_matching(value)
    if not normalized:
        raise ValueError("request must contain visible characters")
    if len(normalized) <= MAX_DISPLAY_TITLE:
        return normalized
    return normalized[: MAX_DISPLAY_TITLE - 1].rstrip() + "…"


def build_authoritative_request(request_verbatim: str) -> AuthoritativeRequest:
    if not isinstance(request_verbatim, str) or not request_verbatim.strip():
        raise ValueError("request must contain visible characters")
    return AuthoritativeRequest(
        request_verbatim=request_verbatim,
        request_normalized=normalize_request_for_matching(request_verbatim),
        request_sha256=sha256_text(request_verbatim),
        display_title=display_title_for_request(request_verbatim),
    )


def _has_direct_change_intent(value: str) -> bool:
    """Recognize affirmative mutation clauses, excluding advisory framing."""

    for clause in re.split(r"(?<=[.!?])\s+", value):
        direct_matches = [
            match
            for pattern in (
                _DIRECT_MUTATION_INTENT_RE,
                _DIRECT_BUILD_INTENT_RE,
                _DIRECT_COMPLETION_INTENT_RE,
                _DIRECT_BEHAVIOR_CONSTRAINT_RE,
                _DIRECT_REFERENTIAL_CHANGE_INTENT_RE,
            )
            if (match := pattern.search(clause)) is not None
        ]
        if not direct_matches:
            continue
        first_direct = min(direct_matches, key=lambda match: match.start())
        advisory_frame = _ADVISORY_CHANGE_FRAME_RE.search(clause)
        if advisory_frame is None or first_direct.start() < advisory_frame.start():
            return True
    return False


def infer_task_mode(request: str) -> TaskMode:
    normalized = normalize_request_for_matching(
        _request_directive_text(request)
    ).casefold()
    if _TEST_ONLY_INTENT_RE.search(normalized):
        return TaskMode.TEST_ONLY
    explicit_read_only = request_explicitly_forbids_edits(request)
    report = bool(
        re.search(
            r"\b(?:write|produce|generate|give|provide)\b.{0,30}"
            r"\b(?:report|summary)\b",
            normalized,
        )
    )
    plan = bool(
        re.search(
            r"\b(?:make|create|write|produce|give|provide)\b.{0,30}"
            r"\bplan\b",
            normalized,
        )
    )
    diagnosis = bool(
        re.search(
            r"\b(?:diagnose|debug|investigate|root cause|why is|why does)\b",
            normalized,
        )
    )
    review = bool(
        re.search(
            r"\b(?:review|audit|inspect|assess|check|critique|validate|verify)\b",
            normalized,
        )
    )
    explanation = bool(
        re.search(
            r"\b(?:answer|brainstorm|describe|discuss|explain|explore|"
            r"summari[sz]e|walk me through)\b",
            normalized,
        )
    )
    hypothetical_change = bool(
        _HYPOTHETICAL_CHANGE_INTENT_RE.search(normalized)
    )
    direct_change = _has_direct_change_intent(normalized)
    if explicit_read_only and diagnosis:
        return TaskMode.DIAGNOSE
    if explicit_read_only and review:
        return TaskMode.REVIEW
    if explicit_read_only and explanation:
        return TaskMode.REPORT
    if explicit_read_only:
        # An explicit no-edit boundary always outranks implementation verbs.
        # Diagnose is the safest executable interpretation when the user asks
        # about a change but expressly withholds write authority.
        return TaskMode.DIAGNOSE
    if direct_change:
        return TaskMode.CHANGE
    if _DIRECT_TEST_INTENT_RE.search(normalized):
        return TaskMode.TEST_ONLY
    if report:
        return TaskMode.REPORT
    if diagnosis:
        return TaskMode.DIAGNOSE
    if review:
        return TaskMode.REVIEW
    if plan or hypothetical_change:
        return TaskMode.PLAN
    if explanation:
        return TaskMode.REPORT
    # An unmatched request carries no affirmative authority to mutate the
    # checkout. Callers may ask for a more specific mode after clarifying it.
    return TaskMode.REPORT


def request_explicitly_forbids_edits(request: str) -> bool:
    normalized = normalize_request_for_matching(
        _request_directive_text(request)
    ).casefold()
    return bool(
        re.search(
            r"\b(?:read[- ]only|no edits?|"
            r"no (?:file|code|product|repository) changes?|"
            r"do not (?:edit|change|modify|make (?:any )?changes)|"
            r"don't (?:edit|change|modify|make (?:any )?changes)|"
            r"without (?:edits?|editing|changes?|changing|modifying|"
            r"making (?:any )?changes)|"
            r"(?:review|audit|report|findings?) only)\b",
            normalized,
        )
    )


def resolve_task_mode(
    request: str,
    requested_mode: TaskMode | str | None,
) -> TaskMode:
    inferred = infer_task_mode(request)
    if requested_mode is None:
        return inferred
    resolved = (
        requested_mode
        if isinstance(requested_mode, TaskMode)
        else TaskMode(str(requested_mode))
    )
    if resolved.allows_edits and request_explicitly_forbids_edits(request):
        return inferred if not inferred.allows_edits else TaskMode.DIAGNOSE
    return resolved


def compile_request_requirements(
    request: AuthoritativeRequest,
    *,
    task_mode: TaskMode,
) -> tuple[tuple[RequestSourceSpan, ...], tuple[AtomicRequirement, ...]]:
    raw_spans = _request_span_offsets(request.request_verbatim)
    source_spans: list[RequestSourceSpan] = []
    requirements: list[AtomicRequirement] = []
    active_section: str | None = None
    for start, end in raw_spans:
        semantic_ranges = _semantic_request_ranges(
            request.request_verbatim,
            start,
            end,
        )
        semantic_text = " ".join(
            normalize_request_for_matching(
                request.request_verbatim[semantic_start:semantic_end]
            )
            for semantic_start, semantic_end in semantic_ranges
        ).strip()
        if not semantic_text:
            continue
        section = _request_section_heading(semantic_text)
        if section is not None:
            active_section = section
            kind = SourceSpanKind.BACKGROUND
        elif _request_span_is_quoted_or_fenced(
            request.request_verbatim,
            start,
        ) or _HISTORICAL_SPEECH_RE.search(semantic_text):
            kind = SourceSpanKind.BACKGROUND
        elif active_section == "acceptance":
            kind = SourceSpanKind.ACCEPTANCE_CRITERION
        elif active_section == "background":
            kind = SourceSpanKind.BACKGROUND
        elif (
            _request_list_item(semantic_text)
            and _background_list_item(semantic_text)
        ):
            kind = SourceSpanKind.BACKGROUND
        elif is_non_verifiable_execution_guidance(semantic_text):
            kind = SourceSpanKind.CONSTRAINT
        elif (
            task_mode is TaskMode.CHANGE
            and _request_list_item(semantic_text)
        ):
            kind = SourceSpanKind.ACCEPTANCE_CRITERION
        else:
            kind = _source_span_kind(semantic_text, task_mode=task_mode)
        span_ids: list[str] = []
        for semantic_start, semantic_end in semantic_ranges:
            semantic_exact = request.request_verbatim[
                semantic_start:semantic_end
            ]
            span_id = f"S{len(source_spans) + 1}"
            span_ids.append(span_id)
            source_spans.append(RequestSourceSpan(
                id=span_id,
                start_char=semantic_start,
                end_char=semantic_end,
                text=semantic_exact,
                text_sha256=sha256_text(semantic_exact),
                kind=kind,
                substantive=True,
            ))
        priority = (
            RequirementPriority.CONTEXT
            if (
                kind is SourceSpanKind.BACKGROUND
                or (
                    kind is SourceSpanKind.CONSTRAINT
                    and is_non_verifiable_execution_guidance(semantic_text)
                )
            )
            else RequirementPriority.MUST
        )
        requirements.append(AtomicRequirement(
            id=f"R{len(requirements) + 1}",
            text=semantic_text,
            priority=priority,
            source_span_ids=tuple(span_ids),
        ))
    if not source_spans:
        raise ValueError("request contains no substantive source spans")
    return tuple(source_spans), tuple(requirements)


def _semantic_request_ranges(
    request_verbatim: str,
    start: int,
    end: int,
) -> tuple[tuple[int, int], ...]:
    """Return exact request ranges with image transport markup removed."""

    ranges: list[tuple[int, int]] = []
    cursor = start
    for match in _IMAGE_TRANSPORT_TAG_RE.finditer(
        request_verbatim,
        start,
        end,
    ):
        if match.start() > cursor:
            semantic = _trim_request_range(
                request_verbatim,
                cursor,
                match.start(),
            )
            if semantic is not None:
                ranges.append(semantic)
        cursor = match.end()
    if cursor < end:
        semantic = _trim_request_range(request_verbatim, cursor, end)
        if semantic is not None:
            ranges.append(semantic)
    return tuple(ranges)


def _trim_request_range(
    value: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    while start < end and value[start].isspace():
        start += 1
    while end > start and value[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _request_section_heading(value: str) -> str | None:
    stripped = value.strip()
    if re.match(r"^(?:[-*+]|\d+[.)])\s+", stripped):
        return None
    markdown_heading = stripped.startswith("#")
    label = re.sub(r"^#{1,6}\s*", "", stripped).strip()
    marked_heading = markdown_heading or label.endswith(":")
    label = label.rstrip(":").strip().casefold()
    if re.fullmatch(
        r"(?:acceptance(?: criteria)?|definition of done|done when|"
        r"expected behavio[u]?r|implementation requirements?|must[- ]haves?|"
        r"requirements?|success criteria|"
        r"(?:implement|ensure|make|verify) (?:all of )?the following|"
        r"make (?:all of )?these changes|the result must)",
        label,
    ):
        return "acceptance"
    if re.fullmatch(
        r"(?:background|context|current state|existing state|"
        r"current implementation|existing implementation|history|notes?|"
        r"for reference|non-goals?|out of scope)",
        label,
    ):
        return "background"
    if marked_heading and _NON_AUTHORITATIVE_HEADING_RE.search(label):
        return "background"
    return "other" if marked_heading else None


def _request_directive_text(value: str) -> str:
    """Remove quoted/history regions before inferring execution authority."""

    raw_value = str(value or "")
    request_marker = _CURRENT_USER_REQUEST_MARKER_RE.search(raw_value)
    if request_marker is not None:
        raw_value = raw_value[request_marker.end():]
    lines: list[str] = []
    fence_marker: str | None = None
    ignore_section = False
    for raw_line in raw_value.splitlines():
        stripped = raw_line.strip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            continue
        if fence_marker is not None or stripped.startswith(">"):
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            ignore_section = bool(
                _NON_AUTHORITATIVE_HEADING_RE.search(
                    heading_match.group(1)
                )
            )
            continue
        if ignore_section or _HISTORICAL_SPEECH_RE.search(stripped):
            continue
        without_inline_history = re.sub(
            r"(?i)\b(?:the\s+)?(?:prior|previous|historical)\s+"
            r"(?:agent|assistant|user|transcript|message)\s+"
            r"(?:said|says|wrote|asked|claimed|reported)\b.*$",
            " ",
            raw_line,
        )
        without_reference_links = re.sub(
            r"\[[^\]\n]{1,500}\]\([^\)\n]{1,2000}\)",
            " ",
            without_inline_history,
        )
        without_request_wrapper = re.sub(
            r"^\s*(?:[-*+]|\d+[.)])\s+",
            "",
            without_reference_links,
        )
        without_request_wrapper = re.sub(
            r"^\s*\*\*(?:action|goal|request|task)\s*:?\*\*\s*",
            "",
            without_request_wrapper,
            flags=re.IGNORECASE,
        )
        without_request_wrapper = re.sub(
            r"^\s*(?:action|goal|request|task)\s*:\s*",
            "",
            without_request_wrapper,
            flags=re.IGNORECASE,
        )
        without_quoted_history = re.sub(
            r'"[^"\n]{1,500}"|“[^”\n]{1,500}”|'
            r"(?<!\w)'[^'\n]{1,500}'(?!\w)|‘[^’\n]{1,500}’",
            " ",
            without_request_wrapper,
        )
        if without_quoted_history.strip():
            lines.append(without_quoted_history)
    return "\n".join(lines)


def _request_span_is_quoted_or_fenced(value: str, start: int) -> bool:
    prefix = value[:start]
    line_start = prefix.rfind("\n") + 1
    line = value[line_start:value.find("\n", start) if "\n" in value[start:] else len(value)]
    if line.lstrip().startswith(">") or re.match(
        r"^\s*(?:`{3,}|~{3,})",
        line,
    ):
        return True
    fence_marker: str | None = None
    for prior_line in prefix.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", prior_line)
        if match is None:
            continue
        marker = match.group(1)[0]
        if fence_marker is None:
            fence_marker = marker
        elif marker == fence_marker:
            fence_marker = None
    return fence_marker is not None


def _request_list_item(value: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", value))


def _background_list_item(value: str) -> bool:
    text = re.sub(
        r"^\s*(?:[-*+]|\d+[.)])\s+",
        "",
        value,
    ).casefold()
    return bool(
        re.match(
            r"(?:for context\b|currently\b|historically\b|today\b|"
            r"(?:the )?(?:current|existing|prior|previous|legacy)\b|"
            r"(?:this )?(?:codebase|repository|project)\s+"
            r"(?:contains|has|includes|uses)\b)",
            text,
        )
    )


def _request_span_offsets(value: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for line in value.splitlines(keepends=True):
        content_end = len(line.rstrip("\r\n"))
        content = line[:content_end]
        leading = len(content) - len(content.lstrip())
        trailing_end = len(content.rstrip())
        if leading < trailing_end:
            segment = content[leading:trailing_end]
            segment_start = cursor + leading
            sentence_starts = [0]
            sentence_starts.extend(
                match.end()
                for match in re.finditer(r"(?<=[.!?])\s+", segment)
            )
            sentence_starts = sorted(set(sentence_starts))
            for position, relative_start in enumerate(sentence_starts):
                relative_end = (
                    sentence_starts[position + 1]
                    if position + 1 < len(sentence_starts)
                    else len(segment)
                )
                while (
                    relative_start < relative_end
                    and segment[relative_start].isspace()
                ):
                    relative_start += 1
                while (
                    relative_end > relative_start
                    and segment[relative_end - 1].isspace()
                ):
                    relative_end -= 1
                if relative_start < relative_end:
                    sentence = segment[relative_start:relative_end]
                    for clause_start, clause_end in _clause_offsets(sentence):
                        spans.append((
                            segment_start + relative_start + clause_start,
                            segment_start + relative_start + clause_end,
                        ))
        cursor += len(line)
    if cursor < len(value):
        tail = value[cursor:]
        leading = len(tail) - len(tail.lstrip())
        trailing_end = len(tail.rstrip())
        if leading < trailing_end:
            spans.append((cursor + leading, cursor + trailing_end))
    return spans


def _clause_offsets(value: str) -> list[tuple[int, int]]:
    action = (
        r"(?:accomplish|add|build|change|continue|create|debug|diagnose|"
        r"ensure|fix|implement|inspect|investigate|make|remove|repair|"
        r"replace|resume|review|run|ship|test|update|verify|write)"
    )
    separators = list(re.finditer(
        rf"(?:;\s+|\s+(?:and|then)\s+)(?={action}\b)",
        value,
        re.IGNORECASE,
    ))
    starts = [0, *(match.end() for match in separators)]
    ends = [*(match.start() for match in separators), len(value)]
    result: list[tuple[int, int]] = []
    for start, end in zip(starts, ends, strict=True):
        while start < end and value[start].isspace():
            start += 1
        while end > start and value[end - 1].isspace():
            end -= 1
        if start < end:
            result.append((start, end))
    return result


def _source_span_kind(value: str, *, task_mode: TaskMode) -> SourceSpanKind:
    normalized = normalize_request_for_matching(value)
    lowered = normalized.casefold()
    if normalized.endswith("?"):
        return SourceSpanKind.QUESTION
    if re.search(r"\b(?:definition of done|acceptance|done when|must pass)\b", lowered):
        return SourceSpanKind.ACCEPTANCE_CRITERION
    if is_non_verifiable_execution_guidance(normalized):
        return SourceSpanKind.CONSTRAINT
    if re.search(r"\b(?:do not|don't|must not|never|preserve|without|only)\b", lowered):
        return SourceSpanKind.CONSTRAINT
    if re.search(
        r"\b(?:accomplish|add|build|change|continue|create|debug|diagnose|fix|implement|inspect|"
        r"investigate|make|remove|repair|replace|review|run|ship|test|update|"
        r"verify|write|ensure|must|need|resume|should)\b",
        lowered,
    ):
        return SourceSpanKind.REQUIREMENT
    if re.search(
        r"^(?:for context\b|currently\b|historically\b|today\b|"
        r"(?:the )?(?:current|existing|prior|previous|legacy)\b|"
        r"(?:this )?(?:codebase|repository|project)\s+"
        r"(?:contains|has|includes|uses)\b)",
        lowered,
    ):
        return SourceSpanKind.BACKGROUND
    if task_mode is TaskMode.CHANGE:
        # In change mode, silently dropping an unrecognized imperative or
        # conditional clause is more dangerous than carrying an extra MUST.
        # Explicit background headings and declarative current-state clauses
        # are handled above.
        return SourceSpanKind.REQUIREMENT
    if task_mode in {
        TaskMode.REVIEW,
        TaskMode.REPORT,
        TaskMode.PLAN,
        TaskMode.DIAGNOSE,
    }:
        return SourceSpanKind.REQUIREMENT
    return SourceSpanKind.BACKGROUND
