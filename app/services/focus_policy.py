from __future__ import annotations


FOCUS_FACT_TYPES = frozenset({"task", "issue", "requirement", "decision", "blocker"})
INELIGIBLE_FOCUS_STATUSES = frozenset({"rejected", "resolved", "superseded"})


def focus_eligibility(fact_type: str | None, status: str | None) -> tuple[bool, str | None]:
    normalized_type = (fact_type or "fact").lower()
    normalized_status = (status or "active").lower()
    if normalized_type not in FOCUS_FACT_TYPES:
        if normalized_type in {"pr", "github_pr"}:
            return (
                False,
                "Pull requests are delivery evidence. Prepare from a linked issue, task, "
                "decision, requirement, or blocker.",
            )
        return False, "This evidence type cannot be used as an agent task."
    if normalized_status in INELIGIBLE_FOCUS_STATUSES:
        return False, f"This {normalized_type} is {normalized_status} and is no longer actionable."
    return True, None
