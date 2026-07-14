from __future__ import annotations

import re

from app.processing.extractor import ExtractedFact
from app.taxonomy import AGENT_SESSION_SOURCE_TYPES, AI_CONTEXT_COMPAT_TYPES


SEMANTIC_FACT_TYPES = {
    "action_item",
    "ai_blocker",
    "ai_decision",
    "ai_task",
    "blocker",
    "decision",
    "feature",
    "metric",
    "review_finding",
    "risk",
    "task",
}

_LABEL_PREFIX = re.compile(
    r"^\s*(?:decision|task|risk|blocker|feature|metric|review finding)\s*:\s*",
    re.IGNORECASE,
)
_MEDIA_NOISE = re.compile(
    r"data:image/|base64|[A-Za-z0-9+/]{180,}={0,2}",
    re.IGNORECASE,
)
_INSTRUCTION_NOISE = re.compile(
    r"\b(base_instructions|permissions instructions|developer instructions|system message|"
    r"knowledge cutoff|request escalation|prefix_rule|sandbox_permissions|function_call|"
    r"function_call_output|internal_chat_message_metadata|local_images|session_meta|"
    r"tool_call|working with the user)\b",
    re.IGNORECASE,
)
_CONTINUATION_PREFIX = re.compile(
    r"^(?:and|or|but|then|which|that|is|are|was|were|appears)\b",
    re.IGNORECASE,
)
_PROGRESS_NARRATION = re.compile(
    r"\bnext pass will\b",
    re.IGNORECASE,
)


def extracted_fact_rejection_reason(
    fact: ExtractedFact,
    *,
    source_type: str,
) -> str | None:
    """Return a narrow semantic-quality rejection reason for a derived fact.

    This classifier never mutates or removes SourceDocument content. Structural
    inventory roots, files, provider records, and session roots are deliberately
    outside its scope; it only guards semantic claims that would otherwise drive
    summaries, handoffs, or graph reasoning.
    """
    fact_type = str(fact.fact_type or "").strip().lower()
    if fact_type not in SEMANTIC_FACT_TYPES:
        return None

    fields = [fact.name, fact.value, fact.excerpt]
    text = " ".join(str(value) for value in fields if value).strip()
    if not text:
        return "empty_semantic_fact"
    if _MEDIA_NOISE.search(text):
        return "media_noise"
    claim_text = str(fact.value or fact.name or fact.excerpt or "").strip()
    claim_text = _LABEL_PREFIX.sub("", claim_text).strip()
    if not claim_text:
        return "empty_semantic_fact"
    if re.match(r"^[,.;:]", claim_text):
        return "leading_punctuation_fragment"

    source_type = str(source_type or "").strip().lower()
    is_agent_session = (
        source_type in AGENT_SESSION_SOURCE_TYPES | AI_CONTEXT_COMPAT_TYPES
        or source_type in {"agent_session", "codex", "claude", "opencode"}
        or source_type.startswith("ai_context")
    )
    if is_agent_session and _INSTRUCTION_NOISE.search(text):
        return "instruction_noise"
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", claim_text)
    if is_agent_session:
        if len(words) < 3:
            return "session_fragment"
        if re.match(r"^(?!I\b)[A-Za-z]\b[,.;:]?", claim_text):
            return "session_fragment"
        if _CONTINUATION_PREFIX.match(claim_text):
            return "session_fragment"
        if re.match(r"^\w{1,12},\s+(?:and|then|but|so)\b", claim_text, re.IGNORECASE):
            return "session_fragment"
        if _PROGRESS_NARRATION.search(claim_text):
            return "progress_narration"
    compact = re.sub(r"\s+", "", claim_text)
    noisy_chars = sum(1 for char in compact if char in "/.\\{}[]<>_=+:;|")
    if len(compact) >= 12 and len(words) < 3 and noisy_chars / len(compact) > 0.34:
        return "symbol_noise"
    return None


def extracted_fact_dedupe_key(fact: ExtractedFact) -> tuple[str, str, str]:
    def normalize(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()

    return (
        normalize(fact.model_name),
        normalize(fact.name),
        normalize(fact.value),
    )
