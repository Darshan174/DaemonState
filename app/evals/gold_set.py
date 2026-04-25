"""Expanded gold-set questions for startup-context regression checks.

The canonical fixture source is ``fixtures.jsonl`` (one JSON object per line).
``load_fixtures()`` parses it into ``EvalCase`` objects grouped by domain.
``STARTUP_GOLD_SET`` is the original hand-curated tuple kept for backward
compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from app.evals.harness import EvalCase


_FIXTURES_PATH = Path(__file__).with_name("fixtures.jsonl")


def load_fixtures(
    *,
    domains: Sequence[str] | None = None,
    ids: Sequence[str] | None = None,
) -> list[EvalCase]:
    """Load eval cases from ``fixtures.jsonl``.

    Parameters
    ----------
    domains:
        If given, only return cases whose ``domain`` field is in this list.
    ids:
        If given, only return cases whose ``id`` field is in this list.
    """
    cases: list[EvalCase] = []
    domain_set = set(domains) if domains else None
    id_set = set(ids) if ids else None

    with _FIXTURES_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if domain_set is not None and row.get("domain") not in domain_set:
                continue
            if id_set is not None and row.get("id") not in id_set:
                continue
            cases.append(
                EvalCase(
                    question=row["question"],
                    expected_answer_substrings=tuple(
                        row.get("expected_answer_substrings", ())
                    ),
                    expected_component_names=tuple(
                        row.get("expected_component_names", ())
                    ),
                    expected_source_types=tuple(
                        row.get("expected_source_types", ())
                    ),
                    expected_source_external_ids=tuple(
                        row.get("expected_source_external_ids", ())
                    ),
                    excluded_source_external_ids=tuple(
                        row.get("excluded_source_external_ids", ())
                    ),
                    expected_freshness=row.get("expected_freshness"),
                    case_id=row.get("id", ""),
                    domain=row.get("domain", ""),
                )
            )
    return cases


def load_default_cases(
    *,
    domains: Sequence[str] | None = None,
    ids: Sequence[str] | None = None,
) -> list[EvalCase]:
    """Load the full JSONL fixture set, falling back to the legacy tuple."""
    cases = load_fixtures(domains=domains, ids=ids)
    if cases:
        return cases
    if domains or ids:
        return []
    return list(STARTUP_GOLD_SET)


# Original hand-curated gold set (backward compatible).
STARTUP_GOLD_SET: tuple[EvalCase, ...] = (
    EvalCase(
        question="What is our enterprise pricing?",
        expected_answer_substrings=("$600/seat",),
        expected_component_names=("Enterprise Plan",),
        expected_source_types=("notion", "slack"),
        expected_source_external_ids=(
            "notion-enterprise-plan",
            "slack-enterprise-plan",
        ),
        expected_freshness="current",
        case_id="pricing-001",
        domain="pricing",
    ),
    EvalCase(
        question="What is the starter plan price?",
        expected_answer_substrings=("$29/mo",),
        expected_component_names=("Starter Plan",),
        expected_source_types=("notion",),
        expected_source_external_ids=("notion-starter-plan",),
        expected_freshness="current",
        case_id="pricing-002",
        domain="pricing",
    ),
    EvalCase(
        question="What blockers are active?",
        expected_answer_substrings=("engineering bandwidth",),
        expected_component_names=("SSO Blocker",),
        expected_source_types=("slack", "zoom"),
        case_id="blocker-001",
        domain="blocker",
    ),
    EvalCase(
        question="Why is SSO blocked?",
        expected_answer_substrings=("blocked", "engineering bandwidth"),
        expected_component_names=("SSO Blocker",),
        expected_source_types=("slack", "zoom"),
        case_id="blocker-002",
        domain="blocker",
    ),
    EvalCase(
        question="What decisions have we made about pricing?",
        expected_answer_substrings=("Enterprise", "$600/seat"),
        expected_component_names=("Enterprise Plan",),
        expected_source_types=("notion", "slack"),
        case_id="pricing-003",
        domain="pricing",
    ),
    EvalCase(
        question="What did we decide about onboarding?",
        expected_answer_substrings=("onboarding", "ship"),
        expected_component_names=("Decision in Weekly Product Review",),
        expected_source_types=("zoom",),
        case_id="decision-001",
        domain="decision",
    ),
    EvalCase(
        question="What is on the roadmap?",
        expected_answer_substrings=("Q3",),
        expected_component_names=("SSO Launch Target",),
        expected_source_types=("notion",),
        case_id="roadmap-001",
        domain="roadmap",
    ),
    EvalCase(
        question="What is the SSO launch target?",
        expected_answer_substrings=("Q3",),
        expected_component_names=("SSO Launch Target",),
        expected_source_types=("notion",),
        case_id="roadmap-002",
        domain="roadmap",
    ),
    EvalCase(
        question="What are the current blockers from meetings?",
        expected_answer_substrings=("legal approval",),
        expected_component_names=("Blocker in Weekly Product Review",),
        expected_source_types=("zoom",),
        case_id="blocker-003",
        domain="blocker",
    ),
    EvalCase(
        question="What did the latest meeting say about launch timing?",
        expected_answer_substrings=("next Tuesday",),
        expected_component_names=("Decision in Weekly Product Review",),
        expected_source_types=("zoom",),
        case_id="decision-002",
        domain="decision",
    ),
)
