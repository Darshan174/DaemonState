from __future__ import annotations

from app.services.repo_indexer import RepoIndexer, inspect_repo_state


def test_python_repo_symbol_indexing(tmp_path):
    package = tmp_path / "app"
    package.mkdir()
    (package / "service.py").write_text(
        '''import os
from pathlib import Path

class ContextCompiler:
    """Compile context."""

    def compile(self, goal):
        return goal

def parse_goal(goal):
    return goal.split()
''',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")

    index = RepoIndexer().index(tmp_path)

    symbols = {(symbol.symbol_type, symbol.qualified_name) for symbol in index.symbols}
    assert ("class", "ContextCompiler") in symbols
    assert ("method", "ContextCompiler.compile") in symbols
    assert ("function", "parse_goal") in symbols
    assert any(item["module"] == "os" for item in index.imports)
    assert "tests/test_service.py" in index.test_files
    assert "pyproject.toml" in index.package_manifests


def test_typescript_file_indexing_smoke(tmp_path):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "ContextPanel.tsx").write_text(
        """import React from 'react';

export function ContextPanel() {
  return <section />;
}

const useContextPack = () => fetch('/api/context/prepare');
""",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "package.json").write_text(
        '{"scripts":{"test":"vitest run","build":"vite build"},"dependencies":{"react":"latest"}}',
        encoding="utf-8",
    )

    state = inspect_repo_state(tmp_path)
    symbol_names = {
        symbol["qualified_name"]
        for symbol in state["index"]["symbols"]
    }

    assert "ContextPanel" in symbol_names
    assert "useContextPack" in symbol_names
    assert "frontend/package.json" in state["package_manifests"]
    assert "cd frontend && npm test" in state["likely_test_commands"]
    assert "cd frontend && npm run build" in state["likely_test_commands"]
