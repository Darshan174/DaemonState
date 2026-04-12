from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge import Component


class ReviewItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("component_id"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="review_items_confidence_range",
        ),
    )

    component_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="needs_review",
        server_default=text("'needs_review'"),
    )
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="medium",
        server_default=text("'medium'"),
    )
    kind: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="review_item",
        server_default=text("'review_item'"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    component: Mapped["Component"] = orm_relationship(
        foreign_keys=[component_id],
        back_populates="review_item",
    )
    decision_history: Mapped[list["ReviewDecision"]] = orm_relationship(
        back_populates="review_item",
        cascade="all, delete-orphan",
        order_by=lambda: (ReviewDecision.created_at.desc(), ReviewDecision.id.desc()),
    )


class ReviewDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_decisions"

    review_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="operator",
        server_default=text("'operator'"),
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    review_item: Mapped["ReviewItem"] = orm_relationship(
        foreign_keys=[review_item_id],
        back_populates="decision_history",
    )
