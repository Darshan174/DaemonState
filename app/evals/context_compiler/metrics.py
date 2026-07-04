from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONTEXT_COMPILER_METRICS = (
    "context_recall",
    "context_precision",
    "evidence_coverage",
    "stale_context_rate",
    "conflict_detection_rate",
    "token_efficiency",
    "verification_success",
)


def load_fixture_expectations(
    fixture_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(fixture_root) if fixture_root else Path(__file__).parent / "fixture_project"
    expected = root / "expected"
    return (
        json.loads((expected / "required_context.json").read_text(encoding="utf-8")),
        json.loads((expected / "forbidden_context.json").read_text(encoding="utf-8")),
    )


def evaluate_context_pack_manifest(
    manifest: dict[str, Any],
    required_context: dict[str, Any],
    forbidden_context: dict[str, Any],
) -> dict[str, float]:
    selected = list(manifest.get("selected_context") or [])
    excluded = list(manifest.get("excluded_context") or [])
    verification = manifest.get("verification") or {}
    budget = int((manifest.get("target_model") or {}).get("context_budget_tokens") or 0)
    selected_text = "\n".join(_item_text(item) for item in selected).lower()
    excluded_text = "\n".join(_item_text(item) for item in excluded).lower()

    required_items = list(required_context.get("items") or [])
    forbidden_items = list(forbidden_context.get("items") or [])
    required_hits = sum(
        1 for item in required_items
        if _terms_match(item.get("must_include_terms", []), selected_text)
    )
    forbidden_selected = sum(
        1 for item in forbidden_items
        if _terms_match(item.get("must_exclude_terms", []), selected_text)
    )
    forbidden_excluded = sum(
        1 for item in forbidden_items
        if _terms_match(item.get("must_exclude_terms", []), excluded_text)
    )
    selected_count = len(selected)
    evidence_backed = sum(1 for item in selected if _has_evidence(item))
    stale_selected = sum(
        1 for item in selected
        if str(item.get("status") or "").lower() in {"stale", "superseded", "rejected"}
    )
    expected_conflicts = list(required_context.get("expected_conflicts") or [])
    risks_text = json.dumps(manifest.get("risks") or []).lower()
    conflict_hits = sum(
        1 for item in expected_conflicts
        if _terms_match(item.get("terms", []), selected_text + "\n" + risks_text)
    )
    used_tokens = sum(int(item.get("token_cost") or 0) for item in selected)
    has_commands = bool(verification.get("commands"))
    has_acceptance = bool(verification.get("acceptance_criteria"))

    return {
        "context_recall": _ratio(required_hits, len(required_items)),
        "context_precision": _ratio(max(0, selected_count - forbidden_selected), selected_count),
        "evidence_coverage": _ratio(evidence_backed, selected_count),
        "stale_context_rate": _ratio(stale_selected + forbidden_selected, selected_count),
        "conflict_detection_rate": _ratio(conflict_hits + forbidden_excluded, len(expected_conflicts) + len(forbidden_items)),
        "token_efficiency": 1.0 if not budget or used_tokens <= budget else round(budget / used_tokens, 4),
        "verification_success": 1.0 if has_commands and has_acceptance else 0.0,
    }


def _item_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            item.get("id"),
            item.get("title"),
            item.get("summary"),
            item.get("excerpt"),
            item.get("reason"),
            " ".join(item.get("file_paths") or []),
        )
    )


def _terms_match(terms: list[str], text: str) -> bool:
    return all(str(term).lower() in text for term in terms)


def _has_evidence(item: dict[str, Any]) -> bool:
    source = item.get("source") or {}
    if source.get("document_id") or source.get("url"):
        return True
    if item.get("excerpt"):
        return True
    return str(item.get("type") or "").startswith("repo_")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)
