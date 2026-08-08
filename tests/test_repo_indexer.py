from __future__ import annotations

import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import CodeEdge, CodeFile, CodeSymbol, Workspace
from app.services import repo_indexer
from app.services.repo_indexer import RepoIndexer


def test_git_state_preserves_porcelain_index_and_worktree_columns(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "index.py").write_text("index = True\n", encoding="utf-8")
    (tmp_path / "worktree.py").write_text("worktree = True\n", encoding="utf-8")

    def fake_git(_root, *args):
        command = tuple(args)
        if command == ("rev-parse", "--is-inside-work-tree"):
            return "true\n"
        if command == ("status", "--short"):
            return "M  index.py\n M worktree.py\n?? notes.txt\n"
        if command == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main\n"
        if command == ("rev-parse", "HEAD"):
            return "a" * 40
        return ""

    monkeypatch.setattr(repo_indexer, "_git", fake_git)

    state = repo_indexer._git_state(tmp_path)

    assert [item["status"] for item in state["changed_files"]] == [
        "M ",
        " M",
        "??",
    ]


async def test_repo_frame_reports_bounded_head_vs_worktree_semantic_delta(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "workspace-foundation@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Workspace Foundation Test"],
        cwd=tmp_path,
        check=True,
    )
    service = tmp_path / "service.py"
    service.write_text(
        "def run_service():\n"
        "    return 'old'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "service.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
    )

    service.write_text(
        "import json\n\n"
        "class ServiceResult:\n"
        "    pass\n\n"
        "def run_service():\n"
        "    return json.dumps({'status': 'new'})\n",
        encoding="utf-8",
    )
    (tmp_path / "test_service.py").write_text(
        "def test_run_service():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    changes = {item["path"]: item for item in frame.changed_files}
    service_delta = changes["service.py"]["semantic_delta"]

    assert service_delta["observer"] == "head_vs_worktree_syntax.v1"
    assert service_delta["status"] == "observed"
    assert service_delta["parser_coverage"] == "parsed"
    assert service_delta["parser_languages"] == ["python"]
    assert service_delta["complete"] is True
    assert service_delta["lines_added"] > 0
    assert service_delta["lines_removed"] > 0
    assert service_delta["symbols_added"] == ["class:ServiceResult"]
    assert service_delta["symbols_modified"] == ["function:run_service"]
    assert service_delta["imports_added"] == ["json"]

    untracked_delta = changes["test_service.py"]["semantic_delta"]
    assert untracked_delta["status"] == "observed"
    assert untracked_delta["lines_added"] == 2
    assert untracked_delta["symbols_added"] == ["function:test_run_service"]


async def test_semantic_delta_for_unsupported_language_is_explicitly_line_only(
    tmp_path,
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "workspace-foundation@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Workspace Foundation Test"],
        cwd=tmp_path,
        check=True,
    )
    source = tmp_path / "Application.swift"
    source.write_text("struct Application {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "Application.swift"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
    )
    source.write_text(
        "struct Application {\n    let enabled = true\n}\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    delta = next(
        item["semantic_delta"]
        for item in frame.changed_files
        if item["path"] == "Application.swift"
    )

    assert delta["status"] == "partial"
    assert delta["parser_coverage"] == "line_only"
    assert delta["parser_languages"] == ["swift"]
    assert delta["complete"] is False
    assert delta["lines_added"] is not None
    assert delta["lines_removed"] is not None
    assert not any(key.startswith("symbols_") for key in delta)


async def test_indexes_python_files_symbols_and_routes(tmp_path):
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "api.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "class Worker:\n"
        "    pass\n\n"
        "@router.post('/items')\n"
        "async def create_item(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text(
        "def test_create_item():\n    assert True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    api_file = next(item for item in frame.indexed_files if item.path == "app/api.py")
    names = {symbol.name for symbol in api_file.symbols}
    assert {"Worker", "create_item", "POST /items"} <= names
    assert "fastapi.APIRouter" in api_file.imports
    assert "tests/test_api.py" in frame.test_files
    assert frame.persistence_available is False


