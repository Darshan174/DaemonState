from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "0004_truth_access"
down_revision = "0003_project_compiler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in ("source_documents", "evidence_spans"):
        columns = _columns(bind, table_name)
        additions = (
            sa.Column("visibility_scope", sa.String(32), nullable=False, server_default="workspace"),
            sa.Column("permission_source", sa.String(64), nullable=False, server_default="workspace_default"),
            sa.Column("permission_observed_at", sa.DateTime(), nullable=True),
            sa.Column("permission_snapshot_sha256", sa.String(64), nullable=True),
        )
        for column in additions:
            if column.name not in columns:
                op.add_column(table_name, column)

    _backfill_permissions(bind)
    for table_name in ("source_documents", "evidence_spans"):
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column("permission_observed_at", existing_type=sa.DateTime(), nullable=False)
            batch.alter_column(
                "permission_snapshot_sha256", existing_type=sa.String(64), nullable=False
            )
        _create_index_if_missing(
            bind, f"ix_{table_name}_visibility_scope", table_name, ["visibility_scope"]
        )

    if not _has_table(bind, "source_read_grants"):
        op.create_table(
            "source_read_grants",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column(
                "source_document_id", sa.Uuid(),
                sa.ForeignKey("source_documents.id"), nullable=False,
            ),
            sa.Column("principal_id", sa.String(255), nullable=False),
            sa.Column("grant_key", sa.String(64), nullable=False),
            sa.Column("permission_snapshot_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _create_index_if_missing(bind, "uq_source_read_grants_grant_key", "source_read_grants", ["grant_key"], unique=True)
    _create_index_if_missing(bind, "ix_source_read_grants_document_principal", "source_read_grants", ["source_document_id", "principal_id"])
    _create_index_if_missing(bind, "ix_source_read_grants_workspace_principal", "source_read_grants", ["workspace_id", "principal_id"])

    claim_columns = _columns(bind, "claims")
    if "scope_identity_sha256" not in claim_columns:
        op.add_column("claims", sa.Column("scope_identity_sha256", sa.String(64), nullable=True))
    _backfill_claim_scopes(bind)
    with op.batch_alter_table("claims") as batch:
        batch.alter_column("scope_identity_sha256", existing_type=sa.String(64), nullable=False)
    _create_index_if_missing(bind, "uq_claims_scope_identity_sha256", "claims", ["scope_identity_sha256"], unique=True)

    revision_columns = _columns(bind, "claim_revisions")
    additions = (
        sa.Column("revision_key", sa.String(64), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_to", sa.DateTime(), nullable=True),
        sa.Column("validity_basis", sa.String(32), nullable=False, server_default="unknown"),
    )
    for column in additions:
        if column.name not in revision_columns:
            op.add_column("claim_revisions", column)
    _backfill_revisions(bind)
    with op.batch_alter_table("claim_revisions") as batch:
        batch.alter_column("revision_key", existing_type=sa.String(64), nullable=False)
        batch.alter_column("observed_at", existing_type=sa.DateTime(), nullable=False)
    _create_index_if_missing(bind, "uq_claim_revisions_revision_key", "claim_revisions", ["revision_key"], unique=True)
    _create_index_if_missing(bind, "ix_claim_revisions_claim_valid", "claim_revisions", ["claim_id", "valid_from", "valid_to"])
    _create_index_if_missing(bind, "ix_claim_revisions_claim_transaction", "claim_revisions", ["claim_id", "created_at", "transaction_to"])


def downgrade() -> None:
    bind = op.get_bind()
    for name in (
        "ix_claim_revisions_claim_transaction",
        "ix_claim_revisions_claim_valid",
        "uq_claim_revisions_revision_key",
    ):
        _drop_index_if_present(bind, name, "claim_revisions")
    with op.batch_alter_table("claim_revisions") as batch:
        for name in (
            "validity_basis", "transaction_to", "observed_at", "valid_to",
            "valid_from", "revision_key",
        ):
            if name in _columns(bind, "claim_revisions"):
                batch.drop_column(name)
    _drop_index_if_present(bind, "uq_claims_scope_identity_sha256", "claims")
    with op.batch_alter_table("claims") as batch:
        if "scope_identity_sha256" in _columns(bind, "claims"):
            batch.drop_column("scope_identity_sha256")
    if _has_table(bind, "source_read_grants"):
        op.drop_table("source_read_grants")
    for table_name in ("evidence_spans", "source_documents"):
        _drop_index_if_present(bind, f"ix_{table_name}_visibility_scope", table_name)
        with op.batch_alter_table(table_name) as batch:
            for name in (
                "permission_snapshot_sha256", "permission_observed_at",
                "permission_source", "visibility_scope",
            ):
                if name in _columns(bind, table_name):
                    batch.drop_column(name)


def _backfill_permissions(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, ingested_at FROM source_documents"
    )).all()
    for row in rows:
        snapshot = _hash(["workspace", "workspace_default", str(row[0])])
        bind.execute(sa.text(
            "UPDATE source_documents SET visibility_scope='workspace', "
            "permission_source='workspace_default', permission_observed_at=ingested_at, "
            "permission_snapshot_sha256=:snapshot WHERE id=:id"
        ), {"snapshot": snapshot, "id": row[0]})
    bind.execute(sa.text(
        "UPDATE evidence_spans SET visibility_scope=(SELECT visibility_scope FROM source_documents "
        "WHERE source_documents.id=evidence_spans.source_document_id), "
        "permission_source=(SELECT permission_source FROM source_documents WHERE "
        "source_documents.id=evidence_spans.source_document_id), "
        "permission_observed_at=(SELECT permission_observed_at FROM source_documents WHERE "
        "source_documents.id=evidence_spans.source_document_id), "
        "permission_snapshot_sha256=(SELECT permission_snapshot_sha256 FROM source_documents "
        "WHERE source_documents.id=evidence_spans.source_document_id)"
    ))


def _backfill_claim_scopes(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, workspace_id, identity_key, claim_type FROM claims"
    )).all()
    seen: set[str] = set()
    for row in rows:
        key = _hash([str(row[1]) if row[1] is not None else "global", row[3], row[2]])
        if key in seen:
            raise RuntimeError(
                "duplicate claim identities detected; reconcile claims before migration 0004"
            )
        seen.add(key)
        bind.execute(sa.text(
            "UPDATE claims SET scope_identity_sha256=:key WHERE id=:id"
        ), {"key": key, "id": row[0]})


def _backfill_revisions(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, claim_id, evidence_span_id, operation, value, created_at "
        "FROM claim_revisions"
    )).all()
    for row in rows:
        bind.execute(sa.text(
            "UPDATE claim_revisions SET revision_key=:key, observed_at=created_at, "
            "validity_basis='unknown' WHERE id=:id"
        ), {"key": _hash(["legacy", str(row[0]), str(row[1]), str(row[2]), row[3], row[4]]), "id": row[0]})


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _columns(bind, table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(table_name)}


def _create_index_if_missing(bind, name: str, table: str, columns: list[str], **kwargs) -> None:
    if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns, **kwargs)


def _drop_index_if_present(bind, name: str, table: str) -> None:
    if name in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
        op.drop_index(name, table_name=table)
