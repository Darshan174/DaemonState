from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.taxonomy import canonical_model_name, canonical_relationship_type

logger = logging.getLogger(__name__)


@dataclass
class ExtractedRelationship:
    target_name: str
    relationship_type: str
    confidence: float = 0.7
    evidence: str | None = None


@dataclass
class ExtractedFact:
    model_name: str
    name: str
    value: str
    fact_type: str
    confidence: float
    temporal: str = "unknown"
    temporal_hint: str = "current"
    relationships: list[ExtractedRelationship] = field(default_factory=list)
    provenance: str | None = None
    excerpt: str | None = None


@dataclass
class ExtractionQualityReport:
    fact_count: int = 0
    relationship_count: int = 0
    low_confidence_count: int = 0
    missing_provenance_count: int = 0
    missing_excerpt_count: int = 0
    missing_relationship_evidence_count: int = 0
    duplicate_fact_count: int = 0
    model_counts: dict[str, int] = field(default_factory=dict)
    fact_type_counts: dict[str, int] = field(default_factory=dict)


EXTRACTION_PROMPT = """You are a context extraction engine for startup knowledge graphs.

Extract structured facts and organize them into CANONICAL ENTITY TYPES:

  CORE:     Company, Product, Feature, Customer, User, Team, Person
  WORK:     Repo, PR, Issue, Task, Document, Message, Email, Meeting
  STRATEGY: Decision, Risk, Metric, Context Pack
  AI WORK:  Agent Session

RULES for model_name — use ONLY the canonical types above:
  - "Decision"      → any choice made, option selected, direction set
  - "Task"          → any action item, todo, follow-up, thing to build
  - "Risk"          → blockers, concerns, unknowns, dependencies at risk
  - "Metric"        → numbers, KPIs, success criteria, targets, SLAs
  - "Feature"       → product capabilities, user-facing functionality
  - "Meeting"       → standups, syncs, reviews, retrospectives, 1:1s
  - "Agent Session" → AI coding/conversation sessions (Claude, Codex, ChatGPT, OpenCode)
  - "PR"            → pull requests, code reviews, merges
  - "Issue"         → bug reports, feature requests, tickets
  - "Document"      → specs, RFCs, design docs, runbooks, wikis
  - "Message"       → Slack messages, chat threads, DMs
  - "Email"         → email threads, newsletters, announcements
  - "Context Pack"  → curated context bundles for AI sessions

Return JSON with this exact schema:
{
  "facts": [
    {
      "model_name": "one of the canonical entity types above",
      "name": "short unique identifier (max 8 words) — be specific, e.g. 'Rate limit auth decision Q1-2025'",
      "value": "full description or exact quote from the source",
      "fact_type": "decision | task | blocker | risk | metric | feature | meeting_note | ai_step | fact",
      "temporal": "current | past | future | unknown",
      "confidence": 0.0,
      "relationships": [
        {"target_name": "exact name of another extracted fact", "relationship_type": "...", "confidence": 0.0}
      ]
    }
  ]
}

TEMPORAL RULES — assign one of:
  - "current"  → present state, exists/is true right now, ongoing
  - "past"     → completed, historical, was done, shipped, decided
  - "future"   → planned, roadmap, will do, next steps, proposed
  - "unknown"  → cannot be determined from context

RELATIONSHIP TYPES — use the strongest applicable link:
  - created_from       → this fact originates from a source (PR created from Issue)
  - mentions           → this fact references another entity
  - decides            → this Decision is about another entity
  - blocks             → this fact is preventing another entity from progressing
  - solves             → this fact resolves or closes another entity
  - depends_on         → this fact requires another entity to proceed
  - assigned_to        → this fact is owned by a Person/Team
  - owned_by           → this entity belongs to a Team or Person
  - implemented_in     → this Decision/Feature is built in a PR/Repo
  - discussed_in       → this Decision happened in a Meeting/Message
  - caused_by          → this Risk/Issue was triggered by another fact
  - supersedes         → this fact replaces or deprecates another
  - generated_by_agent → this fact was produced by an Agent Session
  - verified_by_human  → this fact was confirmed by a Person
  - contradicts        → this fact conflicts with another
  - part_of            → this is a sub-item of another entity

QUALITY RULES:
  - Use ONLY canonical model_name types — never invent new types
  - name is unique and specific (bad: "Auth decision", good: "OAuth2 rate limit auth decision")
  - One idea per component — atomic facts only, no compound items
  - Cross-entity relationships are especially valuable — always add them when visible
  - Max 20 facts. Priority: Decisions > Tasks > Risks > Features > Metrics > rest
  - Always link Decisions to their source Meeting/Message when visible
  - Always link Tasks to the Risk/Decision they address when visible
  - Always link Agent Sessions to the Decisions and Tasks they generated

Document:
{content}
"""


