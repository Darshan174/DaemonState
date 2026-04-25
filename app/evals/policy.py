"""Phase 3B accuracy policy and exit criteria."""

from __future__ import annotations

from dataclasses import dataclass

from app.evals.harness import EvalSummary


@dataclass(frozen=True, slots=True)
class EvalPolicy:
    min_total_cases: int
    min_cases_per_domain: int
    required_domains: tuple[str, ...]
    pass_threshold: float
    min_pass_rate: float
    min_retrieval_hit_quality: float
    min_extracted_fact_correctness: float
    min_final_answer_correctness: float
    min_citation_accuracy: float
    min_stale_context_detection: float
    max_confidence_calibration_error: float


PHASE_3B_POLICY = EvalPolicy(
    min_total_cases=30,
    min_cases_per_domain=5,
    required_domains=("pricing", "blocker", "roadmap", "decision", "meeting", "staleness"),
    pass_threshold=0.5,
    min_pass_rate=0.80,
    min_retrieval_hit_quality=0.80,
    min_extracted_fact_correctness=0.80,
    min_final_answer_correctness=0.75,
    min_citation_accuracy=0.80,
    min_stale_context_detection=0.90,
    max_confidence_calibration_error=0.25,
)


def evaluate_exit_criteria(
    summary: EvalSummary,
    *,
    policy: EvalPolicy = PHASE_3B_POLICY,
) -> list[str]:
    failures: list[str] = []
    if summary.total < policy.min_total_cases:
        failures.append(
            f"total_cases {summary.total} < {policy.min_total_cases}"
        )
    if summary.pass_rate < policy.min_pass_rate:
        failures.append(
            f"pass_rate {summary.pass_rate:.2f} < {policy.min_pass_rate:.2f}"
        )
    if summary.average_retrieval_hit_quality < policy.min_retrieval_hit_quality:
        failures.append(
            "retrieval "
            f"{summary.average_retrieval_hit_quality:.2f} < "
            f"{policy.min_retrieval_hit_quality:.2f}"
        )
    if (
        summary.average_extracted_fact_correctness
        < policy.min_extracted_fact_correctness
    ):
        failures.append(
            "extraction "
            f"{summary.average_extracted_fact_correctness:.2f} < "
            f"{policy.min_extracted_fact_correctness:.2f}"
        )
    if summary.average_final_answer_correctness < policy.min_final_answer_correctness:
        failures.append(
            "answer "
            f"{summary.average_final_answer_correctness:.2f} < "
            f"{policy.min_final_answer_correctness:.2f}"
        )
    if summary.average_citation_accuracy < policy.min_citation_accuracy:
        failures.append(
            "citation "
            f"{summary.average_citation_accuracy:.2f} < "
            f"{policy.min_citation_accuracy:.2f}"
        )
    if summary.average_stale_context_detection < policy.min_stale_context_detection:
        failures.append(
            "stale_context "
            f"{summary.average_stale_context_detection:.2f} < "
            f"{policy.min_stale_context_detection:.2f}"
        )
    if (
        summary.confidence_calibration_error
        > policy.max_confidence_calibration_error
    ):
        failures.append(
            "confidence_calibration_error "
            f"{summary.confidence_calibration_error:.2f} > "
            f"{policy.max_confidence_calibration_error:.2f}"
        )

    domain_summary = {item.domain: item for item in summary.domain_summaries}
    for domain in policy.required_domains:
        item = domain_summary.get(domain)
        if item is None:
            failures.append(f"missing_domain {domain}")
            continue
        if item.case_count < policy.min_cases_per_domain:
            failures.append(
                f"domain_case_count[{domain}] {item.case_count} < {policy.min_cases_per_domain}"
            )

    return failures
