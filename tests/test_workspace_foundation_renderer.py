from __future__ import annotations

from types import SimpleNamespace

from app.schemas.workspace_foundation import CommandVerificationStatus, RepositoryChangeRole
from app.services.context_compiler import _workspace_repository_inventory
from app.services.repo_indexer import RepoIndexer
from app.services.workspace_foundation import compile_workspace_foundation
from app.services.workspace_foundation_renderer import (
    _required_check_status_counts,
    _select_repository_changes,
    render_workspace_foundation_markdown,
)


def _change(
    path: str,
    role: RepositoryChangeRole,
    *,
    lines: int,
    symbols: int,
    parser_coverage: str = "parsed",
    capability_ids: tuple[str, ...] = (),
) -> SimpleNamespace:
    delta = SimpleNamespace(
        parser_coverage=parser_coverage,
        lines_added=lines,
        lines_removed=0,
        symbols_added=tuple(f"symbol-{index}" for index in range(symbols)),
        symbols_modified=(),
        symbols_removed=(),
        routes_added=(),
        routes_removed=(),
        imports_added=(),
        imports_removed=(),
        headings_added=(),
        headings_removed=(),
    )
    return SimpleNamespace(
        path=path,
        role=role,
        capability_ids=capability_ids,
        semantic_delta=delta,
    )


def test_change_projection_prefers_semantic_signal_with_role_diversity() -> None:
    changes = [
        _change(
            "app/services/small.py",
            RepositoryChangeRole.IMPLEMENTATION,
            lines=4,
            symbols=1,
            capability_ids=("capability.deploy",),
        ),
        _change(
            "app/services/foundation.py",
            RepositoryChangeRole.IMPLEMENTATION,
            lines=400,
            symbols=8,
        ),
        _change(
            "tests/test_small.py",
            RepositoryChangeRole.TEST,
            lines=20,
            symbols=1,
        ),
        _change(
            "tests/test_foundation.py",
            RepositoryChangeRole.TEST,
            lines=300,
            symbols=6,
        ),
        _change(
            "desktop/Changed.swift",
            RepositoryChangeRole.TEST,
            lines=2_000,
            symbols=0,
            parser_coverage="line_only",
        ),
    ]

    selected = _select_repository_changes(changes, limit=2)

    assert [item.path for item in selected] == [
        "app/services/foundation.py",
        "tests/test_foundation.py",
    ]


async def test_engineering_notes_cover_each_kind_and_keep_limit_qualifiers(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Atlas\n\n## Overview\n\nAtlas prepares controlled deployments.\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text(
        "# Architecture\n\n## Current Limitations\n\n"
        + "".join(
            f"- Export adapter {index} supports local files only; "
            "cloud delivery requires explicit approval.\n"
            for index in range(8)
        )
        + "\n## Architecture Decisions\n\n- Keep processing local to avoid data transfers.\n"
        "\n## Engineering Conventions\n\n- Preserve exact evidence tiers.\n"
        "\n## Known Failures\n\n- A stale repository digest attaches the wrong evidence.\n"
        "\n## Lessons Learned\n\n- Check source identity before exporting.\n",
        encoding="utf-8",
    )
    frame = await RepoIndexer(None).inspect_repo(tmp_path)
    artifact = compile_workspace_foundation(
        frame=frame, inventory=_workspace_repository_inventory(frame), durable_foundation=None,
    )

    rendered = render_workspace_foundation_markdown(artifact)
    notes = rendered.split("## Repository engineering notes (source-scoped)\n", 1)[1]
    notes = notes.split("\n## ", 1)[0]

    assert "Keep processing local to avoid data transfers." in notes
    assert "Preserve exact evidence tiers." in notes
    assert "A stale repository digest attaches the wrong evidence." in notes
    assert "Check source identity before exporting." in notes
    assert "cloud delivery requires explicit approval." in notes
    assert "docs/architecture.md:L" in notes
    assert len(notes) / 4 < 850


def test_required_check_counts_use_the_exact_command_and_cwd_key() -> None:
    artifact = SimpleNamespace(
        verification_policy=SimpleNamespace(
            required_commands=(
                SimpleNamespace(
                    key=SimpleNamespace(command="pytest -q", working_directory="."),
                ),
                SimpleNamespace(
                    key=SimpleNamespace(command="npm test", working_directory="frontend"),
                ),
                SimpleNamespace(
                    key=SimpleNamespace(command="ruff check app", working_directory="."),
                ),
            ),
        ),
        commands=(
            SimpleNamespace(
                command="pytest -q",
                working_directory=".",
                verification=SimpleNamespace(status=CommandVerificationStatus.PASSED),
            ),
            SimpleNamespace(
                command="npm test",
                working_directory=".",
                verification=SimpleNamespace(status=CommandVerificationStatus.PASSED),
            ),
            SimpleNamespace(
                command="ruff check app",
                working_directory=".",
                verification=SimpleNamespace(status=CommandVerificationStatus.FAILED),
            ),
        ),
    )

    assert _required_check_status_counts(artifact) == (1, 1, 1)
