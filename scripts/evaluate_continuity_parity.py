#!/usr/bin/env python3
"""Aggregate externally recorded same-model continuity-parity trials.

This command is deliberately offline.  It does not call a provider, launch an
agent, or infer success from model prose.  Each input condition must already
contain externally observed outcome evidence.  A future experiment runner can
write this schema after executing full-history, compiled-composite, and blank
conditions against identical repository snapshots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.evals.continuity_parity import (
    ContinuityParityValidationError,
    evaluate_paired_continuity_trials,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate recorded full-history/compiled-composite/blank trials; "
            "never calls a model or network service."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSON list of paired trials, or an object with a trials list.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the JSON report. The report is always printed.",
    )
    return parser.parse_args(argv)


def _load_trials(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityParityValidationError(
            f"could not read paired trial input: {exc}"
        ) from exc
    trials = payload.get("trials") if isinstance(payload, dict) else payload
    if not isinstance(trials, list):
        raise ContinuityParityValidationError(
            "paired trial input must be a list or an object with a trials list"
        )
    if any(not isinstance(item, dict) for item in trials):
        raise ContinuityParityValidationError("every paired trial must be an object")
    return trials


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = evaluate_paired_continuity_trials(_load_trials(args.input))
    except ContinuityParityValidationError as exc:
        raise SystemExit(f"continuity parity input error: {exc}") from exc
    rendered = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
