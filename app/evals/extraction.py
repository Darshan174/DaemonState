from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.processing.extractor import ExtractedFact, Extractor, evaluate_extraction_quality
from app.processing.source_extractors import (
    extract_agent_session,
    extract_github_issue,
    extract_github_pr,
)


@dataclass(frozen=True)
class ExtractionEvalCase:
    id: str
    source_type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    expected_fact_types: tuple[str, ...] = ()
    expected_terms: tuple[str, ...] = ()
    expected_relationship_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionEvalCaseResult:
    id: str
    source_type: str
    passed: bool
    fact_count: int
    relationship_count: int
    warnings: list[str]
    missing_fact_types: list[str]
    missing_terms: list[str]
    missing_relationship_types: list[str]


@dataclass(frozen=True)
class ExtractionEvalReport:
    case_count: int
    passed_count: int
    failed_count: int
    fact_count: int
    relationship_count: int
    warning_count: int
    cases: list[ExtractionEvalCaseResult]

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.case_count if self.case_count else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pass_rate": self.pass_rate,
            "fact_count": self.fact_count,
            "relationship_count": self.relationship_count,
            "warning_count": self.warning_count,
            "cases": [
                {
                    "id": case.id,
                    "source_type": case.source_type,
                    "passed": case.passed,
                    "fact_count": case.fact_count,
                    "relationship_count": case.relationship_count,
                    "warnings": case.warnings,
                    "missing_fact_types": case.missing_fact_types,
                    "missing_terms": case.missing_terms,
                    "missing_relationship_types": case.missing_relationship_types,
                }
                for case in self.cases
            ],
        }


CORE_EXTRACTION_EVAL_CASES: tuple[ExtractionEvalCase, ...] = (
    ExtractionEvalCase(
        id="local-decision-postgres",
        source_type="local",
        content="Decision: Use Postgres and pgvector for production retrieval.",
        metadata={"source_type": "local", "external_id": "eval:local:postgres"},
        expected_fact_types=("decision",),
        expected_terms=("Postgres", "pgvector"),
    ),
    ExtractionEvalCase(
        id="slack-decision-root",
        source_type="slack",
        content="Decision: Ship the Slack OAuth connector behind a feature flag.",
        metadata={
            "source_type": "slack",
            "external_id": "slack:C123:100.1",
            "channel_name": "engineering",
            "author_name": "Darshan",
            "user_id": "U123",
            "ts": "100.1",
        },
        expected_fact_types=("decision", "message"),
        expected_terms=("Slack OAuth", "feature flag", "engineering"),
        expected_relationship_types=("discussed_in", "part_of"),
    ),
    ExtractionEvalCase(
        id="github-issue-blocker",
        source_type="github_issue",
        content=json.dumps({
            "title": "Login page crashes on mobile",
            "body": "Blocker: OAuth callback fails on iOS Safari.",
            "state": "open",
            "number": 42,
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/acme/app/issues/42",
        }),
        metadata={"source_type": "github_issue", "repository": "acme/app"},
        expected_fact_types=("issue", "blocker"),
        expected_terms=("Login page crashes", "OAuth callback"),
        expected_relationship_types=("part_of",),
    ),
    ExtractionEvalCase(
        id="github-pr-solves-issue",
        source_type="github_pr",
        content=json.dumps({
            "title": "Fix OAuth redirect on iOS",
            "body": "Fixes #42\nChanged files: app/auth/callback.py",
            "state": "open",
            "number": 7,
            "html_url": "https://github.com/acme/app/pull/7",
            "head": {"ref": "fix/oauth-ios"},
        }),
        metadata={"source_type": "github_pr", "repository": "acme/app"},
        expected_fact_types=("pr",),
        expected_terms=("OAuth redirect", "app/auth/callback.py"),
        expected_relationship_types=("fixes", "solves"),
    ),
    ExtractionEvalCase(
        id="agent-session-handoff",
        source_type="agent_session",
        content=(
            "Decision: keep connector sync idempotent.\n"
            "Task: add regression tests for duplicate sync jobs.\n"
            "Risk: stale worker jobs can overwrite fresh status."
        ),
        metadata={"source_type": "agent_session", "connector_type": "codex"},
        expected_fact_types=("session_root", "decision", "task", "risk"),
        expected_terms=("idempotent", "duplicate sync jobs", "stale worker jobs"),
        expected_relationship_types=("generated_by_agent",),
    ),
)


