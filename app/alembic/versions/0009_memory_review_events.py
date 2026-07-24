"""Add append-only Memory review events."""

from alembic import op
import sqlalchemy as sa


revision = "0009_memory_review_events"
down_revision = "0008_work_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("memory_review_events"):
        op.create_table(
            "memory_review_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("component_id", sa.Uuid(), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("previous_component_status", sa.String(length=50)),
            sa.Column("next_component_status", sa.String(length=50)),
            sa.Column("previous_claim_status", sa.String(length=50)),
            sa.Column("next_claim_status", sa.String(length=50)),
            sa.Column("previous_evidence_status", sa.String(length=50)),
            sa.Column("next_evidence_status", sa.String(length=50)),
            sa.Column("reviewed_by", sa.String(length=255), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["component_id"], ["components.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes("memory_review_events")}
    if "ix_memory_review_events_workspace_created" not in existing:
        op.create_index(
            "ix_memory_review_events_workspace_created",
            "memory_review_events",
            ["workspace_id", "created_at"],
        )
    if "ix_memory_review_events_component_created" not in existing:
        op.create_index(
            "ix_memory_review_events_component_created",
            "memory_review_events",
            ["component_id", "created_at"],
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("memory_review_events"):
        op.drop_table("memory_review_events")
