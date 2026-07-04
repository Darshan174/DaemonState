from __future__ import annotations

import hashlib
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
    event,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship as orm_relationship,
)

from app.taxonomy import default_trust_zone_for_source


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
    evidence_spans: Mapped[list["EvidenceSpan"]] = orm_relationship(back_populates="workspace")
    claims: Mapped[list["Claim"]] = orm_relationship(back_populates="workspace")
    context_packs: Mapped[list["ContextPack"]] = orm_relationship(back_populates="workspace")
    agent_runs: Mapped[list["AgentRun"]] = orm_relationship(back_populates="workspace")
    unresolved_relationships: Mapped[list["UnresolvedRelationship"]] = orm_relationship(
        back_populates="workspace"
    )


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id"),
        nullable=False,
        index=True,
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
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="connector_sync")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    queued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
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
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trust_zone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    evidence_spans: Mapped[list["EvidenceSpan"]] = orm_relationship(
        back_populates="source_document"
    )


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"
    __table_args__ = (
        Index("ix_evidence_spans_workspace_document", "workspace_id", "source_document_id"),
        Index("ix_evidence_spans_source_range", "source_document_id", "start_char", "end_char"),
        Index("ix_evidence_spans_trust_risk", "trust_zone", "prompt_injection_risk_score"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False, index=True
    )
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False, default="extracted_fact")
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    trust_zone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="untrusted_external"
    )
    prompt_injection_risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    extraction_method: Mapped[str] = mapped_column(
        String(50), nullable=False, default="deterministic"
    )
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="verified")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="evidence_spans")
    source_document: Mapped["SourceDocument"] = orm_relationship(back_populates="evidence_spans")
    claim_revisions: Mapped[list["ClaimRevision"]] = orm_relationship(
        back_populates="evidence_span"
    )


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
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True, index=True
    )
    identity_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False, default="fact")
    temporal: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
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
    claim: Mapped["Claim | None"] = orm_relationship(back_populates="components")
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
    unresolved_relationships: Mapped[list["UnresolvedRelationship"]] = orm_relationship(
        back_populates="source_component",
        foreign_keys="UnresolvedRelationship.source_component_id",
    )
    superseded_by_component: Mapped["Component | None"] = orm_relationship(
        remote_side="Component.id",
        foreign_keys=[superseded_by_id],
        post_update=True,
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_workspace_identity", "workspace_id", "identity_key"),
        Index("ix_claims_workspace_status", "workspace_id", "status"),
        Index("ix_claims_type_status", "claim_type", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False, default="fact")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="needs_review")
    temporal: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="claims")
    revisions: Mapped[list["ClaimRevision"]] = orm_relationship(
        back_populates="claim",
        foreign_keys="ClaimRevision.claim_id",
        order_by="ClaimRevision.created_at",
    )
    components: Mapped[list["Component"]] = orm_relationship(back_populates="claim")


class ClaimRevision(Base):
    __tablename__ = "claim_revisions"
    __table_args__ = (
        Index("ix_claim_revisions_claim_created", "claim_id", "created_at"),
        Index("ix_claim_revisions_evidence_span", "evidence_span_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    evidence_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_spans.id"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False, default="create")
    confidence_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status_after: Mapped[str] = mapped_column(String(50), nullable=False, default="needs_review")
    supersedes_claim_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    contradicts_claim_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    claim: Mapped["Claim"] = orm_relationship(
        back_populates="revisions",
        foreign_keys=[claim_id],
    )
    evidence_span: Mapped["EvidenceSpan"] = orm_relationship(back_populates="claim_revisions")


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
    extractor_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="extractor.v1"
    )
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
        UniqueConstraint(
            "component_id", "normalized_mention", name="uq_mentions_component_normalized"
        ),
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
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, default="related_to")
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


class UnresolvedRelationship(Base):
    __tablename__ = "unresolved_relationships"
    __table_args__ = (
        Index("ix_unresolved_relationships_workspace_status", "workspace_id", "status"),
        Index("ix_unresolved_relationships_source_status", "source_component_id", "status"),
        Index("ix_unresolved_relationships_source_document", "source_document_id"),
        Index("ix_unresolved_relationships_target_identity", "target_identity_key"),
        Index(
            "ix_unresolved_relationships_source_target_type",
            "source_component_id",
            "target_identity_key",
            "relationship_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    source_component_id: Mapped[UUID] = mapped_column(
        ForeignKey("components.id"), nullable=False, index=True
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True, index=True
    )
    target_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_identity_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, default="related_to")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unresolved")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_relationship_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(
        back_populates="unresolved_relationships"
    )
    source_component: Mapped["Component"] = orm_relationship(
        back_populates="unresolved_relationships",
        foreign_keys=[source_component_id],
    )
    source_document: Mapped["SourceDocument | None"] = orm_relationship()
    resolved_relationship: Mapped["Relationship | None"] = orm_relationship()


