#!/usr/bin/env python3
"""Replay frozen real captures with 4K/8K retrieval and no model calls.

Reads only evaluation snapshots, never the live application database. Writes
each attempt separately. Gold is hashed for identity, never used for ranking.
Run: python -m scripts.evaluate_session_retrieval --help
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Base, WorkCheckpoint
from app.services.access import AccessScope
from app.services.checkpoints import TrustedRequestImageDescriptor
from app.services.session_context import build_session_context_artifact
from app.services.session_retrieval import load_session_retrieval_context
from scripts.session_eval_replay import _restore_request, _save, _seed, _typed_row


async def run(args):
    output = args.output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    output.mkdir(parents=True)
    code_paths = [
        "app/services/session_retrieval.py", "app/services/session_context.py",
        "app/services/context_quality_adapters.py",
        "app/services/session_events.py", "app/services/context_export.py", "app/api/checkpoints.py",
        "scripts/evaluate_session_retrieval.py",
    ]
    report = {
        "model_calls": 0, "gold_sha256": hashlib.sha256(args.gold.read_bytes()).hexdigest(),
        "selector_inputs": "source events only; no gold or questions",
        "code_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in code_paths},
        "cases": [],
    }
    for case_id in ("claude_reasoning", "opencode_eligible", "codex_eligible", "codex_sparse"):
        frozen_bytes = (args.frozen / f"{case_id}.json").read_bytes()
        frozen = json.loads(frozen_bytes)
        snapshot_bytes = (args.frozen / f"{case_id}.source_snapshot.json").read_bytes()
        if hashlib.sha256(snapshot_bytes).hexdigest() != frozen["selection"]["snapshot_sha256"]:
            raise ValueError(f"Frozen snapshot changed: {case_id}")
        snapshot = json.loads(snapshot_bytes)
        checkpoint = WorkCheckpoint(**_typed_row(WorkCheckpoint.__table__, snapshot["checkpoint"]))
        if hashlib.sha256(checkpoint.payload_json.encode()).hexdigest() != checkpoint.payload_sha256:
            raise ValueError(f"Invalid frozen checkpoint: {case_id}")
        case = {
            "case_id": case_id, "frozen_inputs_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
            "public_eligibility": frozen["public_eligibility"], "arms": {},
        }
        with tempfile.TemporaryDirectory(prefix="daemonstate-retrieval-eval-") as directory:
            engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(Path(directory) / "eval.db")))
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    await _seed(session, frozen)
                    started = time.perf_counter()
                    retrieval = await load_session_retrieval_context(
                        session, checkpoint,
                        boundary_sequence=frozen["selection"]["boundary_sequence_number"],
                        access_scope=AccessScope.local(),
                    )
                    case["retrieval_seconds"] = time.perf_counter() - started
                    _save(output / case_id / "retrieval-candidates.json", retrieval)
                    for name, budget, evidence in (
                        ("baseline", 4_000, None), ("4k", 4_000, retrieval), ("8k", 8_000, retrieval),
                    ):
                        started = time.perf_counter()
                        artifact = build_session_context_artifact(
                            checkpoint, request_verbatim=_restore_request(frozen),
                            supporting_context=copy.deepcopy(frozen["supporting_context"]),
                            trusted_attachment_descriptors=[TrustedRequestImageDescriptor(**item) for item in frozen["attachment_descriptors"]],
                            allow_local_artifacts=False, checkpoint_data=copy.deepcopy(frozen["checkpoint_data"]),
                            repository_comparison=copy.deepcopy(frozen["repository_comparison"]),
                            token_budget=budget, retrieval_context=evidence,
                        )
                        selected = artifact.get("retrieval_context") or {}
                        # Verify every locator against the frozen original,
                        # including decoded JSON fields and capture boundaries.
                        events_by_id = {str(row["id"]).replace("-", ""): row for row in frozen["events"]}
                        for span in selected.get("spans", []):
                            event = events_by_id[span["source_event_id"].replace("-", "")]
                            value = event["content"]
                            if span["field"].startswith("content.json:"):
                                value = json.loads(value)
                                for part in json.loads(span["field"].removeprefix("content.json:")):
                                    value = value[part]
                            assert value[span["start_char"]:span["end_char"]] == span["statement"]
                            assert hashlib.sha256(span["statement"].encode()).hexdigest() == span["excerpt_sha256"]
                            assert span["source_event_sha256"] == event["content_sha256"]
                            assert span["source_sequence_number"] <= frozen["selection"]["boundary_sequence_number"]
                        assert artifact["estimated_tokens"] <= budget, "Replay context exceeded its requested budget"
                        details = artifact["portable_details"]
                        assert hashlib.sha256(details["content"].encode()).hexdigest() == details["sha256"]
                        assert json.loads(details["content"])["retrieval_context"] == artifact["retrieval_context"]
                        case["arms"][name] = {
                            "render_seconds": time.perf_counter() - started,
                            "estimated_tokens": artifact["estimated_tokens"],
                            "selected_count": selected.get("selected_count", 0),
                            "selected_tool_spans": sum(span["kind"] == "tool" for span in selected.get("spans", [])),
                            "content_sha256": artifact["sha256"],
                            "copy_ready": artifact["quality_report"]["copy_ready"],
                            "source_locators_validated": len(selected.get("spans", [])),
                        }
                        _save(output / case_id / name / "artifact.json", artifact)
                        (output / case_id / name / "context.md").write_text(artifact["content"])
                report["cases"].append(case)
                _save(output / "metrics.json", report)
                print(case_id, json.dumps(case["arms"]), flush=True)
            finally:
                await engine.dispose()
    print(f"Output: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path("data/evaluations/context-quality-2026-10-16")
    parser.add_argument("--frozen", type=Path, default=root / "final/frozen")
    parser.add_argument("--gold", type=Path, default=root / "gold/frozen_gold.json")
    parser.add_argument("--output", type=Path, default=root / "retrieval-only")
    asyncio.run(run(parser.parse_args()))
