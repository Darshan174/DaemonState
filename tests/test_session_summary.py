from app.services.session_summary import derive_session_topic


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
