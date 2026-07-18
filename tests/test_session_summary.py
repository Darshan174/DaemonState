from app.services.session_summary import derive_session_topic, derive_session_topics


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