class Extractor:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._model = model or settings.extraction_model
        self._api_key = api_key or settings.litellm_api_key
        self.last_error: str | None = None
        self.last_warnings: list[str] = []
        self.last_report: ExtractionQualityReport | None = None

    async def extract(self, content: str, metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
        self.last_error = None
        self.last_warnings = []
        self.last_report = None
        is_ollama = (self._model or "").startswith("ollama/")
        if self._model and (self._api_key or is_ollama):
            try:
                facts = await self._llm_extract(content)
                facts = _attach_slack_structure(facts, content, metadata or {})
                return self._finish_extraction(_attach_source_provenance(facts, content, metadata or {}))
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("llm extraction failed; falling back to regex: %s", self.last_error)
        return self._finish_extraction(self._regex_extract(content, metadata))

    async def _llm_extract(self, content: str) -> list[ExtractedFact]:
        from litellm import acompletion

        truncated = content[:12000]
        # NOTE: str.format() would choke on the literal JSON braces in the
        # prompt template, so substitute the placeholder directly.
        prompt = EXTRACTION_PROMPT.replace("{content}", truncated)

        response = await acompletion(
            model=self._model,
            api_key=self._api_key,
            messages=[
                {"role": "system", "content": "Extract structured startup knowledge. Return strict JSON only. Use only canonical entity types."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        facts, warnings = _facts_from_llm_payload(data)
        self.last_warnings.extend(warnings)
        if not facts:
            raise ValueError("LLM extraction returned no valid facts")
        return facts[:20]

    def _finish_extraction(self, facts: list[ExtractedFact]) -> list[ExtractedFact]:
        self.last_report = evaluate_extraction_quality(facts)
        return facts

    def _regex_extract(self, content: str, metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []

        def detect_temporal(text: str) -> str:
            t = text.lower()
            past_words = re.compile(r"\b(was|were|decided|implemented|shipped|launched|completed|done|fixed|resolved|had|used to|merged|closed|deprecated)\b")
            future_words = re.compile(r"\b(will|plan|should|roadmap|upcoming|next|todo|need to|going to|intend|propose|want to|Q[1-4]|H[12]\s*20)\b")
            if past_words.search(t):
                return "past"
            if future_words.search(t):
                return "future"
            return "current"

        # Decisions
        for m in re.finditer(r"(?:decision|decided|we chose|we will use)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Decision", name=f"Decision: {text[:120]}",
                    value=text, fact_type="decision",
                    confidence=0.80, temporal=detect_temporal(text),
                    temporal_hint=detect_temporal(text),
                ))

        # Tasks / Action items
        for m in re.finditer(r"(?:action item|todo|task|action|follow.?up)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Task", name=f"Task: {text[:120]}",
                    value=text, fact_type="task",
                    confidence=0.75, temporal=detect_temporal(text),
                    temporal_hint=detect_temporal(text),
                ))

        # Risks / Blockers
        for m in re.finditer(r"(?:blocker|blocked by|risk|concern|dependency risk)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Risk", name=f"Risk: {text[:120]}",
                    value=text, fact_type="blocker",
                    confidence=0.82, temporal="current", temporal_hint="current",
                ))

        # Features
        for m in re.finditer(r"(?:feature|capability|we (?:built|added|shipped|launched))\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Feature", name=f"Feature: {text[:120]}",
                    value=text, fact_type="feature",
                    confidence=0.72, temporal=detect_temporal(text),
                    temporal_hint=detect_temporal(text),
                ))

        # Metrics
        for m in re.finditer(r"(?:metric|kpi|target|goal|measure|success criteria)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Metric", name=f"Metric: {text[:120]}",
                    value=text, fact_type="metric",
                    confidence=0.73, temporal=detect_temporal(text),
                    temporal_hint=detect_temporal(text),
                ))

        # Meeting outcomes
        for m in re.finditer(r"(?:outcome|meeting outcome|conclusion|agreed)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Meeting", name=f"Meeting outcome: {text[:120]}",
                    value=text, fact_type="meeting_note",
                    confidence=0.77, temporal="past", temporal_hint="past",
                ))

        # Agent session steps
        for m in re.finditer(r"(?:agent|ai session|claude|codex|next step|failed attempt)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Agent Session", name=f"AI step: {text[:120]}",
                    value=text, fact_type="ai_step",
                    confidence=0.70, temporal=detect_temporal(text),
                    temporal_hint=detect_temporal(text),
                ))

        if _clean_inline((metadata or {}).get("source_type")).lower() == "slack":
            existing_values = {_clean_inline(f.value).lower() for f in facts}
            facts.extend(_slack_explicit_facts(content, metadata or {}, detect_temporal, existing_values))

        facts = _attach_slack_structure(facts, content, metadata or {})

        if not facts:
            fallback = _source_fallback_fact(content, metadata or {})
            if fallback is not None:
                facts.append(fallback)

        return _attach_source_provenance(facts, content, metadata or {})

    @staticmethod
    def _detect_temporal_hint(content: str) -> str:
        t = content.lower()
        past = re.compile(r"\b(was|were|previously|earlier|deprecated|removed|replaced|used to|old|shipped|completed)\b")
        future = re.compile(r"\b(will|plan to|going to|future|next quarter|roadmap|upcoming|planned|target)\b")
        past_count = len(past.findall(t))
        future_count = len(future.findall(t))
        if future_count > past_count and future_count > 0:
            return "future"
        if past_count > future_count and past_count > 0:
            return "past"
        return "current"


