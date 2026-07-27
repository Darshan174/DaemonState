from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.schemas.continuation_execution import (
    ContinuationExecutionContract,
    HandoffTruthState,
    RequirementPriority,
    VerifierType,
)
from app.services.execution_prompt_renderer import (
    RENDERED_REPOSITORY_EVIDENCE_LIMIT,
    canonical_contract_json,
    execution_prompt_sha256,
)
from app.services.provider_capabilities import check_provider_capabilities


SUPPORTED_AUTOMATIC_VERIFIERS = frozenset({
    VerifierType.UNIT_TEST,
    VerifierType.INTEGRATION_TEST,
    VerifierType.STATIC_ANALYSIS,
    VerifierType.DATABASE_STATE_ASSERTION,
    VerifierType.GIT_DIFF_ASSERTION,
})
_REQUIRED_RUNTIME_EVIDENCE_VERIFIERS = frozenset({
    VerifierType.BROWSER_ASSERTION,
    VerifierType.SCREENSHOT_COMPARISON,
    VerifierType.EVENT_ASSERTION,
})
_EXECUTABLE_VERIFIER_TYPES = (
    SUPPORTED_AUTOMATIC_VERIFIERS
    | _REQUIRED_RUNTIME_EVIDENCE_VERIFIERS
)
_REFERENCED_CONTEXT_DEPENDENCY_RE = re.compile(
    r"(?:chatgpt-conversation://|https?://(?:www\.)?chatgpt\.com/|"
    r"\b(?:the\s+)?last\s+(?:prompt|message|response)\b|"
    r"\b(?:the\s+)?(?:above|previous|referenced)\s+"
    r"(?:idea|proposal|conversation)\b|"
    r"\bidea\s+discussed\b|"
    r"\b(?:idea|proposal|approach)\s+(?:described|discussed)\s+"
    r"(?:above|before|previously)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContinuationQualityIssue:
    code: str
    severity: str
    message: str
    requirement_id: str | None = None
    verifier_id: str | None = None
    artifact_id: str | None = None
    project_context_id: str | None = None
    repository_evidence_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class ContinuationQualityReport:
    launchable: bool
    issues: tuple[ContinuationQualityIssue, ...]
    contract_sha256: str
    prompt_sha256: str

    @property
    def automatic_execution_ready(self) -> bool:
        return self.launchable

    def to_dict(self) -> dict[str, Any]:
        return {
            "launchable": self.launchable,
            "automatic_execution_ready": self.automatic_execution_ready,
            "issues": [item.to_dict() for item in self.issues],
            "contract_sha256": self.contract_sha256,
            "prompt_sha256": self.prompt_sha256,
        }

    def require_launchable(self) -> None:
        if self.launchable:
            return
        summary = "; ".join(item.message for item in self.issues[:5])
        raise ContinuationQualityGateError(
            summary or "continuation execution contract is not launchable",
            report=self,
        )


class ContinuationQualityGateError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        report: ContinuationQualityReport,
    ) -> None:
        self.report = report
        super().__init__(message)


