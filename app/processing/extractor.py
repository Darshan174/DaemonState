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
    confidence: float
    relationships: list[ExtractedRelationship] = field(default_factory=list)


EXTRACTION_PROMPT = """You extract structured product knowledge from documents.

For each fact, output JSON with this schema:
{"facts": [{"model_name": "", "name": "", "value": "", "fact_type": "", "confidence": 0.0, "relationships": [{"target_name": "", "relationship_type": "", "confidence": 0.0}]}]}

Rules:
- model_name: The product domain (e.g., "Pricing", "Features", "Roadmap", "Decisions", "Blockers")
- name: Short, specific name (e.g., "$20 Basic Tier", "OAuth2 Support")
- value: Full description or exact quote from text
- fact_type: One of: decision, action_item, blocker, discussion, fact
- confidence: 0.0-1.0 reflecting extraction certainty
- relationships: List of edges to OTHER components mentioned in this document
  - relationship_type: depends_on, blocked_by, enables, contradicts, supersedes, confirms, related_to
- If you see a change (old price $20, new price $80), create BOTH components.
- Be atomic. One idea per component.
- Return at most 12 facts. Decisions first, then blockers, then action items, then discussion.

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
                {"role": "system", "content": "Extract only structured facts. Return strict JSON."},
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
            facts.append(ExtractedFact(
                model_name=item.get("model_name", "General"),
                name=item["name"],
                value=item["value"],
                fact_type=item.get("fact_type", "fact"),
                confidence=min(max(float(item.get("confidence", 0.7)), 0.0), 1.0),
                relationships=rels,
            ))
        return facts[:12]

    def _regex_extract(self, content: str) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []

        for m in re.finditer(r"(?:decision|decided)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Decisions", name=f"Decision: {text[:60]}",
                    value=text, fact_type="decision", confidence=0.75,
                ))

        for m in re.finditer(r"(?:action item|todo|AI)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Actions", name=f"Action: {text[:60]}",
                    value=text, fact_type="action_item", confidence=0.70,
                ))

        for m in re.finditer(r"(?:blocker|blocked by)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Blockers", name=f"Blocker: {text[:60]}",
                    value=text, fact_type="blocker", confidence=0.80,
                ))

        for m in re.finditer(r"(?:meeting outcome|outcome)\s*:\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
            text = m.group(1).strip()
            if text:
                facts.append(ExtractedFact(
                    model_name="Decisions", name=f"Outcome: {text[:60]}",
                    value=text, fact_type="decision", confidence=0.77,
                ))

        if not facts:
            first_lines = content[:500].strip()
            if first_lines:
                facts.append(ExtractedFact(
                    model_name="General", name="Document content",
                    value=first_lines, fact_type="fact", confidence=0.50,
                ))

        return facts
