from __future__ import annotations

import re

CANONICAL_MODEL_NAMES = {
    "Agent Session",
    "Company",
    "Context Pack",
    "Customer",
    "Decision",
    "Document",
    "Email",
    "Feature",
    "GitHub",
    "Issue",
    "Meeting",
    "Message",
    "Metric",
    "Person",
    "PR",
    "Product",
    "Repo",
    "Risk",
    "Task",
    "Team",
    "User",
}

VALID_SOURCE_TYPES = {
    "local",
    "local_folder",
    "browser_upload",
    "paste",
    "github_issue",
    "github_pr",
    "agent_session",
    "slack",
    "discord",
    "gmail",
    "gdrive",
    "zoom",
    "notion",
}

VALID_FACT_TYPES = {
    "decision",
    "task",
    "blocker",
    "risk",
    "metric",
    "feature",
    "meeting_note",
    "ai_step",
    "fact",
    "issue",
    "pr",
    "github_issue",
    "github_pr",
    "pr_review_finding",
    "commit_reference",
    "changed_file",
    "ai_session",
    "ai_task",
    "ai_decision",
    "ai_blocker",
    "open_question",
    "session_root",
    "review_finding",
}

VALID_TEMPORAL_STATES = {"current", "past", "future", "unknown"}

VALID_COMPONENT_STATUSES = {"active", "needs_review", "proposed", "stale", "deprecated"}

VALID_TRUST_ZONES = {
    "trusted_system",
    "trusted_human",
    "trusted_repo",
    "semi_trusted_tool",
    "untrusted_external",
    "hostile_test",
}

VALID_CLAIM_STATUSES = {
    "active",
    "proposed",
    "needs_review",
    "superseded",
    "rejected",
    "stale",
    "resolved",
}

VALID_CLAIM_OPERATIONS = {
    "assert",
    "confirm",
    "update",
    "supersede",
    "contradict",
    "retract",
    "resolve",
}

VALID_RELATIONSHIP_ORIGINS = {"deterministic", "extracted", "ai_proposed", "human_verified", "proposed"}

GITHUB_SOURCE_TYPES = {"github", "github_issue", "github_pr"}

AGENT_SESSION_SOURCE_TYPES = {
    "agent_session", "codex", "claude", "opencode",
    "ai_context", "ai_context_codex", "ai_context_claude_code", "ai_context_opencode",
}

AI_CONTEXT_COMPAT_TYPES = {
    "ai_context", "ai_context_codex", "ai_context_claude_code", "ai_context_opencode",
    "codex", "claude", "opencode",
}

_MODEL_ALIASES = {
    "action": "Task",
    "actions": "Task",
    "action item": "Task",
    "action items": "Task",
    "ai step": "Agent Session",
    "agent": "Agent Session",
    "agent sessions": "Agent Session",
    "blocker": "Risk",
    "blockers": "Risk",
    "bug": "Issue",
    "bugs": "Issue",
    "decisions": "Decision",
    "discussion": "Message",
    "discussions": "Message",
    "fact": "Document",
    "facts": "Document",
    "features": "Feature",
    "general": "Document",
    "github": "GitHub",
    "issues": "Issue",
    "meetings": "Meeting",
    "metrics": "Metric",
    "outcome": "Decision",
    "outcomes": "Decision",
    "people": "Person",
    "persons": "Person",
    "points": "Document",
    "prs": "PR",
    "pull request": "PR",
    "pull requests": "PR",
    "risks": "Risk",
    "slack": "Message",
    "tasks": "Task",
    "users": "User",
}

_RELATIONSHIP_ALIASES = {
    "causes": "caused_by",
    "generated_by": "generated_by_agent",
    "implements": "implemented_in",
    "relates_to": "related_to",
    "fix": "fixes",
    "closes": "fixes",
    "resolves": "fixes",
    "resolved_by": "resolved_by",
    "touch": "touches_file",
    "touches": "touches_file",
    "conflicts": "conflicts_with",
    "implement": "implements",
}

VALID_RELATIONSHIP_TYPES = {
    "assigned_to",
    "blocked_by",
    "blocks",
    "caused_by",
    "co_occurs",
    "confirms",
    "conflicts_with",
    "contains",
    "contradicts",
    "created_from",
    "decides",
    "depends_on",
    "discussed_in",
    "duplicates",
    "enables",
    "fixes",
    "generated_by_agent",
    "implemented_in",
    "implements",
    "mentions",
    "owned_by",
    "part_of",
    "related_to",
    "resolved_by",
    "solves",
    "supersedes",
    "touches_file",
    "verified_by_human",
}


def canonical_model_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "Document"

    collapsed = re.sub(r"[_\-\s]+", " ", raw).strip()
    key = collapsed.lower()
    if key in _MODEL_ALIASES:
        return _MODEL_ALIASES[key]

    titled = collapsed.title()
    return titled if titled in CANONICAL_MODEL_NAMES else collapsed


def model_bucket(name: str | None) -> str:
    return canonical_model_name(name).lower()


def canonical_relationship_type(value: str | None) -> str:
    key = re.sub(r"[\s\-]+", "_", (value or "related_to").strip().lower())
    key = _RELATIONSHIP_ALIASES.get(key, key)
    return key if key in VALID_RELATIONSHIP_TYPES else "related_to"