def _attach_source_provenance(
    facts: list[ExtractedFact],
    content: str,
    metadata: dict[str, Any],
) -> list[ExtractedFact]:
    if not facts:
        return facts

    snippet = _content_snippet(content)
    provenance = _fallback_provenance(metadata, {
        "title": metadata.get("title") or metadata.get("name") or metadata.get("subject"),
        "author": metadata.get("author") or metadata.get("from"),
        "workspace_id": metadata.get("workspace_id"),
    })
    for fact in facts:
        if not fact.provenance:
            fact.provenance = provenance
        if not fact.excerpt and snippet:
            fact.excerpt = _truncate(snippet, 280)
    return facts


def _facts_from_llm_payload(data: Any) -> tuple[list[ExtractedFact], list[str]]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        return [], ["llm_payload_not_object"]

    raw_facts = data.get("facts")
    if not isinstance(raw_facts, list):
        return [], ["llm_facts_not_list"]

    facts: list[ExtractedFact] = []
    for idx, item in enumerate(raw_facts):
        if len(facts) >= 20:
            warnings.append("llm_fact_limit_truncated")
            break
        if not isinstance(item, dict):
            warnings.append(f"fact_{idx}_not_object")
            continue

        name = _truncate(_clean_inline(item.get("name")), 255)
        value = _clean_inline(item.get("value"))
        if not name:
            warnings.append(f"fact_{idx}_missing_name")
            continue
        if not value:
            warnings.append(f"fact_{idx}_missing_value")
            continue

        temporal = _clean_inline(item.get("temporal")).lower() or "unknown"
        if temporal not in ("current", "past", "future", "unknown"):
            warnings.append(f"fact_{idx}_invalid_temporal")
            temporal = "unknown"

        relationships = _relationships_from_llm_item(item, idx, warnings)
        facts.append(ExtractedFact(
            model_name=canonical_model_name(item.get("model_name", "Document")),
            name=name,
            value=value,
            fact_type=_truncate(_clean_inline(item.get("fact_type")) or "fact", 50),
            confidence=_coerce_confidence(item.get("confidence"), 0.7, warnings, f"fact_{idx}_invalid_confidence"),
            temporal=temporal,
            temporal_hint=temporal if temporal != "unknown" else "current",
            relationships=relationships,
            provenance=_optional_clean_text(item.get("provenance"), 2000),
            excerpt=_optional_clean_text(item.get("excerpt"), 500),
        ))

    return facts, warnings


