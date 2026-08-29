#!/usr/bin/env python3
"""Re-evaluate the frozen Session and Workspace Context corpus read-only.

The script never chooses a latest checkpoint, never persists a ContextPack, and
never writes its report to disk. Redirect stdout explicitly if a durable report
is desired after reviewing the output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.database import AsyncSessionLocal, engine
from app.evals.context_quality_benchmark import (
    BenchmarkInputError,
    load_frozen_baseline,
    load_frozen_gold,
    run_context_quality_benchmark,
)


DEFAULT_BASELINE = Path(
    "docs/experiments/context-quality-engine-baseline-2026-08-20.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render and score the exact frozen context-quality corpus without "
            "database writes or latest-session selection."
        )
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"Frozen benchmark manifest (default: {DEFAULT_BASELINE}).",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        help=(
            "Separately adjudicated frozen gold manifest. Required for session "
            "and all modes; runtime-derived expectations are forbidden."
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository used for the read-only Workspace Context candidate compile.",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "sessions", "workspace"),
        default="all",
        help="Benchmark both context kinds or one isolated lane.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict:
    baseline = load_frozen_baseline(args.baseline)
    frozen_gold = (
        load_frozen_gold(args.gold, baseline=baseline)
        if args.gold is not None
        else None
    )
    async with AsyncSessionLocal() as session:
        return await run_context_quality_benchmark(
            session,
            baseline=baseline,
            repo_path=str(args.repo.resolve()),
            mode=args.mode,
            frozen_gold=frozen_gold,
        )


def main() -> int:
    args = _parse_args()
    try:
        payload = asyncio.run(_run(args))
    except BenchmarkInputError as exc:
        raise SystemExit(f"benchmark input error: {exc}") from exc
    finally:
        asyncio.run(engine.dispose())
    print(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