def canonical_source_type(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "local"
    if raw.startswith("ai_context"):
        return "agent_session"
    if raw in ("agent", "ai", "ai_session", "cursor", "codex", "claude", "opencode"):
        return "agent_session"
    if raw == "github":
        return "github_issue"
    if raw in VALID_SOURCE_TYPES:
        return raw
    return raw


def resolve_github_item_type(source_type: str | None, metadata: dict | None = None) -> str:
    raw_source_type = (source_type or "").strip().lower()
    if raw_source_type == "github_issue":
        return "github_issue"
    if raw_source_type == "github_pr":
        return "github_pr"
    if raw_source_type == "github" and metadata:
        item_type = str(metadata.get("item_type", "")).lower()
        meta_source_type = str(metadata.get("source_type", "")).lower()
        source_url = str(metadata.get("source_url", "") or metadata.get("url", "")).lower()
        if (
            item_type == "pull_request"
            or "pull_request" in meta_source_type
            or metadata.get("pr_number") is not None
            or "/pull/" in source_url
        ):
            return "github_pr"
        if item_type == "issue" or "issue" in meta_source_type or metadata.get("issue_number") is not None:
            return "github_issue"
    if raw_source_type == "github":
        return "github_issue"
    return canonical_source_type(source_type)


def resolve_agent_session_type(source_type: str | None) -> str:
    source_type = (source_type or "").strip().lower()
    if source_type in AGENT_SESSION_SOURCE_TYPES:
        return "agent_session"
    if source_type.startswith("ai_context"):
        return "agent_session"
    return source_type


def canonical_fact_type(value: str | None) -> str:
    raw = (value or "fact").strip().lower()
    return raw if raw in VALID_FACT_TYPES else "fact"


def canonical_temporal(value: str | None) -> str:
    raw = (value or "unknown").strip().lower()
    return raw if raw in VALID_TEMPORAL_STATES else "unknown"


def canonical_origin(value: str | None) -> str:
    raw = (value or "proposed").strip().lower()
    if raw in VALID_RELATIONSHIP_ORIGINS:
        return raw
    if raw in ("auto", "rule", "algorithm"):
        return "deterministic"
    if raw in ("ai", "llm", "inferred"):
        return "ai_proposed"
    if raw in ("human", "verified", "manual"):
        return "human_verified"
    if raw in ("source", "text"):
        return "extracted"
    return "proposed"


def default_trust_zone_for_source(source_type: str | None, metadata: dict | None = None) -> str:
    """Conservative source trust defaults used before human review."""
    raw = (source_type or "").strip().lower()
    meta = metadata or {}
    meta_zone = str(meta.get("trust_zone") or "").strip().lower()
    if meta_zone in VALID_TRUST_ZONES:
        return meta_zone
    if raw in {"hostile_test", "adversarial", "adversarial_test"} or meta.get("hostile_test"):
        return "hostile_test"
    if raw in {"local", "local_folder", "repo", "code", "filesystem"}:
        return "trusted_repo"
    if raw in {"paste", "manual", "user_note", "user"}:
        return "trusted_human"
    if raw in GITHUB_SOURCE_TYPES:
        return "semi_trusted_tool"
    if raw in AGENT_SESSION_SOURCE_TYPES or raw.startswith("ai_context"):
        if meta.get("verified_by_human") or meta.get("human_authored"):
            return "trusted_human"
        return "semi_trusted_tool"
    if raw in {"slack", "discord", "gmail", "gdrive", "drive", "web", "browser_upload", "upload", "notion", "zoom"}:
        return "untrusted_external"
    return "untrusted_external"


def canonical_trust_zone(value: str | None, source_type: str | None = None, metadata: dict | None = None) -> str:
    raw = (value or "").strip().lower()
    return raw if raw in VALID_TRUST_ZONES else default_trust_zone_for_source(source_type, metadata)


def relationship_display_label(relationship_type: str, origin: str | None = None) -> str:
    label = relationship_type.replace("_", " ").title()
    if origin == "deterministic":
        label = f"{label} (deterministic)"
    return label


def source_type_display(source_type: str | None) -> str:
    if not source_type:
        return "Unknown"
    labels = {
        "local": "Local File",
        "local_folder": "Local Folder",
        "browser_upload": "Browser Upload",
        "paste": "Pasted Text",
        "github": "GitHub",
        "github_issue": "GitHub Issue",
        "github_pr": "GitHub Pull Request",
        "agent_session": "Agent Session",
        "codex": "Codex Session",
        "claude": "Claude Session",
        "opencode": "OpenCode Session",
        "ai_context": "AI Context",
        "ai_context_codex": "Codex AI Context",
        "ai_context_claude_code": "Claude AI Context",
        "ai_context_opencode": "OpenCode AI Context",
        "slack": "Slack",
        "discord": "Discord",
        "gmail": "Gmail",
        "gdrive": "Google Drive",
        "zoom": "Zoom",
        "notion": "Notion",
    }
    return labels.get(source_type, source_type.replace("_", " ").title())
