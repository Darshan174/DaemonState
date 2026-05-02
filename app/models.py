from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship as orm_relationship,
)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    connectors: Mapped[list["Connector"]] = orm_relationship(back_populates="workspace")


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="disconnected")
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    credentials_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = orm_relationship(back_populates="connectors")
    sync_jobs: Mapped[list["SyncJob"]] = orm_relationship(back_populates="connector")


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    connector: Mapped["Connector"] = orm_relationship(back_populates="sync_jobs")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", Text, nullable=False, default="{}"
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    components: Mapped[list["Component"]] = orm_relationship(back_populates="source_document")


class Model(Base):
    __tablename__ = "models"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    components: Mapped[list["Component"]] = orm_relationship(back_populates="model")


class Component(Base):
    __tablename__ = "components"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model_id: Mapped[UUID] = mapped_column(ForeignKey("models.id"), nullable=False, index=True)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="fact"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("components.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    model: Mapped["Model"] = orm_relationship(back_populates="components")
    source_document: Mapped["SourceDocument"] = orm_relationship(back_populates="components")
    outgoing_relationships: Mapped[list["Relationship"]] = orm_relationship(
        back_populates="source_component",
        foreign_keys="Relationship.source_component_id",
    )
    incoming_relationships: Mapped[list["Relationship"]] = orm_relationship(
        back_populates="target_component",
        foreign_keys="Relationship.target_component_id",
    )
    superseded_by_component: Mapped["Component | None"] = orm_relationship(
        remote_side="Component.id",
        foreign_keys=[superseded_by_id],
        post_update=True,
    )


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_component_id: Mapped[UUID] = mapped_column(
        ForeignKey("components.id"), nullable=False, index=True
    )
    target_component_id: Mapped[UUID] = mapped_column(
        ForeignKey("components.id"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="related_to"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    source_component: Mapped["Component"] = orm_relationship(
        back_populates="outgoing_relationships",
        foreign_keys=[source_component_id],
    )
    target_component: Mapped["Component"] = orm_relationship(
        back_populates="incoming_relationships",
        foreign_keys=[target_component_id],
    )