async def test_indexes_conservative_python_local_call_hints(tmp_path):
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "service.py").write_text(
        "def run_service(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    (app_dir / "api.py").write_text(
        "from .service import run_service as execute\n"
        "import app.service as service_module\n\n"
        "def local_helper(payload):\n"
        "    return payload\n\n"
        "async def create_item(payload):\n"
        "    first = execute(payload)\n"
        "    second = service_module.run_service(first)\n"
        "    return local_helper(second)\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    api_file = next(item for item in frame.indexed_files if item.path == "app/api.py")

    assert [
        (
            item.caller_name,
            item.target_name,
            item.target_specifier,
            item.binding_kind,
            item.start_line,
        )
        for item in api_file.call_hints
    ] == [
        ("create_item", "run_service", ".service", "imported_symbol", 8),
        ("create_item", "run_service", "app.service", "imported_module", 9),
        ("create_item", "local_helper", None, "local_symbol", 10),
    ]


async def test_python_call_hints_reject_shadowed_and_reassigned_bindings(tmp_path):
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "service.py").write_text(
        "def run_service(payload):\n    return payload\n",
        encoding="utf-8",
    )
    (app_dir / "parameter_shadow.py").write_text(
        "from .service import run_service as execute\n"
        "import app.service as service_module\n\n"
        "def local_helper(payload):\n"
        "    return payload\n\n"
        "def run(execute, service_module, local_helper, payload):\n"
        "    execute(payload)\n"
        "    service_module.run_service(payload)\n"
        "    return local_helper(payload)\n",
        encoding="utf-8",
    )
    (app_dir / "local_shadow.py").write_text(
        "from .service import run_service as execute\n"
        "import app.service as service_module\n\n"
        "def local_helper(payload):\n"
        "    return payload\n\n"
        "def run(payload):\n"
        "    execute = payload\n"
        "    service_module = payload\n"
        "    local_helper = payload\n"
        "    execute(payload)\n"
        "    service_module.run_service(payload)\n"
        "    return local_helper(payload)\n",
        encoding="utf-8",
    )
    (app_dir / "module_reassignment.py").write_text(
        "from .service import run_service as execute\n"
        "execute = lambda payload: payload\n\n"
        "def run(payload):\n"
        "    return execute(payload)\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    for path in (
        "app/parameter_shadow.py",
        "app/local_shadow.py",
        "app/module_reassignment.py",
    ):
        indexed = next(item for item in frame.indexed_files if item.path == path)
        assert indexed.call_hints == []