def _relationships_from_llm_item(
    item: dict,
    fact_index: int,
    warnings: list[str],
) -> list[ExtractedRelationship]:
    raw_relationships = item.get("relationships", [])
    if raw_relationships in (None, ""):
        return []
    if not isinstance(raw_relationships, list):
        warnings.append(f"fact_{fact_index}_relationships_not_list")
        return []

    relationships: list[ExtractedRelationship] = []
    for rel_index, raw_rel in enumerate(raw_relationships[:20]):
        if not isinstance(raw_rel, dict):
            warnings.append(f"fact_{fact_index}_rel_{rel_index}_not_object")
            continue
        target_name = _truncate(_clean_inline(raw_rel.get("target_name")), 255)
        if not target_name:
            warnings.append(f"fact_{fact_index}_rel_{rel_index}_missing_target")
            continue
        relationships.append(ExtractedRelationship(
            target_name=target_name,
            relationship_type=canonical_relationship_type(raw_rel.get("relationship_type", "related_to")),
            confidence=_coerce_confidence(
                raw_rel.get("confidence"),
                0.7,
                warnings,
                f"fact_{fact_index}_rel_{rel_index}_invalid_confidence",
            ),
            evidence=_optional_clean_text(raw_rel.get("evidence"), 500),
        ))
    if len(raw_relationships) > 20:
        warnings.append(f"fact_{fact_index}_relationships_truncated")
    return relationships


def evaluate_extraction_quality(facts: list[ExtractedFact]) -> ExtractionQualityReport:
    report = ExtractionQualityReport(fact_count=len(facts))
    seen_keys: set[tuple[str, str, str]] = set()
    for fact in facts:
        model_name = canonical_model_name(fact.model_name)
        fact_type = _clean_inline(fact.fact_type) or "fact"
        report.model_counts[model_name] = report.model_counts.get(model_name, 0) + 1
        report.fact_type_counts[fact_type] = report.fact_type_counts.get(fact_type, 0) + 1
        if _safe_float(fact.confidence, 0.0) < 0.6:
            report.low_confidence_count += 1
        if not fact.provenance:
            report.missing_provenance_count += 1
        if not fact.excerpt:
            report.missing_excerpt_count += 1

        dedupe_key = (
            model_name.lower(),
            _clean_inline(fact.name).lower(),
            _clean_inline(fact.value).lower(),
        )
        if dedupe_key in seen_keys:
            report.duplicate_fact_count += 1
        else:
            seen_keys.add(dedupe_key)

        report.relationship_count += len(fact.relationships)
        report.missing_relationship_evidence_count += sum(
            1 for rel in fact.relationships if not rel.evidence
        )
    return report