def evaluate_continuation_quality(
    contract: ContinuationExecutionContract,
    *,
    prompt_markdown: str,
    project_context_markdown: str | None = None,
    provider: str | None = None,
    expected_contract_sha256: str | None = None,
    expected_prompt_sha256: str | None = None,
) -> ContinuationQualityReport:
    """Fail closed on omissions that could create a false verified outcome."""

    contract_payload = canonical_contract_json(contract)
    contract_sha256 = hashlib.sha256(contract_payload.encode("utf-8")).hexdigest()
    prompt_sha256 = execution_prompt_sha256(prompt_markdown)
    issues: list[ContinuationQualityIssue] = []
    if (
        _REFERENCED_CONTEXT_DEPENDENCY_RE.search(
            contract.task.request_verbatim
        )
        and not contract.supporting_context
    ):
        issues.append(ContinuationQualityIssue(
            code="referenced_context_unresolved",
            severity="blocking",
            message=(
                "The authoritative request depends on referenced historical "
                "material that was not embedded into the portable contract."
            ),
        ))
    if any(
        item.truth_state is HandoffTruthState.CONTRADICTED
        for item in (
            *contract.handoff.completed,
            *contract.handoff.in_progress,
            *contract.handoff.remaining,
            *contract.handoff.unknowns,
        )
    ):
        issues.append(ContinuationQualityIssue(
            code="handoff_semantic_conflict",
            severity="blocking",
            message=(
                "The restored handoff contains contradictory work-state claims; "
                "inspect the repository and reconcile them before automatic execution."
            ),
        ))
    if expected_contract_sha256 and contract_sha256 != expected_contract_sha256:
        issues.append(ContinuationQualityIssue(
            code="contract_hash_mismatch",
            severity="blocking",
            message="Persisted execution contract hash does not match its content.",
        ))
    if expected_prompt_sha256 and prompt_sha256 != expected_prompt_sha256:
        issues.append(ContinuationQualityIssue(
            code="prompt_hash_mismatch",
            severity="blocking",
            message="Persisted execution prompt hash does not match its content.",
        ))
    if contract.task.request_verbatim not in prompt_markdown:
        issues.append(ContinuationQualityIssue(
            code="authoritative_request_missing",
            severity="blocking",
            message="Execution prompt does not contain the full authoritative request.",
        ))
    for item in contract.supporting_context:
        first_line = item.text.splitlines()[0]
        expected_line = f"> [historical {item.role}] {first_line}"
        if expected_line not in prompt_markdown.splitlines():
            issues.append(ContinuationQualityIssue(
                code="referenced_context_missing_from_prompt",
                severity="blocking",
                message=(
                    "Execution prompt omits hash-bound referenced historical "
                    f"context ({item.role})."
                ),
            ))
        if (
            project_context_markdown is not None
            and expected_line not in project_context_markdown.splitlines()
        ):
            issues.append(ContinuationQualityIssue(
                code="project_context_copy_reference_missing",
                severity="blocking",
                message=(
                    "Project Context copy omits hash-bound referenced historical "
                    f"context ({item.role})."
                ),
            ))
    _check_worker_handoff_shape(
        contract,
        markdown=prompt_markdown,
        context_name="Execution prompt",
        issues=issues,
    )
    if project_context_markdown is not None:
        _check_worker_handoff_shape(
            contract,
            markdown=project_context_markdown,
            context_name="Project Context",
            issues=issues,
            issue_prefix="project_context_copy",
        )
    for requirement in contract.requirements:
        if requirement.priority is not RequirementPriority.MUST:
            continue
        if f"{requirement.id}:" not in prompt_markdown:
            issues.append(ContinuationQualityIssue(
                code="mandatory_requirement_missing_from_prompt",
                severity="blocking",
                message=(
                    f"Execution prompt omits mandatory requirement {requirement.id}."
                ),
                requirement_id=requirement.id,
            ))

    for item in contract.project_context:
        if item.truth_state != "current" or item.provenance != "verified":
            issues.append(ContinuationQualityIssue(
                code="project_context_untrusted",
                severity="blocking",
                message=(
                    f"Project context item {item.id} is not current and "
                    "provenance-verified."
                ),
                project_context_id=item.id,
            ))
        if _looks_like_conversation_dump(f"{item.title}\n{item.statement}"):
            issues.append(ContinuationQualityIssue(
                code="project_context_conversation_dump",
                severity="blocking",
                message=(
                    f"Project context item {item.id} is transcript-shaped rather "
                    "than a current atomic project fact."
                ),
                project_context_id=item.id,
            ))
        statement_lines = item.statement.splitlines() or [""]
        expected_first_line = (
            f"> [{item.kind.value}; current; verified] "
            f"{item.title} — {statement_lines[0]}"
        )
        expected_continuations = [
            f"> {line}" if line else ">"
            for line in statement_lines[1:]
        ]
        if (
            expected_first_line not in prompt_markdown.splitlines()
            or any(
                line not in prompt_markdown.splitlines()
                for line in expected_continuations
            )
        ):
            issues.append(ContinuationQualityIssue(
                code="project_context_missing_from_prompt",
                severity="blocking",
                message=(
                    f"Execution prompt omits project context item {item.id}."
                ),
                project_context_id=item.id,
            ))
        if project_context_markdown is not None and (
            expected_first_line not in project_context_markdown.splitlines()
            or any(
                line not in project_context_markdown.splitlines()
                for line in expected_continuations
            )
        ):
            issues.append(ContinuationQualityIssue(
                code="project_context_copy_fact_missing",
                severity="blocking",
                message=(
                    f"Project Context copy omits current fact {item.id}."
                ),
                project_context_id=item.id,
            ))

    prompt_lines = prompt_markdown.splitlines()
    project_context_lines = (
        project_context_markdown.splitlines()
        if project_context_markdown is not None
        else None
    )
    for item in contract.repository_evidence[
        :RENDERED_REPOSITORY_EVIDENCE_LIMIT
    ]:
        expected_line = _repository_evidence_prompt_line(item)
        if expected_line not in prompt_lines:
            issues.append(ContinuationQualityIssue(
                code="repository_evidence_missing_from_prompt",
                severity="blocking",
                message=(
                    "Execution prompt omits current repository evidence "
                    f"{item.id}."
                ),
                repository_evidence_id=item.id,
            ))
        if (
            project_context_lines is not None
            and expected_line not in project_context_lines
        ):
            issues.append(ContinuationQualityIssue(
                code="project_context_copy_repository_evidence_missing",
                severity="blocking",
                message=(
                    "Project Context copy omits current repository evidence "
                    f"{item.id}."
                ),
                repository_evidence_id=item.id,
            ))

    repository = contract.repository
    if not repository.status_fingerprint:
        issues.append(ContinuationQualityIssue(
            code="repository_fingerprint_missing",
            severity="blocking",
            message="Execution contract has no repository status fingerprint.",
        ))
    if repository.status_truncated:
        issues.append(ContinuationQualityIssue(
            code="repository_baseline_truncated",
            severity="blocking",
            message=(
                "Repository preservation baseline is truncated and cannot prove "
                "that pre-existing changes survived."
            ),
        ))
    if not contract.authority.preserve_preexisting_changes:
        issues.append(ContinuationQualityIssue(
            code="preservation_policy_disabled",
            severity="blocking",
            message=(
                "Execution authority does not require preservation of "
                "pre-existing user changes."
            ),
        ))
    try:
        root = Path(repository.root).expanduser().resolve(strict=True)
    except OSError:
        root = None
        issues.append(ContinuationQualityIssue(
            code="repository_unavailable",
            severity="blocking",
            message="Execution repository is not locally readable.",
        ))
    if root is not None and not root.is_dir():
        issues.append(ContinuationQualityIssue(
            code="repository_unavailable",
            severity="blocking",
            message="Execution repository is not a directory.",
        ))

    requirement_ids = {item.id for item in contract.requirements}
    verifiers = {item.id: item for item in contract.verification}
    mandatory_requirements = [
        item
        for item in contract.requirements
        if item.priority is RequirementPriority.MUST
    ]
    if not mandatory_requirements:
        issues.append(ContinuationQualityIssue(
            code="mandatory_requirements_missing",
            severity="blocking",
            message="Execution contract contains no mandatory requirement.",
        ))
    for verifier in contract.verification:
        if not verifier.required:
            continue
        if not verifier.requirement_ids:
            issues.append(ContinuationQualityIssue(
                code="orphan_required_verifier",
                severity="blocking",
                message=(
                    f"Required verifier {verifier.id} is not linked to a "
                    "requirement."
                ),
                verifier_id=verifier.id,
            ))
        if (
            verifier.verifier_type not in SUPPORTED_AUTOMATIC_VERIFIERS
            and not verifier.command_argv
        ):
            issues.append(ContinuationQualityIssue(
                code="verifier_executor_unavailable",
                severity=(
                    "blocking"
                    if verifier.verifier_type
                    in _REQUIRED_RUNTIME_EVIDENCE_VERIFIERS
                    else "warning"
                ),
                message=(
                    f"Required verifier {verifier.id} uses "
                    f"{verifier.verifier_type.value}, which this runtime cannot "
                    "execute automatically. It cannot prove a requirement "
                    "without separate executable or external evidence."
                ),
                verifier_id=verifier.id,
            ))
    for requirement in contract.requirements:
        if requirement.priority is not RequirementPriority.MUST:
            continue
        required = [
            verifiers[verifier_id]
            for verifier_id in requirement.verification_ids
            if verifier_id in verifiers and verifiers[verifier_id].required
        ]
        if not required:
            issues.append(ContinuationQualityIssue(
                code="mandatory_verifier_missing",
                severity="blocking",
                message=(
                    f"Mandatory requirement {requirement.id} has no required verifier."
                ),
                requirement_id=requirement.id,
            ))
        elif not any(
            verifier.verifier_type in _EXECUTABLE_VERIFIER_TYPES
            and verifier.command_argv
            for verifier in required
        ):
            issues.append(ContinuationQualityIssue(
                code="mandatory_requirement_verification_unexecutable",
                severity="blocking",
                message=(
                    f"Mandatory requirement {requirement.id} has no required "
                    "executable verifier. Its verification remains unproven, "
                    "so automatic execution is disabled; the Project Context "
                    "may still be copied for manual continuation."
                ),
                requirement_id=requirement.id,
            ))
        for verifier in required:
            if not verifier.command_argv:
                issues.append(ContinuationQualityIssue(
                    code="verifier_command_missing",
                    severity=(
                        "blocking"
                        if verifier.verifier_type
                        in _REQUIRED_RUNTIME_EVIDENCE_VERIFIERS
                        else "warning"
                    ),
                    message=(
                        f"Verifier {verifier.id} has no executable argv; "
                        "this requirement remains unproven until executable "
                        "or external evidence is supplied."
                    ),
                    requirement_id=requirement.id,
                    verifier_id=verifier.id,
                ))
            if not _safe_relative_path(verifier.cwd, allow_dot=True):
                issues.append(ContinuationQualityIssue(
                    code="verifier_cwd_invalid",
                    severity="blocking",
                    message=f"Verifier {verifier.id} has an unsafe working directory.",
                    requirement_id=requirement.id,
                    verifier_id=verifier.id,
                ))

    for artifact in contract.artifacts:
        if not artifact.required:
            continue
        if not artifact.available or not artifact.sha256:
            issues.append(ContinuationQualityIssue(
                code="required_artifact_unresolved",
                severity="blocking",
                message=(
                    f"Required artifact {artifact.id} is not available with "
                    "verified content."
                ),
                artifact_id=artifact.id,
            ))
            continue
        unknown_requirements = set(artifact.requirement_ids) - requirement_ids
        if unknown_requirements:
            # Normally caught by the typed schema. Retaining this check makes
            # the quality report self-explanatory for data loaded from storage.
            issues.append(ContinuationQualityIssue(
                code="artifact_requirement_unknown",
                severity="blocking",
                message=f"Artifact {artifact.id} references an unknown requirement.",
                artifact_id=artifact.id,
            ))
        path = Path(artifact.path).expanduser()
        if path.is_symlink():
            issues.append(ContinuationQualityIssue(
                code="required_artifact_invalid",
                severity="blocking",
                message=(
                    f"Required artifact {artifact.id} must not be a symbolic link."
                ),
                artifact_id=artifact.id,
            ))
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            issues.append(ContinuationQualityIssue(
                code="required_artifact_missing",
                severity="blocking",
                message=f"Required artifact {artifact.id} is not locally readable.",
                artifact_id=artifact.id,
            ))
            continue
        if not resolved.is_file():
            issues.append(ContinuationQualityIssue(
                code="required_artifact_invalid",
                severity="blocking",
                message=f"Required artifact {artifact.id} is not a regular file.",
                artifact_id=artifact.id,
            ))
            continue
        if _sha256_file(resolved) != artifact.sha256:
            issues.append(ContinuationQualityIssue(
                code="required_artifact_hash_mismatch",
                severity="blocking",
                message=f"Required artifact {artifact.id} has changed since compilation.",
                artifact_id=artifact.id,
            ))

    if provider is not None:
        for check in check_provider_capabilities(provider, contract):
            if not check.supported:
                issues.append(ContinuationQualityIssue(
                    code="provider_capability_missing",
                    severity="blocking",
                    message=check.message,
                ))

    return ContinuationQualityReport(
        launchable=not any(item.severity == "blocking" for item in issues),
        issues=tuple(issues),
        contract_sha256=contract_sha256,
        prompt_sha256=prompt_sha256,
    )