async def test_python_call_hints_are_strictly_capped_per_file(tmp_path):
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    call_count = repo_indexer.MAX_INDEXED_CALL_HINTS_PER_FILE + 20
    calls = "".join("    helper()\n" for _index in range(call_count))
    (app_dir / "many_calls.py").write_text(
        "def helper():\n"
        "    return True\n\n"
        "def run():\n"
        f"{calls}",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    indexed = next(
        item for item in frame.indexed_files if item.path == "app/many_calls.py"
    )

    assert len(indexed.call_hints) == repo_indexer.MAX_INDEXED_CALL_HINTS_PER_FILE


async def test_indexes_typescript_imports_components_and_routes(tmp_path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "server.tsx").write_text(
        "import React from 'react';\n"
        "import express from 'express';\n"
        "const app = express();\n"
        "app.get('/health', () => true);\n"
        "export const StatusPanel = () => <div />;\n"
        "function helper() { return true; }\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    indexed = next(item for item in frame.indexed_files if item.path == "src/server.tsx")
    assert "react" in indexed.imports
    assert "GET /health" in indexed.route_hints
    symbols = {(symbol.symbol_type, symbol.name) for symbol in indexed.symbols}
    assert ("component", "StatusPanel") in symbols
    assert ("function", "helper") in symbols


async def test_indexes_static_javascript_http_method_and_path_references(tmp_path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "hooks.js").write_text(
        "import { api } from './client';\n"
        "export async function loadWorkspace(id) {\n"
        "  const workspace = await api.get(`/workspaces/${id}?include=true`);\n"
        "  await api.post('/continuations/prepare', workspace);\n"
        "  return workspace;\n"
        "}\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    hooks = next(item for item in frame.indexed_files if item.path == "src/hooks.js")

    assert [
        (item.method, item.path, item.start_line)
        for item in hooks.http_references
    ] == [
        ("GET", "/workspaces/{}", 3),
        ("POST", "/continuations/prepare", 4),
    ]


async def test_javascript_http_references_require_a_stable_proven_client(tmp_path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "declared.js").write_text(
        "import transport from 'axios';\n"
        "const workspaceTransport = transport.create({ baseURL: '/api' });\n"
        "workspaceTransport.get('/workspaces');\n",
        encoding="utf-8",
    )
    (src / "unknown.js").write_text(
        "const api = makeObject();\n"
        "api.get('/invented');\n",
        encoding="utf-8",
    )
    (src / "wrong_import.js").write_text(
        "import { api } from './formatters';\n"
        "api.get('/invented');\n",
        encoding="utf-8",
    )
    (src / "parameter_shadow.js").write_text(
        "import { api } from './client';\n"
        "function load(api) {\n"
        "  return api.get('/shadowed');\n"
        "}\n",
        encoding="utf-8",
    )
    (src / "local_shadow.js").write_text(
        "import { api } from './client';\n"
        "function load() {\n"
        "  const api = makeObject();\n"
        "  return api.get('/shadowed');\n"
        "}\n",
        encoding="utf-8",
    )
    (src / "reassigned.js").write_text(
        "import { client } from './http-client';\n"
        "client = makeObject();\n"
        "client.get('/shadowed');\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    by_path = {item.path: item for item in frame.indexed_files}

    assert [
        (item.method, item.path)
        for item in by_path["src/declared.js"].http_references
    ] == [("GET", "/workspaces")]
    for path in (
        "src/unknown.js",
        "src/wrong_import.js",
        "src/parameter_shadow.js",
        "src/local_shadow.js",
        "src/reassigned.js",
    ):
        assert by_path[path].http_references == []


async def test_javascript_http_references_are_strictly_capped_per_file(tmp_path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    reference_count = repo_indexer.MAX_INDEXED_HTTP_REFERENCES_PER_FILE + 20
    references = "".join(
        f"api.get('/items/{index}');\n" for index in range(reference_count)
    )
    (src / "many_requests.js").write_text(
        "import { api } from './client';\n" + references,
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    indexed = next(
        item for item in frame.indexed_files if item.path == "src/many_requests.js"
    )

    assert (
        len(indexed.http_references)
        == repo_indexer.MAX_INDEXED_HTTP_REFERENCES_PER_FILE
    )


async def test_regex_test_calls_do_not_turn_application_javascript_into_tests(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "NowPage.jsx").write_text(
        "export const valid = (value) => /continue/.test(value);\n",
        encoding="utf-8",
    )
    (src / "NowPage.test.jsx").write_text(
        "test('renders continuation', () => true);\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "conftest.py").write_text(
        "def shared_fixture():\n    return True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    assert "src/NowPage.jsx" not in frame.test_files
    assert "src/NowPage.test.jsx" in frame.test_files
    assert "tests/conftest.py" not in frame.test_files


async def test_automatic_context_ranking_excludes_agent_runs_and_fixtures(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "continuation.py").write_text(
        "def continue_workflow():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / ".agent-runs").mkdir()
    (tmp_path / ".agent-runs" / "continuation-workflow.md").write_text(
        "Continue the workflow.\n",
        encoding="utf-8",
    )
    fixture = (
        tmp_path
        / "app"
        / "evals"
        / "compiler"
        / "fixture_project"
        / "repo"
    )
    fixture.mkdir(parents=True)
    (fixture / "continuation.py").write_text(
        "def continue_fixture():\n    return True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    relevant = frame.relevant_files_for_goal(
        {"continue", "continuation", "workflow"},
        [],
    )

    assert [item["path"] for item in relevant] == ["app/continuation.py"]


async def test_git_index_respects_ignores_and_keeps_tracked_files(
    monkeypatch, tmp_path
):
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    (tmp_path / ".gitignore").write_text(
        ".next/\nignored-cache/\ntracked-cache/\n",
        encoding="utf-8",
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.ts").write_text(
        "export const value = 1;\n",
        encoding="utf-8",
    )
    generated_dir = tmp_path / ".next" / "dev"
    generated_dir.mkdir(parents=True)
    (generated_dir / "chunk.js").write_text("x" * 1_000, encoding="utf-8")
    ignored_dir = tmp_path / "ignored-cache"
    ignored_dir.mkdir()
    (ignored_dir / "data.json").write_text("x" * 1_000, encoding="utf-8")
    tracked_dir = tmp_path / "tracked-cache"
    tracked_dir.mkdir()
    (tracked_dir / "kept.ts").write_text(
        "export const kept = 1;\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--force", "tracked-cache/kept.ts"],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(repo_indexer, "MAX_INDEXED_BYTES", 80)

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    assert [item.path for item in frame.indexed_files] == [
        "src/main.ts",
        "tracked-cache/kept.ts",
    ]


async def test_filesystem_fallback_excludes_generated_directories(
    monkeypatch, tmp_path
):
    # An incomplete .git directory exercises the non-Git fallback used by local folders.
    (tmp_path / ".git").mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("value = 1\n", encoding="utf-8")
    generated_dir = tmp_path / ".next" / "dev"
    generated_dir.mkdir(parents=True)
    (generated_dir / "chunk.js").write_text("x" * 1_000, encoding="utf-8")
    monkeypatch.setattr(repo_indexer, "MAX_INDEXED_BYTES", 80)

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)

    assert [item.path for item in frame.indexed_files] == ["app/main.py"]


async def test_index_still_rejects_genuine_source_over_aggregate_limit(
    monkeypatch, tmp_path
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "one.py").write_text("x" * 30, encoding="utf-8")
    (tmp_path / "two.py").write_text("y" * 30, encoding="utf-8")
    monkeypatch.setattr(repo_indexer, "MAX_INDEXED_BYTES", 40)

    with pytest.raises(ValueError, match="indexing safety limit"):
        await RepoIndexer(None).inspect_repo(tmp_path, persist=False)


async def test_objective_ranking_prefers_core_code_over_generic_test_tokens(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "github_sync.py").write_text(
        "def fetch_github_pagination(next_cursor):\n"
        "    return next_cursor\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_connector.py").write_text(
        "def test_connector_update():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    relevant = frame.relevant_files_for_goal(
        {"finish", "github", "connector", "pagination", "tests"},
        [],
    )

    assert relevant[0]["path"] == "app/github_sync.py"
    assert relevant[0]["ranking_score"] > next(
        item["ranking_score"]
        for item in relevant
        if item["path"] == "tests/test_connector.py"
    )
    assert relevant[0]["matched_terms"] == ["github", "pagination"]
    assert relevant[0]["line_ranges"] == [{"start_line": 1, "end_line": 2}]
    assert relevant[0]["sha256"]


async def test_repository_evidence_filters_deictic_verbs_but_keeps_exact_file_names(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "telemetry.py").write_text(
        "def configure_telemetry():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "remove.py").write_text(
        "def execute_action():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "unrelated.py").write_text(
        "def remove_shown_panel():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'fixture'\n"
        "dependencies = [\n"
        "  'fastapi>=0.100',\n"
        "  'opentelemetry-api>=1.25',\n"
        "]\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    keywords = {"remove", "shown", "OpenTelemetry"}
    relevant = frame.relevant_files_for_goal(keywords, [])
    relevant_paths = {item["path"] for item in relevant}

    assert "app/telemetry.py" in relevant_paths
    assert "app/remove.py" in relevant_paths
    assert "app/unrelated.py" not in relevant_paths
    remove_file = next(item for item in relevant if item["path"] == "app/remove.py")
    assert remove_file["match_basis"]["file_name"] == ["remove"]

    evidence = frame.repository_evidence_for_goal(keywords, [])
    assert evidence["schema_version"] == "repository_evidence.v2"
    assert len(evidence["items"]) <= 24
    assert {
        (item["path"], item["symbol_name"])
        for item in evidence["items"]
        if item["kind"] == "symbol_declaration"
    } == {("app/telemetry.py", "configure_telemetry")}
    symbol = next(
        item for item in evidence["items"]
        if item["kind"] == "symbol_declaration"
    )
    assert set(symbol) == {
        "id",
        "kind",
        "path",
        "file_sha256",
        "symbol_type",
        "symbol_name",
        "start_line",
        "end_line",
    }
    dependencies = [
        item
        for item in evidence["items"]
        if item["kind"] == "manifest_dependency"
    ]
    assert [item["dependency_name"] for item in dependencies] == [
        "opentelemetry-api"
    ]
    assert set(dependencies[0]) == {
        "id",
        "kind",
        "manifest_path",
        "manifest_sha256",
        "dependency_group",
        "dependency_name",
        "declaration",
    }
    assert all(
        "docstring" not in item and "source" not in item and "signature" not in item
        for item in evidence["items"]
    )


async def test_license_self_host_goal_excludes_ambiguous_copy_self_host_symbols(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "deploy" / "production").mkdir(parents=True)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "LICENSE").write_text(
        "Source-available license terms.\n",
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "LICENSE").write_text(
        "Bundled dependency terms.\n",
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim\n",
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile.production").write_text(
        "FROM python:3.12-slim\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    build: .\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.production.yml").write_text(
        "services:\n  app:\n    build: .\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.smoke.yml").write_text(
        "services:\n  app:\n    build: .\n",
        encoding="utf-8",
    )
    (tmp_path / "deploy" / "production" / "production.env.example").write_text(
        "PORT=8000\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / ".env.example").write_text(
        "VITE_API_URL=/api\n",
        encoding="utf-8",
    )
    (tmp_path / "fixtures" / "docker-compose.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "self-host.sh").write_text(
        "#!/bin/sh\necho ready\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "self-host-smoke.sh").write_text(
        "#!/bin/sh\necho smoke\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "self-hosting.md").write_text(
        "# Self-hosting\nRun the deployment locally.\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_docs.py").write_text(
        "def test_license_and_self_hosting_contracts_are_explicit():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "cache.py").write_text(
        "def _copy_value():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "auth.py").write_text(
        "def _client_host_digest():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_agents.py").write_text(
        "def test_agent_cannot_resolve_self_reference():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_continuation_execution_contract.py").write_text(
        "def test_copy_contract_cannot_self_upgrade():\n    assert True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    lead = (
        "Update the license so users can self host the project, but cannot "
        "copy it into a product to make themselves money. Research the "
        "license and make the project self hostable."
    )
    keywords = set(repo_indexer._tokenize(lead))
    relevant = frame.relevant_files_for_goal(keywords, [])
    relevant_paths = {item["path"] for item in relevant}

    assert {
        "LICENSE",
        "Dockerfile",
        "Dockerfile.production",
        "docker-compose.yml",
        "docker-compose.production.yml",
        "docker-compose.smoke.yml",
        "deploy/production/production.env.example",
        "scripts/self-host.sh",
        "scripts/self-host-smoke.sh",
        "docs/self-hosting.md",
        "tests/test_docs.py",
    } <= relevant_paths
    assert not {
        "app/auth.py",
        "app/cache.py",
        "tests/test_agents.py",
        "tests/test_continuation_execution_contract.py",
        "vendor/LICENSE",
        "frontend/.env.example",
        "fixtures/docker-compose.yml",
    } & relevant_paths
    assert all(item["why"] for item in relevant)

    evidence = frame.repository_evidence_for_goal(keywords, [])
    evidence_paths = {
        item.get("path")
        for item in evidence["items"]
        if item["kind"] in {"file_presence", "symbol_declaration"}
    }
    assert {
        "LICENSE",
        "Dockerfile",
        "Dockerfile.production",
        "docker-compose.yml",
        "docker-compose.production.yml",
        "docker-compose.smoke.yml",
        "deploy/production/production.env.example",
        "scripts/self-host.sh",
        "scripts/self-host-smoke.sh",
        "docs/self-hosting.md",
        "tests/test_docs.py",
    } <= evidence_paths
    assert not {
        "app/auth.py",
        "app/cache.py",
        "tests/test_agents.py",
        "tests/test_continuation_execution_contract.py",
        "vendor/LICENSE",
        "frontend/.env.example",
        "fixtures/docker-compose.yml",
    } & evidence_paths
    assert all(
        item["kind"] == "file_presence"
        for item in evidence["items"]
        if item.get("path") in {
            "LICENSE",
            "Dockerfile",
            "Dockerfile.production",
            "docker-compose.yml",
            "docker-compose.production.yml",
            "docker-compose.smoke.yml",
            "deploy/production/production.env.example",
            "scripts/self-host.sh",
            "scripts/self-host-smoke.sh",
            "docs/self-hosting.md",
        }
    )


async def test_license_variants_and_lowercase_dockerfile_are_discovered_safely(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "LICENSE.txt").write_text(
        "Project source-available terms.\n",
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "LICENSE.md").write_text(
        "Bundled dependency terms.\n",
        encoding="utf-8",
    )
    (tmp_path / "dockerfile").write_text(
        "FROM python:3.12-slim\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    keywords = {"license", "self", "host"}
    relevant = frame.relevant_files_for_goal(keywords, [])
    relevant_paths = {item["path"] for item in relevant}

    assert {"LICENSE.txt", "dockerfile"} <= relevant_paths
    assert "vendor/LICENSE.md" not in relevant_paths
    evidence_paths = {
        item.get("path")
        for item in frame.repository_evidence_for_goal(keywords, [])["items"]
    }
    assert {"LICENSE.txt", "dockerfile"} <= evidence_paths
    assert "vendor/LICENSE.md" not in evidence_paths


async def test_repository_evidence_applies_per_kind_bounds(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "telemetry.py").write_text(
        "\n\n".join(
            f"def telemetry_handler_{index}():\n    return {index}"
            for index in range(14)
        ),
        encoding="utf-8",
    )

    frame = await RepoIndexer(None).inspect_repo(tmp_path, persist=False)
    evidence = frame.repository_evidence_for_goal({"telemetry"}, [])

    assert len([
        item
        for item in evidence["items"]
        if item["kind"] == "symbol_declaration"
    ]) == 10
    assert evidence["truncated"] is True


def test_git_output_preserves_leading_porcelain_status_column(monkeypatch, tmp_path):
    from app.services import repo_indexer

    monkeypatch.setattr(
        repo_indexer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=" M app/api/connectors.py\n?? new_file.py\n",
        ),
    )

    output = repo_indexer._git(tmp_path, "status", "--short")

    assert output.splitlines()[0] == " M app/api/connectors.py"


def test_git_commands_trust_only_the_validated_repository(
    monkeypatch,
    tmp_path,
):
    tracked = tmp_path / "tracked.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        assert command[:4] == [
            "git",
            "-c",
            f"safe.directory={tmp_path}",
            "-C",
        ]
        assert command[4] == str(tmp_path)
        stdout = "true\n" if kwargs.get("text") else b"tracked.py\0"
        return SimpleNamespace(returncode=0, stdout=stdout)

    monkeypatch.setattr(repo_indexer.subprocess, "run", fake_run)

    assert repo_indexer._git(tmp_path, "rev-parse", "--is-inside-work-tree") == "true"
    assert repo_indexer._git_visible_files(tmp_path) == [tracked]
    assert len(commands) == 2


async def test_repo_index_endpoint_persists_workspace_files_and_exposes_project_path(
    client, db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(),
        name="Indexed project",
        slug=f"indexed-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.py").write_text(
        "def project_entrypoint():\n    return True\n",
        encoding="utf-8",
    )

    response = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(tmp_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == str(workspace.id)
    assert payload["repo_path"] == str(tmp_path.resolve())
    assert payload["files_indexed"] == 1
    assert payload["symbols_indexed"] >= 1
    assert payload["persistence_available"] is True

    files = list(await db_session.scalars(
        select(CodeFile).where(CodeFile.workspace_id == workspace.id)
    ))
    assert [item.path for item in files] == ["src/main.py"]
    assert files[0].repo_root == str(tmp_path.resolve())
    assert files[0].sha256

    digest = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert digest.status_code == 200
    digest_data = digest.json()
    assert digest_data["scope"]["project_paths"] == [str(tmp_path.resolve())]
    architecture_cards = [
        card for card in digest_data["cards"] if card["category"] == "code_area"
    ]
    assert {card["source_snapshot"]["source_type"] for card in architecture_cards} == {
        "local_repository"
    }
    assert len(architecture_cards) == 2
    assert any("Repository:" in card["title"] for card in architecture_cards)
    assert any("Area: src" in card["title"] for card in architecture_cards)
    assert all(
        card["evidence"]["verification_status"] == "verified"
        for card in architecture_cards
    )
    architecture_ids = {card["id"] for card in architecture_cards}
    assert any(
        link["relationship_type"] == "part_of"
        and link["source_card_id"] in architecture_ids
        and link["target_card_id"] in architecture_ids
        for link in digest_data["links"]
    )


async def test_repo_index_endpoint_validates_workspace_and_path(client, db_session, tmp_path):
    missing_workspace = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(uuid4()), "repo_path": str(tmp_path)},
    )
    assert missing_workspace.status_code == 404

    workspace = Workspace(
        id=uuid4(),
        name="Invalid path",
        slug=f"invalid-path-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    missing_path = await client.post(
        "/api/repo/index",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(tmp_path / "not-a-project"),
        },
    )
    assert missing_path.status_code == 422

    empty_path = tmp_path / "empty-project"
    empty_path.mkdir()
    (empty_path / ".git").mkdir()
    empty_project = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(empty_path)},
    )
    assert empty_project.status_code == 422
    assert "No supported project files" in empty_project.json()["detail"]


async def test_repo_index_endpoint_replaces_the_previous_workspace_project(
    client, db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(),
        name="Replace indexed project",
        slug=f"replace-indexed-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    first_root = tmp_path / "first-project"
    second_root = tmp_path / "second-project"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / ".git").mkdir()
    (second_root / ".git").mkdir()
    (first_root / "first.py").write_text(
        "def first_project():\n    return True\n",
        encoding="utf-8",
    )
    (second_root / "second.py").write_text(
        "def second_project():\n    return True\n",
        encoding="utf-8",
    )

    first_response = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(first_root)},
    )
    second_response = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(second_root)},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    files = list(await db_session.scalars(
        select(CodeFile).where(CodeFile.workspace_id == workspace.id)
    ))
    assert [(item.repo_root, item.path) for item in files] == [
        (str(second_root.resolve()), "second.py")
    ]
    digest = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert digest.status_code == 200
    assert digest.json()["scope"]["project_paths"] == [str(second_root.resolve())]


