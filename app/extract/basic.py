from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Model, Relationship, SourceDocument

logger = logging.getLogger(__name__)

FACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bdecision\s*:\s*(.{10,})', re.IGNORECASE), "decision"),
    (re.compile(r'\bwe decided\s+(?:to\s+)?(.{10,})', re.IGNORECASE), "decision"),
    (re.compile(r'\bwe(?:\'re| are) going to\s+(.{10,})', re.IGNORECASE), "decision"),
    (re.compile(r'\baction\s*(?:item)?\s*:\s*(.{10,})', re.IGNORECASE), "action_item"),
    (re.compile(r'\btodo\s*:\s*(.{10,})', re.IGNORECASE), "action_item"),
    (re.compile(r'\bplease\s+(\w.{10,})\s+by\b', re.IGNORECASE), "action_item"),
    (re.compile(r'\bblocker\s*:\s*(.{10,})', re.IGNORECASE), "blocker"),
    (re.compile(r'\bblocked\s+(?:on|by)\s+(.{10,})', re.IGNORECASE), "blocker"),
    (re.compile(r'\bwaiting\s+(?:on|for)\s+(.{10,})', re.IGNORECASE), "blocker"),
    (re.compile(r'\bdeadline\s*:\s*(.{5,})', re.IGNORECASE), "deadline"),
    (re.compile(r'\bdue\s+(?:on\s+|by\s+)(.{5,})', re.IGNORECASE), "deadline"),
    (re.compile(r'\blaunch(?:ing)?\s+(?:on|by|at)\s+(.{5,})', re.IGNORECASE), "deadline"),
    (re.compile(r'\bgoal\s*:\s*(.{10,})', re.IGNORECASE), "goal"),
    (re.compile(r'\bour\s+goal\s+is\s+(?:to\s+)?(.{10,})', re.IGNORECASE), "goal"),
    (re.compile(r'\brisk\s*:\s*(.{10,})', re.IGNORECASE), "risk"),
    (re.compile(r'\bconcern\s*:\s*(.{10,})', re.IGNORECASE), "risk"),
]

FACT_CONFIDENCE: dict[str, float] = {
    "decision": 0.85,
    "action_item": 0.80,
    "blocker": 0.80,
    "deadline": 0.75,
    "goal": 0.70,
    "risk": 0.70,
}

_PAST_RE = re.compile(
    r'\b(was|were|had|has been|launched|shipped|completed|deployed|released|removed|deprecated|'
    r'last (?:week|month|quarter|year)|previously|already|used to)\b',
    re.IGNORECASE,
)
_FUTURE_RE = re.compile(
    r'\b(will|going to|plan(?:ned|ning)?|upcoming|next (?:week|month|quarter|year)|'
    r'Q[1-4]\s*20\d{2}|H[12]\s*20\d{2}|coming soon|roadmap|schedule[d]?|intended)\b',
    re.IGNORECASE,
)
_CURRENT_RE = re.compile(
    r'\b(is|are|currently|active|now|today|this (?:week|month|sprint)|ongoing|in progress|'
    r'present|at the moment)\b',
    re.IGNORECASE,
)

_FACT_TYPE_TEMPORAL: dict[str, str] = {
    "blocker": "current",
    "action_item": "current",
    "deadline": "future",
}


def _infer_temporal(value: str, fact_type: str) -> str:
    if _PAST_RE.search(value):
        return "past"
    if _FUTURE_RE.search(value):
        return "future"
    if _CURRENT_RE.search(value):
        return "current"
    return _FACT_TYPE_TEMPORAL.get(fact_type, "unknown")


async def _get_or_create_model(name: str, description: str, session: AsyncSession) -> Model:
    model = await session.scalar(select(Model).where(Model.name == name))
    if not model:
        model = Model(id=uuid4(), name=name, description=description)
        session.add(model)
        await session.flush()
    return model


