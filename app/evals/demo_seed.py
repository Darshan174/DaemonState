"""Deterministic demo seed data for local smoke runs and eval regressions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import BigInteger

from app.evals.gold_set import load_default_cases
from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.processing.embedder import HashingEmbedder


DEFAULT_WORKSPACE_NAME = "Acme Accuracy Demo"
_EMBEDDER = HashingEmbedder()

# Stable 64-bit signed integer used with pg_advisory_xact_lock() to serialize
# concurrent callers of seed_demo_workspace(). Without this lock, two requests
# can both observe "no workspace yet" and both insert a fresh demo workspace
# because Workspace.name has no unique constraint. The lock is transaction-
# scoped and released automatically at commit or rollback.
#
# The key is derived from a fixed string so the value is stable across processes
# (unlike Python's builtin hash() which is randomized by PYTHONHASHSEED). Any
# unique 64-bit integer works; this derivation just guarantees uniqueness and
# is self-documenting.
_SEED_ADVISORY_LOCK_KEY: int = int.from_bytes(
    hashlib.sha256(b"context-engine:demo-seed").digest()[:8],
    byteorder="big",
    signed=True,
)


async def _acquire_seed_lock(session: AsyncSession) -> None:
    """Block until this transaction holds the demo-seed advisory lock.

    pg_advisory_xact_lock is a blocking, reentrant lock bound to the current
    transaction. Two concurrent callers racing to seed the demo workspace will
    be serialized here: the first caller creates the workspace and commits
    (releasing the lock), the second caller then acquires the lock and
    observes the already-created workspace via the subsequent SELECT.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)").bindparams(
            bindparam("key", type_=BigInteger)
        ),
        {"key": _SEED_ADVISORY_LOCK_KEY},
    )


@dataclass(frozen=True, slots=True)
class SourceSeed:
    connector_type: ConnectorType
    external_id: str
    content: str
    label_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class ComponentSeed:
    model_name: str
    model_description: str
    name: str
    value: str
    sources: tuple[SourceSeed, ...]
    authority_weight: float = 0.9
    valid_from_days_ago: int = 0
    valid_to_days_ago: int | None = None
    last_verified_days_ago: int = 0
    is_stale: bool = False


@dataclass(frozen=True, slots=True)
class SeedResult:
    workspace_id: UUID
    workspace_name: str
    status: str
    seeded_case_count: int


class SeedWorkspaceNotFoundError(LookupError):
    """Raised when a requested workspace for demo seeding does not exist."""