def _source_fallback_fact(content: str, metadata: dict[str, Any]) -> ExtractedFact | None:
    first_lines = content[:500].strip()
    if not first_lines:
        return None

    source_type = _clean_inline(metadata.get("source_type")).lower()
    if source_type == "gmail":
        return _gmail_fallback_fact(content, metadata)
    if source_type == "slack":
        return _slack_fallback_fact(content, metadata)
    if source_type == "gdrive":
        return ExtractedFact(
            model_name="Document",
            name=_truncate(f"Drive document: {_clean_inline(metadata.get('name')) or _generic_title(first_lines, metadata)}", 120),
            value=first_lines,
            fact_type="document",
            confidence=0.60,
            temporal="unknown",
            temporal_hint="current",
            provenance=_fallback_provenance(metadata, {"name": metadata.get("name")}),
            excerpt=_truncate(_clean_inline(first_lines), 280),
        )

    external_id = _clean_inline(metadata.get("external_id"))
    title = external_id or first_lines.splitlines()[0][:80].strip() or "content"
    return ExtractedFact(
        model_name="Document",
        name=f"Document: {title}"[:120],
        value=first_lines,
        fact_type="fact",
        confidence=0.50,
        temporal="unknown",
        temporal_hint="current",
    )


def _gmail_fallback_fact(content: str, metadata: dict[str, Any]) -> ExtractedFact:
    subject = _clean_inline(metadata.get("subject")) or "(no subject)"
    sender = _email_sender_label(metadata.get("from"))
    snippet = _clean_inline(metadata.get("snippet")) or _content_snippet(content)

    sender_suffix = f" from {sender}" if sender else ""
    name = _truncate(f"Email: {subject}{sender_suffix}", 120)
    value_lines = [f"Subject: {subject}"]
    if sender:
        value_lines.append(f"From: {sender}")
    if snippet:
        value_lines.extend(["", snippet])

    return ExtractedFact(
        model_name="Email",
        name=name,
        value="\n".join(value_lines).strip() or content[:500].strip(),
        fact_type="email",
        confidence=0.70,
        temporal="unknown",
        temporal_hint="current",
        provenance=_fallback_provenance(metadata, {
            "subject": subject,
            "from": sender,
            "snippet": snippet,
            "thread_id": metadata.get("thread_id"),
        }),
        excerpt=_truncate(snippet, 280) if snippet else None,
    )


def _slack_fallback_fact(content: str, metadata: dict[str, Any]) -> ExtractedFact:
    channel = _slack_channel_label(metadata)
    author = _slack_author_label(
        metadata.get("author_name") or metadata.get("author") or metadata.get("user_name") or metadata.get("user_id")
    )
    snippet = _content_snippet(content)

    context = " - ".join(part for part in (channel, author) if part)
    if context and snippet:
        name = f"Slack: {context}: {snippet}"
    elif context:
        name = f"Slack: {context}"
    else:
        name = f"Slack message: {snippet or _generic_title(content, metadata)}"

    value_lines = []
    if channel:
        value_lines.append(f"Channel: {channel}")
    if author:
        value_lines.append(f"Author: {author}")
    if metadata.get("is_thread_reply") and metadata.get("parent_ts"):
        value_lines.append(f"Thread reply to: {metadata.get('parent_ts')}")
    if snippet:
        value_lines.extend(["", snippet])

    return ExtractedFact(
        model_name="Message",
        name=_truncate(name, 120),
        value="\n".join(value_lines).strip() or content[:500].strip(),
        fact_type="message",
        confidence=0.70,
        temporal="unknown",
        temporal_hint="current",
        provenance=_fallback_provenance(metadata, {
            "channel_name": metadata.get("channel_name"),
            "channel_id": metadata.get("channel_id"),
            "author": author,
            "user_id": metadata.get("user_id") or metadata.get("author"),
            "ts": metadata.get("ts"),
            "thread_ts": metadata.get("thread_ts"),
            "parent_ts": metadata.get("parent_ts"),
            "is_thread_reply": metadata.get("is_thread_reply"),
            "permalink": metadata.get("permalink"),
        }),
        excerpt=_truncate(snippet, 280) if snippet else None,
    )


