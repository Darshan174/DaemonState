from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"decision|task|action\s*item|todo|risk|blocker|feature|metric|"
    r"meeting\s*outcome|outcome|issue|pr|pull\s*request|document|message|email"
    r")\s*:\s*",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def identity_key_for_component_name(name: str | None) -> str | None:
    normalized = normalize_identity_text(name)
    if not normalized:
        return None

    key_body = "-".join(normalized.split())
    key = f"component:{key_body}"
    if len(key) <= 255:
        return key

    digest = hashlib.sha256(key_body.encode("utf-8")).hexdigest()[:16]
    return f"component:{key_body[:228].rstrip('-')}:{digest}"


def normalize_identity_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    previous = None
    while previous != text:
        previous = text
        text = _LABEL_PREFIX_RE.sub("", text).strip()

    tokens = _TOKEN_RE.findall(text.lower())
    return " ".join(tokens)


async def ensure_entity_for_identity(
    session: AsyncSession,
    *,
    model_id: UUID | str | None,
    workspace_id: UUID | str | None,
    identity_key: str | None,
    canonical_name: str | None,
):
    if not identity_key:
        return None

    from app.models import Entity

    normalized_workspace_id = _coerce_uuid(workspace_id)
    normalized_model_id = _coerce_uuid(model_id)
    stmt = select(Entity).where(Entity.identity_key == identity_key)
    if normalized_workspace_id:
        stmt = stmt.where(Entity.workspace_id == normalized_workspace_id)
    else:
        stmt = stmt.where(Entity.workspace_id.is_(None))

    entity = await session.scalar(stmt)
    if entity is None:
        entity = Entity(
            workspace_id=normalized_workspace_id,
            model_id=normalized_model_id,
            identity_key=identity_key,
            canonical_name=_canonical_name(canonical_name, identity_key),
        )
        session.add(entity)
        await session.flush()
    else:
        if normalized_model_id and not entity.model_id:
            entity.model_id = normalized_model_id
        if not entity.canonical_name:
            entity.canonical_name = _canonical_name(canonical_name, identity_key)
    await ensure_entity_alias(
        session,
        entity_id=entity.id,
        workspace_id=entity.workspace_id,
        alias=canonical_name or entity.canonical_name,
        confidence=1.0,
    )
    return entity


async def ensure_entity_alias(
    session: AsyncSession,
    *,
    entity_id: UUID | str | None,
    workspace_id: UUID | str | None,
    alias: str | None,
    source_document_id: UUID | str | None = None,
    confidence: float = 1.0,
):
    normalized_alias = normalize_identity_text(alias)
    normalized_entity_id = _coerce_uuid(entity_id)
    if not normalized_entity_id or not normalized_alias:
        return None

    from app.models import EntityAlias

    stmt = select(EntityAlias).where(
        EntityAlias.entity_id == normalized_entity_id,
        EntityAlias.normalized_alias == normalized_alias,
    )
    existing = await session.scalar(stmt)
    if existing is not None:
        existing.confidence = max(float(existing.confidence or 0.0), _clamp_confidence(confidence))
        if source_document_id and not existing.source_document_id:
            existing.source_document_id = _coerce_uuid(source_document_id)
        return existing

    alias_row = EntityAlias(
        workspace_id=_coerce_uuid(workspace_id),
        entity_id=normalized_entity_id,
        source_document_id=_coerce_uuid(source_document_id),
        alias=_canonical_name(alias, normalized_alias),
        normalized_alias=normalized_alias,
        confidence=_clamp_confidence(confidence),
    )
    session.add(alias_row)
    await session.flush()
    return alias_row


async def record_component_evidence(
    session: AsyncSession,
    *,
    component: Any,
    extracted_fact: Any,
) -> None:
    """Mirror a component into auditable fact/mention records.

    Components remain the compatibility surface for the current API. These
    tables give the backend a stable place to evolve toward canonical facts,
    mentions, aliases, and source-backed provenance without breaking clients.
    """
    from app.models import Fact, Mention

    entity_id = _coerce_uuid(getattr(component, "entity_id", None))
    workspace_id = _coerce_uuid(getattr(component, "workspace_id", None))
    source_document_id = _coerce_uuid(getattr(component, "source_document_id", None))
    component_id = _coerce_uuid(getattr(component, "id", None))
    if not component_id or not source_document_id:
        return

    claim = _claim_text(component, extracted_fact)
    fact = await session.scalar(select(Fact).where(Fact.component_id == component_id))
    if fact is None:
        fact = Fact(
            workspace_id=workspace_id,
            entity_id=entity_id,
            component_id=component_id,
            source_document_id=source_document_id,
            claim=claim,
            fact_type=str(getattr(component, "fact_type", None) or "fact")[:50],
            confidence=_clamp_confidence(getattr(component, "confidence", 0.5)),
            status=str(getattr(component, "status", None) or "active")[:50],
            provenance=getattr(component, "provenance", None),
            excerpt=getattr(component, "excerpt", None),
        )
        session.add(fact)
    else:
        fact.workspace_id = workspace_id
        fact.entity_id = entity_id
        fact.source_document_id = source_document_id
        fact.claim = claim
        fact.fact_type = str(getattr(component, "fact_type", None) or "fact")[:50]
        fact.confidence = _clamp_confidence(getattr(component, "confidence", 0.5))
        fact.status = str(getattr(component, "status", None) or "active")[:50]
        fact.provenance = getattr(component, "provenance", None)
        fact.excerpt = getattr(component, "excerpt", None)

    mention_text = str(getattr(extracted_fact, "name", None) or getattr(component, "name", "")).strip()
    normalized_mention = normalize_identity_text(mention_text)
    if normalized_mention:
        mention = await session.scalar(select(Mention).where(
            Mention.component_id == component_id,
            Mention.normalized_mention == normalized_mention,
        ))
        if mention is None:
            session.add(Mention(
                workspace_id=workspace_id,
                entity_id=entity_id,
                source_document_id=source_document_id,
                component_id=component_id,
                mention_text=mention_text[:255],
                normalized_mention=normalized_mention[:255],
                confidence=_clamp_confidence(getattr(component, "confidence", 0.8)),
            ))
        else:
            mention.workspace_id = workspace_id
            mention.entity_id = entity_id
            mention.source_document_id = source_document_id
            mention.mention_text = mention_text[:255]
            mention.confidence = max(
                float(mention.confidence or 0.0),
                _clamp_confidence(getattr(component, "confidence", 0.8)),
            )

    if entity_id:
        await ensure_entity_alias(
            session,
            entity_id=entity_id,
            workspace_id=workspace_id,
            alias=mention_text,
            source_document_id=source_document_id,
            confidence=_clamp_confidence(getattr(component, "confidence", 0.8)),
        )
    await session.flush()


def _canonical_name(value: str | None, identity_key: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        name = identity_key.removeprefix("component:").replace("-", " ")
    return name[:255]


def _coerce_uuid(value: UUID | str | None) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _clamp_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return min(max(confidence, 0.0), 1.0)


def _claim_text(component: Any, extracted_fact: Any) -> str:
    name = str(getattr(component, "name", "") or "").strip()
    value = str(getattr(component, "value", "") or "").strip()
    if name and value:
        return f"{name}: {value}"
    return name or value or str(getattr(extracted_fact, "value", "") or "fact")
