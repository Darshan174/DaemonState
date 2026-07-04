from __future__ import annotations

from app.services.repo_indexer import RepoIndexer


async def test_indexes_python_files_symbols_and_routes(tmp_path):
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
