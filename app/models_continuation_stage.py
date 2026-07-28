from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.time import utc_now


class ContinuationStageRequest(Base):
    """Durable idempotency ledger for one visible desktop handoff request."""

    __tablename__ = "continuation_stage_requests"
    __table_args__ = (
        Index(
            "uq_continuation_stage_requests_workspace_key",
            "workspace_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_continuation_stage_requests_workspace_created",
            "workspace_id",
            "created_at",
        ),
        Index(
            "uq_continuation_stage_requests_workspace_current",
            "workspace_id",
            unique=True,
            sqlite_where=text(
                "status IN ('pending','succeeded','failed')"
            ),
            postgresql_where=text(
                "status IN ('pending','succeeded','failed')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    context_pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("context_packs.id"), nullable=False, index=True
    )
    continuation_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("continuation_executions.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    response_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    error_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        onupdate=func.now(),
    )
