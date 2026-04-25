"""Standalone eval runner — ``python -m app.evals.runner``.

Prints a clear pass/fail report to stdout.  Exit code 0 on success, 1 on
any failure.  Suitable for local use and CI pipelines.

Usage
-----
    # Run all domains from the first workspace
    python -m app.evals.runner

    # Run specific domains
    python -m app.evals.runner --domains pricing blocker

    # Run against a specific workspace (CI-friendly)
    python -m app.evals.runner --workspace-id <uuid> --json

    # Set custom pass threshold
    python -m app.evals.runner --threshold 0.6

    # JSON output (for CI parsing)
    python -m app.evals.runner --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence
from uuid import UUID

from app.evals.harness import EvalSummary


def format_report(summary: EvalSummary) -> str:
    """Human-readable eval report."""
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("  CONTEXT ENGINE — EVAL REPORT")
    lines.append("=" * 72)
    lines.append("")

    # Per-case results
    for r in summary.cases:
        status = "PASS" if r.passed else "FAIL"
        tag = f"[{r.domain}]" if r.domain else ""
        lines.append(
            f"  [{status}] {tag} {r.case_id or '?'}: {r.question}"
        )
        lines.append(
            f"         retrieval={r.retrieval_hit_quality:.2f}  "
            f"extraction={r.extracted_fact_correctness:.2f}  "
            f"answer={r.final_answer_correctness:.2f}  "
            f"citation={r.citation_accuracy:.2f}  "
            f"stale={r.stale_context_detection:.2f}  "
            f"lift={r.context_answer_lift:+.2f}"
        )
        if r.detail:
            lines.append(f"         >> {r.detail}")
        lines.append("")

    # Domain summaries
    lines.append("-" * 72)
    lines.append("  DOMAIN SUMMARY")
    lines.append("-" * 72)
    for ds in summary.domain_summaries:
        lines.append(
            f"  {ds.domain:<12}  cases={ds.case_count}  "
            f"retrieval={ds.avg_retrieval:.2f}  "
            f"extraction={ds.avg_extraction:.2f}  "
            f"answer={ds.avg_answer:.2f}  "
            f"citation={ds.avg_citation:.2f}  "
            f"stale={ds.avg_staleness:.2f}  "
            f"lift={ds.avg_context_lift:+.2f}  "
            f"pass_rate={ds.pass_rate:.0%}"
        )
    lines.append("")

    # Overall
    lines.append("-" * 72)
    lines.append("  OVERALL")
    lines.append("-" * 72)
    lines.append(f"  Total:      {summary.total}")
    lines.append(f"  Passed:     {summary.passed_count}")
    lines.append(f"  Failed:     {summary.failed_count}")
    lines.append(f"  Pass rate:  {summary.pass_rate:.0%}")
    lines.append(f"  Threshold:  {summary.pass_threshold:.2f}")
    lines.append(
        f"  Avg retrieval:   {summary.average_retrieval_hit_quality:.2f}"
    )
    lines.append(
        f"  Avg extraction:  {summary.average_extracted_fact_correctness:.2f}"
    )
    lines.append(
        f"  Avg answer:      {summary.average_final_answer_correctness:.2f}"
    )
    lines.append(
        f"  Avg citation:    {summary.average_citation_accuracy:.2f}"
    )
    lines.append(
        f"  Avg staleness:   {summary.average_stale_context_detection:.2f}"
    )
    lines.append(
        f"  Naive answer:    {summary.average_naive_answer_correctness:.2f}"
    )
    lines.append(
        f"  Context lift:    {summary.average_context_answer_lift:+.2f}"
    )
    lines.append(
        f"  Calibration ECE: {summary.confidence_calibration_error:.2f}"
    )
    lines.append("")

    verdict = "ALL PASSED" if summary.all_passed else "FAILURES DETECTED"
    lines.append(f"  Result: {verdict}")
    lines.append("=" * 72)
    lines.append("")
    return "\n".join(lines)


def summary_to_json(summary: EvalSummary) -> dict:
    """Serialize EvalSummary to a JSON-safe dict."""
    blockers = [
        {
            "case_id": r.case_id,
            "domain": r.domain,
            "question": r.question,
            "detail": r.detail or "Eval case failed",
        }
        for r in summary.cases
        if not r.passed
    ]
    return {
        "status": "passed" if summary.all_passed else "failed",
        "total": summary.total,
        "passed": summary.passed_count,
        "failed": summary.failed_count,
        "pass_rate": summary.pass_rate,
        "pass_threshold": summary.pass_threshold,
        "average_retrieval_hit_quality": summary.average_retrieval_hit_quality,
        "average_extracted_fact_correctness": summary.average_extracted_fact_correctness,
        "average_final_answer_correctness": summary.average_final_answer_correctness,
        "average_citation_accuracy": summary.average_citation_accuracy,
        "average_stale_context_detection": summary.average_stale_context_detection,
        "average_naive_answer_correctness": summary.average_naive_answer_correctness,
        "average_context_answer_lift": summary.average_context_answer_lift,
        "confidence_calibration_error": summary.confidence_calibration_error,
        "all_passed": summary.all_passed,
        "blockers": blockers,
        "domains": [
            {
                "domain": ds.domain,
                "case_count": ds.case_count,
                "avg_retrieval": ds.avg_retrieval,
                "avg_extraction": ds.avg_extraction,
                "avg_answer": ds.avg_answer,
                "avg_citation": ds.avg_citation,
                "avg_staleness": ds.avg_staleness,
                "avg_context_lift": ds.avg_context_lift,
                "pass_rate": ds.pass_rate,
            }
            for ds in summary.domain_summaries
        ],
        "cases": [
            {
                "case_id": r.case_id,
                "domain": r.domain,
                "question": r.question,
                "predicted_confidence": r.predicted_confidence,
                "retrieval_hit_quality": r.retrieval_hit_quality,
                "extracted_fact_correctness": r.extracted_fact_correctness,
                "final_answer_correctness": r.final_answer_correctness,
                "citation_accuracy": r.citation_accuracy,
                "stale_context_detection": r.stale_context_detection,
                "naive_answer_correctness": r.naive_answer_correctness,
                "context_answer_lift": r.context_answer_lift,
                "passed": r.passed,
                "detail": r.detail,
            }
            for r in summary.cases
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Context Engine eval runner",
    )
    parser.add_argument(
        "--workspace-id",
        type=UUID,
        default=None,
        help="Explicit workspace UUID. If omitted, uses the first workspace in the database.",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=None,
        help="Only run cases from these domains (pricing, blocker, roadmap, decision, meeting, staleness)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Per-metric pass threshold (default: 0.5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON instead of human-readable report",
    )
    return parser


async def _run(
    workspace_id: UUID | None,
    domains: Sequence[str] | None,
    threshold: float,
) -> EvalSummary:
    """Execute the eval harness against a live database."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.evals.baseline import NaiveRagBaseline
    from app.evals.gold_set import load_default_cases
    from app.evals.harness import StartupEvalHarness
    from app.models.user import Workspace
    from app.services.query_service import QueryService

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            session = AsyncSession(bind=conn)
            try:
                # Find the first workspace
                from sqlalchemy import select

                workspace = None
                if workspace_id is not None:
                    workspace = await session.scalar(
                        select(Workspace).where(Workspace.id == workspace_id).limit(1)
                    )
                else:
                    workspace = await session.scalar(select(Workspace).limit(1))
                if workspace is None:
                    print("ERROR: No workspace found in the database.", file=sys.stderr)
                    sys.exit(2)

                cases = load_default_cases(domains=domains)

                if not cases:
                    print("ERROR: No eval cases matched the filters.", file=sys.stderr)
                    sys.exit(2)

                harness = StartupEvalHarness(
                    QueryService(session),
                    baseline_runner=NaiveRagBaseline(session),
                    pass_threshold=threshold,
                )
                summary = await harness.run(
                    workspace_id=workspace.id,
                    cases=cases,
                )
                return summary
            finally:
                await session.close()
    finally:
        await engine.dispose()


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    summary = asyncio.run(_run(args.workspace_id, args.domains, args.threshold))

    if args.json_output:
        print(json.dumps(summary_to_json(summary), indent=2))
    else:
        print(format_report(summary))

    sys.exit(0 if summary.all_passed else 1)


if __name__ == "__main__":
    main()
