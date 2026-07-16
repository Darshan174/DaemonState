from __future__ import annotations

import json
import hashlib
import math
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
    "citation_validity",
    "stale_leakage",
    "rendered_budget_compliance",
    "retrieval_relevance",
)

FINAL_MANIFEST_KEYS = {
    "schema_version",
    "compiler",
    "context_pack_id",
    "objective",
    "created_at",
    "workspace_id",
    "input_fingerprint",
    "target_model",
    "execution_policy",
    "repo_state",
    "selected_context",
    "excluded_context",
    "risks",
    "uncertainties",
    "implementation_plan",
    "verification",
    "stop_conditions",
    "token_accounting",
    "context_health",
    "persistence",
    "rendering",
    "lockfile",
}


async def evaluate_compiler_fixture(
    compiler: Any,
    *,
    fixture_root: str | Path | None = None,
    objective: str = "finish GitHub connector pagination and add tests",
    token_budget: int = 4000,
    source_documents: dict[str, str] | None = None,
) -> tuple[Any, dict[str, float]]:
    """Invoke the real compiler and score its emitted artifact.

    This is intentionally an evidence-producing seam, not a claim that one
    model performs better than another.
    """
    fixture = load_fixture_project(fixture_root)
    required, forbidden = load_fixture_expectations(fixture_root)
    result = await compiler.compile_context_pack(
        objective,
        repo_path=str(fixture["repo_root"]),
        target_model="qwen2.5-coder-7b",
        token_budget=token_budget,
        persist=False,
    )
    metrics = evaluate_context_pack_manifest(
        result.manifest,
        required,
        forbidden,
        markdown=result.markdown,
        source_documents=source_documents,
    )
    return result, metrics


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
    *,
    markdown: str | None = None,
    source_documents: dict[str, str] | None = None,
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
    citations = [
        citation
        for item in selected
        for citation in item.get("citations") or []
        if isinstance(citation, dict)
    ]
    valid_citations = sum(
        1
        for citation in citations
        if _citation_is_valid(citation, manifest, source_documents)
    )
    rendering = manifest.get("rendering") or {}
    rendered_tokens = int(rendering.get("estimated_tokens") or 0)
    if markdown is not None:
        rendered_tokens = max(1, math.ceil(len(markdown) / 4))
    rendered_budget_ok = bool(
        budget
        and rendered_tokens <= budget
        and (markdown is None or rendering.get("markdown_sha256") == _sha256(markdown))
    )

    return {
        "context_recall": _ratio(required_hits, len(required_items)),
        "context_precision": _ratio(max(0, selected_count - forbidden_selected), selected_count),
        "evidence_coverage": _ratio(evidence_backed, selected_count),
        "stale_context_rate": _ratio(stale_selected + forbidden_selected, selected_count),
        "conflict_detection_rate": _ratio(conflict_hits + forbidden_excluded, len(expected_conflicts) + len(forbidden_items)),
        "token_efficiency": 1.0 if not budget or used_tokens <= budget else round(budget / used_tokens, 4),
        "verification_success": 1.0 if has_commands and has_acceptance else 0.0,
        "citation_validity": _ratio(valid_citations, len(citations)),
        "stale_leakage": _ratio(stale_selected + forbidden_selected, selected_count),
        "rendered_budget_compliance": 1.0 if rendered_budget_ok else 0.0,
        "retrieval_relevance": _ratio(required_hits, len(required_items)),
    }


def _citation_is_valid(
    citation: dict[str, Any],
    manifest: dict[str, Any],
    source_documents: dict[str, str] | None,
) -> bool:
    source_type = str(citation.get("source_type") or "")
    quote = str(citation.get("quote") or "")
    if not citation.get("citation_id") or not quote:
        return False
    evidence_span_id = citation.get("evidence_span_id")
    if evidence_span_id:
        if citation.get("validated") is not True:
            return False
        source_id = str(citation.get("source_document_id") or "")
        if source_documents is None:
            return bool(
                source_id
                and citation.get("start_char") is not None
                and citation.get("end_char") is not None
                and citation.get("text_sha256")
            )
        content = source_documents.get(source_id)
        if content is None:
            return False
        start = citation.get("start_char")
        end = citation.get("end_char")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if start < 0 or end <= start or end > len(content):
            return False
        exact = content[start:end]
        normalized_exact = " ".join(exact.split())
        normalized_quote = " ".join(quote.split())
        quote_matches = (
            normalized_exact == normalized_quote
            or (
                normalized_quote.endswith("...")
                and normalized_exact.startswith(normalized_quote[:-3].rstrip())
            )
        )
        return quote_matches and _sha256(exact) == citation.get("text_sha256")
    if source_type == "repo_file":
        path = str(citation.get("source_url") or "")
        file_ref = next(
            (
                ref
                for item in manifest.get("selected_context") or []
                for ref in item.get("file_refs") or []
                if ref.get("path") == path
            ),
            None,
        )
        if not file_ref or not file_ref.get("sha256"):
            return False
        repo_root = Path(str((manifest.get("repo_state") or {}).get("repo_path") or ""))
        file_path = repo_root / path
        return file_path.is_file() and _sha256_bytes(file_path.read_bytes()) == file_ref["sha256"]
    return source_type in {"repo_index", "repo_state", "task_contract", "user_task"}


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
    loaded: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(
            part == "__pycache__" or part.startswith(".") for part in relative.parts
        ):
            continue
        try:
            loaded[str(relative)] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Eval fixtures model source context. Generated bytecode and other
            # binary artifacts are not candidate context and must not make the
            # fixture dependent on local tooling state.
            continue
    return loaded


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
