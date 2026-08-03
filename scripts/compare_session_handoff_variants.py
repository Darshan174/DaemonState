#!/usr/bin/env python3
"""Run a paired, read-only comparison of legacy and compact handoffs.

The benchmark uses the same saved checkpoint and typed handoff contract for
both renderers. It never stages a desktop handoff, starts a provider turn, or
writes experiment results to the application database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import json
import re
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models import Workspace
from app.services.access import AccessScope
from app.services.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    build_session_handoff_contract,
    checkpoint_to_dict,
    list_checkpoints,
    render_session_handoff,
    resolve_session_handoff_attachment_descriptors,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
    session_handoff_render_issues,
)


VARIANTS = ("legacy_v1", "compact_v2")
ACTION_HEADINGS = {
    "legacy_v1": "## Exact next action",
    "compact_v2": "## Start here",
}
DONE_HEADINGS = {
    "legacy_v1": "## Acceptance criteria",
    "compact_v2": "## Done when",
}
STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "for",
    "from", "in", "is", "it", "of", "on", "or", "that", "the", "then",
    "this", "to", "with",
})


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    provider: str
    contract: dict[str, Any]
    request_verbatim: str
    supporting_context: tuple[dict[str, str], ...]
    prompts: dict[str, str]
    render_issues: dict[str, tuple[str, ...]]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare legacy_v1 and compact_v2 on identical saved checkpoints."
        )
    )
    parser.add_argument("--workspace", default="daemonstate")
    parser.add_argument("--cases", type=int, default=20)
    parser.add_argument("--scan-limit", type=int, default=100)
    parser.add_argument(
        "--ollama-model",
        default=None,
        help="Optional local Ollama model used for a behavioral extraction replay.",
    )
    parser.add_argument("--model-cases", type=int, default=6)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model-timeout", type=float, default=300.0)
    parser.add_argument("--max-model-prompt-chars", type=int, default=28_000)
    return parser.parse_args()


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_./+-]+", _normalized(value))
        if len(token) > 1 and token not in STOP_WORDS
    }


def _token_recall(candidate: Any, expected: Any) -> float:
    expected_tokens = _tokens(expected)
    if not expected_tokens:
        return 1.0
    return len(_tokens(candidate) & expected_tokens) / len(expected_tokens)


def _section(content: str, heading: str) -> str:
    lines = content.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return ""
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _heading_position(content: str, heading: str) -> float:
    index = content.find(heading)
    return round(index / max(1, len(content)), 4) if index >= 0 else 1.0


def _duplicate_line_rate(content: str) -> float:
    lines = [
        _normalized(re.sub(r"^[>#*\-\s]+", "", line))
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    material = [line for line in lines if len(line) >= 24]
    if not material:
        return 0.0
    return round((len(material) - len(set(material))) / len(material), 4)


def _requirements(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in contract.get("requirements") or []
        if str(item.get("id") or "").strip()
        and str(item.get("text") or "").strip()
    ]


def _requirement_coverage(content: str, contract: dict[str, Any]) -> float:
    requirements = _requirements(contract)
    if not requirements:
        return 1.0
    normalized_content = _normalized(content)
    covered = sum(
        _normalized(item["text"]) in normalized_content
        for item in requirements
    )
    return covered / len(requirements)


def _opaque_action_references(
    content: str,
    contract: dict[str, Any],
    *,
    variant: str,
) -> int:
    action = _section(content, ACTION_HEADINGS[variant])
    normalized_action = _normalized(action)
    opaque = 0
    for item in _requirements(contract):
        requirement_id = str(item["id"]).strip()
        if not re.search(
            rf"(?<![A-Za-z0-9]){re.escape(requirement_id)}(?![A-Za-z0-9])",
            action,
        ):
            continue
        if _normalized(item["text"]) not in normalized_action:
            opaque += 1
    return opaque


def _structural_metrics(case: BenchmarkCase, variant: str) -> dict[str, Any]:
    content = case.prompts[variant]
    requirements = _requirements(case.contract)
    done_section = _section(content, DONE_HEADINGS[variant])
    action_section = _section(content, ACTION_HEADINGS[variant])
    return {
        "chars": len(content),
        "estimated_tokens": max(1, (len(content) + 3) // 4),
        "nonempty_lines": sum(bool(line.strip()) for line in content.splitlines()),
        "headings": sum(line.startswith("#") for line in content.splitlines()),
        "action_prefix_chars": max(0, content.find(ACTION_HEADINGS[variant])),
        "action_position": _heading_position(content, ACTION_HEADINGS[variant]),
        "action_chars": len(action_section),
        "opaque_action_requirement_refs": _opaque_action_references(
            content,
            case.contract,
            variant=variant,
        ),
        "all_requirements_in_prompt": (
            _requirement_coverage(content, case.contract) == 1.0
        ),
        "done_requirement_coverage": _requirement_coverage(
            done_section,
            case.contract,
        ),
        "duplicate_line_rate": _duplicate_line_rate(content),
        "render_issue_count": len(case.render_issues[variant]),
        "requirement_count": len(requirements),
    }


def _expected_traps(contract: dict[str, Any]) -> list[str]:
    result: list[str] = []
    sections: Iterable[Iterable[dict[str, Any]]] = (
        contract.get("failed_attempts") or [],
        (contract.get("reconciliation") or {}).get(
            "active_reported_blockers"
        ) or [],
        contract.get("open_items") or [],
        contract.get("decisions") or [],
    )
    remaining = 4
    for values in sections:
        if remaining <= 0:
            break
        values_list = list(values)
        for item in values_list[-min(2, remaining):]:
            statement = str(item.get("statement") or "").strip()
            if statement:
                result.append(statement)
                remaining -= 1
    return result


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _score_model_answer(
    answer: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    requirements = _requirements(contract)
    requirement_by_id = {
        str(item["id"]): str(item["text"])
        for item in requirements
    }
    expected_action = str(
        (contract.get("exact_next_action") or {}).get("text") or ""
    ).strip()
    referenced_ids = [
        requirement_id
        for requirement_id in requirement_by_id
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(requirement_id)}(?![A-Za-z0-9])",
            expected_action,
        )
    ]
    first_action = str(answer.get("first_action") or "").strip()
    if referenced_ids:
        action_matches = [
            _token_recall(
                first_action,
                requirement_by_id[requirement_id],
            ) >= 0.35
            for requirement_id in referenced_ids
        ]
        first_action_correct = all(action_matches)
    else:
        first_action_correct = _token_recall(first_action, expected_action) >= 0.45

    done_items = _json_list(answer.get("done_when"))
    done_coverage = (
        sum(
            any(
                _token_recall(candidate, requirement["text"]) >= 0.35
                for candidate in done_items
            )
            for requirement in requirements
        ) / len(requirements)
        if requirements
        else 1.0
    )
    expected_traps = _expected_traps(contract)
    avoidance_items = _json_list(answer.get("do_not_repeat"))
    avoidance_coverage = (
        sum(
            any(
                _token_recall(candidate, expected) >= 0.3
                for candidate in avoidance_items
            )
            for expected in expected_traps
        ) / len(expected_traps)
        if expected_traps
        else 1.0
    )
    permission_correct = _normalized(answer.get("permission_mode")) == _normalized(
        (contract.get("execution_policy") or {}).get("permission_mode")
    )
    preservation_correct = answer.get("preserve_preexisting_changes") is True
    repository_inspection_only = bool(
        re.search(r"\b(?:git status|inspect (?:the )?(?:live )?repository)\b", first_action, re.I)
        and not any(
            _token_recall(first_action, requirement["text"]) >= 0.35
            for requirement in requirements
        )
    )
    weighted_score = (
        (3.0 if first_action_correct else 0.0)
        + (2.0 * done_coverage)
        + avoidance_coverage
        + (1.0 if permission_correct else 0.0)
        + (1.0 if preservation_correct else 0.0)
    ) / 8.0
    return {
        "first_action_correct": first_action_correct,
        "done_requirement_coverage": round(done_coverage, 4),
        "avoidance_coverage": round(avoidance_coverage, 4),
        "permission_correct": permission_correct,
        "preservation_correct": preservation_correct,
        "repository_inspection_only": repository_inspection_only,
        "orientation_score": round(weighted_score, 4),
    }


def _extract_json(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("model response was not a JSON object")
    return parsed


def _ollama_answer(
    *,
    base_url: str,
    model: str,
    content: str,
    timeout: float,
) -> dict[str, Any]:
    instruction = """You are evaluating a coding-session continuation handoff.
