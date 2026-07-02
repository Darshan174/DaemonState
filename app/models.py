from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    source_documents: Mapped[list["SourceDocument"]] = orm_relationship(back_populates="workspace")
    entities: Mapped[list["Entity"]] = orm_relationship(back_populates="workspace")
    entity_aliases: Mapped[list["EntityAlias"]] = orm_relationship(back_populates="workspace")
    facts: Mapped[list["Fact"]] = orm_relationship(back_populates="workspace")
    mentions: Mapped[list["Mention"]] = orm_relationship(back_populates="workspace")
    components: Mapped[list["Component"]] = orm_relationship(back_populates="workspace")


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True,
        default=UUID("00000000-0000-0000-0000-000000000000"),
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

    @property
    def items_synced(self) -> int:
        try:
            config = json.loads(self.config_json or "{}")
        except json.JSONDecodeError:
            return 0
        return int(config.get("items_synced", 0) or 0)

    @items_synced.setter
    def items_synced(self, value: int) -> None:
        try:
            config = json.loads(self.config_json or "{}")
        except json.JSONDecodeError:
            config = {}
        config["items_synced"] = int(value or 0)
        self.config_json = json.dumps(config)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index("ix_sync_jobs_workspace_status", "workspace_id", "status"),
        Index("ix_sync_jobs_idempotency_key", "idempotency_key"),
        Index("ix_sync_jobs_job_type_status", "job_type", "status"),
        Index("ix_sync_jobs_queue_due", "job_type", "status", "available_at"),
        Index("ix_sync_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="connector_sync"
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    queued_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    available_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    connector: Mapped["Connector"] = orm_relationship(back_populates="sync_jobs")


class RetrievalEvent(Base):
    __tablename__ = "retrieval_events"
    __table_args__ = (
        Index("ix_retrieval_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_retrieval_events_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False, default="query.v1")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    min_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hybrid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    component_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        Index(
            "ix_source_documents_workspace_source_external",
            "workspace_id",
            "source_type",
            "external_id",
        ),
        Index("ix_source_documents_source_type_external_id", "source_type", "external_id"),
        Index("ix_source_documents_processed_at", "processed_at"),
        Index("ix_source_documents_ingested_at", "ingested_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
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

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="source_documents")
    components: Mapped[list["Component"]] = orm_relationship(back_populates="source_document")


class Model(Base):
    __tablename__ = "models"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    entities: Mapped[list["Entity"]] = orm_relationship(back_populates="model")
    components: Mapped[list["Component"]] = orm_relationship(back_populates="model")


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_workspace_identity", "workspace_id", "identity_key"),
        Index("ix_entities_identity_key", "identity_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("models.id"), nullable=True, index=True
    )
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="entities")
    model: Mapped["Model | None"] = orm_relationship(back_populates="entities")
    aliases: Mapped[list["EntityAlias"]] = orm_relationship(back_populates="entity")
    facts: Mapped[list["Fact"]] = orm_relationship(back_populates="entity")
    mentions: Mapped[list["Mention"]] = orm_relationship(back_populates="entity")
    components: Mapped[list["Component"]] = orm_relationship(back_populates="entity")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", name="uq_entity_aliases_entity_alias"),
        Index("ix_entity_aliases_workspace_normalized", "workspace_id", "normalized_alias"),
        Index("ix_entity_aliases_entity", "entity_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    entity_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="entity_aliases")
    entity: Mapped["Entity"] = orm_relationship(back_populates="aliases")
    source_document: Mapped["SourceDocument | None"] = orm_relationship()


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        Index("ix_components_workspace_status_confidence", "workspace_id", "status", "confidence"),
        Index("ix_components_workspace_model_status", "workspace_id", "model_id", "status"),
        Index("ix_components_workspace_identity_status", "workspace_id", "identity_key", "status"),
        Index("ix_components_workspace_entity_status", "workspace_id", "entity_id", "status"),
        Index("ix_components_status_confidence", "status", "confidence"),
        Index("ix_components_model_status", "model_id", "status"),
        Index("ix_components_source_status", "source_document_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    model_id: Mapped[UUID] = mapped_column(ForeignKey("models.id"), nullable=False, index=True)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False, index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    identity_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="fact"
    )
    temporal: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
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
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="components")
    entity: Mapped["Entity | None"] = orm_relationship(back_populates="components")
    model: Mapped["Model"] = orm_relationship(back_populates="components")
    source_document: Mapped["SourceDocument"] = orm_relationship(back_populates="components")
    fact: Mapped["Fact | None"] = orm_relationship(back_populates="component")
    mentions: Mapped[list["Mention"]] = orm_relationship(back_populates="component")
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


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("component_id", name="uq_facts_component_id"),
        Index("ix_facts_workspace_status_confidence", "workspace_id", "status", "confidence"),
        Index("ix_facts_workspace_entity", "workspace_id", "entity_id"),
        Index("ix_facts_source_document", "source_document_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    component_id: Mapped[UUID] = mapped_column(
        ForeignKey("components.id"), nullable=False, index=True
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False, index=True
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False, default="fact")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False, default="extractor.v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="facts")
    entity: Mapped["Entity | None"] = orm_relationship(back_populates="facts")
    component: Mapped["Component"] = orm_relationship(back_populates="fact")
    source_document: Mapped["SourceDocument"] = orm_relationship()


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        UniqueConstraint("component_id", "normalized_mention", name="uq_mentions_component_normalized"),
        Index("ix_mentions_workspace_normalized", "workspace_id", "normalized_mention"),
        Index("ix_mentions_entity", "entity_id"),
        Index("ix_mentions_source_document", "source_document_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False, index=True
    )
    component_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("components.id"), nullable=True, index=True
    )
    mention_text: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_mention: Mapped[str] = mapped_column(String(255), nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="mentions")
    entity: Mapped["Entity | None"] = orm_relationship(back_populates="mentions")
    source_document: Mapped["SourceDocument"] = orm_relationship()
    component: Mapped["Component | None"] = orm_relationship(back_populates="mentions")


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_relationships_status_origin", "status", "origin"),
        Index("ix_relationships_source_status", "source_component_id", "status"),
        Index("ix_relationships_target_status", "target_component_id", "status"),
        Index(
            "ix_relationships_source_target_type",
            "source_component_id",
            "target_component_id",
            "relationship_type",
        ),
    )

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
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
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
