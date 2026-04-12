from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from app.cli.http import APIError, api_request
from app.importers.base import ImporterError
from app.importers.generic import GenericFileScanner

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_LOCAL_WORKSPACE_NAME = "Local Workspace"
DEFAULT_DEMO_WORKSPACE_NAME = "Acme Accuracy Demo"
WORKSPACES_PATH = "/api/workspaces"
SEED_DEMO_PATH = "/api/seed-demo"
IMPORTS_PATH = "/api/imports"
QUERY_PATH = "/api/query"


class CLIError(RuntimeError):
    """Raised when CLI execution cannot continue."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctxe",
        description="Context Engine developer CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    up_parser = subparsers.add_parser(
        "up",
        help="Boot the local Docker stack and apply migrations.",
    )
    up_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL to check for readiness (default: {DEFAULT_BASE_URL})",
    )
    up_parser.add_argument(
        "--wait-timeout",
        type=int,
        default=90,
        help="Seconds to wait for /health/ready after boot (default: 90)",
    )
    up_parser.set_defaults(func=run_up)

    demo_parser = subparsers.add_parser(
        "demo",
        help="Boot the local Docker stack, apply migrations, and seed demo data via the HTTP API.",
    )
    demo_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL to check for readiness (default: {DEFAULT_BASE_URL})",
    )
    demo_parser.add_argument(
        "--wait-timeout",
        type=int,
        default=90,
        help="Seconds to wait for /health/ready after boot (default: 90)",
    )
    demo_parser.add_argument(
        "--workspace",
        help=(
            "Existing workspace name or UUID to seed. If omitted, ctxe seeds the canonical "
            f"demo workspace ({DEFAULT_DEMO_WORKSPACE_NAME})."
        ),
    )
    demo_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the raw JSON response.",
    )
    demo_parser.set_defaults(func=run_demo)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Import a local file or directory into Context Engine.",
    )
    ingest_parser.add_argument("path", help="File or directory to ingest")
    ingest_parser.add_argument(
        "--workspace",
        help="Workspace name or UUID. If omitted, ctxe will resolve or create a local workspace.",
    )
    ingest_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for the API (default: {DEFAULT_BASE_URL})",
    )
    ingest_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the raw JSON response.",
    )
    ingest_parser.set_defaults(func=run_ingest)

    query_parser = subparsers.add_parser(
        "query",
        help="Query structured context from the terminal.",
    )
    query_parser.add_argument("question", help="Question to send to the query API")
    query_parser.add_argument(
        "--workspace",
        help="Workspace name or UUID. If omitted, ctxe auto-resolves when unambiguous.",
    )
    query_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for the API (default: {DEFAULT_BASE_URL})",
    )
    query_parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Restrict the query to a model. Repeat to pass multiple models.",
    )
    query_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="Minimum confidence filter for components (default: 0.5)",
    )
    query_parser.add_argument(
        "--max-age-days",
        type=int,
        help="Exclude components older than this many days.",
    )
    query_parser.add_argument(
        "--as-of",
        help="Historical query timestamp in ISO-8601 format.",
    )
    query_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the raw JSON response.",
    )
    query_parser.set_defaults(func=run_query)

    return parser


def run_up(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    compose = resolve_compose_command(project_root)

    run_subprocess(
        [*compose, "up", "-d", "postgres", "redis", "api", "worker"],
        cwd=project_root,
    )
    run_subprocess_with_retries(
        [*compose, "exec", "-T", "api", "alembic", "upgrade", "head"],
        cwd=project_root,
        timeout_seconds=max(30, args.wait_timeout),
    )
    wait_for_ready(args.base_url, timeout_seconds=args.wait_timeout)

    print(f"Context Engine is ready at {args.base_url.rstrip('/')}")
    return 0


def run_demo(args: argparse.Namespace) -> int:
    run_up(args)

    workspace_id: str | None = None
    if args.workspace:
        workspace = resolve_workspace(
            args.base_url,
            selector=args.workspace,
            create_if_missing=False,
        )
        workspace_id = workspace["id"]

    response = api_request(
        args.base_url,
        "POST",
        SEED_DEMO_PATH,
        payload={"workspace_id": workspace_id} if workspace_id else {},
        timeout=60,
    )

    if args.json_output:
        print_json(response)
        return 0

    workspace_name = response.get("workspaceName", DEFAULT_DEMO_WORKSPACE_NAME)
    resolved_workspace_id = response.get("workspaceId", "unknown")
    status = response.get("status", "unknown")
    print(f"Demo workspace ready: {workspace_name} ({resolved_workspace_id}) [{status}]")
    return 0


def run_ingest(args: argparse.Namespace) -> int:
    scanner = GenericFileScanner()
    source_path = Path(args.path).expanduser()
    ok, error_message = scanner.validate_source(source_path)
    if not ok:
        raise CLIError(error_message or f"Invalid source path: {source_path}")

    workspace = resolve_workspace(
        args.base_url,
        selector=args.workspace,
        create_if_missing=True,
    )
    documents = [serialize_document(doc) for doc in scanner.ingest(source_path)]
    if not documents:
        raise CLIError(f"No readable text files found in {source_path}")

    response = api_request(
        args.base_url,
        "POST",
        IMPORTS_PATH,
        payload={
            "workspace_id": workspace["id"],
            "documents": documents,
        },
        timeout=120,
    )

    if args.json_output:
        print_json(response)
    else:
        print(
            f"Imported {response['total_documents']} documents into "
            f"{workspace['name']} ({workspace['id']})."
        )
        print(
            f"Created {response['created_documents']}, updated {response['updated_documents']}, "
            f"unchanged {response['unchanged_documents']}, processed {response['processed_documents']}."
        )
        if response["failed_documents"]:
            print(
                f"{response['failed_documents']} documents failed during processing.",
                file=sys.stderr,
            )
            for item in response["documents"]:
                if item.get("error"):
                    print(
                        f"- {item['label']}: {item['error']}",
                        file=sys.stderr,
                    )

    return 0 if response["failed_documents"] == 0 else 1


def run_query(args: argparse.Namespace) -> int:
    workspace = resolve_workspace(
        args.base_url,
        selector=args.workspace,
        create_if_missing=False,
    )

    payload: dict[str, Any] = {
        "question": args.question,
        "workspace_id": workspace["id"],
        "model_names": args.models,
        "min_confidence": args.min_confidence,
        "max_age_days": args.max_age_days,
        "as_of": args.as_of,
    }
    response = api_request(
        args.base_url,
        "POST",
        QUERY_PATH,
        payload=payload,
        timeout=60,
    )

    if args.json_output:
        print_json(response)
        return 0

    print(response["answer"])
    print(
        f"\nworkspace: {workspace['name']} | confidence: {response['confidence']} "
        f"| freshness: {response['freshness']}"
    )
    for source in response.get("sources", [])[:3]:
        label = source.get("url") or source.get("author") or source.get("type")
        print(f"source: {label}")
    return 0


def resolve_workspace(
    base_url: str,
    *,
    selector: str | None,
    create_if_missing: bool,
) -> dict[str, Any]:
    workspaces = api_request(base_url, "GET", WORKSPACES_PATH)

    if selector:
        workspace = resolve_workspace_selector(base_url, workspaces, selector)
        if workspace is not None:
            return workspace
        if create_if_missing and not looks_like_uuid(selector):
            return create_workspace(base_url, selector)
        raise CLIError(f"Workspace not found: {selector}")

    if len(workspaces) == 1:
        return workspaces[0]

    preferred = [
        workspace
        for workspace in workspaces
        if workspace["name"] in {DEFAULT_LOCAL_WORKSPACE_NAME, DEFAULT_DEMO_WORKSPACE_NAME}
    ]
    if len(preferred) == 1:
        return preferred[0]

    if not workspaces and create_if_missing:
        return create_workspace(base_url, DEFAULT_LOCAL_WORKSPACE_NAME)

    if not workspaces:
        raise CLIError("No workspaces found. Run 'ctxe ingest <path>' or 'ctxe demo' first.")

    names = ", ".join(workspace["name"] for workspace in workspaces)
    raise CLIError(
        "Multiple workspaces found; pass --workspace NAME_OR_UUID. "
        f"Available workspaces: {names}"
    )


def resolve_workspace_selector(
    base_url: str,
    workspaces: list[dict[str, Any]],
    selector: str,
) -> dict[str, Any] | None:
    if looks_like_uuid(selector):
        return api_request(base_url, "GET", f"{WORKSPACES_PATH}/{selector}")

    normalized = selector.strip().lower()
    matches = [workspace for workspace in workspaces if workspace["name"].strip().lower() == normalized]
    if len(matches) > 1:
        raise CLIError(f"Multiple workspaces matched {selector!r}; use a UUID instead.")
    return matches[0] if matches else None


def create_workspace(base_url: str, name: str) -> dict[str, Any]:
    return api_request(
        base_url,
        "POST",
        WORKSPACES_PATH,
        payload={
            "name": name,
            "description": "Workspace created by the ctxe CLI.",
        },
    )


def serialize_document(document) -> dict[str, Any]:
    return {
        "external_id": document.external_id,
        "content": document.content,
        "author": document.author,
        "source_url": document.source_url,
        "created_at_source": document.created_at.isoformat() if document.created_at else None,
        "metadata": document.metadata or {},
    }


def looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def find_project_root() -> Path:
    current = Path.cwd().resolve()
    candidates = [current, *current.parents]
    module_root = Path(__file__).resolve().parent
    candidates.extend([module_root, *module_root.parents])
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "docker-compose.yml").exists():
            return candidate
    raise CLIError("Could not find the project root containing pyproject.toml and docker-compose.yml")


def resolve_compose_command(project_root: Path) -> list[str]:
    candidates = (["docker", "compose"], ["docker-compose"])
    for candidate in candidates:
        try:
            subprocess.run(
                [*candidate, "version"],
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise CLIError("Docker Compose is required for 'ctxe up' and 'ctxe demo'")


def run_subprocess(
    command: list[str],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise CLIError(stderr or f"Command failed: {' '.join(command)}") from exc


def run_subprocess_with_retries(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    interval_seconds: int = 3,
) -> subprocess.CompletedProcess[str]:
    deadline = time.monotonic() + timeout_seconds
    last_error: CLIError | None = None
    while time.monotonic() < deadline:
        try:
            return run_subprocess(command, cwd=cwd, capture_output=True)
        except CLIError as exc:
            last_error = exc
            time.sleep(interval_seconds)
    if last_error is not None:
        raise last_error
    raise CLIError(f"Command timed out: {' '.join(command)}")


def wait_for_ready(base_url: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            ready = api_request(base_url, "GET", "/health/ready", timeout=5)
        except Exception as exc:  # pragma: no cover - exercised through CLI integration
            last_error = exc
            time.sleep(2)
            continue
        if ready.get("status") == "ready":
            return
        time.sleep(2)
    if last_error is not None:
        raise CLIError(f"Timed out waiting for Context Engine readiness: {last_error}")
    raise CLIError("Timed out waiting for Context Engine readiness")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (APIError, CLIError, ImporterError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
