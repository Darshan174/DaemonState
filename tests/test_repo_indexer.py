from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.models import CodeEdge, CodeFile, CodeSymbol, Workspace
from app.services.repo_indexer import RepoIndexer


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
