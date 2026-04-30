from __future__ import annotations

import argparse
import json
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
    ingest_parser.add_argument("--sync", action="store_true", help="Process synchronously")
    ingest_parser.add_argument("--json", action="store_true", dest="json_output")
    ingest_parser.set_defaults(func=run_ingest)

    query_parser = subparsers.add_parser("query", help="Query structured context.")
    query_parser.add_argument("question", help="Question to ask")
    query_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    query_parser.add_argument("--json", action="store_true", dest="json_output")
    query_parser.set_defaults(func=run_query)

    graph_parser = subparsers.add_parser("graph", help="Get knowledge graph.")
    graph_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    graph_parser.add_argument("--json", action="store_true", dest="json_output")
    graph_parser.set_defaults(func=run_graph)

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
        if len(payload["documents"]) == 1:
            resp = api_request(args.base_url, "POST", "/api/sources", payload=payload["documents"][0])
        else:
            resp = api_request(args.base_url, "POST", "/api/sources/bulk", payload=payload)
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
        resp = api_request(args.base_url, "POST", "/api/query", payload={"question": args.question})
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
        resp = api_request(args.base_url, "GET", "/api/graph")
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


def run_mcp(args: argparse.Namespace) -> int:
    from app.mcp.server import run_mcp_server
    import asyncio
    asyncio.run(run_mcp_server())
    return 0


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
