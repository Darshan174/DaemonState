from __future__ import annotations

from dataclasses import dataclass, replace


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
    max_evidence_quote_chars: int
    max_selected_items: int
    stop_conditions_required: bool = True

    def with_budget(self, token_budget: int | None) -> "ModelCapabilityProfile":
        if token_budget is None:
            return self
        return replace(self, max_pack_tokens=max(1, int(token_budget)))


def small_coder_model(token_budget: int | None = None) -> ModelCapabilityProfile:
    return ModelCapabilityProfile(
        name="small_coder_model",
        max_pack_tokens=12000,
        needs_explicit_file_paths=True,
        needs_stepwise_plan=True,
        max_open_questions=3,
        include_verification_commands=True,
        include_raw_excerpts="short",
        avoid_long_narrative=True,
        format="strict_markdown",
        max_evidence_quote_chars=600,
        max_selected_items=24,
        stop_conditions_required=True,
    ).with_budget(token_budget)


def general_coder_model(token_budget: int | None = None) -> ModelCapabilityProfile:
    return ModelCapabilityProfile(
        name="general_coder_model",
        max_pack_tokens=24000,
        needs_explicit_file_paths=True,
        needs_stepwise_plan=True,
        max_open_questions=6,
        include_verification_commands=True,
        include_raw_excerpts="medium",
        avoid_long_narrative=True,
        format="structured_markdown",
        max_evidence_quote_chars=1000,
        max_selected_items=40,
        stop_conditions_required=True,
    ).with_budget(token_budget)


def frontier_coder_model(token_budget: int | None = None) -> ModelCapabilityProfile:
    return ModelCapabilityProfile(
        name="frontier_coder_model",
        max_pack_tokens=64000,
        needs_explicit_file_paths=True,
        needs_stepwise_plan=False,
        max_open_questions=10,
        include_verification_commands=True,
        include_raw_excerpts="medium",
        avoid_long_narrative=False,
        format="structured_markdown",
        max_evidence_quote_chars=1400,
        max_selected_items=80,
        stop_conditions_required=True,
    ).with_budget(token_budget)


_SMALL_MODEL_HINTS = (
    "1.5b",
    "3b",
    "4b",
    "6b",
    "7b",
    "8b",
    "mini-coder",
    "small-coder",
    "qwen2.5-coder",
    "qwen3-coder",
    "codellama-7b",
    "deepseek-coder-6.7b",
    "starcoder2-7b",
)

_FRONTIER_MODEL_HINTS = (
    "gpt-5",
    "gpt-4.1",
    "gpt-4o",
    "o3",
    "o4",
    "claude-opus",
    "claude-sonnet-4",
    "gemini-2.5-pro",
)

_GENERAL_MODEL_HINTS = (
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "claude-haiku",
    "claude-sonnet",
    "codestral",
    "deepseek-coder",
    "llama",
    "qwen",
)


def profile_for_target_model(
    target_model: str | None,
    token_budget: int | None = None,
) -> ModelCapabilityProfile:
    normalized = (target_model or "").strip().lower()
    if not normalized:
        return general_coder_model(token_budget)
    if normalized in {"small_coder_model", "small"}:
        return small_coder_model(token_budget)
    if normalized in {"general_coder_model", "general"}:
        return general_coder_model(token_budget)
    if normalized in {"frontier_coder_model", "frontier"}:
        return frontier_coder_model(token_budget)

    if any(hint in normalized for hint in _SMALL_MODEL_HINTS):
        return small_coder_model(token_budget)
    if any(hint in normalized for hint in _FRONTIER_MODEL_HINTS):
        return frontier_coder_model(token_budget)
    if any(hint in normalized for hint in _GENERAL_MODEL_HINTS):
        return general_coder_model(token_budget)
    return general_coder_model(token_budget)