def _slack_explicit_facts(
    content: str,
    metadata: dict[str, Any],
    detect_temporal,
    existing_values: set[str],
) -> list[ExtractedFact]:
    """Conservative Slack-only patterns for common chat phrasing without colons."""
    patterns = [
        (
            r"\b(?:we decided to|decided to)\s+(.+?)(?:[.!?](?:\s|$)|$)",
            "Decision",
            "Decision",
            "decision",
            0.78,
        ),
        (
            r"^\s*(?:todo|task|action item|follow[- ]?up)\s*(?:-|:)\s*(.+?)\s*$",
            "Task",
            "Task",
            "task",
            0.74,
        ),
        (
            r"\b(?:risk|concern|blocker)\s+(?:is|are)\s+(.+?)(?:[.!?](?:\s|$)|$)",
            "Risk",
            "Risk",
            "blocker",
            0.78,
        ),
        (
            r"^\s*(?:feature|capability)\s*(?:-|:)\s*(.+?)\s*$",
            "Feature",
            "Feature",
            "feature",
            0.72,
        ),
        (
            r"^\s*(?:metric|kpi|target|goal)\s*(?:-|:)\s*(.+?)\s*$",
            "Metric",
            "Metric",
            "metric",
            0.73,
        ),
    ]
    facts: list[ExtractedFact] = []
    snippet = _content_snippet(content)
    provenance = _fallback_provenance(metadata, {
        "channel_name": metadata.get("channel_name"),
        "channel_id": metadata.get("channel_id"),
        "author": metadata.get("author_name") or metadata.get("author") or metadata.get("user_id"),
        "ts": metadata.get("ts"),
        "thread_ts": metadata.get("thread_ts"),
        "parent_ts": metadata.get("parent_ts"),
        "is_thread_reply": metadata.get("is_thread_reply"),
        "permalink": metadata.get("permalink"),
    })

    for pattern, model_name, prefix, fact_type, confidence in patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
            text = _clean_inline(match.group(1))
            if not text:
                continue
            key = text.lower()
            if key in existing_values:
                continue
            existing_values.add(key)
            temporal = "current" if model_name == "Risk" else detect_temporal(text)
            facts.append(ExtractedFact(
                model_name=model_name,
                name=_truncate(f"{prefix}: {text}", 120),
                value=text,
                fact_type=fact_type,
                confidence=confidence,
                temporal=temporal,
                temporal_hint=temporal,
                provenance=provenance,
                excerpt=_truncate(snippet, 280) if snippet else None,
            ))
    return facts


def _attach_slack_structure(
    facts: list[ExtractedFact],
    content: str,
    metadata: dict[str, Any],
) -> list[ExtractedFact]:
    """Deterministic Slack structure rules:

    - every Slack message keeps a Message root component as evidence anchor;
    - extracted facts link to their message root via ``discussed_in``;
    - the message root links to a channel hub component via ``part_of``.
    """
    source_type = _clean_inline(metadata.get("source_type")).lower()
    if source_type != "slack":
        return facts

    root = _slack_fallback_fact(content, metadata)
    snippet = root.excerpt or _truncate(content, 280)
    provenance = _fallback_provenance(metadata, {
        "channel_name": metadata.get("channel_name"),
        "channel_id": metadata.get("channel_id"),
        "author": metadata.get("author_name") or metadata.get("author") or metadata.get("user_id"),
        "ts": metadata.get("ts"),
        "thread_ts": metadata.get("thread_ts"),
        "parent_ts": metadata.get("parent_ts"),
        "is_thread_reply": metadata.get("is_thread_reply"),
        "permalink": metadata.get("permalink"),
    })
    for fact in facts:
        if not fact.provenance:
            fact.provenance = provenance
        if not fact.excerpt and snippet:
            fact.excerpt = _truncate(snippet, 280)
        if fact.model_name == "Message":
            continue
        fact.relationships.append(ExtractedRelationship(
            target_name=root.name,
            relationship_type="discussed_in",
            confidence=0.9,
            evidence=f'Extracted from Slack message: "{snippet}"',
        ))
    facts = [*facts, root]

    channel = _slack_channel_fact(metadata)
    if channel is not None:
        root.relationships.append(ExtractedRelationship(
            target_name=channel.name,
            relationship_type="part_of",
            confidence=0.95,
            evidence=f"Message posted in Slack channel {_slack_channel_label(metadata)}.",
        ))
        facts.append(channel)
    return facts


