"""CI/local regression runner for the Phase 3B eval policy."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from app.database import AsyncSessionLocal
from app.evals.baseline import NaiveRagBaseline
from app.evals.gold_set import load_default_cases
from app.evals.harness import StartupEvalHarness
from app.evals.policy import PHASE_3B_POLICY, evaluate_exit_criteria
from app.evals.runner import summary_to_json
from app.schemas.query import QueryFilters
from app.services.query_service import QueryResourceNotFoundError, QueryService


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Phase 3B eval regressions against a seeded workspace."
    )
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--domains", nargs="+", default=None)
    parser.add_argument("--case-ids", nargs="+", default=None)
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=PHASE_3B_POLICY.pass_threshold,
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


async def _run(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    cases = load_default_cases(domains=args.domains, ids=args.case_ids)
    if not cases:
        payload = {
            "status": "failed",
            "failures": ["no_eval_cases_matched_requested_filters"],
        }
        return payload, 2

    async with AsyncSessionLocal() as session:
        try:
            summary = await StartupEvalHarness(
                QueryService(session),
                baseline_runner=NaiveRagBaseline(session),
                pass_threshold=args.pass_threshold,
            ).run(
                workspace_id=args.workspace_id,
                cases=cases,
                filters=QueryFilters(),
            )
        except QueryResourceNotFoundError:
            payload = {
                "status": "failed",
                "failures": [f"workspace_not_found {args.workspace_id}"],
            }
            return payload, 2

    failures = evaluate_exit_criteria(summary)
    payload = summary_to_json(summary)
    payload["criteria"] = {
        "min_total_cases": PHASE_3B_POLICY.min_total_cases,
        "min_cases_per_domain": PHASE_3B_POLICY.min_cases_per_domain,
        "required_domains": list(PHASE_3B_POLICY.required_domains),
        "pass_threshold": args.pass_threshold,
        "min_pass_rate": PHASE_3B_POLICY.min_pass_rate,
        "min_retrieval_hit_quality": PHASE_3B_POLICY.min_retrieval_hit_quality,
        "min_extracted_fact_correctness": PHASE_3B_POLICY.min_extracted_fact_correctness,
        "min_final_answer_correctness": PHASE_3B_POLICY.min_final_answer_correctness,
        "min_citation_accuracy": PHASE_3B_POLICY.min_citation_accuracy,
        "min_stale_context_detection": PHASE_3B_POLICY.min_stale_context_detection,
        "max_confidence_calibration_error": PHASE_3B_POLICY.max_confidence_calibration_error,
    }
    payload["status"] = "passed" if not failures else "failed"
    payload["failures"] = failures
    return payload, (0 if not failures else 1)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    payload, exit_code = asyncio.run(_run(args))

    if args.json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_report_payload(payload))
    return exit_code


def format_report_payload(payload: dict[str, object]) -> str:
    if "pass_rate" not in payload:
        failures = payload.get("failures") or []
        return "\n".join(
            [
                "Phase 3B eval regression",
                f"Status: {payload['status']}",
                *(f" - {item}" for item in failures),
            ]
        )
    summary = ["Phase 3B eval regression"]
    summary.append(f"Status: {payload['status']}")
    summary.append(
        f"Pass rate: {payload['pass_rate']:.0%} "
        f"({payload['passed']}/{payload['total']})"
    )
    summary.append(
        "Averages: "
        f"retrieval={payload['average_retrieval_hit_quality']:.2f}, "
        f"extraction={payload['average_extracted_fact_correctness']:.2f}, "
        f"answer={payload['average_final_answer_correctness']:.2f}, "
        f"citation={payload['average_citation_accuracy']:.2f}, "
        f"stale={payload['average_stale_context_detection']:.2f}, "
        f"lift={payload['average_context_answer_lift']:+.2f}, "
        f"calibration={payload['confidence_calibration_error']:.2f}"
    )
    failures = payload.get("failures") or []
    if failures:
        summary.append("Failures:")
        summary.extend(f" - {item}" for item in failures)
    return "\n".join(summary)


if __name__ == "__main__":
    raise SystemExit(main())