async def extract_github_documents(
    session: AsyncSession,
    batch_size: int = 200,
) -> dict:
    """Extract structured components from GitHub Issue and Pull Request source documents."""
    github_model = await _get_or_create_model(
        name="GitHub",
        description="Pull requests, issues, and code review discussions from GitHub repositories",
        session=session,
    )

    docs = list(await session.scalars(
        select(SourceDocument)
        .where(SourceDocument.source_type == "github")
        .where(SourceDocument.processed_at.is_(None))
        .limit(batch_size)
    ))

    components_created = 0
    docs_processed = 0

    for doc in docs:
        meta_raw = doc.metadata_json
        meta: dict = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})

        item_type = meta.get("item_type", "issue")
        number = meta.get("number", "?")
        title = meta.get("title", "")
        state = meta.get("state", "open")
        merged = meta.get("merged", False)
        labels: list[str] = meta.get("labels", [])

        if merged:
            temporal = "past"
        elif state == "closed":
            temporal = "past"
        else:
            temporal = "current" if item_type == "issue" else "future"

        display_type = "PR" if item_type == "pull_request" else "Issue"
        raw_name = f"{display_type} #{number}: {title}"
        component_name = raw_name[:55] + ("…" if len(raw_name) > 55 else "")
        status_val = ("merged" if merged else state)

        primary_comp = Component(
            id=uuid4(),
            model_id=github_model.id,
            source_document_id=doc.id,
            name=component_name,
            value=status_val,
            fact_type=item_type,
            confidence=0.95,
            authority_weight=0.85,
            status="active",
            temporal=temporal,
        )
        session.add(primary_comp)
        components_created += 1

        # Label components create tagged sub-facts linking PRs/issues to domain topics
        label_comps: list[Component] = []
        for label in labels[:5]:
            label_comp = Component(
                id=uuid4(),
                model_id=github_model.id,
                source_document_id=doc.id,
                name=f"{display_type} #{number} [{label}]",
                value=label,
                fact_type="label",
                confidence=0.90,
                authority_weight=0.70,
                status="active",
                temporal=temporal,
            )
            session.add(label_comp)
            label_comps.append(label_comp)
            components_created += 1

        # Run generic FACT_PATTERNS on the body text for additional signal
        body_sep = doc.content.find("\n\n")
        body_text = doc.content[body_sep:] if body_sep != -1 else doc.content
        seen_values: set[str] = set()
        pattern_comps: list[Component] = []

        for pattern, fact_type in FACT_PATTERNS:
            for match in pattern.finditer(body_text):
                value = match.group(1).strip().rstrip(".,;")
                key = f"{fact_type}:{value[:60].lower()}"
                if key in seen_values or len(value) < 10:
                    continue
                seen_values.add(key)

                fact_temporal = _infer_temporal(value, fact_type)
                short_name = value[:55] + ("…" if len(value) > 55 else "")
                extra = Component(
                    id=uuid4(),
                    model_id=github_model.id,
                    source_document_id=doc.id,
                    name=short_name,
                    value=value,
                    fact_type=fact_type,
                    confidence=FACT_CONFIDENCE.get(fact_type, 0.7),
                    authority_weight=0.60,
                    status="active",
                    temporal=fact_temporal,
                )
                session.add(extra)
                pattern_comps.append(extra)
                components_created += 1

        await session.flush()

        # Create edges: primary PR/Issue → each derived fact
        all_derived = (label_comps + pattern_comps)[:8]
        for derived in all_derived:
            rel = Relationship(
                id=uuid4(),
                source_component_id=primary_comp.id,
                target_component_id=derived.id,
                relationship_type="contains",
            )
            session.add(rel)

        doc.processed_at = datetime.utcnow()
        docs_processed += 1

    await session.commit()
    logger.info(
        "GitHub extraction complete: %d docs processed, %d components created",
        docs_processed,
        components_created,
    )
    return {"documents_processed": docs_processed, "components_created": components_created}


async def extract_from_source_documents(
    source_type: str,
    session: AsyncSession,
    batch_size: int = 500,
) -> dict:
    from app.services.ingest import IngestionService

    # Connector jobs used to mark documents processed even when the lightweight
    # regex extractor produced zero components. Include those legacy rows so a
    # later sync can repair the graph without requiring manual DB edits.
    has_components = exists().where(Component.source_document_id == SourceDocument.id)
    docs = list(await session.scalars(
        select(SourceDocument)
        .where(SourceDocument.source_type == source_type)
        .where((SourceDocument.processed_at.is_(None)) | (~has_components))
        .order_by(SourceDocument.ingested_at.desc())
        .limit(batch_size)
    ))

    ingestor = IngestionService(session)
    components_created = 0
    docs_processed = 0

    for doc in docs:
        if doc.processed_at is not None:
            doc.processed_at = None
            await session.flush()
        components_created += await ingestor.process_document(doc.id)
        docs_processed += 1

    await session.commit()

    logger.info(
        "Extraction complete: %d docs processed, %d components created",
        docs_processed, components_created,
    )
    return {
        "documents_processed": docs_processed,
        "components_created": components_created,
    }
