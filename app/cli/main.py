from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.cli.http import api_request, APIError

DEFAULT_BASE_URL = "http://localhost:8000"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctxe", description="Context Engine CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest files or directories.")
    ingest_parser.add_argument("path", help="File or directory to ingest")
    ingest_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ingest_parser.add_argument("--api-key", default=None, help="API key for protected servers")
    ingest_parser.add_argument("--sync", action="store_true", help="Process synchronously")
    ingest_parser.add_argument("--json", action="store_true", dest="json_output")
    ingest_parser.set_defaults(func=run_ingest)

    query_parser = subparsers.add_parser("query", help="Query structured context.")
    query_parser.add_argument("question", help="Question to ask")
    query_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    query_parser.add_argument("--api-key", default=None, help="API key for protected servers")
    query_parser.add_argument("--workspace-id", default=None)
    query_parser.add_argument(
        "--retrieval-mode", choices=["indexed", "live", "combined"], default="indexed"
    )
    query_parser.add_argument(
        "--live-source", action="append", default=[], choices=["local_repo", "github"]
    )
    query_parser.add_argument("--repo", default=None, help="Active indexed local repo path")
    query_parser.add_argument("--json", action="store_true", dest="json_output")
    query_parser.set_defaults(func=run_query)

    prepare_parser = subparsers.add_parser("prepare", help="Compile a context_pack.v2 for a coding task.")
    prepare_parser.add_argument("objective", help="Coding-agent objective")
    prepare_parser.add_argument("--repo", default=".", help="Repository path to inspect")
    prepare_parser.add_argument("--target-model", default="general-coder", help="Target coding model name")
    prepare_parser.add_argument("--budget", type=int, default=None, help="Context token budget")
    prepare_parser.add_argument("--workspace-id", default=None)
    prepare_parser.add_argument("--out", default=None, help="Write markdown context pack to this path")
    prepare_parser.add_argument("--manifest-out", default=None, help="Write manifest JSON to this path")
    prepare_parser.add_argument(
        "--file-output-only",
        action="store_true",
        help="Do not persist; manifest marks persistence.available=false",
    )
    prepare_parser.add_argument("--json", action="store_true", dest="json_output")
    prepare_parser.set_defaults(func=run_prepare)

    graph_parser = subparsers.add_parser("graph", help="Get knowledge graph.")
    graph_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    graph_parser.add_argument("--api-key", default=None, help="API key for protected servers")
    graph_parser.add_argument("--json", action="store_true", dest="json_output")
    graph_parser.set_defaults(func=run_graph)

    repo_parser = subparsers.add_parser("repo", help="Inspect or index a local repository.")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command", required=True)
    repo_index_parser = repo_subparsers.add_parser("index", help="Index repo files and symbols.")
    repo_index_parser.add_argument("path", nargs="?", default=".")
    repo_index_parser.add_argument("--workspace-id", default=None)
    repo_index_parser.add_argument("--no-persist", action="store_true")
    repo_index_parser.add_argument("--json", action="store_true", dest="json_output")
    repo_index_parser.set_defaults(func=run_repo)

    repo_watch_parser = repo_subparsers.add_parser(
        "watch",
        help="Watch a local repository and persist bounded change evidence.",
    )
    repo_watch_parser.add_argument("path", nargs="?", default=".")
    repo_watch_parser.add_argument("--workspace-id", required=True)
    repo_watch_parser.add_argument("--poll-interval", type=float, default=2.0)
    repo_watch_parser.add_argument("--debounce", type=float, default=0.5)
    repo_watch_parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll cycle and stop.",
    )
    repo_watch_parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Stop after this many poll cycles (primarily for tests/automation).",
    )
    repo_watch_parser.add_argument("--json", action="store_true", dest="json_output")
    repo_watch_parser.set_defaults(func=run_repo)

    eval_parser = subparsers.add_parser("eval", help="Run local quality evals.")
    eval_parser.add_argument(
        "suite", choices=["extraction", "harness"], help="Eval suite to run"
    )
    eval_parser.add_argument(
        "--input",
        default=None,
        help="JSON experiment rows for the harness paired evaluator",
    )
    eval_parser.add_argument(
        "--minimum-directional-tasks",
        type=int,
        default=10,
        help="Minimum complete task triplets before reporting a directional result",
    )
    eval_parser.add_argument("--json", action="store_true", dest="json_output")
    eval_parser.set_defaults(func=run_eval)

    harness_parser = subparsers.add_parser(
        "harness",
        help="Wrap an explicit local coding-agent command and measure observed outcomes.",
    )
    harness_subparsers = harness_parser.add_subparsers(
        dest="harness_command", required=True
    )
    harness_run_parser = harness_subparsers.add_parser(
        "run",
        help="Compile context, run one explicit worker command, and preserve evidence.",
        epilog=(
            "Worker syntax: append `-- executable arg ...`. An exact "
            "`{context_file}` argument is replaced with the generated brief path."
        ),
    )
    harness_run_parser.add_argument("objective", help="Trusted coding task objective")
    harness_run_parser.add_argument("--repo", default=".", help="Git repository path")
    harness_run_parser.add_argument("--workspace-id", required=True)
    harness_run_parser.add_argument(
        "--target-model", default="general-coder", help="Worker model name or profile"
    )
    harness_run_parser.add_argument("--budget", type=int, default=None)
    harness_run_parser.add_argument(
        "--run-key",
        default=None,
        help="Optional workspace-level duplicate guard; generated when omitted",
    )
    harness_run_parser.add_argument(
        "--tool", default="local-harness", help="Worker/tool label stored with the run"
    )
    harness_run_parser.add_argument(
        "--verify",
        action="store_true",
        help="Explicitly run required verification commands from the compiled pack",
    )
    harness_run_parser.add_argument(
        "--output-limit-bytes", type=int, default=32_768
    )
    harness_run_parser.add_argument("--command-timeout", type=float, default=3_600.0)
    harness_run_parser.add_argument(
        "--verification-timeout", type=float, default=900.0
    )
    harness_run_parser.add_argument("--json", action="store_true", dest="json_output")
    harness_run_parser.set_defaults(func=run_harness, worker_command=[])

    harness_report_parser = harness_subparsers.add_parser(
        "report", help="Summarize observed outcomes by model and model profile."
    )
    harness_report_parser.add_argument("--workspace-id", required=True)
    harness_report_parser.add_argument("--json", action="store_true", dest="json_output")
    harness_report_parser.set_defaults(func=run_harness)

    worker_parser = subparsers.add_parser("worker", help="Run local background workers.")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)
    sync_worker_parser = worker_subparsers.add_parser("sync", help="Drain pending connector sync jobs.")
    sync_worker_parser.add_argument("--limit", type=int, default=10)
    sync_worker_parser.add_argument("--watch", action="store_true", help="Keep polling for jobs")
    sync_worker_parser.add_argument("--poll-interval", type=float, default=None)
    sync_worker_parser.add_argument("--lease-seconds", type=int, default=None)
    sync_worker_parser.add_argument("--retry-base-seconds", type=int, default=None)
    sync_worker_parser.add_argument("--retry-max-seconds", type=int, default=None)
    sync_worker_parser.add_argument("--worker-id", default=None)
    sync_worker_parser.add_argument("--json", action="store_true", dest="json_output")
    sync_worker_parser.set_defaults(func=run_sync_worker)

    db_parser = subparsers.add_parser("db", help="Manage database migrations.")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_upgrade_parser = db_subparsers.add_parser("upgrade", help="Run Alembic migrations.")
    db_upgrade_parser.add_argument("revision", nargs="?", default="head")
    db_upgrade_parser.add_argument("--database-url", default=None)
    db_upgrade_parser.set_defaults(func=run_db)
    db_current_parser = db_subparsers.add_parser("current", help="Show current Alembic revision.")
    db_current_parser.add_argument("--database-url", default=None)
    db_current_parser.set_defaults(func=run_db)
    db_history_parser = db_subparsers.add_parser("history", help="Show Alembic revision history.")
    db_history_parser.add_argument("--database-url", default=None)
    db_history_parser.set_defaults(func=run_db)
    db_stamp_parser = db_subparsers.add_parser(
        "stamp-head",
        help="Mark an existing database as current without running migrations.",
    )
    db_stamp_parser.add_argument("--database-url", default=None)
    db_stamp_parser.set_defaults(func=run_db)

    credentials_parser = subparsers.add_parser("credentials", help="Manage stored credentials.")
    credentials_subparsers = credentials_parser.add_subparsers(
        dest="credentials_command",
        required=True,
    )
    credentials_rotate_parser = credentials_subparsers.add_parser(
        "rotate",
        help="Re-encrypt stored connector credentials with the primary ENCRYPTION_KEY.",
    )
    credentials_rotate_parser.add_argument("--database-url", default=None)
    credentials_rotate_parser.set_defaults(func=run_credentials)

    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server.")
    mcp_parser.set_defaults(func=run_mcp)

    return parser