def _slack_channel_fact(metadata: dict[str, Any]) -> ExtractedFact | None:
    channel = _slack_channel_label(metadata)
    if not channel:
        return None
    return ExtractedFact(
        model_name="Message",
        name=_truncate(f"Slack channel {channel}", 120),
        value=f"Slack channel {channel} — hub for messages ingested from this channel.",
        fact_type="fact",
        confidence=0.9,
        temporal="current",
        temporal_hint="current",
        provenance=_fallback_provenance(metadata, {
            "channel_name": metadata.get("channel_name"),
            "channel_id": metadata.get("channel_id"),
            "thread_ts": metadata.get("thread_ts"),
            "permalink": metadata.get("permalink"),
        }),
    )


def _fallback_provenance(metadata: dict[str, Any], extra: dict[str, Any]) -> str:
    payload = {
        "source_type": metadata.get("source_type"),
        "external_id": metadata.get("external_id"),
        "source_url": metadata.get("source_url") or metadata.get("permalink"),
        **extra,
    }
    return json.dumps({k: v for k, v in payload.items() if v not in (None, "", [])})


def _generic_title(content: str, metadata: dict[str, Any]) -> str:
    return _clean_inline(metadata.get("external_id")) or _clean_inline(content.splitlines()[0] if content else "") or "content"


def _content_snippet(content: str, limit: int = 220) -> str:
    lines = []
    for line in content.splitlines():
        clean = _clean_inline(line)
        if not clean:
            continue
        if clean.startswith("[Gmail]") or clean.startswith("From:") or clean.startswith("To:") or clean.startswith("Date:"):
            continue
        lines.append(clean)
    return _truncate(" ".join(lines) or _clean_inline(content), limit)


def _clean_inline(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _optional_clean_text(value: Any, max_chars: int) -> str | None:
    cleaned = _clean_inline(value)
    return _truncate(cleaned, max_chars) if cleaned else None


def _coerce_confidence(
    value: Any,
    default: float,
    warnings: list[str],
    warning_code: str,
) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        warnings.append(warning_code)
        confidence = default
    return min(max(confidence, 0.0), 1.0)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truncate(value: str, max_chars: int) -> str:
    text = _clean_inline(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars - 3].rstrip()}..."


def _email_sender_label(value: Any) -> str:
    text = _clean_inline(value)
    if not text:
        return ""
    match = re.match(r'(?:"?([^"<]+)"?\s*)?<([^>]+)>', text)
    if match:
        name = _clean_inline(match.group(1))
        email = _clean_inline(match.group(2))
        return name or email
    return text


def _slack_channel_label(metadata: dict[str, Any]) -> str:
    channel = _clean_inline(metadata.get("channel_name"))
    if channel and not _looks_like_slack_id(channel, "C"):
        return channel if channel.startswith("#") else f"#{channel}"
    return ""


def _slack_author_label(value: Any) -> str:
    author = _clean_inline(value)
    if not author or _looks_like_slack_id(author, "UW"):
        return ""
    return author


def _looks_like_slack_id(value: str, prefixes: str) -> bool:
    return bool(re.fullmatch(rf"[{prefixes}][A-Z0-9]{{1,}}", value))