def _check_worker_handoff_shape(
    contract: ContinuationExecutionContract,
    *,
    markdown: str,
    context_name: str,
    issues: list[ContinuationQualityIssue],
    issue_prefix: str = "worker_handoff",
) -> None:
    lead_section = _markdown_section(
        markdown,
        headings=(
            "## Authoritative request",
            "### Authoritative current lead",
        ),
    )
    expected_lead = contract.task.request_verbatim.rstrip("\r\n")
    if expected_lead not in lead_section:
        issues.append(ContinuationQualityIssue(
            code=f"{issue_prefix}_current_lead_missing",
            severity="blocking",
            message=f"{context_name} omits the authoritative current lead.",
        ))

    repository_section = _markdown_section(
        markdown,
        headings=(
            "## Current validated repository state",
            "### Current repository state",
        ),
    )
    repository_values = [
        contract.repository.root,
        contract.repository.branch,
        contract.repository.head_commit,
    ]
    missing_repository_values = [
        str(value)
        for value in repository_values
        if value and str(value) not in repository_section
    ]
    if missing_repository_values:
        issues.append(ContinuationQualityIssue(
            code=f"{issue_prefix}_repository_state_missing",
            severity="blocking",
            message=f"{context_name} omits current repository state.",
        ))

    done_section = _markdown_section(
        markdown,
        headings=(
            "## Definition of done",
            "### Definition of done",
        ),
    )
    if not done_section:
        issues.append(ContinuationQualityIssue(
            code=f"{issue_prefix}_definition_of_done_missing",
            severity="blocking",
            message=f"{context_name} omits the definition of done.",
        ))
    else:
        requirements = {item.id: item for item in contract.requirements}
        for requirement_id in contract.definition_of_done:
            requirement = requirements.get(requirement_id)
            if requirement is None or requirement.text in done_section:
                continue
            issues.append(ContinuationQualityIssue(
                code=f"{issue_prefix}_definition_of_done_incomplete",
                severity="blocking",
                message=(
                    f"{context_name} omits definition-of-done requirement "
                    f"{requirement_id}."
                ),
                requirement_id=requirement_id,
            ))

    if "Reconciliation and unresolved state" not in markdown:
        issues.append(ContinuationQualityIssue(
            code=f"{issue_prefix}_reconciliation_missing",
            severity="blocking",
            message=f"{context_name} omits repository/checkpoint reconciliation.",
        ))


