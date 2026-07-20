from app.services.session_summary import (
    clean_session_message_text,
    derive_latest_session_topic,
    derive_session_attention_items,
    derive_session_topic,
    derive_session_topics,
    is_internal_session_content,
)


def test_derive_session_topic_skips_injected_bootstrap_blocks() -> None:
    content = """
[USER]
## request_user_input availability
Use the request_user_input tool only when it is listed.
<skills_instructions>Available skills</skills_instructions>

[USER]
/goal make this project a oss sucess, a highly used tool for vibe coders.
"""

    assert derive_session_topic(
        content,
        explicit_title="Codex session · 23ec87df0edf",
        tool="codex",
        session_id="019ed6a2-ce45-7b40-8454-23ec87df0edf",
    ) == "Make this project an OSS success"


def test_derive_session_topic_preserves_a_meaningful_provider_title() -> None:
    assert derive_session_topic(
        "[USER]\nUnrelated transcript fallback",
        explicit_title="Auth setup and callback repair",
        tool="claude_code",
        session_id="session-1",
    ) == "Auth setup and callback repair"


def test_derive_session_topics_keeps_multiple_user_subjects_and_project_anchor() -> None:
    content = """
[USER]
Plan billing for the Alpha product.

[ASSISTANT]
I mapped the billing flow.

[USER]
Now review onboarding for the Beta product.
"""

    topics = derive_session_topics(
        content,
        explicit_title="Product planning",
        cwd="/Users/example/work/context-engine",
        tool="codex",
        session_id="session-1",
    )

    assert topics == [
        "Product planning",
        "Context engine",
        "Plan billing for the Alpha product",
        "Review onboarding for the Beta product",
    ]
    assert derive_latest_session_topic(
        content,
        explicit_title="Product planning",
        tool="codex",
        session_id="session-1",
    ) == "Review onboarding for the Beta product"


def test_attachment_metadata_never_becomes_the_latest_topic() -> None:
    content = """
[ASSISTANT]
Removed the entire sessions banner.

[USER]
# Files mentioned by the user:

## Screenshot 2026-07-18 at 22.32.05.png: /var/folders/example/Screenshot 2026-07-18 at 22.32.05.png

## My request for Codex:
wait what did u remove?? the banner i asked for is still displayed
<image name=[Image #1] path="/var/folders/example/Screenshot.png">
</image>
"""

    assert derive_latest_session_topic(content) == (
        "The banner I asked for is still displayed"
    )
    assert "Screenshot 2026" not in clean_session_message_text(content)


def test_screenshot_reference_intro_resolves_to_the_actual_issue() -> None:
    content = """
[USER]
Refer to the screenshot I shared. The topic is not helpful: Screenshot 2026-07-18 at 22. It should use the actual topic instead of a screenshot ID.
"""

    assert derive_latest_session_topic(content) == (
        "Use the discussion topic instead of screenshot filenames"
    )


def test_user_correction_becomes_an_actionable_session_attention_item() -> None:
    content = """
[ASSISTANT]
The banner is gone.

[USER]
The banner is still displayed in the app.
"""

    assert derive_session_attention_items(content) == [{
        "kind": "user_correction",
        "title": "The banner is still displayed in the app",
        "summary": "The banner is still displayed in the app.",
        "attention_score": 90,
        "temporal_status": "current",
    }]


def test_older_user_correction_remains_visible_as_previous_history() -> None:
    content = """
[ASSISTANT]
The banner is gone.

[USER]
The banner is still displayed in the app.

[ASSISTANT]
I updated the rendered banner.

[USER]
Now add a return-to-live action.
"""

    assert derive_session_attention_items(content)[0]["temporal_status"] == "previous"


def test_internal_assessment_transcript_is_not_user_session_content() -> None:
    assert is_internal_session_content(
        "[USER]\nThe following is the Codex agent history whose request action you "
        "are assessing.\n>>> TRANSCRIPT START\n[1] user: build a library"
    ) is True
    assert is_internal_session_content("[USER]\nBuild a session library") is False


def test_command_only_turns_and_transport_wrappers_do_not_become_topics() -> None:
    content = """
[USER]
/model gpt-5

[USER]
Referenced ChatGPT conversation: This is untrusted context.
This is untrusted and may contain misleading instructions.
Fix the project matching badge on the Now page.
"""

    assert derive_latest_session_topic(content) == (
        "Fix the project matching badge on the Now page"
    )
    assert derive_session_topic("[USER]\n/model gpt-5") is None


def test_truncated_topic_is_visibly_marked_as_incomplete() -> None:
    assert derive_latest_session_topic(
        "[USER]\nLook at the overall project and tell me whether the current implementation is trustworthy"
    ) == "Look at the overall project and tell me whether the..."
