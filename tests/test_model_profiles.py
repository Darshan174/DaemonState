from __future__ import annotations

from dataclasses import asdict

import pytest

from app.services.model_profiles import (
    frontier_coder_model,
    general_coder_model,
    profile_for_target_model,
    render_execution_policy_markdown,
    small_coder_model,
)


def test_small_model_policy_is_stricter_than_frontier_policy():
    small = small_coder_model().execution_policy
    frontier = frontier_coder_model().execution_policy

    assert small.require_plan is True
    assert frontier.require_plan is False
    assert small.max_files_per_step < frontier.max_files_per_step
    assert small.require_diff_review is True
    assert small.require_verification is True
    assert small.max_retries == 1
    assert small.max_retries <= frontier.max_retries
    assert small.refresh_context_before_retry is True
    assert frontier.refresh_context_before_retry is False
    assert small.stop_on_verification_failure is True


def test_execution_policy_has_stable_manifest_shape():
    profile = small_coder_model(token_budget=2000)

    assert profile.execution_policy.to_manifest() == {
        "policy_version": "agent_execution_policy.v1",
        "require_plan": True,
        "max_files_per_step": 2,
        "require_diff_review": True,
        "require_verification": True,
        "max_retries": 1,
        "refresh_context_before_retry": True,
        "stop_on_verification_failure": True,
    }
    assert asdict(profile)["execution_policy"] == profile.execution_policy.to_manifest()
    assert profile.max_pack_tokens == 2000


def test_budget_override_does_not_change_execution_policy():
    default = general_coder_model()
    constrained = default.with_budget(1500)

    assert constrained.max_pack_tokens == 1500
    assert constrained.execution_policy == default.execution_policy


def test_small_model_policy_renders_worker_instructions_deterministically():
    rendered = render_execution_policy_markdown(small_coder_model().execution_policy)

    assert rendered == "\n".join(
        [
            "## Execution Policy",
            "",
            "- Write a short stepwise plan before editing.",
            "- Keep each implementation step to at most 2 files.",
            "- Review the final diff before reporting completion.",
            "- A verified finish requires results for every required verification command.",
            "- Make at most 1 retry after the first attempt.",
            "- Refresh the context pack before every retry.",
            "- Stop and report the failure when required verification still fails.",
        ]
    )


@pytest.mark.parametrize(
    ("target_model", "expected_profile"),
    [
        ("gpt-4.1-mini", "general_coder_model"),
        ("gpt-4.1", "frontier_coder_model"),
        ("gpt-4o-mini", "general_coder_model"),
        ("gpt-4o", "frontier_coder_model"),
        ("claude-sonnet-4", "frontier_coder_model"),
        ("qwen2.5-coder-7b", "small_coder_model"),
        ("deepseek-coder-6.7b", "small_coder_model"),
    ],
)
def test_model_hint_selection_prefers_the_most_specific_match(
    target_model: str,
    expected_profile: str,
):
    assert profile_for_target_model(target_model).name == expected_profile
