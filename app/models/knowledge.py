from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
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
from app.models.source import enum_values

if TYPE_CHECKING:
    from app.models.review import ReviewItem
    from app.models.source import SourceDocument
    from app.models.user import Workspace


class KnowledgeModelStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RelationshipType(str, enum.Enum):
    DEPENDS_ON = "depends_on"
    BLOCKED_BY = "blocked_by"
    ENABLES = "enables"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    RELATED_TO = "related_to"


class RelationshipSentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class KnowledgeModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_models"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[KnowledgeModelStatus] = mapped_column(
        Enum(
            KnowledgeModelStatus,
            name="knowledge_model_status_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        default=KnowledgeModelStatus.ACTIVE,
        server_default=text("'active'"),
    )
    auto_generated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    workspace: Mapped["Workspace"] = orm_relationship(back_populates="knowledge_models")
    components: Mapped[list["Component"]] = orm_relationship(
        back_populates="model",
        cascade="all, delete-orphan",
    )


class Component(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "components"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="components_confidence_range"),
        CheckConstraint(
            "authority_weight >= 0 AND authority_weight <= 1",
            name="components_authority_weight_range",
        ),
    )

    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    authority_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authority_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        server_default=text("0.5"),
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("components.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_stale: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

    model: Mapped["KnowledgeModel"] = orm_relationship(back_populates="components")
    outgoing_relationships: Mapped[list["Relationship"]] = orm_relationship(
        back_populates="source_component",
        foreign_keys="Relationship.source_component_id",
        cascade="all, delete-orphan",
    )
    incoming_relationships: Mapped[list["Relationship"]] = orm_relationship(
        back_populates="target_component",
        foreign_keys="Relationship.target_component_id",
        cascade="all, delete-orphan",
    )
    source_links: Mapped[list["ComponentSource"]] = orm_relationship(
        back_populates="component",
        cascade="all, delete-orphan",
    )
    review_item: Mapped["ReviewItem | None"] = orm_relationship(
        back_populates="component",
        cascade="all, delete-orphan",
        uselist=False,
    )
    source_documents: Mapped[list["SourceDocument"]] = orm_relationship(
        secondary="component_sources",
        back_populates="components",
        viewonly=True,
    )
    superseded_by_component: Mapped["Component | None"] = orm_relationship(
        remote_side="Component.id",
        foreign_keys=[superseded_by_id],
        post_update=True,
    )

    @property
    def model_name(self) -> str | None:
        if self.model is None:
            return None
        return self.model.name

    @property
    def review_status(self) -> str | None:
        if self.review_item is None:
            return None
        return self.review_item.status

    @property
    def review_summary(self) -> str | None:
        if self.review_item is None:
            return None
        return self.review_item.summary

    @property
    def review_item_id(self) -> UUID | None:
        if self.review_item is None:
            return None
        return self.review_item.id

    @property
    def decision_history(self):
        if self.review_item is None:
            return []
        return list(self.review_item.decision_history)

    @property
    def temporal_state(self) -> str | None:
        if self.valid_to is None:
            return None
        return "historical"

    @property
    def superseded_by(self) -> UUID | None:
        return self.superseded_by_id

    @property
    def source_count(self) -> int:
        """Number of source documents supporting this component.

        Returns 0 if the relationship is not loaded (avoids accidental
        lazy-load in property access).
        """
        if "source_links" not in self.__dict__:
            return 0
        return len(self.source_links)

    @property
    def is_rejected(self) -> bool:
        """True when the review status is explicitly rejected."""
        return self.review_status == "rejected"

    @property
    def is_superseded(self) -> bool:
        """True when this component has been superseded by a newer version."""
        return self.valid_to is not None

    @property
    def is_hidden(self) -> bool:
        """True when this component should be hidden from default graph views.

        A component is hidden if it is rejected or superseded.
        Historical (valid_to set but not superseded) components are NOT hidden —
        they represent earlier versions of facts that are still part of the lineage.
        """
        return self.is_rejected or (
            self.is_superseded and self.superseded_by_id is not None
        )


class Relationship(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="relationships_confidence_range"),
        CheckConstraint(
            "source_component_id <> target_component_id",
            name="relationships_distinct_components",
        ),
    )

    source_component_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_component_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(
        Enum(
            RelationshipType,
            name="relationship_type_enum",
            values_callable=enum_values,
        ),
        nullable=False,
    )
    sentiment: Mapped[RelationshipSentiment] = mapped_column(
        Enum(
            RelationshipSentiment,
            name="relationship_sentiment_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        default=RelationshipSentiment.NEUTRAL,
        server_default=text("'neutral'"),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("relationships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source_component: Mapped["Component"] = orm_relationship(
        back_populates="outgoing_relationships",
        foreign_keys=[source_component_id],
    )
    target_component: Mapped["Component"] = orm_relationship(
        back_populates="incoming_relationships",
        foreign_keys=[target_component_id],
    )
    superseded_by_relationship: Mapped["Relationship | None"] = orm_relationship(
        remote_side="Relationship.id",
        foreign_keys=[superseded_by_id],
        post_update=True,
    )

    @property
    def source_component_name(self) -> str | None:
        if self.source_component is None:
            return None
        return self.source_component.name

    @property
    def target_component_name(self) -> str | None:
        if self.target_component is None:
            return None
        return self.target_component.name

    @property
    def temporal_state(self) -> str | None:
        if self.valid_to is None:
            return None
        return "historical"

    @property
    def superseded_by(self) -> UUID | None:
        return self.superseded_by_id

    @property
    def source_review_status(self) -> str | None:
        """Review status of the source component."""
        if self.source_component is None:
            return None
        return self.source_component.review_status

    @property
    def target_review_status(self) -> str | None:
        """Review status of the target component."""
        if self.target_component is None:
            return None
        return self.target_component.review_status

    @property
    def is_hidden(self) -> bool:
        """True when either endpoint is hidden — the relationship should be
        hidden from default graph views.
        """
        if self.source_component is not None and self.source_component.is_hidden:
            return True
        if self.target_component is not None and self.target_component.is_hidden:
            return True
        return self.valid_to is not None


class ComponentSource(Base):
    __tablename__ = "component_sources"

    component_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    extraction_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extractor_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extractor_schema_version: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    component: Mapped["Component"] = orm_relationship(back_populates="source_links")
    source_document: Mapped["SourceDocument"] = orm_relationship(back_populates="component_links")
