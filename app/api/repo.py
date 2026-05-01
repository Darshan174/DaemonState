from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "node_modules",
}
TECH_FILES = {
    "package.json": "Node.js / React",
    "vite.config.js": "Vite",
    "tailwind.config.js": "Tailwind CSS",
    "pyproject.toml": "Python",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
}
EXTENSION_TECH = {
    ".py": "Python",
    ".jsx": "React",
    ".js": "JavaScript",
    ".css": "CSS",
    ".html": "HTML",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
}


class RepoNode(BaseModel):
    id: str
    label: str
    type: str
    detail: str | None = None
    path: str | None = None
    technology: str | None = None
    x: int | None = None
    y: int | None = None


class RepoEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class RepoGraphResponse(BaseModel):
    root: str
    nodes: list[RepoNode]
    edges: list[RepoEdge]


@router.get("/repo/graph", response_model=RepoGraphResponse)
async def get_repo_graph() -> RepoGraphResponse:
    nodes: dict[str, RepoNode] = {}
    edges: list[RepoEdge] = []

    def add_node(node: RepoNode) -> None:
        nodes[node.id] = node

    def add_edge(source: str, target: str, label: str) -> None:
        edge_id = f"{source}->{target}:{label}"
        edges.append(RepoEdge(id=edge_id, source=source, target=target, label=label))

    areas = _repo_areas()
    add_node(RepoNode(id="repo:root", label=REPO_ROOT.name, type="repo", detail=str(REPO_ROOT), path=".", x=100, y=640))

    for index, area in enumerate(areas):
        area_id = f"area:{area['key']}"
        area_y = 140 + index * 250
        add_node(
            RepoNode(
                id=area_id,
                label=area["label"],
                type="area",
                detail=area["detail"],
                path=area["path"],
                x=300,
                y=area_y,
            )
        )
        add_edge("repo:root", area_id, "contains")

        file_count = len(area["files"])
        for file_index, rel in enumerate(area["files"]):
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            file_id = f"file:{rel}"
            add_node(
                RepoNode(
                    id=file_id,
                    label=path.name,
                    type="file",
                    detail=rel,
                    path=rel,
                    technology=_technology_for_file(path),
                    x=650,
                    y=area_y + (file_index - (file_count - 1) / 2) * 58,
                )
            )
            add_edge(area_id, file_id, "key file")

    area_tech = _area_technologies()
    tech_positions: dict[str, int] = {}
    for area_index, area in enumerate(areas):
        area_id = f"area:{area['key']}"
        for tech in area_tech.get(area["key"], []):
            if tech not in tech_positions:
                tech_positions[tech] = len(tech_positions)
                add_node(
                    RepoNode(
                        id=f"tech:{tech}",
                        label=tech,
                        type="technology",
                        detail=f"Used by {area['label']}",
                        technology=tech,
                        x=1040,
                        y=120 + tech_positions[tech] * 84,
                    )
                )
            add_edge(area_id, f"tech:{tech}", "uses")

    return RepoGraphResponse(root=REPO_ROOT.name, nodes=list(nodes.values()), edges=edges)


def _repo_areas() -> list[dict[str, Any]]:
    return [
        {
            "key": "backend",
            "label": "Backend API",
            "detail": "FastAPI routes, data models, ingestion, extraction, and query services.",
            "path": "app",
            "files": [
                "app/main.py",
                "app/api/router.py",
                "app/api/graph.py",
                "app/api/sources.py",
                "app/api/query.py",
                "app/api/repo.py",
                "app/models.py",
                "app/database.py",
            ],
        },
        {
            "key": "engine",
            "label": "Knowledge Engine",
            "detail": "Converts source documents into components, relationships, and embeddings.",
            "path": "app/services",
            "files": [
                "app/services/ingest.py",
                "app/processing/extractor.py",
                "app/processing/embedder.py",
                "app/services/query.py",
            ],
        },
        {
            "key": "frontend",
            "label": "Frontend UI",
            "detail": "React app, graph view, source manager, dashboard, and connector surfaces.",
            "path": "frontend/src",
            "files": [
                "frontend/src/App.jsx",
                "frontend/src/pages/GraphView.jsx",
                "frontend/src/pages/SourceManager.jsx",
                "frontend/src/pages/Connectors.jsx",
                "frontend/src/api/hooks.js",
            ],
        },
        {
            "key": "runtime",
            "label": "Runtime & Infra",
            "detail": "Build tooling, Python package config, Docker, and local orchestration.",
            "path": ".",
            "files": [
                "pyproject.toml",
                "frontend/package.json",
                "frontend/vite.config.js",
                "frontend/tailwind.config.js",
                "Dockerfile",
                "docker-compose.yml",
            ],
        },
        {
            "key": "docs_tests",
            "label": "Docs & Tests",
            "detail": "Project documentation and test scaffolding.",
            "path": ".",
            "files": [
                "README.md",
                "project.md",
                "tests/conftest.py",
            ],
        },
    ]


def _area_technologies() -> dict[str, list[str]]:
    return {
        "backend": ["Python", "FastAPI", "SQLAlchemy"],
        "engine": ["Python", "LiteLLM", "Embeddings"],
        "frontend": ["React", "Cytoscape", "React Query", "Tailwind CSS"],
        "runtime": ["Vite", "Docker", "Docker Compose"],
        "docs_tests": ["Markdown", "Pytest"],
    }


def _interesting_top_level_dirs() -> list[str]:
    return [
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_dir() and path.name not in IGNORED_DIRS and not path.name.startswith(".")
    ]


def _interesting_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix in EXTENSION_TECH or path.name in TECH_FILES:
            files.append(path)
    return files


def _detect_technologies() -> dict[str, list[str]]:
    technologies: dict[str, list[str]] = {}
    for file_path in _interesting_files():
        tech = _technology_for_file(file_path)
        if tech:
            technologies.setdefault(tech, []).append(file_path.relative_to(REPO_ROOT).as_posix())

    package_json = REPO_ROOT / "frontend" / "package.json"
    if package_json.exists():
        try:
            package_data: dict[str, Any] = json.loads(package_json.read_text())
            deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
            for dep, tech in {
                "react": "React",
                "cytoscape": "Cytoscape",
                "@tanstack/react-query": "React Query",
                "tailwindcss": "Tailwind CSS",
                "vite": "Vite",
            }.items():
                if dep in deps:
                    technologies.setdefault(tech, []).append("frontend/package.json")
        except (OSError, json.JSONDecodeError):
            pass

    return technologies


def _technology_for_file(path: Path) -> str | None:
    if path.name in TECH_FILES:
        return TECH_FILES[path.name]
    return EXTENSION_TECH.get(path.suffix)
