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

    async def extract(self, content: str, metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
        self.last_error = None
        is_ollama = (self._model or "").startswith("ollama/")
        if self._model and (self._api_key or is_ollama):
            try:
                return await self._llm_extract(content)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("llm extraction failed; falling back to regex: %s", self.last_error)
        return self._regex_extract(content)

    async def _llm_extract(self, content: str) -> list[ExtractedFact]:
        from litellm import acompletion

        truncated = content[:12000]
        prompt = EXTRACTION_PROMPT.format(content=truncated)

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
        facts = []
        for item in data.get("facts", []):
            rels = [
                ExtractedRelationship(
                    target_name=r["target_name"],
                    relationship_type=canonical_relationship_type(r.get("relationship_type", "related_to")),
                    confidence=min(max(float(r.get("confidence", 0.7)), 0.0), 1.0),
                    evidence=r.get("evidence"),
                )
                for r in item.get("relationships", [])
                if r.get("target_name")
            ]
            temporal = item.get("temporal", "unknown")
            if temporal not in ("current", "past", "future", "unknown"):
                temporal = "unknown"
            facts.append(ExtractedFact(
                model_name=canonical_model_name(item.get("model_name", "Document")),
                name=item["name"],
                value=item["value"],
                fact_type=item.get("fact_type", "fact"),
                confidence=min(max(float(item.get("confidence", 0.7)), 0.0), 1.0),
                temporal=temporal,
                temporal_hint=temporal if temporal != "unknown" else "current",
                relationships=rels,
            ))
        return facts[:20]

    def _regex_extract(self, content: str) -> list[ExtractedFact]:
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

        if not facts:
            first_lines = content[:500].strip()
            if first_lines:
                facts.append(ExtractedFact(
                    model_name="Document", name="Document content",
                    value=first_lines, fact_type="fact",
                    confidence=0.50, temporal="unknown", temporal_hint="current",
                ))

        return facts

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
