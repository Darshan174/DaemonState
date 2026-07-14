from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.models import CodeFile, CodeSymbol, Workspace
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
