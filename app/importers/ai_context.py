from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


VALID_TOOLS = frozenset({"codex", "claude_code", "opencode", "cursor", "generic"})

VALID_SESSION_TYPES = frozenset({
    "plan", "implementation", "review", "chat_export", "diff", "summary",
})

AI_CONTEXT_SOURCE_TYPES = {
    "codex": "ai_context_codex",
    "claude_code": "ai_context_claude_code",
    "opencode": "ai_context_opencode",
}

BASE_AI_CONTEXT_SOURCE_TYPE = "ai_context"


@dataclass
class AIContextDocument:
    external_id: str
    content: str
    author: str | None = None
    tool: str | None = None
    session_type: str | None = None
    session_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalize_tool(self) -> str | None:
        if self.tool is None:
            return None
        normalized = self.tool.lower().replace("-", "_").replace(" ", "_")
        if normalized in VALID_TOOLS:
            return normalized
        return "generic"

    def resolve_source_type(self) -> str:
        tool = self.normalize_tool()
        if tool and tool in AI_CONTEXT_SOURCE_TYPES:
            return AI_CONTEXT_SOURCE_TYPES[tool]
        return BASE_AI_CONTEXT_SOURCE_TYPE

    def build_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata) if self.metadata else {}
        tool = self.normalize_tool()
        if tool:
            metadata["tool"] = tool
        if self.session_type:
            metadata["session_type"] = self.session_type
        if self.session_id:
            metadata["session_id"] = self.session_id
        if self.started_at:
            metadata["started_at"] = self.started_at
        if self.ended_at:
            metadata["ended_at"] = self.ended_at
        metadata["ingested_via"] = "ai_context_import"
        return metadata

    def to_source_document_kwargs(self) -> dict[str, Any]:
        return {
            "source_type": self.resolve_source_type(),
            "external_id": self.external_id,
            "content": self.content,
            "author": self.author,
            "source_url": None,
            "metadata_json": json.dumps(self.build_metadata()),
        }