def run_ingest(args: argparse.Namespace) -> int:
    from app.importers.generic import GenericFileScanner

    scanner = GenericFileScanner()
    source_path = Path(args.path).expanduser()
    ok, err = scanner.validate_source(source_path)
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    documents = list(scanner.ingest(source_path))
    if not documents:
        print("No readable files found.", file=sys.stderr)
        return 1

    payload = {
        "documents": [
            {
                "source_type": "local",
                "external_id": doc.external_id,
                "content": doc.content,
                "author": doc.author,
                "url": doc.source_url,
                "metadata": doc.metadata,
            }
            for doc in documents
        ]
    }

    try:
        suffix = "?sync=true" if args.sync else ""
        if len(payload["documents"]) == 1:
            resp = api_request(
                args.base_url,
                "POST",
                f"/api/sources{suffix}",
                payload=payload["documents"][0],
                api_key=_api_key(args),
            )
        else:
            resp = api_request(
                args.base_url,
                "POST",
                f"/api/sources/bulk{suffix}",
                payload=payload,
                api_key=_api_key(args),
            )
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(resp, indent=2))
    else:
        count = resp.get("created", 1)
        print(f"Ingested {count} document(s).")
    return 0


def run_query(args: argparse.Namespace) -> int:
    payload = {"question": args.question}
    if args.workspace_id:
        payload["workspace_id"] = args.workspace_id
    if args.retrieval_mode != "indexed":
        payload["retrieval_mode"] = args.retrieval_mode
        payload["live_sources"] = args.live_source
    if args.repo:
        payload["repo_path"] = args.repo
    try:
        resp = api_request(
            args.base_url,
            "POST",
            "/api/query",
            payload=payload,
            api_key=_api_key(args),
        )
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(resp, indent=2))
    else:
        print(resp.get("answer", "No answer."))
        print(f"confidence: {resp.get('confidence', 0)}")
        for src in resp.get("sources", [])[:3]:
            print(f"  source: {src.get('type', '')} {src.get('url', '')}")
    return 0


