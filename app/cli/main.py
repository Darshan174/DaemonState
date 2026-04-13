from __future__ import annotations

import argparse
import base64
import json
import os
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
DEFAULT_VERIFY_QUESTION = "What is the Starter Plan?"
DEFAULT_VERIFY_EXPECT = "$29"
HEALTH_PATH = "/health"
READINESS_PATH = "/health/ready"
WORKSPACES_PATH = "/api/workspaces"
SEED_DEMO_PATH = "/api/seed-demo"
IMPORTS_PATH = "/api/imports"
FOUNDER_BRIEF_PATH = "/api/founder-brief"
QUERY_PATH = "/api/query"
DECISIONS_PATH = "/api/decisions"
SOURCE_DOCUMENTS_PATH = "/api/source-documents"
VERIFY_PHASES = (
    "boot",
    "readiness",
    "seed",
    "smoke",
    "contract-tests",
    "frontend-tests",
    "frontend-build",
)
FRONTEND_VERIFY_PHASES = ("frontend-tests", "frontend-build")
VERIFY_TEST_TARGETS = (
    "tests/test_cli/test_main.py",
    "tests/test_cli/test_http.py",
    "tests/test_api/test_imports.py",
    "tests/test_api/test_admin.py::TestSeedDemoAPI",
    "tests/test_api/test_connectors_upload.py",
    "tests/test_api/test_trust.py",
    "tests/test_api/test_truth_regression.py",
    "tests/test_api/test_query.py",
    "tests/test_api/test_briefing.py",
)
DEFAULT_VERIFY_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine_verify",
)


class CLIError(RuntimeError):
    """Raised when CLI execution cannot continue."""