def _markdown_section(
    markdown: str,
    *,
    headings: tuple[str, ...],
) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line not in headings:
            continue
        level = len(line) - len(line.lstrip("#"))
        end = len(lines)
        for candidate_index in range(index + 1, len(lines)):
            candidate = lines[candidate_index]
            match = re.match(r"^(#{1,6})\s+\S", candidate)
            if match and len(match.group(1)) <= level:
                end = candidate_index
                break
        return "\n".join(lines[index + 1:end]).strip()
    return ""


def _looks_like_conversation_dump(value: str) -> bool:
    normalized = value.casefold()
    if any(marker in normalized for marker in (
        "referenced chatgpt conversation",
        '"conversationid"',
        '"conversation":[',
        '"content_type":"text"',
        "chatgpt-conversation://",
    )):
        return True
    json_roles = re.findall(
        r'"role"\s*:\s*"(?:user|assistant|system|developer)"',
        normalized,
    )
    line_roles = re.findall(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:user|assistant|system|developer)\s*:",
        value,
    )
    return (
        len(json_roles) >= 2
        or len(line_roles) >= 2
        or len(re.findall(r"(?m)^\s*#{1,6}\s+\S", value)) >= 3
    )


def _repository_evidence_prompt_line(item: Any) -> str:
    kind = str(getattr(item.kind, "value", item.kind))
    if kind == "symbol_declaration":
        return (
            "- Symbol: "
            f"{_inline_code(item.path)}:{item.start_line}-{item.end_line} — "
            f"{item.symbol_type} {_inline_code(item.symbol_name)}."
        )
    if kind == "test_link":
        return (
            "- Exact test link: "
            f"{_inline_code(item.test_path)} → "
            f"{_inline_code(item.target_path)} "
            f"({item.rule_id} {item.rule_version})."
        )
    return (
        "- Dependency: "
        f"{_inline_code(item.dependency_name)} — "
        f"{_inline_code(item.manifest_path)} "
        f"[{item.dependency_group}]."
    )


def _inline_code(value: Any) -> str:
    text = str(value)
    longest = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    fence = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str, *, allow_dot: bool = False) -> bool:
    normalized = str(value or "").replace("\\", "/")
    if allow_dot and normalized in {"", "."}:
        return True
    path = PurePosixPath(normalized)
    return bool(
        normalized
        and not path.is_absolute()
        and ".." not in path.parts
        and "\x00" not in normalized
    )