def run_prepare(args: argparse.Namespace) -> int:
    import asyncio

    try:
        result = asyncio.run(_compile_prepare(args))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    markdown_path = None
    manifest_path = None
    if args.out:
        markdown_path = str(Path(args.out).expanduser())
        Path(markdown_path).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_path).write_text(result.markdown, encoding="utf-8")
    if args.manifest_out:
        manifest_path = str(Path(args.manifest_out).expanduser())
        Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(manifest_path).write_text(
            json.dumps(result.manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    payload = {
        "context_pack_id": result.context_pack_id,
        "schema_version": result.schema_version,
        "health_score": result.health_score,
        "markdown_path": markdown_path,
        "manifest_path": manifest_path,
        "persistence": result.manifest.get("persistence"),
        "manifest": result.manifest,
    }
    if args.json_output:
        print(json.dumps(payload, indent=2))
    else:
        if markdown_path:
            print(f"wrote markdown: {markdown_path}")
        else:
            print(result.markdown)
        if manifest_path:
            print(f"wrote manifest: {manifest_path}")
        if result.context_pack_id:
            print(f"context_pack_id: {result.context_pack_id}")
        else:
            print("context_pack_id: null (file-output-only)")
    return 0


async def _compile_prepare(args: argparse.Namespace):
    from app.database import AsyncSessionLocal
    from app.services.context_compiler import ContextCompiler

    if args.file_output_only:
        compiler = ContextCompiler(None)
        return await compiler.compile_context_pack(
            args.objective,
            workspace_id=args.workspace_id,
            repo_path=args.repo,
            target_model=args.target_model,
            token_budget=args.budget,
            persist=False,
        )

    async with AsyncSessionLocal() as session:
        compiler = ContextCompiler(session)
        result = await compiler.compile_context_pack(
            args.objective,
            workspace_id=args.workspace_id,
            repo_path=args.repo,
            target_model=args.target_model,
            token_budget=args.budget,
            persist=True,
        )
        await session.commit()
        return result


def run_repo(args: argparse.Namespace) -> int:
    import asyncio

    if args.repo_command == "watch":
        try:
            result = asyncio.run(_watch_repo(args))
        except KeyboardInterrupt:
            print("repo watch stopped", file=sys.stderr)
            return 130
        except Exception as exc:
            code = getattr(exc, "code", None)
            prefix = f"Error [{code}]" if code else "Error"
            print(f"{prefix}: {exc}", file=sys.stderr)
            return 1
        if args.json_output:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(
                "repo watch complete: "
                f"cycles={result.cycles} "
                f"changes={result.changes_detected} "
                f"events_created={result.events_created} "
                f"stopped={result.stopped_reason}"
            )
        return 0

    try:
        frame = asyncio.run(_index_repo(args))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = frame.to_manifest()
    data["indexed_file_count"] = len(frame.indexed_files)
    data["indexed_symbol_count"] = sum(len(item.symbols) for item in frame.indexed_files)
    if args.json_output:
        print(json.dumps(data, indent=2))
    else:
        print(
            "repo index: "
            f"files={data['indexed_file_count']} "
            f"symbols={data['indexed_symbol_count']} "
            f"persistence={data['persistence']['available']}"
        )
    return 0


async def _index_repo(args: argparse.Namespace):
    from app.database import AsyncSessionLocal
    from app.services.repo_indexer import RepoIndexer

    if args.no_persist:
        return await RepoIndexer(None).inspect_repo(
            args.path,
            workspace_id=args.workspace_id,
            persist=False,
        )
    async with AsyncSessionLocal() as session:
        frame = await RepoIndexer(session).inspect_repo(
            args.path,
            workspace_id=args.workspace_id,
            persist=True,
        )
        await session.commit()
        return frame


async def _watch_repo(args: argparse.Namespace):
    from app.database import AsyncSessionLocal
    from app.services.repo_watcher import watch_repository

    def _print_event(event) -> None:
        data = event.to_dict()
        if args.json_output:
            print(json.dumps({"type": "repository_event", **data}), flush=True)
            return
        print(
            "repo change: "
            f"added={data['files_added']} "
            f"changed={data['files_changed']} "
            f"deleted={data['files_deleted']} "
            f"snapshot={data['snapshot_fingerprint'][:12]}",
            flush=True,
        )

    async with AsyncSessionLocal() as session:
        return await watch_repository(
            session,
            repo_path=args.path,
            workspace_id=args.workspace_id,
            poll_interval_seconds=args.poll_interval,
            debounce_seconds=args.debounce,
            once=args.once,
            max_cycles=args.max_cycles,
            on_event=_print_event,
        )


def run_graph(args: argparse.Namespace) -> int:
    try:
        resp = api_request(args.base_url, "GET", "/api/graph", api_key=_api_key(args))
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(resp, indent=2))
    else:
        models = resp.get("models", [])
        components = resp.get("components", [])
        relationships = resp.get("relationships", [])
        print(f"Models: {len(models)}, Components: {len(components)}, Relationships: {len(relationships)}")
        for m in models:
            print(f"  {m['name']} ({m.get('component_count', 0)} components)")
    return 0


def run_eval(args: argparse.Namespace) -> int:
    if args.suite == "extraction":
        from app.evals.extraction import run_extraction_eval
        report = run_extraction_eval()
    elif args.suite == "harness":
        from app.evals.harness_outcomes import evaluate_paired_experiment

        if not args.input:
            print("Error: --input is required for the harness eval", file=sys.stderr)
            return 1
        raw = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
        rows = raw.get("rows") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            print("Error: harness eval input must be a JSON list or {'rows': [...]}", file=sys.stderr)
            return 1
        report = evaluate_paired_experiment(
            rows,
            minimum_directional_tasks=args.minimum_directional_tasks,
        )
    else:
        print(f"Unknown eval suite: {args.suite}", file=sys.stderr)
        return 1

    data = report.to_dict()
    if args.json_output:
        print(json.dumps(data, indent=2))
    elif args.suite == "extraction":
        print(
            f"{args.suite}: {data['passed_count']}/{data['case_count']} passed "
            f"({data['pass_rate']:.0%})"
        )
        for case in data["cases"]:
            status = "PASS" if case["passed"] else "FAIL"
            print(f"  {status} {case['id']}")
            problems = (
                case["warnings"]
                + [f"missing fact type: {item}" for item in case["missing_fact_types"]]
                + [f"missing term: {item}" for item in case["missing_terms"]]
                + [
                    f"missing relationship: {item}"
                    for item in case["missing_relationship_types"]
                ]
            )
            for problem in problems:
                print(f"    - {problem}")
    else:
        print(
            f"harness: paired_tasks={data['task_count']} "
            f"claim_status={data['claim_status']}"
        )
        for condition in data["conditions"]:
            print(
                f"  {condition['label']}: solved={condition['solved_count']}/"
                f"{condition['task_count']} ({condition['solve_rate']:.0%})"
            )
    if args.suite == "extraction":
        return 0 if data["failed_count"] == 0 else 1
    return 0


def run_harness(args: argparse.Namespace) -> int:
    import asyncio

    if args.harness_command == "report":
        try:
            data = asyncio.run(_harness_outcome_report(args))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if args.json_output:
            print(json.dumps(data, indent=2))
        else:
            print(
                f"harness outcomes: observed_runs={data['observed_runs']} "
                f"groups={len(data['groups'])}"
            )
            for group in data["groups"]:
                print(
                    f"  {group['model']} / {group['model_profile']}: "
                    f"verified={group['verified_successful_runs']}/"
                    f"{group['observed_runs']}"
                )
        return 0

    worker_command = list(args.worker_command or [])
    if worker_command and worker_command[0] == "--":
        worker_command = worker_command[1:]
    if not worker_command:
        print("Error: provide an explicit worker command after `--`", file=sys.stderr)
        return 1
    try:
        data = asyncio.run(_run_local_harness(args, worker_command))
    except KeyboardInterrupt:
        print("harness run interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(data, indent=2))
    else:
        print(f"harness run: status={data['status']} run_id={data['run_id']}")
        print(f"context_pack_id: {data['context_pack_id']}")
        print(f"changed_files: {len(data['changed_files'])}")
        if not args.verify:
            print("verification: not executed (pass --verify to authorize it)")
        else:
            print(f"verification: {len(data['verification_results'])} command(s) executed")
    return 0 if data["status"] == "completed" else 1


async def _run_local_harness(
    args: argparse.Namespace,
    worker_command: list[str],
) -> dict:
    import asyncio
    from uuid import UUID, uuid4

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models import AgentRun, Workspace
    from app.services.context_compiler import ContextCompiler
    from app.services.local_harness import LocalHarnessRunner
    from app.time import utc_now

    workspace_id = UUID(str(args.workspace_id))
    run_key = str(args.run_key or f"local:{uuid4()}")
    if not run_key.strip() or len(run_key) > 255:
        raise ValueError("run_key must contain 1 to 255 characters")

    async with AsyncSessionLocal() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise ValueError(f"Workspace not found: {workspace_id}")
        pack_result = await ContextCompiler(session).compile_context_pack(
            args.objective,
            workspace_id=workspace_id,
            repo_path=args.repo,
            target_model=args.target_model,
            token_budget=args.budget,
            persist=True,
        )
        if not pack_result.context_pack_id:
            raise RuntimeError("context compiler returned no durable context_pack_id")
        pack_id = UUID(str(pack_result.context_pack_id))
        existing = await session.scalar(
            select(AgentRun).where(
                AgentRun.workspace_id == workspace_id,
                AgentRun.run_key == run_key,
            )
        )
        if existing is not None:
            raise ValueError(
                f"run_key {run_key!r} already exists in this workspace; "
                "use a new key for a new execution"
            )
        repo_state = pack_result.manifest.get("repo_state") or {}
        run = AgentRun(
            workspace_id=workspace_id,
            context_pack_id=pack_id,
            run_key=run_key,
            tool=str(args.tool or "local-harness"),
            model=str(args.target_model),
            objective=str(args.objective),
            branch=repo_state.get("branch"),
            base_commit=repo_state.get("head_commit") or repo_state.get("base_commit"),
            started_at=utc_now(),
            status="running",
        )
        session.add(run)
        await session.commit()
        try:
            result = await LocalHarnessRunner(
                session,
                output_limit_bytes=args.output_limit_bytes,
                command_timeout_seconds=args.command_timeout,
                verification_timeout_seconds=args.verification_timeout,
            ).run(
                context_pack_id=pack_id,
                run_id=run.id,
                repo_path=args.repo,
                command=worker_command,
                verify=bool(args.verify),
            )
        except BaseException:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(session.commit())
            raise
        return {
            **result.to_dict(),
            "target_model": args.target_model,
            "model_profile": pack_result.manifest.get("target_model", {}).get("profile"),
            "execution_policy": pack_result.manifest.get("execution_policy"),
            "verification_authorized": bool(args.verify),
        }


async def _harness_outcome_report(args: argparse.Namespace) -> dict:
    from uuid import UUID

    from app.database import AsyncSessionLocal
    from app.services.harness_outcomes import HarnessOutcomeService

    async with AsyncSessionLocal() as session:
        report = await HarnessOutcomeService(session).summarize(
            workspace_id=UUID(str(args.workspace_id))
        )
        return report.to_dict()


def run_sync_worker(args: argparse.Namespace) -> int:
    import asyncio
    from app.config import settings
    from app.services.sync_worker import run_pending_sync_jobs

    async def _run_once():
        return await run_pending_sync_jobs(
            limit=args.limit,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            retry_base_seconds=args.retry_base_seconds,
            retry_max_seconds=args.retry_max_seconds,
        )

    async def _run_watch() -> int:
        poll_interval = (
            args.poll_interval
            if args.poll_interval is not None
            else settings.sync_worker_poll_interval_seconds
        )
        while True:
            result = await _run_once()
            _print_sync_worker_result(result.to_dict(), json_output=args.json_output)
            await asyncio.sleep(max(0.1, poll_interval))

    if args.watch:
        return asyncio.run(_run_watch())

    result = asyncio.run(_run_once())
    data = result.to_dict()
    _print_sync_worker_result(data, json_output=args.json_output)
    return 0 if data["failed"] == 0 and data.get("dead_lettered", 0) == 0 else 1


def _print_sync_worker_result(data: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2), flush=True)
        return

    print(
        "sync worker: "
        f"started={data['started']} "
        f"completed={data['completed']} "
        f"retried={data.get('retried', 0)} "
        f"failed={data['failed']} "
        f"dead_lettered={data.get('dead_lettered', 0)}",
        flush=True,
    )


def run_db(args: argparse.Namespace) -> int:
    config = _alembic_config(args.database_url)
    if args.db_command == "upgrade":
        revision = args.revision or "head"
        _run_alembic_command("upgrade", config, revision)
        print(f"database upgraded to {revision}")
        return 0
    if args.db_command == "current":
        _run_alembic_command("current", config)
        return 0
    if args.db_command == "history":
        _run_alembic_command("history", config)
        return 0
    if args.db_command == "stamp-head":
        _run_alembic_command("stamp", config, "head")
        print("database stamped at head")
        return 0

    print(f"Unknown db command: {args.db_command}", file=sys.stderr)
    return 1


def run_credentials(args: argparse.Namespace) -> int:
    import asyncio
    from app.services.credentials import CredentialStoreError

    if args.credentials_command == "rotate":
        try:
            result = asyncio.run(_rotate_stored_credentials(args.database_url))
        except CredentialStoreError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(
            "credentials rotated: "
            f"scanned={result['scanned']} "
            f"updated={result['updated']} "
            f"encrypted={result['encrypted']}",
        )
        return 0

    print(f"Unknown credentials command: {args.credentials_command}", file=sys.stderr)
    return 1


async def _rotate_stored_credentials(database_url: str | None = None) -> dict[str, int]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings
    from app.database import _ensure_sqlite_parent_dir, _make_async_url
    from app.models import Connector
    from app.services.credentials import credentials_are_encrypted, rotate_credentials

    db_url = _make_async_url(database_url or settings.database_url)
    _ensure_sqlite_parent_dir(db_url)
    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    scanned = 0
    updated = 0
    encrypted = 0
    try:
        async with session_factory() as session:
            connectors = list(await session.scalars(select(Connector)))
            for connector in connectors:
                scanned += 1
                before = connector.credentials_json or "{}"
                after = rotate_credentials(before)
                if after != before:
                    connector.credentials_json = after
                    updated += 1
                if credentials_are_encrypted(after):
                    encrypted += 1
            await session.commit()
    finally:
        await engine.dispose()
    return {"scanned": scanned, "updated": updated, "encrypted": encrypted}


def run_mcp(args: argparse.Namespace) -> int:
    from app.mcp.server import run_mcp_server
    import asyncio
    asyncio.run(run_mcp_server())
    return 0


def _api_key(args: argparse.Namespace) -> str | None:
    return getattr(args, "api_key", None) or os.environ.get("CONTEXT_ENGINE_API_KEY") or None


def _alembic_config(database_url: str | None = None):
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def _run_alembic_command(name: str, config, revision: str | None = None) -> None:
    from alembic import command

    if name in {"upgrade", "stamp"}:
        if revision is None:
            raise ValueError(f"{name} requires a revision")
        getattr(command, name)(config, revision)
    else:
        getattr(command, name)(config)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parse_argv, worker_command = _split_harness_worker_argv(raw_argv)
    args = parser.parse_args(parse_argv)
    if worker_command is not None:
        args.worker_command = worker_command
    try:
        return int(args.func(args))
    except (APIError, Exception) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _split_harness_worker_argv(
    argv: list[str],
) -> tuple[list[str], list[str] | None]:
    if argv[:2] != ["harness", "run"]:
        return argv, None
    try:
        separator = argv.index("--", 2)
    except ValueError:
        return argv, []
    return argv[:separator], argv[separator + 1 :]


if __name__ == "__main__":
    raise SystemExit(main())