async def test_incremental_index_preserves_unchanged_ids_and_builds_exact_edges(
    db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(), name="Incremental project", slug=f"incremental-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "service.py").write_text(
        "def run_service():\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "app" / "api.py").write_text(
        "from .service import run_service\n"
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.get('/health')\n"
        "def health():\n    return run_service()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text(
        "def test_run_service():\n    assert True\n", encoding="utf-8"
    )

    first = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    assert first.persistence_available is True
    assert first.files_added == 4
    assert first.files_changed == 0
    assert first.edges_indexed == 3
    files_first = {
        item.path: item.id
        for item in await db_session.scalars(
            select(CodeFile).where(CodeFile.workspace_id == workspace.id)
        )
    }
    symbols_first = {
        (str(item.code_file_id), item.symbol_type, item.name): item.id
        for item in await db_session.scalars(select(CodeSymbol))
    }
    edges_first = {
        item.edge_key: item.id for item in await db_session.scalars(select(CodeEdge))
    }
    assert {edge["rule_id"] for edge in first.exact_edges} == {
        "local_module_import.v1",
        "route_handler_owner.v1",
        "test_path_match.v1",
    }
    affected = first.affected_code_for_goal({"service"}, [])
    assert all(item["role"] == "likely_implementation" for item in affected["files"])
    service_file = next(
        item for item in affected["files"] if item["path"] == "app/service.py"
    )
    assert service_file["match_strength"] == "strong_match"
    assert service_file["match_basis"]["path"] == ["service"]
    assert service_file["why"] == "File name matches: service."
    assert service_file["matched_symbols"] == [{
        "name": "run_service",
        "symbol_type": "function",
        "start_line": 1,
        "end_line": 2,
    }]
    assert len({
        (item["start_line"], item["end_line"])
        for item in service_file["line_ranges"]
    }) == len(service_file["line_ranges"])
    assert service_file["related_tests"][0]["path"] == "tests/test_service.py"
    assert {
        tuple(item["paths"]) for item in service_file["impact_paths"]
    } >= {
        ("tests/test_service.py", "app/service.py"),
        ("app/api.py", "app/service.py"),
    }
    repository_evidence = first.repository_evidence_for_goal({"service"}, [])
    exact_test_link = next(
        item
        for item in repository_evidence["items"]
        if item["kind"] == "test_link"
        and item["target_path"] == "app/service.py"
    )
    assert exact_test_link["test_path"] == "tests/test_service.py"
    assert exact_test_link["rule_id"] == "test_path_match.v1"
    assert exact_test_link["test_sha256"]
    assert exact_test_link["target_sha256"]
    assert set(exact_test_link) == {
        "id",
        "kind",
        "test_path",
        "test_sha256",
        "target_path",
        "target_sha256",
        "rule_id",
        "rule_version",
        "edge_key",
    }
    explicit_test = first.affected_code_for_goal(
        {"service"}, ["tests/test_service.py"]
    )
    assert any(
        item["path"] == "tests/test_service.py"
        and item["role"] == "related_test"
        and item["match_strength"] == "linked_test"
        for item in explicit_test["files"]
    )

    second = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    assert second.files_unchanged == 4
    assert second.files_added == second.files_changed == second.files_deleted == 0
    files_second = {
        item.path: item.id
        for item in await db_session.scalars(
            select(CodeFile).where(CodeFile.workspace_id == workspace.id)
        )
    }
    symbols_second = {
        (str(item.code_file_id), item.symbol_type, item.name): item.id
        for item in await db_session.scalars(select(CodeSymbol))
    }
    edges_second = {
        item.edge_key: item.id for item in await db_session.scalars(select(CodeEdge))
    }
    assert files_second == files_first
    assert symbols_second == symbols_first
    assert edges_second == edges_first

    (tmp_path / "app" / "service.py").write_text(
        "def run_service():\n    return 'changed'\n", encoding="utf-8"
    )
    third = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    assert third.files_changed == 1
    assert third.files_unchanged == 3
    files_third = {
        item.path: item.id
        for item in await db_session.scalars(
            select(CodeFile).where(CodeFile.workspace_id == workspace.id)
        )
    }
    assert files_third == files_first
    symbols_third = {
        (str(item.code_file_id), item.symbol_type, item.name): item.id
        for item in await db_session.scalars(select(CodeSymbol))
    }
    assert symbols_third[(str(files_first["app/api.py"]), "module", "app/api.py")] == (
        symbols_first[(str(files_first["app/api.py"]), "module", "app/api.py")]
    )
    assert symbols_third[(str(files_first["app/service.py"]), "module", "app/service.py")] != (
        symbols_first[(str(files_first["app/service.py"]), "module", "app/service.py")]
    )


