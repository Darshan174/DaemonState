from __future__ import annotations

import hashlib
import json
from uuid import UUID

import sqlalchemy as sa
from alembic import op


revision = "0003_project_compiler"
down_revision = "0002_founder_oversight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "code_files"):
        return

    file_columns = _columns(bind, "code_files")
    if "identity_key" not in file_columns:
        op.add_column("code_files", sa.Column("identity_key", sa.String(64), nullable=True))
    if "is_test" not in file_columns:
        op.add_column(
            "code_files",
            sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    symbol_columns = _columns(bind, "code_symbols")
    if "identity_key" not in symbol_columns:
        op.add_column("code_symbols", sa.Column("identity_key", sa.String(64), nullable=True))

    edge_columns = _columns(bind, "code_edges")
    edge_additions = [
        sa.Column("edge_key", sa.String(64), nullable=True),
        sa.Column("rule_id", sa.String(100), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=True),
        sa.Column("evidence_path", sa.Text(), nullable=True),
        sa.Column("evidence_start_line", sa.Integer(), nullable=True),
        sa.Column("evidence_end_line", sa.Integer(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("snapshot_commit", sa.String(100), nullable=True),
        sa.Column("snapshot_dirty", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot_fingerprint", sa.String(64), nullable=True),
    ]
    for column in edge_additions:
        if column.name not in edge_columns:
            op.add_column("code_edges", column)

    _backfill_files(bind)
    _backfill_symbols(bind)
    _backfill_edges(bind)

    with op.batch_alter_table("code_files") as batch:
        batch.alter_column("identity_key", existing_type=sa.String(64), nullable=False)
    with op.batch_alter_table("code_symbols") as batch:
        batch.alter_column("identity_key", existing_type=sa.String(64), nullable=False)
    with op.batch_alter_table("code_edges") as batch:
        batch.alter_column("edge_key", existing_type=sa.String(64), nullable=False)
        batch.alter_column("rule_id", existing_type=sa.String(100), nullable=False)
        batch.alter_column("rule_version", existing_type=sa.String(32), nullable=False)
        batch.alter_column("evidence_sha256", existing_type=sa.String(64), nullable=False)

    _create_index_if_missing(bind, "uq_code_files_identity_key", "code_files", ["identity_key"], unique=True)
    _create_index_if_missing(
        bind,
        "uq_code_files_workspace_root_path",
        "code_files",
        ["workspace_id", "repo_root", "path"],
        unique=True,
    )
    _create_index_if_missing(bind, "uq_code_symbols_identity_key", "code_symbols", ["identity_key"], unique=True)
    _create_index_if_missing(bind, "uq_code_edges_edge_key", "code_edges", ["edge_key"], unique=True)
    _create_index_if_missing(
        bind,
        "ix_code_edges_rule_source",
        "code_edges",
        ["rule_id", "source_symbol_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "code_files"):
        return
    _drop_index_if_present(bind, "ix_code_edges_rule_source", "code_edges")
    _drop_index_if_present(bind, "uq_code_edges_edge_key", "code_edges")
    _drop_index_if_present(bind, "uq_code_symbols_identity_key", "code_symbols")
    _drop_index_if_present(bind, "uq_code_files_workspace_root_path", "code_files")
    _drop_index_if_present(bind, "uq_code_files_identity_key", "code_files")

    with op.batch_alter_table("code_edges") as batch:
        for name in [
            "snapshot_fingerprint",
            "snapshot_dirty",
            "snapshot_commit",
            "evidence_sha256",
            "evidence_json",
            "evidence_end_line",
            "evidence_start_line",
            "evidence_path",
            "rule_version",
            "rule_id",
            "edge_key",
        ]:
            if name in _columns(bind, "code_edges"):
                batch.drop_column(name)
    with op.batch_alter_table("code_symbols") as batch:
        if "identity_key" in _columns(bind, "code_symbols"):
            batch.drop_column("identity_key")
    with op.batch_alter_table("code_files") as batch:
        if "is_test" in _columns(bind, "code_files"):
            batch.drop_column("is_test")
        if "identity_key" in _columns(bind, "code_files"):
            batch.drop_column("identity_key")


def _backfill_files(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, workspace_id, repo_root, path, identity_key FROM code_files"
    )).all()
    seen: set[tuple[object, object, str]] = set()
    for row in rows:
        natural = (
            _uuid_text(row[1]),
            str(row[2]) if row[2] is not None else None,
            str(row[3]).replace("\\", "/"),
        )
        if natural in seen:
            raise RuntimeError(
                "duplicate code_files identities detected; re-index the workspace "
                "before applying migration 0003"
            )
        seen.add(natural)
        bind.execute(
            sa.text("UPDATE code_files SET identity_key = :key WHERE id = :id"),
            {"key": row[4] or _hash(list(natural)), "id": row[0]},
        )


def _backfill_symbols(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, code_file_id, symbol_type, name, qualified_name, start_line, "
        "end_line, identity_key FROM code_symbols"
    )).all()
    for row in rows:
        bind.execute(
            sa.text("UPDATE code_symbols SET identity_key = :key WHERE id = :id"),
            {
                "key": row[7] or _hash([
                    _uuid_text(row[1]), row[2], row[4] or row[3], row[5], row[6]
                ]),
                "id": row[0],
            },
        )


def _backfill_edges(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, edge_key, rule_id, rule_version, evidence_json, evidence_sha256 "
        "FROM code_edges"
    )).all()
    for row in rows:
        evidence = row[4]
        if not evidence or evidence == "{}":
            evidence = json.dumps(
                {"legacy_edge_id": str(row[0])}, sort_keys=True, separators=(",", ":")
            )
        bind.execute(sa.text(
            "UPDATE code_edges SET edge_key = :edge_key, rule_id = :rule_id, "
            "rule_version = :rule_version, evidence_json = :evidence_json, "
            "evidence_sha256 = :evidence_sha256 WHERE id = :id"
        ), {
            "id": row[0],
            "edge_key": row[1] or _hash(["legacy", str(row[0])]),
            "rule_id": row[2] or "legacy.unspecified",
            "rule_version": row[3] or "0",
            "evidence_json": evidence,
            "evidence_sha256": row[5] or hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        })


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _uuid_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return str(value)


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _create_index_if_missing(bind, name: str, table_name: str, columns: list[str], **kwargs) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}:
        op.create_index(name, table_name, columns, **kwargs)


def _drop_index_if_present(bind, name: str, table_name: str) -> None:
    if name in {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}:
        op.drop_index(name, table_name=table_name)