_SEEDS: tuple[ComponentSeed, ...] = (
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Enterprise Plan",
        value="Enterprise pricing is $600/seat with annual terms.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-enterprise-plan",
                "Enterprise pricing is $600/seat.",
                {"page_title": "Pricing Handbook"},
            ),
            SourceSeed(
                ConnectorType.SLACK,
                "slack-enterprise-plan",
                "Decision: enterprise stays at $600/seat.",
                {"channel_name": "pricing"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Legacy Enterprise Plan",
        value="Legacy enterprise pricing was $500/seat before the April pricing update.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-enterprise-plan-legacy",
                "Legacy memo: enterprise pricing was $500/seat before April 2026. Superseded by the pricing handbook.",
                {"page_title": "Old Pricing Memo"},
            ),
        ),
        authority_weight=0.2,
        valid_from_days_ago=120,
        valid_to_days_ago=20,
        last_verified_days_ago=120,
        is_stale=True,
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Starter Plan",
        value="Starter Plan is $29/mo.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-starter-plan",
                "Starter Plan is $29/mo.",
                {"page_title": "Pricing Handbook"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Growth Plan",
        value="Growth tier is $149/mo with team features included.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-growth-plan",
                "Growth Plan: $149/mo with team features.",
                {"page_title": "Pricing Handbook"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Annual Discount Policy",
        value="We offer a 20% discount for annual commitments across all plans.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-annual-discount",
                "Annual discount: 20% off for annual billing on all plans.",
                {"page_title": "Pricing Handbook"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="SSO Blocker",
        value="Active blockers: SSO is blocked by engineering bandwidth and analytics reliability work.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-sso-blocker",
                "SSO is blocked by engineering bandwidth.",
                {"channel_name": "roadmap"},
            ),
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-sso-blocker",
                "Meeting blocker: engineering bandwidth is the blocker for SSO.",
                {"meeting_topic": "Weekly Product Review"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Blocker in Weekly Product Review",
        value="From meetings: current blockers include waiting on legal approval.",
        sources=(
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-legal-blocker",
                "Current blocker: waiting on legal approval.",
                {"meeting_topic": "Weekly Product Review"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="API Migration Blocker",
        value="API migration is blocked by downstream partner integration not being ready.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-api-migration-blocker",
                "Blocker: downstream partner integration not ready for API migration.",
                {"channel_name": "engineering"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="Mobile Release Blocker",
        value="Mobile release is blocked pending app store review approval.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-mobile-release-blocker",
                "Blocker: waiting on app store review for mobile release.",
                {"channel_name": "mobile"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="SSO Launch Target",
        value="SSO launch target is Q3.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-sso-launch",
                "SSO launch target is Q3.",
                {"page_title": "Roadmap"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="Analytics Rewrite Target",
        value="Analytics rewrite is targeted for Q4 delivery.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-analytics-rewrite",
                "Analytics rewrite target: Q4.",
                {"page_title": "Roadmap"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Roadmap",
        model_description="Roadmap facts",
        name="Mobile App Launch",
        value="Mobile app launch is planned for Q2 with cross-platform support.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-mobile-launch",
                "Mobile app launch: Q2 with cross-platform mobile support.",
                {"page_title": "Roadmap"},
            ),
            SourceSeed(
                ConnectorType.SLACK,
                "slack-mobile-launch",
                "Confirmed: mobile app targets Q2 launch.",
                {"channel_name": "product"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Decision in Weekly Product Review",
        value="Meeting decision: we decided the launch timing — ship the onboarding flow next Tuesday.",
        sources=(
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-onboarding-decision",
                "We decided to ship onboarding next Tuesday.",
                {"meeting_topic": "Weekly Product Review"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Decisions",
        model_description="Decision facts",
        name="DB Migration Decision",
        value="We decided to migrate to Postgres 16 using a rolling upgrade strategy.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-db-migration",
                "Decision: migrate to Postgres 16 with rolling upgrade.",
                {"channel_name": "engineering"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Decisions",
        model_description="Decision facts",
        name="Legacy DB Migration Decision",
        value="The old database migration plan proposed a MySQL lift-and-shift.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-db-migration-legacy",
                "Old decision: use a MySQL lift-and-shift for the database migration. Superseded by the Postgres 16 rolling upgrade decision.",
                {"page_title": "Legacy Architecture Decisions"},
            ),
        ),
        authority_weight=0.2,
        valid_from_days_ago=110,
        valid_to_days_ago=14,
        last_verified_days_ago=110,
        is_stale=True,
    ),
    ComponentSeed(
        model_name="Decisions",
        model_description="Decision facts",
        name="Auth Provider Decision",
        value="We chose Auth0 as our authentication provider.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-auth-provider",
                "Decision: going with Auth0 for authentication.",
                {"channel_name": "engineering"},
            ),
            SourceSeed(
                ConnectorType.NOTION,
                "notion-auth-provider",
                "Auth provider decision: Auth0 selected.",
                {"page_title": "Architecture Decisions"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Decisions",
        model_description="Decision facts",
        name="Framework Decision",
        value="We picked FastAPI for the new service framework.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-framework-decision",
                "Decision: picked FastAPI for the new service.",
                {"channel_name": "engineering"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Action Item from Engineering Sync",
        value="Action item: run load test on staging before the release.",
        sources=(
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-eng-action-item",
                "AI: run load test on staging before release.",
                {"meeting_topic": "Engineering Sync"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Sales Pipeline Update",
        value="Enterprise pipeline is growing with three new deals in negotiation.",
        sources=(
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-sales-pipeline",
                "Sales update: enterprise pipeline growing, three new deals.",
                {"meeting_topic": "Sales Standup"},
            ),
            SourceSeed(
                ConnectorType.GONG,
                "gong-sales-pipeline",
                "Enterprise pipeline update: three deals in negotiation.",
                {"location": "Sales Call Recording"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Retro Concern",
        value="Concern raised: deployment rollback process needs improvement.",
        sources=(
            SourceSeed(
                ConnectorType.ZOOM,
                "zoom-retro-concern",
                "Retro: deployment rollback process needs improvement.",
                {"meeting_topic": "Sprint Retrospective"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Zoom Insights",
        model_description="Meeting facts",
        name="Customer Feedback Summary",
        value="Customer feedback: onboarding documentation needs to be clearer.",
        sources=(
            SourceSeed(
                ConnectorType.GONG,
                "gong-customer-feedback",
                "Customer call: onboarding documentation needs improvement.",
                {"location": "Customer Success Call"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Customer Success",
        model_description="Customer-facing operating policies and feedback",
        name="Support SLA Decision",
        value="Current enterprise support SLA is 4 hours for Sev-1 incidents.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-support-sla-current",
                "Current policy: enterprise support SLA is 4 hours for Sev-1 incidents.",
                {"page_title": "Support Handbook"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Customer Success",
        model_description="Customer-facing operating policies and feedback",
        name="Legacy Support SLA",
        value="Legacy enterprise support SLA was 24 hours before customer escalations.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-support-sla-legacy",
                "Old policy: enterprise support SLA was 24 hours. Superseded after customer escalations.",
                {"page_title": "Old Support Handbook"},
            ),
        ),
        authority_weight=0.2,
        valid_from_days_ago=100,
        valid_to_days_ago=10,
        last_verified_days_ago=100,
        is_stale=True,
    ),
    ComponentSeed(
        model_name="Growth",
        model_description="Growth metrics and operating targets",
        name="Activation KPI Target",
        value="Current onboarding activation target is 42% by the end of Q2.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-activation-kpi-current",
                "Current KPI: onboarding activation target is 42% by end of Q2.",
                {"channel_name": "growth"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Growth",
        model_description="Growth metrics and operating targets",
        name="Legacy Activation KPI Target",
        value="The old onboarding activation target was 35%.",
        sources=(
            SourceSeed(
                ConnectorType.SLACK,
                "slack-activation-kpi-legacy",
                "Old KPI: onboarding activation target was 35%. This was replaced by the 42% target.",
                {"channel_name": "growth"},
            ),
        ),
        authority_weight=0.2,
        valid_from_days_ago=90,
        valid_to_days_ago=12,
        last_verified_days_ago=90,
        is_stale=True,
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="AI Credits Policy",
        value="AI credits are included in Growth and Enterprise plans under fair-use limits.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-ai-credits-current",
                "Current policy: AI credits are included in Growth and Enterprise under fair-use limits.",
                {"page_title": "Pricing Handbook"},
            ),
        ),
    ),
    ComponentSeed(
        model_name="Pricing",
        model_description="Pricing facts",
        name="Legacy AI Credits Policy",
        value="AI credits used to be a paid add-on.",
        sources=(
            SourceSeed(
                ConnectorType.NOTION,
                "notion-ai-credits-legacy",
                "Old policy: AI credits were a paid add-on. Superseded by included fair-use credits.",
                {"page_title": "Old Pricing Memo"},
            ),
        ),
        authority_weight=0.2,
        valid_from_days_ago=80,
        valid_to_days_ago=8,
        last_verified_days_ago=80,
        is_stale=True,
    ),
    ComponentSeed(
        model_name="GitHub Insights",
        model_description="GitHub issue and pull-request context",
        name="CI Workflow Follow-up",
        value="GitHub issue tracks tightening accuracy regression gating in CI.",
        sources=(
            SourceSeed(
                ConnectorType.GITHUB,
                "github:acme/context-engine:issue:42",
                "Issue #42: tighten accuracy regression gating in CI and document the local eval path.",
                {
                    "title": "Tighten accuracy regression gating",
                    "repo_full_name": "acme/context-engine",
                },
            ),
        ),
    ),
)


async def seed_demo_workspace(
    session: AsyncSession,
    *,
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
    replace_existing: bool = False,
) -> SeedResult:
    # Serialize concurrent callers under pg_advisory_xact_lock so we cannot
    # observe "no workspace" twice and double-insert. See the module-level
    # comment on _SEED_ADVISORY_LOCK_KEY for why this is necessary.
    await _acquire_seed_lock(session)

    workspace = await session.scalar(
        select(Workspace).where(Workspace.name == workspace_name).limit(1)
    )
    if workspace is not None and replace_existing:
        await session.delete(workspace)
        # Intermediate commit releases the advisory lock, so re-acquire it
        # before recreating and re-check to avoid racing another replace
        # caller that may have recreated the workspace in the meantime.
        await session.commit()
        await _acquire_seed_lock(session)
        workspace = await session.scalar(
            select(Workspace).where(Workspace.name == workspace_name).limit(1)
        )

    if workspace is not None:
        return SeedResult(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            status="existing",
            seeded_case_count=len(load_default_cases()),
        )

    workspace = Workspace(
        name=workspace_name,
        description="Deterministic demo workspace for local smoke tests and eval regressions.",
    )
    session.add(workspace)
    await session.flush()

    return await _populate_demo_workspace(session, workspace=workspace, status="created")


async def seed_demo_into_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> SeedResult:
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).limit(1)
    )
    if workspace is None:
        raise SeedWorkspaceNotFoundError("Workspace not found")

    if await _workspace_has_context(session, workspace.id):
        return SeedResult(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            status="existing",
            seeded_case_count=len(load_default_cases()),
        )

    return await _populate_demo_workspace(session, workspace=workspace, status="created")


async def _populate_demo_workspace(
    session: AsyncSession,
    *,
    workspace: Workspace,
    status: str,
) -> SeedResult:
    connectors = {
        connector_type: await _ensure_connector(session, workspace.id, connector_type)
        for connector_type in {
            source.connector_type
            for seed in _SEEDS
            for source in seed.sources
        }
    }
    models: dict[str, KnowledgeModel] = {}
    now = datetime.now(UTC)

    for seed in _SEEDS:
        model = models.get(seed.model_name)
        if model is None:
            model = KnowledgeModel(
                workspace_id=workspace.id,
                name=seed.model_name,
                description=seed.model_description,
            )
            session.add(model)
            await session.flush()
            models[seed.model_name] = model

        component = Component(
            model_id=model.id,
            name=seed.name,
            value=seed.value,
            confidence=0.95,
            authority_source="seeded-demo",
            authority_weight=seed.authority_weight,
            valid_from=now - timedelta(days=seed.valid_from_days_ago),
            valid_to=(
                now - timedelta(days=seed.valid_to_days_ago)
                if seed.valid_to_days_ago is not None
                else None
            ),
            last_verified_at=now - timedelta(days=seed.last_verified_days_ago),
            is_stale=seed.is_stale,
            embedding=await _EMBEDDER.embed_text(f"{seed.name}\n{seed.value}"),
        )
        session.add(component)
        await session.flush()

        for source_seed in seed.sources:
            connector = connectors[source_seed.connector_type]
            document = SourceDocument(
                connector_id=connector.id,
                connector_type=source_seed.connector_type,
                external_id=source_seed.external_id,
                content=source_seed.content,
                author="seed",
                source_url=f"https://example.com/{source_seed.external_id}",
                created_at_source=now,
                metadata_json=source_seed.label_metadata,
                processed_at=now,
            )
            session.add(document)
            await session.flush()
            session.add(
                ComponentSource(
                    component_id=component.id,
                    source_document_id=document.id,
                    extraction_context=source_seed.content,
                    extractor_name="structured_llm",
                    extractor_kind="llm_structured",
                    extractor_schema_version="fact_extraction.v1",
                )
            )

    await session.commit()
    return SeedResult(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        status=status,
        seeded_case_count=len(load_default_cases()),
    )


async def _ensure_connector(
    session: AsyncSession,
    workspace_id: UUID,
    connector_type: ConnectorType,
) -> Connector:
    existing = await session.scalar(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type == connector_type,
        )
    )
    if existing is not None:
        return existing

    connector = Connector(
        workspace_id=workspace_id,
        connector_type=connector_type,
        status=ConnectorStatus.CONNECTED,
        config=_connector_config(connector_type),
    )
    session.add(connector)
    await session.flush()
    return connector


async def _workspace_has_context(session: AsyncSession, workspace_id: UUID) -> bool:
    """Check whether the workspace already has structured context.

    We look for Component rows (structured facts) linked to the workspace
    via a KnowledgeModel, not merely Connector rows. A workspace can have
    connector config (e.g. a linked Slack connector) without any actual
    seeded or ingested content — connectors are plumbing, components are
    content. Checking only connectors would cause /seed-demo to no-op for
    a workspace that has been connected but never populated.
    """
    component_id = await session.scalar(
        select(Component.id)
        .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
        .where(KnowledgeModel.workspace_id == workspace_id)
        .limit(1)
    )
    return component_id is not None


def _connector_config(connector_type: ConnectorType) -> dict[str, object]:
    if connector_type == ConnectorType.ZOOM:
        return {
            "ingestion_mode": "transcripts_only",
            "source_focus": "meeting_transcripts",
            "auth_mode": "manual_token",
            "sync_delivery_mode": "polling_only",
            "webhook_auto_sync": False,
        }
    if connector_type == ConnectorType.GITHUB:
        return {
            "ingestion_mode": "issues_and_pull_requests",
            "source_focus": "engineering_system_of_record",
            "auth_mode": "manual_token",
            "sync_delivery_mode": "polling_only",
            "webhook_auto_sync": False,
            "repositories": ["acme/context-engine"],
        }
    return {}
