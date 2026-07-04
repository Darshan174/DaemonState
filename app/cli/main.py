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
    query_parser.add_argument("--json", action="store_true", dest="json_output")
    query_parser.set_defaults(func=run_query)

    graph_parser = subparsers.add_parser("graph", help="Get knowledge graph.")
    graph_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    graph_parser.add_argument("--api-key", default=None, help="API key for protected servers")
    graph_parser.add_argument("--json", action="store_true", dest="json_output")
    graph_parser.set_defaults(func=run_graph)

    prepare_parser = subparsers.add_parser("prepare", help="Compile a Context Pack v2 for an agent task.")
    prepare_parser.add_argument("goal", help="Goal or task objective to prepare context for")
    prepare_parser.add_argument("--repo", default=".", help="Repository path to inspect")
    prepare_parser.add_argument("--target-model", default=None)
    prepare_parser.add_argument("--budget", type=int, default=None, help="Context token budget")
    prepare_parser.add_argument("--workspace-id", default=None)
    prepare_parser.add_argument("--out", default=None, help="Write markdown context pack to this path")
    prepare_parser.add_argument("--manifest-out", default=None, help="Write manifest JSON to this path")
    prepare_parser.add_argument("--json", action="store_true", dest="json_output")
    prepare_parser.set_defaults(func=run_prepare)

    repo_parser = subparsers.add_parser("repo", help="Inspect or index a local repository.")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command", required=True)
    repo_index_parser = repo_subparsers.add_parser("index", help="Build a lightweight local repo index.")
    repo_index_parser.add_argument("path", nargs="?", default=".")
    repo_index_parser.add_argument("--json", action="store_true", dest="json_output")
    repo_index_parser.set_defaults(func=run_repo)

    eval_parser = subparsers.add_parser("eval", help="Run local quality evals.")
    eval_parser.add_argument("suite", choices=["extraction"], help="Eval suite to run")
    eval_parser.add_argument("--json", action="store_true", dest="json_output")
    eval_parser.set_defaults(func=run_eval)

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
    try:
        resp = api_request(
            args.base_url,
            "POST",
            "/api/query",
            payload={"question": args.question},
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


def run_prepare(args: argparse.Namespace) -> int:
    import asyncio

    from app.services.context_compiler import ContextCompiler

    async def _run():
        compiler = ContextCompiler()
        return await compiler.compile_context_pack(
            args.goal,
            workspace_id=args.workspace_id,
            repo_path=args.repo,
            target_model=args.target_model,
            token_budget=args.budget,
        )

    result = asyncio.run(_run())
    if args.out:
        Path(args.out).expanduser().write_text(result.markdown, encoding="utf-8")
    if args.manifest_out:
        Path(args.manifest_out).expanduser().write_text(
            json.dumps(result.manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif args.out:
        print(f"Wrote context pack: {args.out}")
        if args.manifest_out:
            print(f"Wrote manifest: {args.manifest_out}")
    else:
        print(result.markdown)
    return 0


def run_repo(args: argparse.Namespace) -> int:
    from app.services.repo_indexer import RepoIndexer

    if args.repo_command != "index":
        print(f"Unknown repo command: {args.repo_command}", file=sys.stderr)
        return 1

    index = RepoIndexer().index(args.path)
    data = index.to_dict()
    data["persistence"] = {
        "available": False,
        "reason": "Repo intelligence persistence tables are unavailable in this checkout.",
    }
    if args.json_output:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(
            "repo index: "
            f"files={len(index.files)} "
            f"symbols={len(index.symbols)} "
            f"tests={len(index.test_files)} "
            f"manifests={len(index.package_manifests)}"
        )
    return 0


def run_eval(args: argparse.Namespace) -> int:
    if args.suite == "extraction":
        from app.evals.extraction import run_extraction_eval
        report = run_extraction_eval()
    else:
        print(f"Unknown eval suite: {args.suite}", file=sys.stderr)
        return 1

    data = report.to_dict()
    if args.json_output:
        print(json.dumps(data, indent=2))
    else:
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
    return 0 if data["failed_count"] == 0 else 1


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
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (APIError, Exception) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