def _generated_realistic_eval_cases() -> tuple[ExtractionEvalCase, ...]:
    topics = (
        "auth callback", "billing sync", "context pack", "graph inspector",
        "agent handoff", "Slack import", "GitHub review", "Google Drive import",
        "Gmail thread", "connector status", "rate limit", "workspace scope",
        "source provenance", "relationship evidence", "demo seed",
        "MCP query", "retrieval trace", "embedding config", "sync worker",
        "dead letter job", "OAuth setup", "frontend guardrail", "graph minimap",
        "stale decision", "risk digest",
    )
    cases: list[ExtractionEvalCase] = []

    for idx, topic in enumerate(topics, start=1):
        cases.append(ExtractionEvalCase(
            id=f"local-mixed-{idx:02d}",
            source_type="local",
            content=(
                f"Decision: Keep {topic} source-backed before release.\n"
                f"Task: Add {topic} regression tests.\n"
                f"Risk: {topic} can drift without source evidence."
            ),
            metadata={"source_type": "local", "external_id": f"eval:local:{idx}"},
            expected_fact_types=("decision", "task", "blocker"),
            expected_terms=(topic, "source-backed", "regression tests"),
        ))

    for idx, topic in enumerate(topics[:20], start=1):
        cases.append(ExtractionEvalCase(
            id=f"github-issue-{idx:02d}",
            source_type="github_issue",
            content=json.dumps({
                "title": f"{topic.title()} blocks launch",
                "body": f"Blocker: {topic} fails without source evidence.",
                "state": "open",
                "number": 100 + idx,
                "labels": [{"name": "bug"}],
                "html_url": f"https://github.com/acme/context-engine/issues/{100 + idx}",
            }),
            metadata={"source_type": "github_issue", "repository": "acme/context-engine"},
            expected_fact_types=("issue", "blocker"),
            expected_terms=(topic, "source evidence"),
            expected_relationship_types=("part_of",),
        ))

    for idx, topic in enumerate(topics[:20], start=1):
        issue_num = 100 + idx
        cases.append(ExtractionEvalCase(
            id=f"github-pr-{idx:02d}",
            source_type="github_pr",
            content=json.dumps({
                "title": f"Fix {topic}",
                "body": (
                    f"Fixes #{issue_num}\n"
                    f"Task: verify {topic} smoke coverage."
                ),
                "state": "open",
                "number": 200 + idx,
                "html_url": f"https://github.com/acme/context-engine/pull/{200 + idx}",
                "changed_files": [{"filename": f"app/{topic.replace(' ', '_')}.py"}],
            }),
            metadata={"source_type": "github_pr", "repository": "acme/context-engine"},
            expected_fact_types=("pr", "changed_file", "task"),
            expected_terms=(topic, "smoke coverage"),
            expected_relationship_types=("fixes", "solves", "touches_file", "part_of"),
        ))

    for idx, topic in enumerate(topics[:20], start=1):
        cases.append(ExtractionEvalCase(
            id=f"agent-session-{idx:02d}",
            source_type="agent_session",
            content=(
                f"# {topic.title()} session\n"
                f"Decision: keep {topic} scoped to source evidence.\n"
                f"Task: add {topic} context pack test.\n"
                f"Risk: {topic} handoff is stale."
            ),
            metadata={
                "source_type": "agent_session",
                "connector_type": "codex",
                "session_id": f"eval-session-{idx}",
                "tool": "codex",
            },
            expected_fact_types=("session_root", "decision", "task", "risk"),
            expected_terms=(topic, "source evidence", "context pack test"),
            expected_relationship_types=("generated_by_agent",),
        ))

    for idx, topic in enumerate(topics[:15], start=1):
        cases.append(ExtractionEvalCase(
            id=f"slack-thread-{idx:02d}",
            source_type="slack",
            content=(
                f"Decision: Ship {topic} only with visible provenance.\n"
                f"Task: confirm {topic} owner before merge.\n"
                f"Risk: {topic} has an unresolved review question."
            ),
            metadata={
                "source_type": "slack",
                "external_id": f"slack:C{idx}:100.{idx}",
                "channel_name": "engineering",
                "author_name": "Darshan",
                "user_id": f"U{idx}",
                "ts": f"100.{idx}",
            },
            expected_fact_types=("decision", "task", "blocker"),
            expected_terms=(topic, "visible provenance", "unresolved review"),
        ))

    return tuple(cases)


