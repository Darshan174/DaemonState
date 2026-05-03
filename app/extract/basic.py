from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
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


async def extract_from_source_documents(
    source_type: str,
    session: AsyncSession,
    batch_size: int = 500,
) -> dict:
    model_name = source_type.replace("_", " ").title()
    model = await _get_or_create_model(
        name=model_name,
        description=f"Facts extracted from {model_name} messages",
        session=session,
    )

    docs = list(await session.scalars(
        select(SourceDocument)
        .where(SourceDocument.source_type == source_type)
        .where(SourceDocument.processed_at.is_(None))
        .limit(batch_size)
    ))

    components_created = 0
    docs_processed = 0
    seen_values: set[str] = set()

    for doc in docs:
        meta_raw = doc.metadata_json
        if isinstance(meta_raw, str):
            meta = json.loads(meta_raw) if meta_raw else {}
        else:
            meta = meta_raw or {}

        channel_name = meta.get("channel_name") or meta.get("session_id") or source_type
        content = doc.content
        doc_components: list[Component] = []

        for pattern, fact_type in FACT_PATTERNS:
            for match in pattern.finditer(content):
                value = match.group(1).strip().rstrip(".,;")
                key = f"{fact_type}:{value[:60].lower()}"
                if key in seen_values or len(value) < 10:
                    continue
                seen_values.add(key)

                temporal = _infer_temporal(value, fact_type)
                short_name = value[:55] + ("…" if len(value) > 55 else "")
                comp = Component(
                    id=uuid4(),
                    model_id=model.id,
                    source_document_id=doc.id,
                    name=short_name,
                    value=value,
                    fact_type=fact_type,
                    confidence=FACT_CONFIDENCE.get(fact_type, 0.7),
                    authority_weight=0.6,
                    status="active",
                    temporal=temporal,
                )
                session.add(comp)
                doc_components.append(comp)
                components_created += 1

        await session.flush()
        if len(doc_components) >= 2:
            for i, src in enumerate(doc_components[:-1]):
                tgt = doc_components[i + 1]
                rel = Relationship(
                    id=uuid4(),
                    source_component_id=src.id,
                    target_component_id=tgt.id,
                    relationship_type="co_occurs",
                )
                session.add(rel)

        doc.processed_at = datetime.utcnow()
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