class ContextPack(Base):
    __tablename__ = "context_packs"
    __table_args__ = (
        Index("ix_context_packs_workspace_created", "workspace_id", "created_at"),
        Index("ix_context_packs_target_model", "target_model"),
        Index(
            "ix_context_packs_workspace_target_created",
            "workspace_id",
            "target_model",
            "created_at",
        ),
        Index("ix_context_packs_idempotency_key", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    target_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pack_version: Mapped[str] = mapped_column(String(50), nullable=False, default="context_pack.v2")
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manifest: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    repo_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="context_packs")
    items: Mapped[list["ContextPackItem"]] = orm_relationship(back_populates="context_pack")
    agent_runs: Mapped[list["AgentRun"]] = orm_relationship(back_populates="context_pack")


class ContextPackItem(Base):
    __tablename__ = "context_pack_items"
    __table_args__ = (
        Index("ix_context_pack_items_pack", "context_pack_id"),
        Index("ix_context_pack_items_claim", "claim_id"),
        Index("ix_context_pack_items_component", "component_id"),
        Index("ix_context_pack_items_evidence", "evidence_span_id"),
        Index("ix_context_pack_items_source_document", "source_document_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    context_pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("context_packs.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, default="component")
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True, index=True
    )
    component_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("components.id"), nullable=True, index=True
    )
    evidence_span_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_spans.id"), nullable=True, index=True
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    context_pack: Mapped["ContextPack"] = orm_relationship(back_populates="items")
    claim: Mapped["Claim | None"] = orm_relationship()
    component: Mapped["Component | None"] = orm_relationship()
    evidence_span: Mapped["EvidenceSpan | None"] = orm_relationship()
    source_document: Mapped["SourceDocument | None"] = orm_relationship()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_workspace_started", "workspace_id", "started_at"),
        Index("ix_agent_runs_context_pack", "context_pack_id"),
        Index("ix_agent_runs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    context_pack_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("context_packs.id"), nullable=True, index=True
    )
    tool: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    head_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")

    workspace: Mapped["Workspace | None"] = orm_relationship(back_populates="agent_runs")
    context_pack: Mapped["ContextPack | None"] = orm_relationship(back_populates="agent_runs")
    observations: Mapped[list["RunObservation"]] = orm_relationship(back_populates="agent_run")


class RunObservation(Base):
    __tablename__ = "run_observations"
    __table_args__ = (
        Index("ix_run_observations_agent_run_created", "agent_run_id", "created_at"),
        Index("ix_run_observations_source_document", "source_document_id"),
        Index("ix_run_observations_event_type", "event_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    agent_run: Mapped["AgentRun"] = orm_relationship(back_populates="observations")
    source_document: Mapped["SourceDocument | None"] = orm_relationship()


class CodeFile(Base):
    __tablename__ = "code_files"
    __table_args__ = (
        Index("ix_code_files_workspace_path", "workspace_id", "path"),
        Index("ix_code_files_sha256", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    repo_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    symbols: Mapped[list["CodeSymbol"]] = orm_relationship(back_populates="code_file")


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (
        Index("ix_code_symbols_file", "code_file_id"),
        Index("ix_code_symbols_qualified_name", "qualified_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_files.id"), nullable=False, index=True
    )
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    code_file: Mapped["CodeFile"] = orm_relationship(back_populates="symbols")
    outgoing_edges: Mapped[list["CodeEdge"]] = orm_relationship(
        back_populates="source_symbol",
        foreign_keys="CodeEdge.source_symbol_id",
    )
    incoming_edges: Mapped[list["CodeEdge"]] = orm_relationship(
        back_populates="target_symbol",
        foreign_keys="CodeEdge.target_symbol_id",
    )


class CodeEdge(Base):
    __tablename__ = "code_edges"
    __table_args__ = (
        Index(
            "ix_code_edges_source_target_type", "source_symbol_id", "target_symbol_id", "edge_type"
        ),
        Index("ix_code_edges_target", "target_symbol_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_symbol_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_symbols.id"), nullable=False, index=True
    )
    target_symbol_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_symbols.id"), nullable=False, index=True
    )
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False, default="references")

    source_symbol: Mapped["CodeSymbol"] = orm_relationship(
        back_populates="outgoing_edges",
        foreign_keys=[source_symbol_id],
    )
    target_symbol: Mapped["CodeSymbol"] = orm_relationship(
        back_populates="incoming_edges",
        foreign_keys=[target_symbol_id],
    )


class RepoEvent(Base):
    __tablename__ = "repo_events"
    __table_args__ = (
        Index("ix_repo_events_workspace_commit", "workspace_id", "commit_sha"),
        Index("ix_repo_events_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    commit_sha: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


@event.listens_for(SourceDocument, "before_insert")
@event.listens_for(SourceDocument, "before_update")
def _populate_source_document_ledger_fields(mapper, connection, target: SourceDocument) -> None:
    if target.content and not target.content_sha256:
        target.content_sha256 = _sha256_text(target.content)
    metadata = _metadata_dict(target.metadata_json)
    if not target.trust_zone:
        target.trust_zone = default_trust_zone_for_source(target.source_type, metadata)
    if not target.source_created_at:
        target.source_created_at = _datetime_from_metadata(metadata)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _metadata_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _datetime_from_metadata(metadata: dict[str, Any]) -> datetime | None:
    for key in ("source_created_at", "created_at", "timestamp", "ts"):
        value = metadata.get(key)
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            continue
    return None
