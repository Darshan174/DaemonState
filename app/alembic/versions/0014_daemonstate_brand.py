from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_daemonstate_brand"
down_revision = "0013_source_ingestion_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    previous_slug, previous_display, previous_sentence_case = _previous_brand()

    if sa.inspect(bind).has_table("workspaces"):
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET name = :current_name
                WHERE name IN (:previous_display, :previous_sentence_case)
            """),
            {
                "current_name": "DaemonState",
                "previous_display": previous_display,
                "previous_sentence_case": previous_sentence_case,
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET name = :current_demo_name
                WHERE name = :previous_demo_name
            """),
            {
                "current_demo_name": "DaemonState Demo",
                "previous_demo_name": f"{previous_display} Demo",
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET slug = :current_slug
                WHERE slug = :previous_slug
            """),
            {
                "current_slug": "daemonstate",
                "previous_slug": previous_slug,
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET slug = :current_demo_slug
                WHERE slug = :previous_demo_slug
            """),
            {
                "current_demo_slug": "daemonstate-demo",
                "previous_demo_slug": f"{previous_slug}-demo",
            },
        )

    if _has_column(bind, "agent_runs", "tool"):
        previous_prefix = f"{previous_slug}:"
        bind.execute(
            sa.text("""
                UPDATE agent_runs
                SET tool = :current_prefix || substr(tool, :suffix_start)
                WHERE lower(tool) LIKE :previous_pattern
            """),
            {
                "current_prefix": "daemonstate:",
                "suffix_start": len(previous_prefix) + 1,
                "previous_pattern": f"{previous_prefix}%",
            },
        )

    _rename_postgres_functions(bind, reverse=False)


def downgrade() -> None:
    bind = op.get_bind()
    previous_slug, previous_display, _previous_sentence_case = _previous_brand()

    if sa.inspect(bind).has_table("workspaces"):
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET name = :previous_name
                WHERE name = :current_name
            """),
            {
                "previous_name": previous_display,
                "current_name": "DaemonState",
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET name = :previous_demo_name
                WHERE name = :current_demo_name
            """),
            {
                "previous_demo_name": f"{previous_display} Demo",
                "current_demo_name": "DaemonState Demo",
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET slug = :previous_slug
                WHERE slug = :current_slug
            """),
            {
                "previous_slug": previous_slug,
                "current_slug": "daemonstate",
            },
        )
        bind.execute(
            sa.text("""
                UPDATE workspaces
                SET slug = :previous_demo_slug
                WHERE slug = :current_demo_slug
            """),
            {
                "previous_demo_slug": f"{previous_slug}-demo",
                "current_demo_slug": "daemonstate-demo",
            },
        )

    if _has_column(bind, "agent_runs", "tool"):
        current_prefix = "daemonstate:"
        bind.execute(
            sa.text("""
                UPDATE agent_runs
                SET tool = :previous_prefix || substr(tool, :suffix_start)
                WHERE lower(tool) LIKE :current_pattern
            """),
            {
                "previous_prefix": f"{previous_slug}:",
                "suffix_start": len(current_prefix) + 1,
                "current_pattern": f"{current_prefix}%",
            },
        )

    _rename_postgres_functions(bind, reverse=True)


def _previous_brand() -> tuple[str, str, str]:
    return (
        "-".join(("context", "engine")),
        " ".join(("Context", "Engine")),
        " ".join(("Context", "engine")),
    )


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name) and column_name in {
        item["name"] for item in inspector.get_columns(table_name)
    }


def _rename_postgres_functions(bind, *, reverse: bool) -> None:
    if bind.dialect.name != "postgresql":
        return

    previous_db_prefix = "".join(("c", "e"))
    for suffix, arguments in (
        ("try_vector", "text"),
        ("sync_component_embedding_vector", ""),
        ("try_jsonb", "text"),
        ("sync_source_document_search", ""),
        ("sync_component_search", ""),
    ):
        previous_name = f"{previous_db_prefix}_{suffix}"
        current_name = f"daemonstate_{suffix}"
        source_name, target_name = (
            (current_name, previous_name)
            if reverse
            else (previous_name, current_name)
        )
        source_signature = f"{source_name}({arguments})"
        target_signature = f"{target_name}({arguments})"
        source_exists = bool(bind.scalar(
            sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"),
            {"signature": source_signature},
        ))
        if not source_exists:
            continue
        target_exists = bool(bind.scalar(
            sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"),
            {"signature": target_signature},
        ))
        if target_exists:
            bind.execute(sa.text(
                f"DROP FUNCTION {source_name}({arguments})"
            ))
        else:
            bind.execute(sa.text(
                f"ALTER FUNCTION {source_name}({arguments}) "
                f"RENAME TO {target_name}"
            ))