Do not use tools and do not perform the task. Read only the handoff below.
Return one JSON object with exactly these fields:
{
  "goal": "one-sentence goal",
  "first_action": "the concrete first action, expanding any opaque requirement ID",
  "do_not_repeat": ["failed approach, blocker, or binding risk"],
  "done_when": ["each requirement ID and its concrete completion criterion"],
  "permission_mode": "workspace_write or read_only",
  "preserve_preexisting_changes": true
}
Use only facts present in the handoff. Keep requirement IDs where present.
"""
    payload = json.dumps({
        "model": model,
        "prompt": f"{instruction}\n--- HANDOFF ---\n{content}",
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "seed": 20260803,
            "num_predict": 700,
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except (
        http.client.HTTPException,
        OSError,
        TimeoutError,
        urllib.error.URLError,
    ) as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    return _extract_json(str(envelope.get("response") or ""))


async def _load_cases(args: argparse.Namespace) -> tuple[list[BenchmarkCase], dict[str, int]]:
    scope = AccessScope.local()
    skips: dict[str, int] = {}
    cases: list[BenchmarkCase] = []
    seen_requests: set[str] = set()
    async with AsyncSessionLocal() as session:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == args.workspace)
        )
        if workspace is None:
            raise RuntimeError(f"workspace not found: {args.workspace}")
        checkpoints = await list_checkpoints(
            session,
            workspace_id=workspace.id,
            limit=max(args.cases, min(args.scan_limit, 100)),
            access_scope=scope,
        )
        for checkpoint in checkpoints:
            if len(cases) >= args.cases:
                break
            if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
                skips["older_schema"] = skips.get("older_schema", 0) + 1
                continue
            if checkpoint.capture_status != "complete":
                skips["incomplete"] = skips.get("incomplete", 0) + 1
                continue
            try:
                request_verbatim = await resolve_session_handoff_request_verbatim(
                    session,
                    checkpoint,
                    access_scope=scope,
                )
                if not request_verbatim:
                    skips["missing_request"] = skips.get("missing_request", 0) + 1
                    continue
                request_key = hashlib.sha256(
                    request_verbatim.encode("utf-8")
                ).hexdigest()
                if request_key in seen_requests:
                    skips["duplicate_request"] = skips.get("duplicate_request", 0) + 1
                    continue
                supporting_context = tuple(
                    await resolve_session_handoff_supporting_context(
                        session,
                        checkpoint,
                        request_verbatim=request_verbatim,
                        access_scope=scope,
                    )
                )
                attachments = await resolve_session_handoff_attachment_descriptors(
                    session,
                    checkpoint,
                    request_verbatim=request_verbatim,
                    access_scope=scope,
                )
                checkpoint_data = checkpoint_to_dict(
                    checkpoint,
                    recovered_goal=request_verbatim,
                )
                contract = build_session_handoff_contract(
                    checkpoint,
                    request_verbatim=request_verbatim,
                    supporting_context=supporting_context,
                    trusted_attachment_descriptors=attachments,
                    allow_local_artifacts=False,
                    checkpoint_data=checkpoint_data,
                )
                if not _requirements(contract):
                    skips["no_requirements"] = skips.get("no_requirements", 0) + 1
                    continue
                if not str(
                    (contract.get("exact_next_action") or {}).get("text") or ""
                ).strip():
                    skips["no_exact_action"] = skips.get("no_exact_action", 0) + 1
                    continue
                prompts = {
                    variant: render_session_handoff(
                        checkpoint,
                        request_verbatim=request_verbatim,
                        supporting_context=supporting_context,
                        contract=contract,
                        checkpoint_data=checkpoint_data,
                        variant=variant,
                    )
                    for variant in VARIANTS
                }
                issues = {
                    variant: tuple(
                        str(item.get("code") or "unknown")
                        for item in session_handoff_render_issues(
                            prompts[variant],
                            request_verbatim=request_verbatim,
                            supporting_context=supporting_context,
                            handoff_contract=contract,
                            variant=variant,
                        )
                    )
                    for variant in VARIANTS
                }
            except (RuntimeError, ValueError) as exc:
                key = f"render_error:{type(exc).__name__}"
                skips[key] = skips.get(key, 0) + 1
                continue
            seen_requests.add(request_key)
            cases.append(BenchmarkCase(
                case_id=hashlib.sha256(str(checkpoint.id).encode()).hexdigest()[:10],
                provider=checkpoint.provider,
                contract=contract,
                request_verbatim=request_verbatim,
                supporting_context=supporting_context,
                prompts=prompts,
                render_issues=issues,
            ))
    return cases, skips


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return round(statistics.fmean(materialized), 4) if materialized else 0.0


def _median(values: Iterable[float]) -> float:
    materialized = list(values)
    return round(statistics.median(materialized), 4) if materialized else 0.0


def _aggregate_structural(
    cases: list[BenchmarkCase],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        row = {
            "case_id": case.case_id,
            "provider": case.provider,
            "variants": {
                variant: _structural_metrics(case, variant)
                for variant in VARIANTS
            },
        }
        rows.append(row)
    summary: dict[str, Any] = {}
    for variant in VARIANTS:
        metrics = [row["variants"][variant] for row in rows]
        summary[variant] = {
            "mean_chars": round(_mean(item["chars"] for item in metrics), 1),
            "median_chars": round(_median(item["chars"] for item in metrics), 1),
            "mean_estimated_tokens": round(
                _mean(item["estimated_tokens"] for item in metrics), 1
            ),
            "mean_nonempty_lines": round(
                _mean(item["nonempty_lines"] for item in metrics), 1
            ),
            "mean_headings": round(_mean(item["headings"] for item in metrics), 1),
            "median_action_position": _median(
                item["action_position"] for item in metrics
            ),
            "median_action_prefix_chars": round(
                _median(item["action_prefix_chars"] for item in metrics), 1
            ),
            "mean_duplicate_line_rate": _mean(
                item["duplicate_line_rate"] for item in metrics
            ),
            "all_requirement_coverage_rate": _mean(
                float(item["all_requirements_in_prompt"]) for item in metrics
            ),
            "mean_done_requirement_coverage": _mean(
                item["done_requirement_coverage"] for item in metrics
            ),
            "cases_with_opaque_action_refs": sum(
                item["opaque_action_requirement_refs"] > 0 for item in metrics
            ),
            "cases_with_render_issues": sum(
                item["render_issue_count"] > 0 for item in metrics
            ),
        }
    legacy_chars = [
        row["variants"]["legacy_v1"]["chars"]
        for row in rows
    ]
    compact_chars = [
        row["variants"]["compact_v2"]["chars"]
        for row in rows
    ]
    reductions = [
        1 - compact / legacy
        for legacy, compact in zip(legacy_chars, compact_chars, strict=True)
        if legacy
    ]
    summary["paired_change"] = {
        "mean_char_reduction": _mean(reductions),
        "median_char_reduction": _median(reductions),
        "compact_shorter_cases": sum(
            compact < legacy
            for legacy, compact in zip(legacy_chars, compact_chars, strict=True)
        ),
    }
    return summary, rows


async def _run_model_replay(
    args: argparse.Namespace,
    cases: list[BenchmarkCase],
) -> dict[str, Any] | None:
    if not args.ollama_model:
        return None
    eligible = [
        case
        for case in cases
        if max(len(prompt) for prompt in case.prompts.values())
        <= args.max_model_prompt_chars
    ][: max(0, args.model_cases)]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for case_index, case in enumerate(eligible):
        order = VARIANTS if case_index % 2 == 0 else tuple(reversed(VARIANTS))
        for variant in order:
            try:
                answer = await asyncio.to_thread(
                    _ollama_answer,
                    base_url=args.ollama_url,
                    model=args.ollama_model,
                    content=case.prompts[variant],
                    timeout=args.model_timeout,
                )
                results.append({
                    "case_id": case.case_id,
                    "variant": variant,
                    **_score_model_answer(answer, case.contract),
                })
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                failures.append({
                    "case_id": case.case_id,
                    "variant": variant,
                    "error": type(exc).__name__,
                })
    summary: dict[str, Any] = {
        "model": args.ollama_model,
        "eligible_cases": len(eligible),
        "successful_responses": len(results),
        "failures": failures,
        "variants": {},
    }
    for variant in VARIANTS:
        variant_rows = [item for item in results if item["variant"] == variant]
        summary["variants"][variant] = {
            "responses": len(variant_rows),
            "first_action_correct_rate": _mean(
                float(item["first_action_correct"]) for item in variant_rows
            ),
            "mean_done_requirement_coverage": _mean(
                item["done_requirement_coverage"] for item in variant_rows
            ),
            "mean_avoidance_coverage": _mean(
                item["avoidance_coverage"] for item in variant_rows
            ),
            "permission_accuracy": _mean(
                float(item["permission_correct"]) for item in variant_rows
            ),
            "preservation_accuracy": _mean(
                float(item["preservation_correct"]) for item in variant_rows
            ),
            "repository_inspection_only_rate": _mean(
                float(item["repository_inspection_only"])
                for item in variant_rows
            ),
            "mean_orientation_score": _mean(
                item["orientation_score"] for item in variant_rows
            ),
        }
    summary["case_results"] = results
    return summary


async def _main(args: argparse.Namespace) -> int:
    cases, skips = await _load_cases(args)
    if not cases:
        raise RuntimeError("no eligible saved checkpoints were found")
    structural, case_rows = _aggregate_structural(cases)
    model_replay = await _run_model_replay(args, cases)
    payload = {
        "schema_version": "session_handoff_variant_benchmark.v1",
        "workspace": args.workspace,
        "paired_cases": len(cases),
        "selection": {
            "latest_distinct_requests": True,
            "checkpoint_schema": CHECKPOINT_SCHEMA_VERSION,
            "skips": skips,
        },
        "structural": structural,
        "model_replay": model_replay,
        "cases": case_rows,
        "interpretation": (
            "Structural results test prompt projection quality. Local-model replay is "
            "a behavioral smoke test, not evidence of production user success."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    parsed_args = _parse_args()
    try:
        raise SystemExit(asyncio.run(_main(parsed_args)))
    finally:
        asyncio.run(engine.dispose())
