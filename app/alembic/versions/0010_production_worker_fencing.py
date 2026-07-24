from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_production_worker_fencing"
down_revision = "0009_memory_review_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("sync_jobs")}
    with op.batch_alter_table("sync_jobs") as batch:
        if "claim_token" not in columns:
            batch.add_column(sa.Column("claim_token", sa.String(length=64), nullable=True))
        if "heartbeat_at" not in columns:
            batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("sync_jobs")}
    # The previous partial unique index did not include ``retrying``, so an
    # older installation can legitimately contain one pending/running row and
    # one retrying row with the same key. Deterministically retain the oldest
    # row before broadening the uniqueness predicate.
    bind.execute(sa.text("""
        UPDATE sync_jobs AS candidate
        SET status = 'failed',
            error_type = COALESCE(error_type, 'duplicate_idempotency_key'),
            error_message = COALESCE(
                error_message,
                'Superseded while enforcing active sync-job idempotency'
            )
        WHERE candidate.idempotency_key IS NOT NULL
          AND candidate.status IN ('pending', 'retrying', 'running')
          AND EXISTS (
              SELECT 1
              FROM sync_jobs AS winner
              WHERE winner.idempotency_key = candidate.idempotency_key
                AND winner.status IN ('pending', 'retrying', 'running')
                AND (
                    winner.created_at < candidate.created_at
                    OR (
                        winner.created_at = candidate.created_at
                        AND CAST(winner.id AS TEXT) < CAST(candidate.id AS TEXT)
                    )
                )
          )
    """))
    if "uq_sync_jobs_active_idempotency_key" in indexes:
        op.drop_index("uq_sync_jobs_active_idempotency_key", table_name="sync_jobs")
    active_predicate = sa.text(
        "idempotency_key IS NOT NULL "
        "AND status IN ('pending','retrying','running')"
    )
    op.create_index(
        "uq_sync_jobs_active_idempotency_key",
        "sync_jobs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=active_predicate,
        postgresql_where=active_predicate,
    )


def downgrade() -> None:
    indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("sync_jobs")
    }
    if "uq_sync_jobs_active_idempotency_key" in indexes:
        op.drop_index("uq_sync_jobs_active_idempotency_key", table_name="sync_jobs")
    previous_predicate = sa.text(
        "idempotency_key IS NOT NULL AND status IN ('pending','running')"
    )
    op.create_index(
        "uq_sync_jobs_active_idempotency_key",
        "sync_jobs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=previous_predicate,
        postgresql_where=previous_predicate,
    )
    columns = {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("sync_jobs")
    }
    with op.batch_alter_table("sync_jobs") as batch:
        if "heartbeat_at" in columns:
            batch.drop_column("heartbeat_at")
        if "claim_token" in columns:
            batch.drop_column("claim_token")
