from __future__ import annotations

from types import SimpleNamespace

from app.schemas.workspace_foundation import CommandVerificationStatus, RepositoryChangeRole
from app.services.workspace_foundation_renderer import (
    _required_check_status_counts,
    _select_repository_engineering_facts,
    _select_repository_changes,
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


def test_engineering_note_projection_preserves_kind_diversity() -> None:
    limitations = [
        SimpleNamespace(
            id=f"limitation-{index}",
            kind=SimpleNamespace(value="current_limitation"),
        )
        for index in range(8)
    ]
    decision = SimpleNamespace(
        id="decision-1",
        kind=SimpleNamespace(value="decision"),
    )
    convention = SimpleNamespace(
        id="convention-1",
        kind=SimpleNamespace(value="convention"),
    )

    selected = _select_repository_engineering_facts(
        [*limitations, decision, convention],
        limit=3,
    )

    assert [item.id for item in selected] == [
        "decision-1",
        "convention-1",
        "limitation-0",
    ]


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