class VerifyPhaseError(CLIError):
    """Raised when a specific verification phase fails."""

    def __init__(
        self,
        phase: str,
        detail: str,
        *,
        next_step: str,
        completed_steps: list[dict[str, str]] | None = None,
        selected_phases: list[str] | None = None,
    ) -> None:
        message = f"verify failed during {phase}: {detail}"
        if next_step:
            message = f"{message}. Next step: {next_step}"
        super().__init__(message)
        self.phase = phase
        self.detail = detail
        self.next_step = next_step
        self.completed_steps = list(completed_steps or [])
        self.selected_phases = list(selected_phases or [])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctxe",
        description="Context Engine OSS operator CLI.",
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

    verify_parser = subparsers.add_parser(
        "verify",
        help="Run the OSS v1 release gate: boot, readiness, demo seed, smoke, contract tests, and frontend checks.",
        description=(
            "Run the OSS v1 release gate in canonical phase order. "
            "On failure, ctxe reports the failing phase, completed phases, and the next command to run."
        ),
    )
    verify_parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL to check for readiness (default: {DEFAULT_BASE_URL})",
    )
    verify_parser.add_argument(
        "--wait-timeout",
        type=int,
        default=90,
        help="Seconds to wait for /health/ready after boot (default: 90)",
    )
    verify_parser.add_argument(
        "--phase",
        action="append",
        choices=VERIFY_PHASES,
        dest="phases",
        help=(
            "Run only the selected verify phase. Repeat to run multiple phases; "
            "default is the full canonical release gate."
        ),
    )
    verify_parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip frontend test/build checks and run the backend release gate only.",
    )
    verify_parser.add_argument(
        "--test-database-url",
        default=DEFAULT_VERIFY_TEST_DATABASE_URL,
        help=(
            "Dedicated TEST_DATABASE_URL used by the contract-tests phase "
            "(default: %(default)s)"
        ),
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the verification summary as JSON.",
    )
    verify_parser.set_defaults(func=run_verify)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Import a local file or directory into Context Engine.",
    )
    ingest_parser.add_argument("path", help="File or directory to ingest")
    ingest_parser.add_argument(
        "--workspace",
        help=(
            "Workspace name or UUID. If omitted, ctxe uses the only workspace, "
            "creates Local Workspace when none exist, and fails when multiple exist."
        ),
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
        help=(
            "Workspace name or UUID. If omitted, ctxe uses the only workspace "
            "and fails when none or multiple exist."
        ),
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
    boot_stack(args.base_url, wait_timeout=args.wait_timeout)
    print(f"Context Engine is ready at {args.base_url.rstrip('/')}")
    return 0


def run_demo(args: argparse.Namespace) -> int:
    boot_stack(args.base_url, wait_timeout=args.wait_timeout)

    workspace_id: str | None = None
    if args.workspace:
        workspace = resolve_workspace(
            args.base_url,
            selector=args.workspace,
            create_if_missing=False,
        )
        workspace_id = workspace["id"]

    response = validate_seed_demo_response(
        seed_demo_workspace(args.base_url, workspace_id=workspace_id),
        context=f"POST {SEED_DEMO_PATH}",
    )

    if args.json_output:
        print_json(response)
        return 0

    workspace_name = response.get("workspaceName", DEFAULT_DEMO_WORKSPACE_NAME)
    resolved_workspace_id = response.get("workspaceId", "unknown")
    status = response.get("status", "unknown")
    print(f"Demo workspace ready: {workspace_name} ({resolved_workspace_id}) [{status}]")
    return 0


def run_verify(args: argparse.Namespace) -> int:
    selected_phases = resolve_verify_phases(args)
    skipped_phases = [phase for phase in VERIFY_PHASES if phase not in selected_phases]
    results: list[dict[str, str]] = []
    project_root = find_project_root()

    if not args.json_output:
        print(f"verify phases: {', '.join(selected_phases)}")
        if skipped_phases:
            print(f"skipped phases: {', '.join(skipped_phases)}")

    if "boot" in selected_phases:
        project_root = _verify_phase(
            "boot",
            lambda: boot_stack(args.base_url, wait_timeout=args.wait_timeout, quiet=True),
            next_step=_verify_phase_next_step("boot", base_url=args.base_url),
            results=results,
            selected_phases=selected_phases,
        )
        _record_verify_result(
            results,
            step="boot",
            detail=f"docker services, migrations, and API boot completed at {args.base_url.rstrip('/')}",
            json_output=args.json_output,
        )

    if "readiness" in selected_phases:
        health, readiness = _verify_phase(
            "readiness",
            lambda: check_verify_readiness(args.base_url),
            next_step=_verify_phase_next_step("readiness", base_url=args.base_url),
            results=results,
            selected_phases=selected_phases,
        )
        readiness_checks = readiness.get("checks", {})
        _record_verify_result(
            results,
            step="readiness",
            detail=(
                f"/health={health.get('status')} | /health/ready={readiness.get('status')} "
                f"(database={readiness_checks.get('database', 'unknown')}, "
                f"redis={readiness_checks.get('redis', 'unknown')})"
            ),
            json_output=args.json_output,
        )

    if "seed" in selected_phases:
        seed = _verify_phase(
            "seed",
            lambda: validate_seed_demo_response(
                seed_demo_workspace(args.base_url),
                context=f"POST {SEED_DEMO_PATH}",
            ),
            next_step=_verify_phase_next_step("seed", base_url=args.base_url),
            results=results,
            selected_phases=selected_phases,
        )
        _record_verify_result(
            results,
            step="seed",
            detail=f"{seed['workspaceName']} ({seed['workspaceId']}) [{seed['status']}]",
            json_output=args.json_output,
        )

    if "smoke" in selected_phases:
        smoke = _verify_phase(
            "smoke",
            lambda: run_subprocess(
                ["bash", "scripts/smoke.sh"],
                cwd=project_root,
                capture_output=True,
                env={
                    "BASE_URL": args.base_url,
                    "SMOKE_QUESTION": DEFAULT_VERIFY_QUESTION,
                    "SMOKE_EXPECT": DEFAULT_VERIFY_EXPECT,
                },
            ),
            next_step=_verify_phase_next_step("smoke", base_url=args.base_url),
            results=results,
            selected_phases=selected_phases,
        )
        _record_verify_result(
            results,
            step="smoke",
            detail=_last_output_line(smoke.stdout) or "backend founder workflows passed",
            json_output=args.json_output,
        )

    if "contract-tests" in selected_phases:
        contract_tests = _verify_phase(
            "contract-tests",
            lambda: run_subprocess(
                [sys.executable, "-m", "pytest", *VERIFY_TEST_TARGETS, "-q"],
                cwd=project_root,
                capture_output=True,
                env={"TEST_DATABASE_URL": args.test_database_url},
            ),
            next_step=_verify_phase_next_step("contract-tests", base_url=args.base_url),
            results=results,
            selected_phases=selected_phases,
        )
        _record_verify_result(
            results,
            step="contract-tests",
            detail=(
                _last_output_line(contract_tests.stdout)
                or f"contract tests passed against {args.test_database_url}"
            ),
            json_output=args.json_output,
        )

    if any(phase in selected_phases for phase in FRONTEND_VERIFY_PHASES):
        frontend_dir = project_root / "frontend"
        if "frontend-tests" in selected_phases:
            frontend_tests = _verify_phase(
                "frontend-tests",
                lambda: run_subprocess(
                    ["npm", "test"],
                    cwd=frontend_dir,
                    capture_output=True,
                ),
                next_step=_verify_phase_next_step("frontend-tests", base_url=args.base_url),
                results=results,
                selected_phases=selected_phases,
            )
            _record_verify_result(
                results,
                step="frontend-tests",
                detail=_last_output_line(frontend_tests.stdout) or "frontend tests passed",
                json_output=args.json_output,
            )

        if "frontend-build" in selected_phases:
            frontend_build = _verify_phase(
                "frontend-build",
                lambda: run_subprocess(
                    ["npm", "run", "build"],
                    cwd=frontend_dir,
                    capture_output=True,
                ),
                next_step=_verify_phase_next_step("frontend-build", base_url=args.base_url),
                results=results,
                selected_phases=selected_phases,
            )
            _record_verify_result(
                results,
                step="frontend-build",
                detail=_last_output_line(frontend_build.stdout) or "frontend build passed",
                json_output=args.json_output,
            )

    if args.json_output:
        print_json(
            {
                "status": "ok",
                "selected_phases": selected_phases,
                "skipped_phases": skipped_phases,
                "steps": results,
            }
        )
        return 0

    print("\nOSS v1 verification passed.")
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

    response = validate_import_response(
        api_request(
            args.base_url,
            "POST",
            IMPORTS_PATH,
            payload={
                "workspace_id": workspace["id"],
                "documents": documents,
            },
            timeout=120,
        ),
        context=f"POST {IMPORTS_PATH}",
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
    response = validate_query_response(
        api_request(
            args.base_url,
            "POST",
            QUERY_PATH,
            payload=payload,
            timeout=60,
        ),
        context=f"POST {QUERY_PATH}",
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
    if selector is not None and not selector.strip():
        raise CLIError("Workspace selector cannot be blank.")

    workspaces = list_workspaces(base_url)

    if selector:
        workspace = resolve_workspace_selector(base_url, workspaces, selector)
        if workspace is not None:
            return workspace
        if create_if_missing and not looks_like_uuid(selector):
            return create_workspace(base_url, selector.strip())
        available = format_workspace_options(workspaces)
        if workspaces:
            raise CLIError(
                f"Workspace not found: {selector}. Available workspaces: {available}"
            )
        raise CLIError(
            f"Workspace not found: {selector}. No workspaces exist yet. "
            "Run 'ctxe demo' for sample data or 'ctxe ingest <path>' to create a workspace."
        )

    if len(workspaces) == 1:
        return workspaces[0]

    if not workspaces and create_if_missing:
        return create_workspace(base_url, DEFAULT_LOCAL_WORKSPACE_NAME)

    if not workspaces:
        raise CLIError(
            "No workspaces found. Run 'ctxe demo' for sample data or "
            "'ctxe ingest <path>' to create a workspace."
        )

    names = format_workspace_options(workspaces)
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
        try:
            return validate_workspace_response(
                api_request(base_url, "GET", f"{WORKSPACES_PATH}/{selector}"),
                context=f"GET {WORKSPACES_PATH}/{selector}",
            )
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    normalized = selector.strip().lower()
    matches = [workspace for workspace in workspaces if workspace["name"].strip().lower() == normalized]
    if len(matches) > 1:
        raise CLIError(
            f"Multiple workspaces matched {selector!r}; use a UUID instead. "
            f"Matches: {format_workspace_options(matches)}"
        )
    return matches[0] if matches else None


def list_workspaces(base_url: str) -> list[dict[str, Any]]:
    workspaces = api_request(base_url, "GET", WORKSPACES_PATH)
    if not isinstance(workspaces, list):
        raise CLIError(f"GET {WORKSPACES_PATH} returned an unexpected response shape.")
    return [
        validate_workspace_response(item, context=f"GET {WORKSPACES_PATH}")
        for item in workspaces
    ]


def create_workspace(base_url: str, name: str) -> dict[str, Any]:
    return validate_workspace_response(
        api_request(
            base_url,
            "POST",
            WORKSPACES_PATH,
            payload={
                "name": name,
                "description": "Workspace created by the ctxe CLI.",
            },
        ),
        context=f"POST {WORKSPACES_PATH}",
    )


def validate_workspace_response(payload: Any, *, context: str) -> dict[str, Any]:
    data = require_mapping(payload, context=context)
    workspace_id = data.get("id")
    workspace_name = data.get("name")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise CLIError(f"{context} response missing 'id'.")
    if not isinstance(workspace_name, str) or not workspace_name.strip():
        raise CLIError(f"{context} response missing 'name'.")
    return data


def validate_seed_demo_response(payload: Any, *, context: str) -> dict[str, Any]:
    data = require_mapping(payload, context=context)
    for key in ("workspaceId", "workspaceName", "status", "seededCaseCount"):
        if key not in data:
            raise CLIError(f"{context} response missing '{key}'.")
    return data


def validate_import_response(payload: Any, *, context: str) -> dict[str, Any]:
    data = require_mapping(payload, context=context)
    required_keys = (
        "total_documents",
        "created_documents",
        "updated_documents",
        "unchanged_documents",
        "processed_documents",
        "failed_documents",
        "documents",
    )
    for key in required_keys:
        if key not in data:
            raise CLIError(f"{context} response missing '{key}'.")
    if not isinstance(data["documents"], list):
        raise CLIError(f"{context} response field 'documents' must be a list.")
    return data


def validate_query_response(payload: Any, *, context: str) -> dict[str, Any]:
    data = require_mapping(payload, context=context)
    for key in ("answer", "confidence", "freshness"):
        if key not in data:
            raise CLIError(f"{context} response missing '{key}'.")
    sources = data.get("sources")
    if sources is not None and not isinstance(sources, list):
        raise CLIError(f"{context} response field 'sources' must be a list when present.")
    return data


def resolve_verify_phases(args: argparse.Namespace) -> list[str]:
    requested = set(args.phases or VERIFY_PHASES)
    if args.skip_frontend and args.phases and requested.intersection(FRONTEND_VERIFY_PHASES):
        raise CLIError("--skip-frontend cannot be combined with --phase frontend-tests/frontend-build.")
    if args.skip_frontend:
        requested = requested.difference(FRONTEND_VERIFY_PHASES)

    selected = [phase for phase in VERIFY_PHASES if phase in requested]
    if not selected:
        raise CLIError("No verify phases selected.")
    return selected


def check_verify_readiness(base_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    health = require_mapping(
        api_request(base_url, "GET", HEALTH_PATH, timeout=10),
        context=f"GET {HEALTH_PATH}",
    )
    if health.get("status") != "ok":
        raise CLIError(f"GET {HEALTH_PATH} did not return status=ok.")

    readiness = require_mapping(
        api_request(base_url, "GET", READINESS_PATH, timeout=10),
        context=f"GET {READINESS_PATH}",
    )
    if readiness.get("status") != "ready":
        raise CLIError(f"GET {READINESS_PATH} did not return status=ready.")
    return health, readiness


def require_mapping(payload: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CLIError(f"{context} returned an unexpected response shape.")
    return payload


def format_workspace_options(workspaces: list[dict[str, Any]]) -> str:
    if not workspaces:
        return "(none)"
    return ", ".join(
        f"{workspace['name']} ({workspace['id']})"
        for workspace in workspaces
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


def _last_output_line(output: str | None) -> str | None:
    if not output:
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _record_verify_result(
    results: list[dict[str, str]],
    *,
    step: str,
    detail: str,
    json_output: bool,
) -> None:
    item = {"step": step, "status": "ok", "detail": detail}
    results.append(item)
    if not json_output:
        print(f"{step}: {detail}")


def _verify_phase(
    name: str,
    fn,
    *,
    next_step: str,
    results: list[dict[str, str]],
    selected_phases: list[str],
):
    try:
        return fn()
    except (APIError, CLIError) as exc:
        detail = str(exc).strip() or f"{name} failed"
        raise VerifyPhaseError(
            name,
            detail,
            next_step=next_step,
            completed_steps=results,
            selected_phases=selected_phases,
        ) from exc


def _verify_phase_next_step(name: str, *, base_url: str) -> str:
    base = base_url.rstrip("/")
    next_steps = {
        "boot": "run 'docker compose ps' and 'docker compose logs --tail 40 api'",
        "readiness": f"probe '{base}{HEALTH_PATH}' and '{base}{READINESS_PATH}', then inspect 'docker compose logs --tail 40 api postgres redis'",
        "seed": f"rerun 'curl -X POST {base}{SEED_DEMO_PATH} -H \"Content-Type: application/json\" -d \"{{}}\"'",
        "smoke": "rerun 'bash scripts/smoke.sh' for the full backend founder-workflow trace",
        "contract-tests": (
            "ensure dropdb/createdb/psql are installed and TEST_DATABASE_URL points at a disposable "
            f"database, then rerun 'python3 -m pytest {' '.join(VERIFY_TEST_TARGETS)} -q'"
        ),
        "frontend-tests": "rerun 'cd frontend && npm test'",
        "frontend-build": "rerun 'cd frontend && npm run build'",
    }
    return next_steps.get(name, "inspect the preceding step output and rerun the failing phase")


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
    raise CLIError("Docker Compose is required for 'ctxe up', 'ctxe demo', and 'ctxe verify'")


def ensure_local_env(project_root: Path) -> None:
    env_path = project_root / ".env"
    env_example_path = project_root / ".env.example"

    if not env_path.exists():
        if not env_example_path.exists():
            raise CLIError("Missing .env and .env.example; cannot bootstrap the local stack.")
        env_path.write_text(env_example_path.read_text(encoding="utf-8"), encoding="utf-8")

    contents = env_path.read_text(encoding="utf-8")
    lines = contents.splitlines()
    key_prefix = "ENCRYPTION_KEY="
    updated = False
    found_key = False

    for index, line in enumerate(lines):
        if not line.startswith(key_prefix):
            continue
        found_key = True
        if line[len(key_prefix):].strip():
            break
        lines[index] = f"{key_prefix}{generate_encryption_key()}"
        updated = True
        break

    if not found_key:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"{key_prefix}{generate_encryption_key()}")
        updated = True

    if updated:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def boot_stack(base_url: str, *, wait_timeout: int, quiet: bool = False) -> Path:
    project_root = find_project_root()
    ensure_local_env(project_root)
    compose = resolve_compose_command(project_root)

    run_subprocess(
        [*compose, "up", "-d", "--build", "postgres", "redis", "api", "worker"],
        cwd=project_root,
        capture_output=quiet,
    )
    run_subprocess_with_retries(
        [*compose, "exec", "-T", "api", "alembic", "upgrade", "head"],
        cwd=project_root,
        timeout_seconds=max(30, wait_timeout),
        capture_output=True,
    )
    wait_for_ready(base_url, timeout_seconds=wait_timeout)
    return project_root


def seed_demo_workspace(base_url: str, *, workspace_id: str | None = None) -> dict[str, Any]:
    return api_request(
        base_url,
        "POST",
        SEED_DEMO_PATH,
        payload={"workspace_id": workspace_id} if workspace_id else {},
        timeout=60,
    )


def run_subprocess(
    command: list[str],
    *,
    cwd: Path,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture_output,
            env={**os.environ, **env} if env is not None else None,
        )
    except FileNotFoundError as exc:
        raise CLIError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        raise CLIError(stderr or stdout or f"Command failed: {' '.join(command)}") from exc


def run_subprocess_with_retries(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    interval_seconds: int = 3,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    deadline = time.monotonic() + timeout_seconds
    last_error: CLIError | None = None
    while time.monotonic() < deadline:
        try:
            return run_subprocess(command, cwd=cwd, capture_output=capture_output)
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
            ready = require_mapping(
                api_request(base_url, "GET", READINESS_PATH, timeout=5),
                context=f"GET {READINESS_PATH}",
            )
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
        if getattr(args, "json_output", False):
            payload = {"status": "error", "detail": str(exc)}
            if isinstance(exc, VerifyPhaseError):
                payload["phase"] = exc.phase
                payload["next_step"] = exc.next_step
                payload["selected_phases"] = exc.selected_phases
                payload["skipped_phases"] = [
                    phase for phase in VERIFY_PHASES if phase not in exc.selected_phases
                ]
                payload["completed_steps"] = exc.completed_steps
            print_json(payload)
        else:
            if isinstance(exc, VerifyPhaseError):
                if exc.selected_phases:
                    print(f"verify phases: {', '.join(exc.selected_phases)}", file=sys.stderr)
                skipped_phases = [phase for phase in VERIFY_PHASES if phase not in exc.selected_phases]
                if skipped_phases:
                    print(f"skipped phases: {', '.join(skipped_phases)}", file=sys.stderr)
                if exc.completed_steps:
                    completed = ", ".join(step["step"] for step in exc.completed_steps)
                    print(f"completed phases: {completed}", file=sys.stderr)
                print(f"verify failed during {exc.phase}: {exc.detail}", file=sys.stderr)
                print(f"next step: {exc.next_step}", file=sys.stderr)
            else:
                print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
