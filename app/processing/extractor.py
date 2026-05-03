from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import settings


@dataclass
class ExtractedRelationship:
    target_name: str
    relationship_type: str
    confidence: float = 0.7


@dataclass
class ExtractedFact:
    model_name: str
    name: str
    value: str
    fact_type: str
    temporal: str
    confidence: float
    relationships: list[ExtractedRelationship] = field(default_factory=list)


EXTRACTION_PROMPT = """You extract structured knowledge from business and product documents.

Organize facts into DOMAIN MODELS — high-level business areas such as:
Pricing, Features, Infrastructure, Team, Roadmap, Users, Integrations,
Competitors, Legal, Marketing, Architecture, Decisions, Blockers.

Return JSON with this exact schema:
{
  "facts": [
    {
      "model_name": "business domain (e.g. Pricing, Features, Infrastructure)",
      "name": "short specific identifier (e.g. '$80/mo Growth Tier', 'OAuth2 Support')",
      "value": "full description or exact quote from the document",
      "fact_type": "decision | action_item | blocker | discussion | fact",
      "temporal": "current | past | future | unknown",
      "confidence": 0.0,
      "relationships": [
        {"target_name": "exact name of another extracted component", "relationship_type": "...", "confidence": 0.0}
      ]
    }
  ]
}

TEMPORAL RULES — assign one of:
- "current"  → present state, what exists/is true right now
- "past"     → completed work, historical decisions, what was done
- "future"   → planned work, roadmap items, will do, should do, next steps
- "unknown"  → cannot be determined from context

RELATIONSHIP RULES — only create if the logical connection is clear:
- depends_on   → A cannot work without B
- enables      → A makes B possible
- blocked_by   → A is blocked by B
- supersedes   → A replaces B (use for price/version changes)
- contradicts  → A and B conflict
- confirms     → A supports B
- part_of      → A is a sub-item of B
- implements   → A builds/realises B
- related_to   → general meaningful connection

QUALITY RULES:
- model_name is a DOMAIN, never a fact type ("Pricing" not "Decision")
- name is unique and specific within its domain
- One idea per component — atomic
- Cross-domain relationships are especially valuable
- Max 15 facts. Order: decisions first, then blockers, then action items, then facts

Document:
{content}
"""


class Extractor:
    def __init__(self) -> None:
        self._model = settings.extraction_model

    async def extract(self, content: str, metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
        if self._model and settings.litellm_api_key:
            try:
                return await self._llm_extract(content)
            except Exception:
                pass
        return self._regex_extract(content)

    async def _llm_extract(self, content: str) -> list[ExtractedFact]:
        from litellm import acompletion

        truncated = content[:12000]
        prompt = EXTRACTION_PROMPT.format(content=truncated)

        response = await acompletion(
            model=self._model,
            api_key=settings.litellm_api_key,
            messages=[
                {"role": "system", "content": "Extract structured business knowledge. Return strict JSON only."},
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
                    relationship_type=r.get("relationship_type", "related_to"),
                    confidence=r.get("confidence", 0.7),
                )
                for r in item.get("relationships", [])
                if r.get("target_name")
            ]
            temporal = item.get("temporal", "unknown")
            if temporal not in ("current", "past", "future", "unknown"):
                temporal = "unknown"
            facts.append(ExtractedFact(
                model_name=item.get("model_name", "General"),
                name=item["name"],
                value=item["value"],
                fact_type=item.get("fact_type", "fact"),
                temporal=temporal,
                confidence=min(max(float(item.get("confidence", 0.7)), 0.0), 1.0),
                relationships=rels,
            ))
        return facts[:15]

    def _regex_extract(self, content: str) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []

        def detect_temporal(text: str) -> str:
            t = text.lower()
            past_words = re.compile(r"\b(was|were|decided|implemented|shipped|launched|completed|done|fixed|resolved|had|used to)\b")
            future_words = re.compile(r"\b(will|plan|should|roadmap|upcoming|next|todo|need to|going to|intend|propose|want to)\b")
            if past_words.search(t):
                return "past"
            if future_words.search(t):
                return "future"
            return "current"

        for m in re.finditer(r"(?:decision|decided)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Decisions", name=f"Decision: {text[:60]}",
                    value=text, fact_type="decision",
                    temporal=detect_temporal(text), confidence=0.75,
                ))

        for m in re.finditer(r"(?:action item|todo|action)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Actions", name=f"Action: {text[:60]}",
                    value=text, fact_type="action_item",
                    temporal=detect_temporal(text), confidence=0.70,
                ))

        for m in re.finditer(r"(?:blocker|blocked by)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Blockers", name=f"Blocker: {text[:60]}",
                    value=text, fact_type="blocker",
                    temporal="current", confidence=0.80,
                ))

        for m in re.finditer(r"(?:risk)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Risks", name=f"Risk: {text[:60]}",
                    value=text, fact_type="fact",
                    temporal="future", confidence=0.72,
                ))

        for m in re.finditer(r"(?:outcome|meeting outcome)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Decisions", name=f"Outcome: {text[:60]}",
                    value=text, fact_type="decision",
                    temporal="past", confidence=0.77,
                ))

        if not facts:
            first_lines = content[:500].strip()
            if first_lines:
                facts.append(ExtractedFact(
                    model_name="General", name="Document content",
                    value=first_lines, fact_type="fact",
                    temporal="unknown", confidence=0.50,
                ))

        return facts