async def test_deleting_indexed_file_removes_incident_edges(db_session, tmp_path):
    workspace = Workspace(
        id=uuid4(), name="Deletion project", slug=f"deletion-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "source.py").write_text("import target\n", encoding="utf-8")
    first = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    assert first.edges_indexed == 1

    (tmp_path / "target.py").unlink()
    second = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    assert second.files_deleted == 1
    assert second.edges_indexed == 0
    assert list(await db_session.scalars(select(CodeEdge))) == []


async def test_typescript_edges_require_one_exact_target(db_session, tmp_path):
    workspace = Workspace(
        id=uuid4(), name="TypeScript edges", slug=f"typescript-edges-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "helper.ts").write_text(
        "export function helper() { return true; }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "server.ts").write_text(
        "import { helper } from './helper';\n"
        "import express from 'express';\n"
        "const app = express();\n"
        "function getHealth() { return helper(); }\n"
        "app.get('/health', getHealth);\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "server.test.ts").write_text(
        "test('health', () => true);\n", encoding="utf-8"
    )
    (tmp_path / "src" / "util.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "util.js").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "ambiguous.ts").write_text(
        "import { value } from './util';\nimport React from 'react';\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )

    assert {
        (edge["rule_id"], edge["source_path"], edge["target_path"])
        for edge in frame.exact_edges
    } == {
        ("local_module_import.v1", "src/server.ts", "src/helper.ts"),
        ("route_handler_owner.v1", "src/server.ts", "src/server.ts"),
        ("test_path_match.v1", "src/server.test.ts", "src/server.ts"),
    }


async def test_javascript_comments_strings_and_unbound_routes_emit_no_edges(
    db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(), name="Masked JavaScript", slug=f"masked-js-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "helper.ts").write_text("export function helper() {}\n", encoding="utf-8")
    (tmp_path / "masked.ts").write_text(
        "// import { helper } from './helper';\n"
        "/* app.get('/comment', commentHandler); */\n"
        "const sample = \"import x from './helper'; app.get('/text', textHandler)\";\n"
        "function looseHandler() { return true; }\n"
        "app.get('/unbound', looseHandler);\n",
        encoding="utf-8",
    )
    (tmp_path / "bound_masked.ts").write_text(
        "const app = express();\n"
        "function hiddenHandler() { return true; }\n"
        "// app.get('/comment', hiddenHandler);\n"
        "const sample = \"app.get('/text', hiddenHandler)\";\n",
        encoding="utf-8",
    )
    (tmp_path / "local_constructor.ts").write_text(
        "function express() { return {}; }\n"
        "const app = express();\n"
        "function fakeHandler() { return true; }\n"
        "app.get('/fake', fakeHandler);\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )

    assert frame.exact_edges == []
    masked = next(item for item in frame.indexed_files if item.path == "masked.ts")
    assert masked.imports == []
    assert masked.route_hints == []


async def test_python_routes_require_local_fastapi_binding(db_session, tmp_path):
    workspace = Workspace(
        id=uuid4(), name="Bound Python routes", slug=f"bound-python-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "routes.py").write_text(
        "class Cache:\n    def get(self, path):\n        return lambda fn: fn\n"
        "cache = Cache()\n\n"
        "@cache.get('/cached')\n"
        "def cached():\n    return True\n\n"
        "@app.get('/unbound')\n"
        "def unbound():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "local_router.py").write_text(
        "def APIRouter():\n    return object()\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/fake')\n"
        "def fake():\n    return True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )

    assert not any(
        edge["rule_id"] == "route_handler_owner.v1" for edge in frame.exact_edges
    )
    routes = next(item for item in frame.indexed_files if item.path == "routes.py")
    assert routes.route_hints == []


async def test_repo_indexer_enforces_one_active_root_without_api(db_session, tmp_path):
    workspace = Workspace(
        id=uuid4(), name="One active root", slug=f"one-root-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / ".git").mkdir()
    (second / ".git").mkdir()
    (first / "first.py").write_text("def first(): pass\n", encoding="utf-8")
    (second / "second.py").write_text("def second(): pass\n", encoding="utf-8")

    await RepoIndexer(db_session).inspect_repo(
        first, workspace_id=workspace.id, persist=True
    )
    await RepoIndexer(db_session).inspect_repo(
        second, workspace_id=workspace.id, persist=True
    )

    stored = list(await db_session.scalars(
        select(CodeFile).where(CodeFile.workspace_id == workspace.id)
    ))
    assert {(item.repo_root, item.path) for item in stored} == {
        (str(second.resolve()), "second.py")
    }


async def test_founder_oversight_objective_does_not_expand_on_generic_terms(
    db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(), name="No lexical slop", slug=f"no-slop-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    for index in range(15):
        (tmp_path / "app" / f"generic_{index}.py").write_text(
            f"def context_agent_project_task_{index}():\n    return True\n",
            encoding="utf-8",
        )
    (tmp_path / "app" / "founder_oversight.py").write_text(
        "def detect_silent_ignore_and_scrutiny():\n    return True\n",
        encoding="utf-8",
    )
    objective = {
        "providing", "birds", "eye", "view", "eyes", "non", "technical",
        "founder", "gaps", "slop", "code", "incomplete", "progress",
        "silent", "ignore", "agents", "scrutiny", "aggressive", "grilling",
        "gathering", "context",
    }

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    affected = frame.affected_code_for_goal(objective, [])

    assert affected is not None
    assert [item["path"] for item in affected["files"]] == [
        "app/founder_oversight.py"
    ]


async def test_exact_file_name_match_suppresses_weaker_word_matches(
    db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(), name="README focus", slug=f"readme-focus-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "README.md").write_text("# Current product\n", encoding="utf-8")
    (tmp_path / "app" / "extraction.py").write_text(
        "def rewrite_source_extraction_provenance():\n    return True\n",
        encoding="utf-8",
    )

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    affected = frame.affected_code_for_goal(
        {"rewrite", "readme", "source", "extraction", "provenance"}, ["README"]
    )

    assert affected is not None
    assert [item["path"] for item in affected["files"]] == ["README.md"]
    assert affected["files"][0]["match_strength"] == "named_in_task"
    assert affected["files"][0]["why"] == "The task names this file."


async def test_accuracy_gate_issue_does_not_match_common_prose(db_session, tmp_path):
    workspace = Workspace(
        id=uuid4(), name="Accuracy gate", slug=f"accuracy-gate-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "evals").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / ".agent-runs").mkdir()
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ISSUE_TEMPLATE").mkdir()
    for index in range(12):
        (tmp_path / "app" / f"generic_{index}.py").write_text(
            f"def current_explicit_state_for_item_{index}():\n    return True\n",
            encoding="utf-8",
        )
    (tmp_path / "app" / "context_compiler.py").write_text(
        "def existing_state():\n    return None\n", encoding="utf-8"
    )
    (tmp_path / "app" / "evaluation.py").write_text(
        "def evaluate_acceptance():\n    return None\n", encoding="utf-8"
    )
    (tmp_path / "evals" / "accuracy_gate.py").write_text(
        "def publish_phase_thresholds():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "overview.md").write_text(
        "Current issue documentation.\n", encoding="utf-8"
    )
    (tmp_path / ".agent-runs" / "hardening-task.md").write_text(
        "Hardening issue task.\n", encoding="utf-8"
    )
    (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug.yml").write_text(
        "name: Issue hardening\n", encoding="utf-8"
    )
    objective = {
        "define", "and", "publish", "the", "phase", "accuracy", "gate",
        "for", "current", "explicit", "thresholds", "is", "at",
    }

    frame = await RepoIndexer(db_session).inspect_repo(
        tmp_path, workspace_id=workspace.id, persist=True
    )
    frame.changed_files = [
        {"path": "app/context_compiler.py"},
        {"path": "app/evaluation.py"},
    ]
    affected = frame.affected_code_for_goal(objective, [])

    assert affected is not None
    assert [item["path"] for item in affected["files"]] == [
        "evals/accuracy_gate.py"
    ]


async def test_repo_index_endpoint_reports_the_persisted_symbol_cap(
    client, db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(),
        name="Symbol cap",
        slug=f"symbol-cap-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / ".git").mkdir()
    (tmp_path / "many_symbols.py").write_text(
        "\n".join(
            f"def symbol_{index}():\n    return {index}\n"
            for index in range(305)
        ),
        encoding="utf-8",
    )

    response = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["symbols_indexed"] == 300
    code_file_ids = select(CodeFile.id).where(CodeFile.workspace_id == workspace.id)
    persisted_symbols = list(await db_session.scalars(
        select(CodeSymbol).where(CodeSymbol.code_file_id.in_(code_file_ids))
    ))
    assert len(persisted_symbols) == 300


async def test_repo_index_rejects_a_directory_that_is_not_a_project_root(
    client, db_session, tmp_path
):
    workspace = Workspace(
        id=uuid4(),
        name="Project root validation",
        slug=f"project-root-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / "loose.py").write_text("value = 1\n", encoding="utf-8")

    response = await client.post(
        "/api/repo/index",
        json={"workspace_id": str(workspace.id), "repo_path": str(tmp_path)},
    )

    assert response.status_code == 422
    assert "not a project root" in response.json()["detail"]
