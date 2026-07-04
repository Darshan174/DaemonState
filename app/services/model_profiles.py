from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelCapabilityProfile:
    name: str
    max_pack_tokens: int
    needs_explicit_file_paths: bool
    needs_stepwise_plan: bool
    max_open_questions: int
    include_verification_commands: bool
    include_raw_excerpts: str
    avoid_long_narrative: bool
    format: str
    include_stop_conditions: bool = True
    max_evidence_excerpt_chars: int = 240

    def to_dict(self) -> dict:
        return asdict(self)


SMALL_CODER_MODEL = ModelCapabilityProfile(
    name="small_coder_model",
    max_pack_tokens=12000,
    needs_explicit_file_paths=True,
    needs_stepwise_plan=True,
    max_open_questions=3,
    include_verification_commands=True,
    include_raw_excerpts="short",
    avoid_long_narrative=True,
    format="strict_markdown",
    include_stop_conditions=True,
    max_evidence_excerpt_chars=220,
)

GENERAL_CODER_MODEL = ModelCapabilityProfile(
    name="general_coder_model",
    max_pack_tokens=24000,
    needs_explicit_file_paths=True,
    needs_stepwise_plan=True,
    max_open_questions=5,
    include_verification_commands=True,
    include_raw_excerpts="medium",
    avoid_long_narrative=False,
    format="structured_markdown",
    include_stop_conditions=True,
    max_evidence_excerpt_chars=360,
)

FRONTIER_CODER_MODEL = ModelCapabilityProfile(
    name="frontier_coder_model",
    max_pack_tokens=64000,
    needs_explicit_file_paths=False,
    needs_stepwise_plan=False,
    max_open_questions=8,
    include_verification_commands=True,
    include_raw_excerpts="medium",
    avoid_long_narrative=False,
    format="structured_markdown",
    include_stop_conditions=True,
    max_evidence_excerpt_chars=480,
)

PROFILES: dict[str, ModelCapabilityProfile] = {
    SMALL_CODER_MODEL.name: SMALL_CODER_MODEL,
    GENERAL_CODER_MODEL.name: GENERAL_CODER_MODEL,
    FRONTIER_CODER_MODEL.name: FRONTIER_CODER_MODEL,
}


def profile_for_model(model_name: str | None) -> ModelCapabilityProfile:
    normalized = str(model_name or "").strip().lower()
    if normalized in PROFILES:
        return PROFILES[normalized]

    if _looks_like_frontier_model(normalized):
        return FRONTIER_CODER_MODEL
    if _looks_like_small_model(normalized):
        return SMALL_CODER_MODEL
    return GENERAL_CODER_MODEL


def target_model_descriptor(
    model_name: str | None,
    token_budget: int | None = None,
) -> dict:
    profile = profile_for_model(model_name)
    budget = token_budget if token_budget is not None else profile.max_pack_tokens
    budget = max(1, min(int(budget), profile.max_pack_tokens))
    return {
        "name": model_name or profile.name,
        "context_budget_tokens": budget,
        "profile": profile.name,
        "capabilities": profile.to_dict(),
    }


def _looks_like_frontier_model(normalized: str) -> bool:
    frontier_markers = (
        "frontier",
        "gpt-5",
        "gpt-4.1",
        "gpt-4o",
        "o3",
        "o4",
        "claude-4",
        "sonnet-4",
        "opus",
        "gemini-2.5-pro",
        "deepseek-r1",
    )
    return any(marker in normalized for marker in frontier_markers)


def _looks_like_small_model(normalized: str) -> bool:
    if not normalized:
        return False
    small_markers = (
        "small",
        "mini",
        "qwen",
        "qwen2.5-coder",
        "qwen3-coder",
        "codellama",
        "starcoder",
        "deepseek-coder",
    )
    size_markers = ("1.5b", "3b", "4b", "6b", "7b", "8b", "9b", "14b")
    return any(marker in normalized for marker in small_markers) or any(
        marker in normalized for marker in size_markers
    )