DEFAULT_EXTRACTION_EVAL_CASES: tuple[ExtractionEvalCase, ...] = (
    CORE_EXTRACTION_EVAL_CASES + _generated_realistic_eval_cases()
)


def run_extraction_eval(
    cases: tuple[ExtractionEvalCase, ...] | list[ExtractionEvalCase] = DEFAULT_EXTRACTION_EVAL_CASES,
) -> ExtractionEvalReport:
    results: list[ExtractionEvalCaseResult] = []
    total_facts = 0
    total_relationships = 0
    total_warnings = 0

    for case in cases:
        facts = _extract_case(case)
        relationship_types = [
            relationship.relationship_type
            for fact in facts
            for relationship in fact.relationships
        ]
        report = evaluate_extraction_quality(facts)
        missing_fact_types = _missing(case.expected_fact_types, [fact.fact_type for fact in facts])
        haystack = "\n".join(
            [
                *(fact.name for fact in facts),
                *(fact.value for fact in facts),
                *(fact.excerpt or "" for fact in facts),
            ]
        ).lower()
        missing_terms = [
            term for term in case.expected_terms
            if term.lower() not in haystack
        ]
        missing_relationship_types = _missing(case.expected_relationship_types, relationship_types)
        warnings = _quality_warnings(report)
        passed = not (missing_fact_types or missing_terms or missing_relationship_types or warnings)
        relationship_count = len(relationship_types)
        total_facts += len(facts)
        total_relationships += relationship_count
        total_warnings += len(warnings)
        results.append(ExtractionEvalCaseResult(
            id=case.id,
            source_type=case.source_type,
            passed=passed,
            fact_count=len(facts),
            relationship_count=relationship_count,
            warnings=warnings,
            missing_fact_types=missing_fact_types,
            missing_terms=missing_terms,
            missing_relationship_types=missing_relationship_types,
        ))

    passed_count = sum(1 for result in results if result.passed)
    return ExtractionEvalReport(
        case_count=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        fact_count=total_facts,
        relationship_count=total_relationships,
        warning_count=total_warnings,
        cases=results,
    )


def _extract_case(case: ExtractionEvalCase) -> list[ExtractedFact]:
    metadata = {"source_type": case.source_type, **case.metadata}
    if case.source_type == "github_issue":
        return extract_github_issue(case.content, metadata)
    if case.source_type == "github_pr":
        return extract_github_pr(case.content, metadata)
    if case.source_type == "agent_session":
        return extract_agent_session(case.content, metadata)
    return Extractor()._regex_extract(case.content, metadata)


def _missing(expected: tuple[str, ...], actual: list[str]) -> list[str]:
    actual_set = set(actual)
    return [item for item in expected if item not in actual_set]


def _quality_warnings(report) -> list[str]:
    warnings: list[str] = []
    if report.low_confidence_count:
        warnings.append(f"{report.low_confidence_count} low-confidence facts")
    if report.missing_provenance_count:
        warnings.append(f"{report.missing_provenance_count} facts missing provenance")
    if report.missing_excerpt_count:
        warnings.append(f"{report.missing_excerpt_count} facts missing excerpts")
    if report.missing_relationship_evidence_count:
        warnings.append(f"{report.missing_relationship_evidence_count} relationships missing evidence")
    if report.duplicate_fact_count:
        warnings.append(f"{report.duplicate_fact_count} duplicate facts")
    return warnings
