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

FINAL_MANIFEST_KEYS = {
    "schema_version",
    "context_pack_id",
    "objective",
    "created_at",
    "target_model",
    "repo_state",
    "selected_context",
    "excluded_context",
    "risks",
    "verification",
    "stop_conditions",
    "rendering",
}


def load_fixture_expectations(
    fixture_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(fixture_root) if fixture_root else Path(__file__).parent / "fixture_project"
    expected = root / "expected"
    return (
        json.loads((expected / "required_context.json").read_text(encoding="utf-8")),
        json.loads((expected / "forbidden_context.json").read_text(encoding="utf-8")),
    )


def load_fixture_project(fixture_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(fixture_root) if fixture_root else Path(__file__).parent / "fixture_project"
    repo_root = root / "repo"
    source_root = root / "sources"
    expected_root = root / "expected"
    return {
        "root": root,
        "repo_root": repo_root,
        "repo_files": _load_files(repo_root),
        "source_files": _load_files(source_root),
        "expected_sections": (expected_root / "expected_pack_sections.md").read_text(
            encoding="utf-8"
        ),
    }


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
    contract_ready_selected = [item for item in selected if _selected_item_has_contract_shape(item)]
    evidence_backed = sum(1 for item in contract_ready_selected if _has_evidence(item))
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
    has_commands = bool(verification.get("commands")) and all(
        _verification_command_has_contract_shape(command)
        for command in verification.get("commands") or []
    )
    has_acceptance = bool(verification.get("acceptance_criteria")) and all(
        _acceptance_criterion_has_contract_shape(item)
        for item in verification.get("acceptance_criteria") or []
    )

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
    citation_text = " ".join(
        " ".join(
            str(value or "")
            for value in (
                citation.get("source_type"),
                citation.get("source_url"),
                citation.get("quote"),
            )
        )
        for citation in item.get("citations") or []
        if isinstance(citation, dict)
    )
    excluded_citation = item.get("citation") or {}
    return " ".join(
        str(value or "")
        for value in (
            item.get("id"),
            item.get("item_type"),
            item.get("title"),
            item.get("summary"),
            item.get("reason"),
            item.get("reason_detail"),
            item.get("status"),
            citation_text,
            excluded_citation.get("quote") if isinstance(excluded_citation, dict) else "",
            " ".join(item.get("files") or []),
        )
    )


def _terms_match(terms: list[str], text: str) -> bool:
    return all(str(term).lower() in text for term in terms)


def _has_evidence(item: dict[str, Any]) -> bool:
    citations = item.get("citations")
    if not isinstance(citations, list) or not citations:
        return "legacy_component" in str(item.get("inclusion_reason") or "")
    for citation in citations:
        if not isinstance(citation, dict):
            return False
        has_source_ref = any(
            citation.get(key)
            for key in ("source_document_id", "evidence_span_id", "source_url")
        )
        required = (
            citation.get("citation_id"),
            citation.get("source_type"),
            citation.get("quote"),
            citation.get("trust_zone"),
        )
        if not has_source_ref or not all(required):
            return False
    return True


def _selected_item_has_contract_shape(item: dict[str, Any]) -> bool:
    required_keys = {
        "id",
        "item_type",
        "title",
        "summary",
        "status",
        "score",
        "token_cost",
        "inclusion_reason",
        "trust_zone",
        "prompt_injection_risk_score",
        "citations",
    }
    if not required_keys <= set(item):
        return False
    return _has_evidence(item)


def _verification_command_has_contract_shape(command: Any) -> bool:
    if not isinstance(command, dict):
        return False
    return all(
        command.get(key) not in (None, "")
        for key in ("id", "command", "cwd", "purpose", "expected")
    ) and isinstance(command.get("required"), bool)


def _acceptance_criterion_has_contract_shape(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return all(item.get(key) not in (None, "") for key in ("id", "text", "evidence_required"))


def _load_files(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)
