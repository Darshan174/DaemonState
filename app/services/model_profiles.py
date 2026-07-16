from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class AgentExecutionPolicy:
    """Deterministic completion policy for a worker using a context pack.

    ``require_verification`` describes the evidence required for a verified
    finish. It does not authorize the harness or worker to execute commands.
    """

    policy_version: str
    require_plan: bool
    max_files_per_step: int
    require_diff_review: bool
    require_verification: bool
    max_retries: int
    refresh_context_before_retry: bool
    stop_on_verification_failure: bool

    def to_manifest(self) -> dict[str, object]:
        return asdict(self)


def small_model_execution_policy() -> AgentExecutionPolicy:
    return AgentExecutionPolicy(
        policy_version="agent_execution_policy.v1",
        require_plan=True,
        max_files_per_step=2,
        require_diff_review=True,
        require_verification=True,
        max_retries=1,
        refresh_context_before_retry=True,
        stop_on_verification_failure=True,
    )


def general_model_execution_policy() -> AgentExecutionPolicy:
    return AgentExecutionPolicy(
        policy_version="agent_execution_policy.v1",
        require_plan=True,
        max_files_per_step=4,
        require_diff_review=True,
        require_verification=True,
        max_retries=2,
        refresh_context_before_retry=True,
        stop_on_verification_failure=True,
    )


def frontier_model_execution_policy() -> AgentExecutionPolicy:
    return AgentExecutionPolicy(
        policy_version="agent_execution_policy.v1",
        require_plan=False,
        max_files_per_step=8,
        require_diff_review=True,
        require_verification=True,
        max_retries=2,
        refresh_context_before_retry=False,
        stop_on_verification_failure=True,
    )


def render_execution_policy_markdown(policy: AgentExecutionPolicy) -> str:
    plan_instruction = (
        "- Write a short stepwise plan before editing."
        if policy.require_plan
        else "- A separate stepwise plan is optional."
    )
    refresh_instruction = (
        "- Refresh the context pack before every retry."
        if policy.refresh_context_before_retry
        else "- Refresh context before retry when repository or source evidence changed."
    )
    retry_label = "retry" if policy.max_retries == 1 else "retries"
    instructions = [
        "## Execution Policy",
        "",
        plan_instruction,
        f"- Keep each implementation step to at most {policy.max_files_per_step} files.",
    ]
    if policy.require_diff_review:
        instructions.append("- Review the final diff before reporting completion.")
    if policy.require_verification:
        instructions.append(
            "- A verified finish requires results for every required verification command."
        )
    instructions.extend(
        [
            f"- Make at most {policy.max_retries} {retry_label} after the first attempt.",
            refresh_instruction,
        ]
    )
    if policy.stop_on_verification_failure:
        instructions.append("- Stop and report the failure when required verification still fails.")
    return "\n".join(instructions)


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
    execution_policy: AgentExecutionPolicy = field(default_factory=general_model_execution_policy)

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
        execution_policy=small_model_execution_policy(),
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
        execution_policy=general_model_execution_policy(),
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
        execution_policy=frontier_model_execution_policy(),
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

    matches = [
        (len(hint), priority, profile_name)
        for priority, (profile_name, hints) in enumerate(
            (
                ("general", _GENERAL_MODEL_HINTS),
                ("frontier", _FRONTIER_MODEL_HINTS),
                ("small", _SMALL_MODEL_HINTS),
            )
        )
        for hint in hints
        if hint in normalized
    ]
    if matches:
        _, _, profile_name = max(matches)
        if profile_name == "small":
            return small_coder_model(token_budget)
        if profile_name == "frontier":
            return frontier_coder_model(token_budget)
        return general_coder_model(token_budget)
    return general_coder_model(token_budget)
