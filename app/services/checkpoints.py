from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.continuation_brief import (
    ContinuationBriefVariant,
    resolve_continuation_brief_variant,
)
from app.models import (
    CheckpointEvidence,
    CheckpointItem,
    CheckpointVerification,
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
)
from app.schemas.continuation_execution import (
    ArtifactReference,
    infer_task_mode,
    is_non_verifiable_execution_guidance,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.local_harness import RepositorySnapshot, capture_repository_snapshot
from app.services.request_artifacts import (
    TrustedRequestImageDescriptor,
    materialize_trusted_request_image_descriptor,
    recover_codex_request_image_descriptors,
    resolve_trusted_request_image_artifacts,
    trusted_request_image_descriptors_from_payload,
    validated_trusted_image_inspection,
)
from app.services.redaction import redact_sensitive_text
from app.services.session_events import event_payload
from app.services.session_scope import (
    normalize_optional_session_key,
    normalize_session_key,
    session_provider_values,
)
from app.services.session_summary import (
    extract_delegated_user_request,
    extract_user_authored_request,
    is_continuation_control,
    is_session_instruction_noise,
    is_substantive_user_request,
    normalize_substantive_user_request,
)
from app.time import utc_now


CHECKPOINT_SCHEMA_VERSION = "work_checkpoint.v10"
SESSION_HANDOFF_SCHEMA_VERSION = "session_handoff.v1"
SESSION_CONTEXT_REQUIRED_HEADINGS = (
    "# Session Context — task-level working memory",
    "## Current main goal",
    "## Scope and non-goals",
    "## Acceptance criteria",
    "## Current state",
    "## Exact next action",
    "## Active decisions that still hold",
    "## Failed or rejected attempts",
    "## Changes made",
    "## Relevant discoveries",
    "## Useful commands executed",
    ("## Latest blockers, risks, assumptions, constraints, and open questions"),
    "## What was fixed and how it was confirmed",
    "### Current repository state",
    "## Verification state",
)
COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS = (
    "# Continuation Brief v2",
    "## Goal",
    "## State now",
    "## Start here",
    "## Do not repeat",
    "## Done when",
)
CHECKPOINT_CATEGORIES = (
    "goal",
    "progress",
    "decisions",
    "failed_attempts",
    "discoveries",
    "useful_commands",
    "open_items",
    "relevant_files",
    "blockers",
    "verification",
    "exact_next_action",
)
MAX_ITEMS_PER_CATEGORY = 12
MAX_STATEMENT_CHARS = 1_200
SESSION_HANDOFF_RENDERED_FILE_LIMIT = 30
SESSION_HANDOFF_RENDERED_ITEM_LIMIT = 2
SESSION_HANDOFF_RENDERED_COMMAND_LIMIT = 2
SESSION_HANDOFF_RENDERED_VERIFICATION_LIMIT = 2
SESSION_HANDOFF_RENDERED_STATEMENT_CHARS = 300
SESSION_HANDOFF_RENDERED_COMMAND_CHARS = 240
SESSION_HANDOFF_RENDERED_RESULT_CHARS = 160
MAX_CONTINUATION_LEAD_CHARS = 12_000
# Roughly 1,750 model tokens: enough for bounded evidence without letting
# session history dominate the authoritative current goal.
SESSION_HANDOFF_MAX_OVERHEAD_CHARS = 7_000
COMPACT_SESSION_HANDOFF_MAX_OVERHEAD_CHARS = 5_000

_DECISION_SIGNAL = re.compile(
    r"\b(?:decid(?:e|ed)|we(?:'ll| will)|will use|keep|remove|replace|exclude|"
    r"must|should|instead|except for|do not|don't)\b",
    re.IGNORECASE,
)
_PROGRESS_SIGNAL = re.compile(
    r"\b(?:added|built|captured|completed|confirmed|created|fixed|implemented|"
    r"in place|passed|removed|replaced|updated|wired|working)\b",
    re.IGNORECASE,
)
_BLOCKER_SIGNAL = re.compile(
    r"(?:\bblocker\s*:|\b(?:is|are|am|was|were|remain(?:s|ed)?)\s+blocked\b|"
    r"\bblocked\s+(?:by|on|because)\b|\bcannot continue\b|\bcan(?:not|'t) proceed\b|"
    r"\bneed user input\b|\bwaiting for\b|\bpermission required\b|"
    r"\bfailed to authenticate\b|\bauthentication_error\b|"
    r"\b(?:access|oauth)\s+token\b.{0,80}\brevoked\b)",
    re.IGNORECASE,
)
_NEXT_SIGNAL = re.compile(
    r"(?:^|[\n.!?]\s+)\s*(?:[-*]\s*)?(?:exact next action|next action|next step|next)"
    r"\s*(?::|—|-|\bis\b)\s*([^\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_COMPLETION_SIGNAL = re.compile(
    r"\b(?:implemented end to end|all remaining tasks are complete|requested work is complete|"
    r"work is fully implemented|finished end to end)\b",
    re.IGNORECASE,
)
_FAILED_OR_REJECTED_ATTEMPT_SIGNAL = re.compile(
    r"(?:^|\b(?:i|we|the\s+team)\s+)"
    r"(?:tried|attempted|rejected|ruled\s+out|abandoned|rolled\s+back|"
    r"reverted)\b|"
    r"\b(?:did\s+not|didn't|could\s+not|couldn't|failed\s+to)\s+"
    r"(?:work|pass|build|compile|resolve|fix|complete|succeed)\b",
    re.IGNORECASE,
)
_FAILED_ATTEMPT_CONTRAST_REASON = re.compile(
    r"\b(?:but|however)\s+(.+?)(?:[.!?])?$",
    re.IGNORECASE,
)
_DISCOVERY_SIGNAL = re.compile(
    r"\b(?:found|located|discovered|confirmed|observed|identified|traced|"
    r"defined\s+in|implemented\s+in|lives?\s+in|depends?\s+on|imports?|"
    r"calls?|routes?\s+(?:to|through)|maps?\s+to|reads?\s+from|"
    r"writes?\s+to|uses?\s+(?:the\s+)?)\b",
    re.IGNORECASE,
)
_OPEN_ITEM_SIGNAL = re.compile(
    r"\b(?:assumptions?|assume[ds]?|risks?|caveats?|constraints?|"
    r"open questions?|unknowns?|unclear|uncertain|not yet verified|"
    r"remains? unverified)\b",
    re.IGNORECASE,
)
_REASON_CLAUSE = re.compile(
    r"\b(?:because|since|so that|in order to|to avoid|to preserve|due to)\s+"
    r"(.+?)(?:[.!?])?$",
    re.IGNORECASE,
)
# This marker retains imported test/build commands as untrusted audit evidence
# so explicit verification can report that replay was refused. It must never
# decide whether a command is promoted into rendered Session Context; only
# _is_useful_verification_command is allowed to do that.
_UNTRUSTED_VERIFICATION_COMMAND_MARKER = re.compile(
    r"(?:^|\s)(?:pytest|python\d*(?:\.\d+)?\s+-m\s+pytest|"
    r"npm\s+(?:test|run\s+(?:test|build|lint|check|typecheck))|"
    r"pnpm\s+(?:test|build|lint|check|typecheck)|"
    r"yarn\s+(?:test|build|lint|check|typecheck)|"
    r"ruff|mypy|pyright|cargo\s+(?:test|check|clippy)|"
    r"go\s+(?:test|vet)|swift\s+(?:test|build)|vitest|jest|tsc)"
    r"(?:\s|$)",
    re.IGNORECASE,
)
_LOW_VALUE_DISCOVERY_COMMAND = re.compile(
    r"^(?:(?:which|type)\s+\S+|command\s+-v\s+\S+|pwd|"
    r"(?:python\d*(?:\.\d+)?|node|npm|pnpm|yarn|git|ruff|pytest)"
    r"\s+(?:--version|-v|version))$",
    re.IGNORECASE,
)
_DERIVED_COMMAND_BLOCKER = re.compile(
    r"^Latest run of `[^`]+` is failing\.$",
    re.IGNORECASE,
)
_INTERNAL_TOOL_NEXT_ACTION = re.compile(
    r"^Fix the failure from `tool:[^`]+` and rerun that command\.$",
    re.IGNORECASE,
)
_DERIVED_BLOCKER_NEXT_ACTION = re.compile(
    r"^Resolve this blocker:\s+",
    re.IGNORECASE,
)
_INACTIVE_BLOCKER_STATES = {
    "cancelled",
    "completed",
    "dismissed",
    "historical",
    "rejected",
    "resolved",
    "superseded",
}
_PATH_PATTERN = re.compile(
    r"(?<![\w])("
    r"(?:/(?:[^\s:'\"`<>|]+/)*[^\s:'\"`<>|]+\.[A-Za-z0-9]{1,12})|"
    r"(?:(?:app|frontend|tests|scripts|docs|src|migrations|alembic)/"
    r"[A-Za-z0-9_@+./-]+)|"
    r"(?:[A-Za-z0-9_.@+-]+\.(?:py|tsx?|jsx?|md|json|ya?ml|sql|toml|css|scss|sh))"
    r")"
)
_SESSION_USER_TURN_RE = re.compile(
    r"(?ms)^\[(?:USER|HUMAN|YOU)\]\r?\n"
    r"(.*?)(?=^\[[A-Z][A-Z_ -]*\]\r?\n|\Z)"
)
_TRUNCATED_OUTPUT_SUFFIXES = (
    "\r\n[output truncated]",
    "\n[output truncated]",
    "[output truncated]",
)
_MIN_RECOVERY_PREFIX_CHARS = 256
_READ_ONLY_INSPECTION_COMMANDS = {
    "cat",
    "find",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "tail",
    "test",
    "type",
    "which",
}
_SENSITIVE_COMMAND_PATH_BASENAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "application_default_credentials.json",
    "authorized_keys",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
    "secrets",
    "secrets.json",
    "shadow",
}
_SENSITIVE_COMMAND_PATH_SUFFIXES = (
    ".key",
    ".p12",
    ".pem",
    ".pfx",
)
_GIT_READ_ONLY_GLOBAL_FLAGS = {
    "--glob-pathspecs",
    "--icase-pathspecs",
    "--literal-pathspecs",
    "--no-optional-locks",
    "--no-pager",
    "--no-replace-objects",
    "--noglob-pathspecs",
    "--paginate",
}
_GIT_MUTATING_BRANCH_FLAGS = {
    "-c",
    "-C",
    "-d",
    "-D",
    "-m",
    "-M",
    "--copy",
    "--delete",
    "--edit-description",
    "--move",
    "--set-upstream-to",
    "--unset-upstream",
}
_SESSION_CONTEXT_EXTRA_SECRET = re.compile(
    r"(?i)(\b(?:"
    r"(?:[A-Z0-9]+_)*(?:token|secret|password|private_key|api_key|"
    r"access_key|credentials?)|database_url|connection_string|dsn"
    r")\b\s*[:=]\s*)([\"']?)[^\"'\s,;}]+(\2)"
)
_EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE = re.compile(
    r"(?:chatgpt-conversation://|https?://(?:www\.)?chatgpt\.com/)",
    re.IGNORECASE,
)
_DEICTIC_SESSION_CONTEXT_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"\b(?:the\s+)?last\s+(?:prompt|message|response)\b|"
    r"\b(?:the\s+)?(?:above|previous|referenced)\s+"
    r"(?:idea|proposal|conversation)\b|"
    r"\bidea\s+discussed\b|"
    r"\b(?:idea|proposal|approach)\s+(?:described|discussed)\s+"
    r"(?:above|before|previously)\b|"
    r"\bas\s+(?:discussed|described)\s+(?:above|before|previously)\b"
    r")",
    re.IGNORECASE,
)
_REFERENCED_CONVERSATION_MARKER_RE = re.compile(
    r"^#{1,6}\s*Referenced ChatGPT conversation:\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CURRENT_CODEX_REQUEST_MARKER_RE = re.compile(
    r"(?<!\S)#{1,6}\s*My request(?: for Codex)?:\s*",
    re.IGNORECASE,
)
_CHATGPT_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\("
    r"(?:chatgpt-conversation://[^)]+|https?://(?:www\.)?chatgpt\.com/[^)]+)"
    r"\)",
    re.IGNORECASE,
)
_CHATGPT_CONVERSATION_ID_RE = re.compile(
    r"(?:chatgpt-conversation://|https?://(?:www\.)?chatgpt\.com/"
    r"(?:share|c)/)([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_SESSION_IMAGE_TAG_RE = re.compile(
    r"(?is)<image\b(?P<attributes>[^>]*)>"
    r"(?P<body>.*?)</image\s*>|"
    r"<image\b(?P<self_closing_attributes>[^>]*)/\s*>"
)
_SESSION_IMAGE_ATTRIBUTE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
)
_SESSION_IMAGE_BRACKET_ATTRIBUTE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*(\[[^\]\r\n]{1,300}\])"
)
_SESSION_TASK_RESET_RE = re.compile(
    r"^\s*(?:new|separate|unrelated|different)\s+(?:task|request|topic)\b|"
    r"^\s*(?:switch|move)\s+(?:on\s+)?to\b|"
    r"\bunrelated\b|"
    r"\b(?:forget|disregard|drop|cancel)\s+(?:the\s+)?"
    r"(?:previous|earlier|last)\s+(?:task|request|instruction)\b",
    re.IGNORECASE,
)
_SESSION_TASK_FOLLOWUP_RE = re.compile(
    r"^\s*(?:also|and|but|plus|then|additionally|furthermore|"
    r"make\s+sure|ensure|remember|keep|still|before\s+you\s+finish|"
    r"while\s+you(?:'re|\s+are)\s+at\s+it)\b|"
    r"^\s*(?:please\s+)?(?:this|that|it|the\s+same|"
    r"(?:these|those)\s+changes?|the\s+(?:fix|result|work|task))\b|"
    r"^\s*(?:please\s+)?(?:do|apply|use|fix|change|update|remove|"
    r"rename|replace|redo|rework|finish|complete)\s+"
    r"(?:this|that|it|the\s+(?:same|fix|work|change|result|task))\b",
    re.IGNORECASE,
)
_SESSION_TASK_DELIVERY_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+)?(?:commit|push|deploy|release|ship|publish)\b|"
    r"^\s*(?:please\s+)?(?:open|create|make)\s+(?:a\s+)?"
    r"(?:pull\s+request|merge\s+request|pr)\b",
    re.IGNORECASE,
)
_SESSION_TASK_TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "also",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "have",
        "i",
        "in",
        "is",
        "it",
        "make",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "should",
        "sure",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "we",
        "with",
        "you",
        "your",
    }
)
_SESSION_ATTACHMENT_EXACT_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"\b(?:match|copy|recreate|replicate|mirror|follow|use)\b"
    r".{0,100}\b(?:attached|image|screenshot|reference|mockup|design)\b"
    r".{0,100}\b(?:exact(?:ly)?|pixel[- ]perfect|identical|same)\b|"
    r"\b(?:exact(?:ly)?|pixel[- ]perfect|identical|same)\b"
    r".{0,100}\b(?:attached|image|screenshot|reference|mockup|design)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_SESSION_ATTACHMENT_VISUAL_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"\b(?:inspect|look\s+at|analy[sz]e|examine|review|check|compare|"
    r"debug|diagnose|explain|tell\s+me)\b"
    r".{0,140}\b(?:attached|image|screenshot|reference|mockup|design|visual)\b|"
    r"\b(?:attached|image|screenshot|reference|mockup|design|visual)\b"
    r".{0,140}\b(?:inspect|look|analy[sz]e|examine|review|check|compare|"
    r"debug|diagnose|explain|tell)\b|"
    r"\b(?:attached|image|screenshot|reference|mockup|design|visual)\b"
    r".{0,160}\b(?:source\s+of\s+truth|colou?rs?|spacing|typography|"
    r"responsive|layout)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CONTINUATION_LEAD_ATTACHMENT_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"\b(?:attached|attachment)\b|"
    r"\b(?:inspect|look\s+at|analy[sz]e|examine|review|check|compare|"
    r"debug|diagnose|explain|use|match|copy|recreate|replicate|mirror|follow)\b"
    r".{0,120}\b(?:this|that|the\s+attached)\s+"
    r"(?:image|screenshot|mockup|visual\s+reference)\b|"
    r"\b(?:this|that|the\s+attached)\s+"
    r"(?:design|diagram|figma(?:\s+design)?|image|mock[- ]?up|photo|picture|"
    r"prototype|reference|screenshot|visual(?:\s+reference)?|wireframe)\b"
    r".{0,120}\b(?:inspect|look|analy[sz]e|examine|review|check|compare|"
    r"debug|diagnose|explain|use|match|copy|recreate|replicate|mirror|follow)\b|"
    r"\b(?:inspect|look\s+at|analy[sz]e|examine|review|check|compare(?:\s+against)?|"
    r"debug|diagnose|explain|use|match|copy|recreate|replicate|mirror|follow)\b"
    r".{0,100}\b(?:the|this|that)\s+"
    r"(?:image|screenshot|mockup|visual\s+reference)\b"
    r".{0,80}\b(?:above|below|exact(?:ly)?|i\s+sent|you\s+sent|we\s+sent|"
    r"source\s+of\s+truth)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_CONTINUATION_LEAD_DEICTIC_VISUAL_RE = re.compile(
    r"(?:"
    r"\b(?:(?:the|this|that|my|our|your)\s+)?"
    r"(?:design|diagram|figma(?:\s+design)?|image|mock[- ]?up|photo|picture|"
    r"prototype|reference|screenshot|visual(?:\s+reference)?|wireframe)\b"
    r".{0,100}\b(?:above|below|source\s+of\s+truth|desired\s+design|"
    r"as\s+(?:a\s+)?reference|i\s+sent|you\s+sent|we\s+sent)\b|"
    r"\b(?:use|match|copy|recreate|replicate|mirror|follow)\s+"
    r"(?:my|our|your|this|that|the\s+attached)\s+"
    r"(?:design|diagram|figma(?:\s+design)?|image|mock[- ]?up|photo|picture|"
    r"prototype|reference|screenshot|visual(?:\s+reference)?|wireframe)\b|"
    r"\b(?:implement|build|make|recreate|replicate|match|copy)\b"
    r".{0,100}\b(?:shown\s+in|look\s+like|match(?:es|ing)?|from)\b"
    r".{0,60}\b(?:(?:the|this|that|my|our|your)\s+)?"
    r"(?:design|diagram|figma(?:\s+design)?|image|mock[- ]?up|photo|picture|"
    r"prototype|reference|screenshot|visual(?:\s+reference)?|wireframe)\b|"
    r"\b(?:build|copy|follow|implement|make|match|recreate|replicate|use)\b"
    r".{0,140}\b(?:i|you|we)\s+sent\b|"
    r"\b(?:based\s+on|copy|follow|inspect|match|mirror|recreate|replicate|"
    r"review|use)\s+the\s+"
    r"(?:design|diagram|image|mock[- ]?up|photo|picture|prototype|reference|"
    r"screenshot|visual|wireframe)\b"
    r"(?!\s+(?:codec|code|file|flow|format|handling|parsing|pipeline|"
    r"processing|serialization|service|upload)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_SESSION_COMPOSITE_REQUEST_HEADING_RE = re.compile(
    r"(?m)^(?:## Additional user-authored requirements|"
    r"### Follow-up \d+)[ \t]*$",
)
_REQUIREMENT_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
_REQUIREMENT_ACTION_RE = re.compile(
    r"\b(?:(?:do\s+not|don['’]?t|never)\s+let|"
    r"should(?:n't|n’t| not)?|must(?:n't|n’t| not)?|"
    r"add|allow|audit|build|carry|change|check|confirm|copy|create|debug|"
    r"determine|diagnose|edit|explain|"
    r"disable|display|divide|document|enable|ensure|expose|finish|fix|hide|"
    r"get|honor|implement|include|keep|make|modify|move|need|paste|power|preserve|"
    r"prevent|reject|remove|rename|repair|replace|restore|retain|route|separate|"
    r"review|send|ship|show|skip|split|summarize|support|surface|update|use|"
    r"verify|wire|work|write|remember|"
    r"prioritize|failed)\b",
    re.IGNORECASE,
)
_INLINE_ACCEPTANCE_MARKER_RE = re.compile(
    r"^(?:done\s+when|ensure(?:\s+that)?)\b",
    re.IGNORECASE,
)
_INLINE_TEST_PASS_OUTCOME_RE = re.compile(
    r"\b(?:tests?|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test)\b"
    r".{0,80}\bpass(?:es|ed|ing)?\b",
    re.IGNORECASE,
)
_INLINE_TEST_PASS_REQUIREMENT_RE = re.compile(
    r"^(?:the\s+)?tests?\s+(?:must|should|need(?:s)?\s+to)\s+pass\b",
    re.IGNORECASE,
)
_HISTORICAL_QUOTED_REPORT_RE = re.compile(
    r"\b(?:the\s+)?(?:prior|previous|historical|earlier|other)\s+"
    r"(?:agent|assistant|user|model)\s+"
    r"(?:previously\s+|earlier\s+)?"
    r"(?:said|wrote|reported|claimed|asked|instructed|suggested|stated)"
    r"\s*(?:that\s+|[:,-]\s*)?"
    r"(?:\"[^\"\n]*\"|“[^”\n]*”|'[^'\n]*'|‘[^’\n]*’)",
    re.IGNORECASE,
)


def _is_inline_observable_acceptance_clause(value: str) -> bool:
    """Recognize source-authored test outcomes embedded in request prose."""

    clause = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:!?-")
    if not clause or _INLINE_TEST_PASS_OUTCOME_RE.search(clause) is None:
        return False
    return bool(
        _INLINE_ACCEPTANCE_MARKER_RE.match(clause) or _INLINE_TEST_PASS_REQUIREMENT_RE.match(clause)
    )


_HISTORICAL_SPEECH_LINE_RE = re.compile(
    r"^\s*(?:the\s+)?(?:prior|previous|historical|earlier|other)\s+"
    r"(?:agent|assistant|user|model)\s+"
    r"(?:previously\s+|earlier\s+)?"
    r"(?:said|wrote|reported|claimed|asked|instructed|suggested|stated)\b",
    re.IGNORECASE,
)
_POSITIVE_REFERENCE_ADOPTION_RE = re.compile(
    r"\b(?:adopt|address|apply|build|fix|implement|ship|use)\s+(?:the\s+)?"
    r"(?:idea|proposal|approach|it|this|that)\b|"
    r"\b(?:idea|proposal|approach)\b[\s\S]{0,80}"
    r"\b(?:is\s+the\s+way\s+to\s+go|should\s+be\s+implemented)\b",
    re.IGNORECASE,
)
_NEGATED_REFERENCE_ADOPTION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|not\s+going\s+to|without)\b[\s\S]{0,48}"
    r"\b(?:adopt|address|apply|build|fix|implement|ship|use)\b",
    re.IGNORECASE,
)
_HISTORICAL_QUOTED_SPEECH_RE = re.compile(
    r"^(?:the\s+)?(?:prior|previous|historical)\s+"
    r"(?:agent|assistant|user|transcript|message)\s+"
    r"(?:said|says|wrote|asked|claimed|reported)\b",
    re.IGNORECASE,
)
_GENERIC_CONTINUATION_RE = re.compile(
    r"^(?:continue|complete|finish|resume)\b[\s\S]*"
    r"(?:current|complete|recovered|carried)?\s*(?:request|task|work)\b",
    re.IGNORECASE,
)
_GENERIC_COMPLETION_CLAIM_RE = re.compile(
    r"^(?:implemented|completed|done|finished|fixed)"
    r"(?:\s+(?:it|everything|end[\s-]*to[\s-]*end|the\s+(?:task|work|request)))?[.!]?$",
    re.IGNORECASE,
)
_COMPLETION_CLAIM_RE = re.compile(
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b",
    re.IGNORECASE,
)
_NEGATED_COMPLETION_RE = re.compile(
    r"\b(?:not|never|isn't|isnt|wasn't|wasnt|aren't|arent|unfinished|"
    r"incomplete|still\s+needs?|failed\s+to)\b[\s\S]{0,64}"
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b|"
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b[\s\S]{0,32}"
    r"\b(?:not|never|incomplete|incorrect|wrong)\b",
    re.IGNORECASE,
)
_STATUS_TOKEN_ALIASES = {
    "added": "add",
    "built": "build",
    "created": "create",
    "finished": "finish",
    "fixed": "fix",
    "implemented": "implement",
    "removed": "remove",
    "replaced": "replace",
    "updated": "update",
    "wired": "wire",
}
_STATUS_MATCH_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "against",
        "also",
        "and",
        "before",
        "build",
        "change",
        "complete",
        "continue",
        "create",
        "current",
        "from",
        "have",
        "implement",
        "into",
        "must",
        "only",
        "request",
        "should",
        "that",
        "the",
        "their",
        "then",
        "this",
        "through",
        "user",
        "verify",
        "when",
        "with",
        "work",
    }
)
_NEGATED_TRANSPARENCY_REQUIREMENT_RE = re.compile(
    r"\b(?:do\s+not|don['’]?t|never)\s+let\s+(?:the\s+)?"
    r"(?P<target>alerts?|badges?|buttons?|cards?|components?|dialogs?|footers?|"
    r"forms?|headers?|inputs?|menus?|messages?|modals?|pages?|panels?|screens?|"
    r"sidebars?|tables?|tabs?|toasts?|widgets?)"
    r"(?P<pre_scope>\s+(?:on|in|while|when|during|across|under|for|at)\b"
    r"[^.!?]*?)?\s+"
    r"(?:be|become|remain|stay|appear|render)\s+transparent\b"
    r"(?P<scope>\s+(?:on|in|while|when|during|across|under|for|at)\b"
    r"[^.!?]*)?",
    re.IGNORECASE,
)
_NEGATED_STATE_REQUIREMENT_RE = re.compile(
    r"\b(?:do\s+not|don['’]?t|never)\s+let\s+(?:the\s+)?"
    r"(?P<target>[a-z][a-z0-9 _./-]{0,100}?)\s+"
    r"(?:be|become|remain|stay|appear|render)\s+"
    r"(?P<state>[a-z][a-z0-9 _/-]{0,60}?)(?:[.!?,]|$)",
    re.IGNORECASE,
)
_PROHIBITED_TRANSPARENCY_STATE_RE = re.compile(
    r"\b(?:the\s+)?(?P<target>alerts?|badges?|buttons?|cards?|components?|"
    r"dialogs?|footers?|forms?|headers?|inputs?|menus?|messages?|modals?|"
    r"pages?|panels?|screens?|sidebars?|tables?|tabs?|toasts?|widgets?)"
    r"(?P<pre_scope>\s+(?:on|in|while|when|during|across|under|for|at)\b"
    r"[^.!?]*?)?\s+"
    r"(?:must|should)(?:n['’]?t|\s+not)\s+"
    r"(?:be|become|remain|stay|appear|render)\s+transparent\b"
    r"(?P<scope>\s+(?:on|in|while|when|during|across|under|for|at)\b"
    r"[^.!?]*)?",
    re.IGNORECASE,
)
_AMBIGUOUS_PRODUCT_TARGET_RE = re.compile(
    r"\b(?:alerts?|badges?|buttons?|cards?|components?|dialogs?|footers?|forms?|"
    r"headers?|inputs?|menus?|messages?|modals?|pages?|panels?|screens?|"
    r"sidebars?|tables?|tabs?|toasts?|widgets?)\b",
    re.IGNORECASE,
)
_GENERIC_UI_TARGET_TOKENS = frozenset(
    {
        "alert",
        "badge",
        "button",
        "card",
        "component",
        "dialog",
        "footer",
        "form",
        "header",
        "input",
        "menu",
        "message",
        "modal",
        "page",
        "panel",
        "screen",
        "sidebar",
        "table",
        "tab",
        "toast",
        "widget",
    }
)
_UI_IMPLEMENTATION_SUFFIXES = frozenset(
    {".css", ".html", ".htm", ".jsx", ".less", ".sass", ".scss", ".svelte", ".tsx", ".vue"}
)
_UI_IMPLEMENTATION_PATH_PARTS = frozenset({"components", "pages", "screens", "ui", "views"})
_NON_UI_IMPLEMENTATION_PATH_PARTS = frozenset(
    {
        "__tests__",
        "api",
        "data",
        "fixtures",
        "generated",
        "mocks",
        "models",
        "scripts",
        "test",
        "tests",
        "types",
    }
)
_DEICTIC_PRODUCT_TARGET_RE = re.compile(
    r"\b(?:this|that|these|those|it|the\s+thing)\b",
    re.IGNORECASE,
)
_OPAQUE_OUTCOME_INTENT_RE = re.compile(
    r"\b(?:ensure|keep|make|render)\b.{0,120}\bopaque\b|"
    r"\b(?:must|should)\s+(?:be|become|remain|stay|appear|render)\s+opaque\b|"
    r"\bopaque\s+(?:alerts?|badges?|buttons?|cards?|components?|dialogs?|"
    r"footers?|forms?|headers?|inputs?|menus?|messages?|modals?|pages?|panels?|"
    r"screens?|sidebars?|tables?|tabs?|toasts?|widgets?)\b|"
    r"\b(?:do\s+not|don['’]?t|never)\b.{0,140}\btransparent\b|"
    r"\b(?:must|should)(?:n['’]?t|\s+not)\b.{0,80}\btransparent\b|"
    r"\bprevent\b.{0,140}\btransparent\b|"
    r"\b(?:no|without)\s+transparen(?:cy|t\s+backgrounds?)\b",
    re.IGNORECASE,
)
_NEGATED_OPAQUE_OUTCOME_RE = re.compile(
    r"\b(?:do\s+not|don['’]?t|never)\b.{0,120}\bopaque\b|"
    r"\b(?:must|should)(?:n['’]?t|\s+not)\b.{0,80}\bopaque\b|"
    r"\b(?:no|without)\s+opaque\b",
    re.IGNORECASE,
)
_PARTIAL_OPACITY_OUTCOME_RE = re.compile(
    r"\b(?:semi[- ]?opaque|partially\s+opaque|more\s+opaque|less\s+opaque|"
    r"(?:\d|[1-9]\d)\s*%\s*opaque|still\s+translucent)\b",
    re.IGNORECASE,
)
_PARTIAL_TRANSPARENCY_OUTCOME_RE = re.compile(
    r"\b(?:completely|fully|partially|semi|slightly|somewhat|too)\s+"
    r"transparent\b|\b(?:\d|[1-9]\d|100)\s*%\s*transparent\b",
    re.IGNORECASE,
)
_NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE = re.compile(
    r"\b(?:already (?:done|completed|implemented)|background|context(?: only)?|"
    r"current state|example|files?|for reference|historical|history|"
    r"non[- ]?goals?|out of scope|own(?:ed|ership)?|prior "
    r"(?:conversation|prompt|response)|progress|quoted|transcript)\b",
    re.IGNORECASE,
)
_PLAIN_REQUIREMENT_SECTION_HEADING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 /&()_-]{0,80}:$")
_TOOL_SELECTION_DECISION_RE = re.compile(
    r"\b(?:i|we)\s*(?:(?:'ll|’ll|will|would|should|can)\s+|"
    r"(?:am|are|'m|’m|'re|’re)\s+(?:now\s+)?)"
    r"(?:call|inspect\s+with|open|run|use|using)\s+"
    r"(?:the\s+)?(?:browser|command|exec|git|js|node|playwright|pytest|"
    r"python|rg|shell|terminal|tool)\b",
    re.IGNORECASE,
)


@dataclass
class DraftItem:
    category: str
    statement: str
    truth_state: str
    events: list[SessionEvent]
    state: str = "active"
    payload: dict[str, Any] = field(default_factory=dict)


def _checkpoint_is_materialized(checkpoint: WorkCheckpoint) -> bool:
    """Return whether the immutable row and its normalized items are complete."""

    payload_json = str(checkpoint.payload_json or "")
    payload_sha256 = str(checkpoint.payload_sha256 or "")
    if not payload_json or not payload_sha256 or _sha256(payload_json) != payload_sha256:
        return False
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or str(payload.get("workspace_id") or "") != str(checkpoint.workspace_id)
        or str(payload.get("provider") or "") != checkpoint.provider
        or str(payload.get("session_id") or "") != checkpoint.session_id
    ):
        return False
    boundary = payload.get("boundary")
    sections = payload.get("sections")
    if (
        not isinstance(boundary, dict)
        or str(boundary.get("session_event_id") or "") != str(checkpoint.boundary_event_id)
        or not isinstance(sections, dict)
        or any(not isinstance(sections.get(category), list) for category in CHECKPOINT_CATEGORIES)
    ):
        return False

    expected_items: list[tuple[str, str]] = []
    for category in CHECKPOINT_CATEGORIES:
        for item in sections[category]:
            if not isinstance(item, dict):
                return False
            item_key = str(item.get("item_key") or "")
            if not item_key:
                return False
            expected_items.append((category, item_key))
    actual_items = [(item.category, item.item_key) for item in checkpoint.items]
    return (
        len(expected_items) == len(set(expected_items))
        and len(actual_items) == len(set(actual_items))
        and set(expected_items) == set(actual_items)
    )


async def capture_checkpoint(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    boundary_event_id: UUID | None = None,
    trigger: str = "manual",
) -> WorkCheckpoint:
    """Build and persist one immutable checkpoint from observed session events."""

    boundary = await _resolve_boundary(
        session,
        workspace_id=workspace_id,
        provider=provider,
        session_id=session_id,
        boundary_event_id=boundary_event_id,
    )
    existing = await session.scalar(
        select(WorkCheckpoint)
        .where(
            WorkCheckpoint.workspace_id == workspace_id,
            WorkCheckpoint.provider == provider,
            WorkCheckpoint.session_id == session_id,
            WorkCheckpoint.boundary_event_id == boundary.id,
            WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
        )
        .options(selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence))
        .with_for_update()
    )
    if existing is not None and _checkpoint_is_materialized(existing):
        return existing

    events = list(
        await session.scalars(
            select(SessionEvent)
            .where(
                SessionEvent.workspace_id == workspace_id,
                SessionEvent.provider == provider,
                SessionEvent.session_id == session_id,
                SessionEvent.sequence_number <= boundary.sequence_number,
            )
            .order_by(SessionEvent.sequence_number, SessionEvent.id)
        )
    )
    if not events:
        raise ValueError("No session events are available for the checkpoint boundary")

    source_document = await session.get(SourceDocument, boundary.source_document_id)
    if source_document is None:
        raise ValueError("Checkpoint source document no longer exists")
    snapshot = await _capture_snapshot(events, source_document)
    sections = _build_sections(events, snapshot)
    _bind_checkpoint_goal_artifacts(
        sections,
        source_document=source_document,
        provider=provider,
    )
    goal_present = bool(sections["goal"])
    next_present = bool(sections["exact_next_action"])
    capture_status = "complete" if goal_present and next_present else "incomplete"
    active_blockers = [
        item
        for item in sections["blockers"]
        if item.state.strip().lower() not in _INACTIVE_BLOCKER_STATES
    ]
    continuation_status = (
        "blocked"
        if active_blockers
        else "ready"
        if capture_status == "complete"
        else "review_required"
    )

    previous = await session.scalar(
        select(WorkCheckpoint)
        .where(
            WorkCheckpoint.workspace_id == workspace_id,
            WorkCheckpoint.provider == provider,
            WorkCheckpoint.session_id == session_id,
            *((WorkCheckpoint.id != existing.id,) if existing is not None else ()),
        )
        .order_by(WorkCheckpoint.created_at.desc(), WorkCheckpoint.id.desc())
        .limit(1)
    )
    candidate = WorkCheckpoint(
        workspace_id=workspace_id,
        source_document_id=boundary.source_document_id,
        provider=provider,
        session_id=session_id,
        boundary_event_id=boundary.id,
        trigger=trigger,
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        capture_status=capture_status,
        continuation_status=continuation_status,
        repo_root=snapshot.root if snapshot else None,
        branch=snapshot.branch if snapshot else None,
        head_commit=snapshot.head_commit if snapshot else None,
        worktree_fingerprint=snapshot.status_fingerprint if snapshot else None,
        payload_json="{}",
        payload_sha256="",
        supersedes_checkpoint_id=previous.id if previous else None,
    )
    payload = _checkpoint_payload(
        candidate,
        boundary=boundary,
        sections=sections,
        snapshot=snapshot,
    )
    candidate.payload_json = _canonical_json(payload)
    candidate.payload_sha256 = _sha256(candidate.payload_json)
    checkpoint = existing or candidate
    try:
        # Keep the parent row, normalized items, evidence, and payload digest
        # inside one savepoint. SQLite may make an outermost savepoint durable
        # before the caller's later work completes, so releasing it must never
        # expose the empty checkpoint shell that older versions could leave
        # behind after a downstream rollback.
        async with session.begin_nested():
            if existing is not None:
                checkpoint.items.clear()
                await session.flush()
                checkpoint.source_document_id = candidate.source_document_id
                checkpoint.trigger = candidate.trigger
                checkpoint.capture_status = candidate.capture_status
                checkpoint.continuation_status = candidate.continuation_status
                checkpoint.repo_root = candidate.repo_root
                checkpoint.branch = candidate.branch
                checkpoint.head_commit = candidate.head_commit
                checkpoint.worktree_fingerprint = candidate.worktree_fingerprint
                checkpoint.payload_json = candidate.payload_json
                checkpoint.payload_sha256 = candidate.payload_sha256
                checkpoint.supersedes_checkpoint_id = candidate.supersedes_checkpoint_id
            else:
                session.add(checkpoint)
            await session.flush()

            persisted_items: list[tuple[CheckpointItem, DraftItem]] = []
            for category in CHECKPOINT_CATEGORIES:
                for ordinal, draft in enumerate(sections[category]):
                    item = CheckpointItem(
                        checkpoint_id=checkpoint.id,
                        item_key=f"{category}:{ordinal + 1}",
                        category=category,
                        ordinal=ordinal,
                        statement=draft.statement,
                        state=draft.state,
                        truth_state=draft.truth_state,
                        payload_json=_canonical_json(draft.payload),
                    )
                    session.add(item)
                    persisted_items.append((item, draft))
            await session.flush()

            for item, draft in persisted_items:
                for evidence_event in _unique_events(draft.events):
                    locator = {
                        "provider_event_id": (evidence_event.provider_event_id),
                        "sequence_number": evidence_event.sequence_number,
                        "event_type": evidence_event.event_type,
                        "source_cursor": evidence_event.source_cursor,
                    }
                    digest_material = {
                        "item_key": item.item_key,
                        "event_sha256": evidence_event.content_sha256,
                        "locator": locator,
                    }
                    session.add(
                        CheckpointEvidence(
                            checkpoint_item_id=item.id,
                            evidence_type="session_event",
                            session_event_id=evidence_event.id,
                            source_document_id=(evidence_event.source_document_id),
                            supports=True,
                            locator_json=_canonical_json(locator),
                            evidence_sha256=_sha256(_canonical_json(digest_material)),
                            observed_at=evidence_event.occurred_at,
                        )
                    )
            await session.flush()
    except IntegrityError:
        if existing is not None:
            raise
        winner = await session.scalar(
            select(WorkCheckpoint)
            .where(
                WorkCheckpoint.workspace_id == workspace_id,
                WorkCheckpoint.provider == provider,
                WorkCheckpoint.session_id == session_id,
                WorkCheckpoint.boundary_event_id == boundary.id,
                WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
            )
            .options(selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence))
            .with_for_update()
        )
        if winner is None:
            raise
        if not _checkpoint_is_materialized(winner):
            return await capture_checkpoint(
                session,
                workspace_id=workspace_id,
                provider=provider,
                session_id=session_id,
                boundary_event_id=boundary.id,
                trigger=trigger,
            )
        return winner
    if existing is not None:
        session.expire(checkpoint, ("items",))
    return checkpoint


async def capture_missing_compaction_checkpoints(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
) -> list[WorkCheckpoint]:
    boundaries = list(
        await session.scalars(
            select(SessionEvent)
            .where(
                SessionEvent.workspace_id == workspace_id,
                SessionEvent.provider == provider,
                SessionEvent.session_id == session_id,
                SessionEvent.event_type == "compaction_boundary",
            )
            .order_by(SessionEvent.sequence_number, SessionEvent.id)
        )
    )
    captured: list[WorkCheckpoint] = []
    for boundary in boundaries:
        captured.append(
            await capture_checkpoint(
                session,
                workspace_id=workspace_id,
                provider=provider,
                session_id=session_id,
                boundary_event_id=boundary.id,
                trigger="compaction",
            )
        )
    return captured


async def capture_checkpoint_schema_upgrades(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
) -> int:
    """Backfill the current schema from already-normalized compaction events."""

    conditions = (
        WorkCheckpoint.workspace_id == workspace_id,
        WorkCheckpoint.provider == provider,
        WorkCheckpoint.session_id == session_id,
        WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
    )
    before = int(
        await session.scalar(select(func.count()).select_from(WorkCheckpoint).where(*conditions))
        or 0
    )
    await capture_missing_compaction_checkpoints(
        session,
        workspace_id=workspace_id,
        provider=provider,
        session_id=session_id,
    )
    after = int(
        await session.scalar(select(func.count()).select_from(WorkCheckpoint).where(*conditions))
        or 0
    )
    return max(0, after - before)


async def get_checkpoint(
    session: AsyncSession,
    checkpoint_id: UUID,
) -> WorkCheckpoint | None:
    return await session.scalar(
        select(WorkCheckpoint)
        .where(WorkCheckpoint.id == checkpoint_id)
        .options(
            selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
            selectinload(WorkCheckpoint.verifications),
            selectinload(WorkCheckpoint.boundary_event),
            selectinload(WorkCheckpoint.source_document),
        )
    )


async def latest_checkpoint(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str | None = None,
    session_id: str | None = None,
    access_scope: AccessScope | None = None,
) -> WorkCheckpoint | None:
    conditions = [WorkCheckpoint.workspace_id == workspace_id]
    normalized_session = normalize_optional_session_key(provider, session_id)
    if normalized_session is not None:
        normalized_provider, normalized_session_id = normalized_session
        conditions.extend(
            (
                WorkCheckpoint.provider.in_(session_provider_values(normalized_provider)),
                WorkCheckpoint.session_id == normalized_session_id,
            )
        )
    conditions.extend(
        _checkpoint_access_conditions(
            workspace_id=workspace_id,
            access_scope=access_scope,
        )
    )

    return await session.scalar(
        select(WorkCheckpoint)
        .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
        .where(*conditions)
        .order_by(
            SessionEvent.occurred_at.desc().nulls_last(),
            SessionEvent.sequence_number.desc(),
            case(
                (
                    WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
                    1,
                ),
                else_=0,
            ).desc(),
            WorkCheckpoint.schema_version.desc(),
            WorkCheckpoint.created_at.desc(),
            WorkCheckpoint.id.desc(),
        )
        .options(
            selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
            selectinload(WorkCheckpoint.verifications),
            selectinload(WorkCheckpoint.boundary_event),
            selectinload(WorkCheckpoint.source_document),
        )
        .limit(1)
    )


async def list_checkpoints(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int = 50,
    provider: str | None = None,
    session_id: str | None = None,
    access_scope: AccessScope | None = None,
) -> list[WorkCheckpoint]:
    requested = max(1, min(limit, 100))
    conditions = [WorkCheckpoint.workspace_id == workspace_id]
    normalized_session = normalize_optional_session_key(provider, session_id)
    if normalized_session is not None:
        normalized_provider, normalized_session_id = normalized_session
        conditions.extend(
            (
                WorkCheckpoint.provider.in_(session_provider_values(normalized_provider)),
                WorkCheckpoint.session_id == normalized_session_id,
            )
        )
    conditions.extend(
        _checkpoint_access_conditions(
            workspace_id=workspace_id,
            access_scope=access_scope,
        )
    )
    values = list(
        await session.scalars(
            select(WorkCheckpoint)
            .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
            .where(*conditions)
            .order_by(
                SessionEvent.occurred_at.desc().nulls_last(),
                SessionEvent.sequence_number.desc(),
                case(
                    (
                        WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
                        1,
                    ),
                    else_=0,
                ).desc(),
                WorkCheckpoint.schema_version.desc(),
                WorkCheckpoint.created_at.desc(),
                WorkCheckpoint.id.desc(),
            )
            .options(
                selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
                selectinload(WorkCheckpoint.verifications),
                selectinload(WorkCheckpoint.boundary_event),
                selectinload(WorkCheckpoint.source_document),
            )
            .limit(min(300, requested * 3))
        )
    )
    result: list[WorkCheckpoint] = []
    seen_boundaries: set[tuple[str, str, UUID]] = set()
    for checkpoint in values:
        key = (
            checkpoint.provider,
            checkpoint.session_id,
            checkpoint.boundary_event_id,
        )
        if key in seen_boundaries:
            continue
        seen_boundaries.add(key)
        result.append(checkpoint)
        if len(result) >= requested:
            break
    return result


async def checkpoints_to_dicts(
    session: AsyncSession,
    checkpoints: Iterable[WorkCheckpoint],
    *,
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """Serialize checkpoints with one coherent session-tip lookup."""

    values = list(checkpoints)
    pairs = {
        key
        for item in values
        if (key := normalize_session_key(item.provider, item.session_id)) is not None
    }
    tips: dict[tuple[str, str], dict[str, Any]] = {}
    if values and pairs:
        pair_predicates = [
            and_(
                SessionEvent.provider.in_(session_provider_values(provider)),
                SessionEvent.session_id == session_id,
            )
            for provider, session_id in pairs
        ]
        tip_conditions = [
            SessionEvent.workspace_id == values[0].workspace_id,
            or_(*pair_predicates),
        ]
        if access_scope is not None:
            tip_conditions.append(
                source_access_predicate(
                    access_scope,
                    workspace_id=values[0].workspace_id,
                )
            )
        rows = await session.execute(
            select(
                SessionEvent.provider,
                SessionEvent.session_id,
                func.max(SessionEvent.sequence_number),
                func.max(SessionEvent.occurred_at),
            )
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(*tip_conditions)
            .group_by(SessionEvent.provider, SessionEvent.session_id)
        )
        for provider, session_id, sequence_number, occurred_at in rows:
            key = normalize_session_key(provider, session_id)
            if key is None or key not in pairs:
                continue
            current = tips.setdefault(
                key,
                {
                    "sequence_number": None,
                    "occurred_at": None,
                },
            )
            if sequence_number is not None:
                current["sequence_number"] = max(
                    sequence_number,
                    current["sequence_number"] or sequence_number,
                )
            if occurred_at is not None:
                current["occurred_at"] = max(
                    occurred_at,
                    current["occurred_at"] or occurred_at,
                )
    serialized: list[dict[str, Any]] = []
    for item in values:
        # The list/latest endpoints drive which immutable checkpoint the UI
        # offers for copying. Historical rows can contain a capped goal even
        # though the lossless turn remains recoverable from their bound source
        # revision. Apply the same source-scoped recovery used by the handoff
        # endpoint here so selection never skips the newest checkpoint and
        # silently routes the user to an older, unrelated task.
        recovered_goal = await resolve_session_handoff_request_verbatim(
            session,
            item,
            access_scope=access_scope,
        )
        serialized.append(
            checkpoint_to_dict(
                item,
                session_tip=tips.get(
                    normalize_session_key(
                        item.provider,
                        item.session_id,
                    )
                ),
                recovered_goal=recovered_goal,
            )
        )
    return serialized


def _checkpoint_access_conditions(
    *,
    workspace_id: UUID,
    access_scope: AccessScope | None,
) -> tuple:
    """Keep hidden checkpoint and evidence sources out of result pagination."""

    if access_scope is None:
        return ()
    checkpoint_source_is_visible = exists(
        select(SourceDocument.id)
        .where(
            SourceDocument.id == WorkCheckpoint.source_document_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .correlate(WorkCheckpoint)
    )
    evidence_source_is_visible = exists(
        select(SourceDocument.id)
        .where(
            SourceDocument.id == CheckpointEvidence.source_document_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .correlate(CheckpointEvidence)
    )
    hidden_evidence_source = exists(
        select(CheckpointEvidence.id)
        .join(
            CheckpointItem,
            CheckpointEvidence.checkpoint_item_id == CheckpointItem.id,
        )
        .where(
            CheckpointItem.checkpoint_id == WorkCheckpoint.id,
            CheckpointEvidence.source_document_id.is_not(None),
            ~evidence_source_is_visible,
        )
        .correlate(WorkCheckpoint)
    )
    return checkpoint_source_is_visible, ~hidden_evidence_source


def checkpoint_to_dict(
    checkpoint: WorkCheckpoint,
    *,
    session_tip: dict[str, Any] | None = None,
    recovered_goal: str | None = None,
    filter_presentation_noise: bool = False,
) -> dict[str, Any]:
    try:
        payload = json.loads(checkpoint.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    sections: dict[str, list[dict[str, Any]]] = {category: [] for category in CHECKPOINT_CATEGORIES}
    for item in sorted(checkpoint.items, key=lambda value: (value.category, value.ordinal)):
        try:
            item_payload = json.loads(item.payload_json or "{}")
        except (TypeError, json.JSONDecodeError):
            item_payload = {}
        sections.setdefault(item.category, []).append(
            {
                "id": str(item.id),
                "item_key": item.item_key,
                "statement": item.statement,
                "state": item.state,
                "truth_state": item.truth_state,
                "payload": item_payload,
                "evidence": [
                    {
                        "id": str(evidence.id),
                        "type": evidence.evidence_type,
                        "session_event_id": (
                            str(evidence.session_event_id) if evidence.session_event_id else None
                        ),
                        "source_document_id": (
                            str(evidence.source_document_id)
                            if evidence.source_document_id
                            else None
                        ),
                        "supports": evidence.supports,
                        "observed_at": evidence.observed_at,
                        "locator": _json_object(evidence.locator_json),
                    }
                    for evidence in item.evidence
                ],
            }
        )
    sections, projection = _safe_checkpoint_projection(
        checkpoint,
        sections,
        recovered_goal=recovered_goal,
        filter_presentation_noise=filter_presentation_noise,
    )
    projected_continuation_status = checkpoint.continuation_status
    if projected_continuation_status == "blocked" and not any(
        str(item.get("state") or "active").strip().lower() not in _INACTIVE_BLOCKER_STATES
        for item in sections["blockers"]
    ):
        projected_continuation_status = "review_required"
    payload = dict(payload)
    payload["sections"] = {
        category: [
            {
                "item_key": item["item_key"],
                "statement": item["statement"],
                "state": item["state"],
                "truth_state": item["truth_state"],
                "payload": item["payload"],
                "evidence_event_ids": [
                    evidence["session_event_id"]
                    for evidence in item["evidence"]
                    if evidence["session_event_id"]
                ],
            }
            for item in sections[category]
        ]
        for category in CHECKPOINT_CATEGORIES
    }
    verifications = sorted(
        checkpoint.verifications,
        key=lambda value: (value.verified_at, value.id),
        reverse=True,
    )
    boundary = _boundary_context(checkpoint, payload, session_tip=session_tip)
    activity = _checkpoint_activity(checkpoint, sections, boundary)
    task_key = next(
        (
            evidence["session_event_id"]
            for evidence in (sections.get("goal") or [{}])[0].get("evidence", [])
            if evidence.get("session_event_id")
        ),
        None,
    )
    return {
        "id": str(checkpoint.id),
        "task_key": task_key,
        "workspace_id": str(checkpoint.workspace_id),
        "provider": (
            normalize_session_key(checkpoint.provider, checkpoint.session_id)
            or (checkpoint.provider, checkpoint.session_id)
        )[0],
        "session_id": checkpoint.session_id,
        "source_document_id": str(checkpoint.source_document_id),
        "boundary_event_id": str(checkpoint.boundary_event_id),
        "trigger": checkpoint.trigger,
        "schema_version": checkpoint.schema_version,
        "capture_status": (checkpoint.capture_status if projection["valid"] else "incomplete"),
        "continuation_status": (
            projected_continuation_status if projection["valid"] else "review_required"
        ),
        "projection": projection,
        "boundary": boundary,
        "currentness": boundary["currentness"],
        "activity": activity,
        "repo": {
            "root": checkpoint.repo_root,
            "branch": checkpoint.branch,
            "head_commit": checkpoint.head_commit,
            "worktree_fingerprint": checkpoint.worktree_fingerprint,
        },
        "sections": sections,
        "verification": _verification_to_dict(verifications[0]) if verifications else None,
        "verification_history": [_verification_to_dict(item) for item in verifications],
        "payload_sha256": checkpoint.payload_sha256,
        "payload": payload,
        "supersedes_checkpoint_id": (
            str(checkpoint.supersedes_checkpoint_id)
            if checkpoint.supersedes_checkpoint_id
            else None
        ),
        "created_at": checkpoint.created_at,
    }


def _boundary_context(
    checkpoint: WorkCheckpoint,
    payload: dict[str, Any],
    *,
    session_tip: dict[str, Any] | None,
) -> dict[str, Any]:
    payload_boundary = payload.get("boundary")
    payload_boundary = payload_boundary if isinstance(payload_boundary, dict) else {}
    boundary_event = checkpoint.__dict__.get("boundary_event")
    source_document = checkpoint.__dict__.get("source_document")
    boundary_event_type = getattr(boundary_event, "event_type", None) or payload_boundary.get(
        "event_type"
    )
    pre_compaction = boundary_event_type == "compaction_boundary"
    boundary_at = getattr(boundary_event, "occurred_at", None) or _parse_datetime(
        payload_boundary.get("occurred_at")
    )
    sequence_number = getattr(boundary_event, "sequence_number", None) or payload_boundary.get(
        "sequence_number"
    )
    latest_sequence = (session_tip or {}).get("sequence_number")
    has_newer_events = bool(
        isinstance(sequence_number, int)
        and isinstance(latest_sequence, int)
        and latest_sequence > sequence_number
    )
    if has_newer_events:
        state = "superseded"
        label = "Superseded checkpoint"
        reason = "This session has events after the captured boundary."
    elif boundary_at is None:
        state = "unknown"
        label = "Checkpoint boundary"
        reason = "The source did not provide a trustworthy boundary time."
    elif utc_now() - boundary_at > timedelta(hours=24):
        state = "historical"
        label = "Historical checkpoint"
        reason = "This is an older immutable session boundary, not live session state."
    else:
        state = "captured"
        label = "Recent checkpoint boundary"
        reason = "This is immutable state at the captured boundary, not a live goal."

    metadata = _json_object(
        getattr(source_document, "metadata_json", None) if source_document else None
    )
    source_activity_at = _first_datetime(
        metadata.get("ended_at"),
        metadata.get("updated_at"),
        metadata.get("source_modified_at"),
        metadata.get("started_at"),
    )
    return {
        "event_id": str(checkpoint.boundary_event_id),
        "event_type": boundary_event_type,
        "snapshot_phase": "pre_compaction" if pre_compaction else "session_tip",
        "snapshot_phase_label": (
            "Pre-compaction snapshot" if pre_compaction else "Session-tip snapshot"
        ),
        "snapshot_phase_description": (
            "Captures session state immediately before context compaction and excludes "
            "all events after the boundary."
            if pre_compaction
            else "Captures session state through the selected latest event."
        ),
        "sequence_number": sequence_number,
        "occurred_at": boundary_at,
        "captured_at": checkpoint.created_at,
        "source_ingested_at": (
            getattr(source_document, "ingested_at", None) if source_document else None
        ),
        "source_activity_at": source_activity_at,
        "session_tip_sequence": latest_sequence,
        "session_tip_at": (session_tip or {}).get("occurred_at"),
        "has_newer_events": has_newer_events,
        "currentness": {
            "state": state,
            "label": label,
            "is_live": False,
            "reason": reason,
        },
    }


def _safe_checkpoint_projection(
    checkpoint: WorkCheckpoint,
    sections: dict[str, list[dict[str, Any]]],
    *,
    recovered_goal: str | None = None,
    filter_presentation_noise: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Make stored checkpoints safe to consume without mutating audit records."""

    projected = {category: list(sections.get(category) or []) for category in CHECKPOINT_CATEGORIES}
    goals = [
        item
        for item in projected["goal"]
        if is_substantive_user_request(str(item.get("statement") or ""))
    ]
    validated_recovery = _validated_session_request(recovered_goal)
    recovered_goal_projection = (
        not goals and validated_recovery is not None and len(projected["goal"]) <= 1
    )
    synthesized_missing_goal = bool(recovered_goal_projection and not projected["goal"])
    recovered_goal_evidence: set[tuple[str, ...]] = set()
    if recovered_goal_projection:
        recovered_item = (
            dict(projected["goal"][0])
            if projected["goal"]
            else {
                "id": None,
                "item_key": "goal:recovered-at-boundary",
                "state": "active",
                "truth_state": "recovered",
                "evidence": [],
            }
        )
        recovered_payload = dict(recovered_item.get("payload") or {})
        recovered_payload.update(
            {
                "request_verbatim": validated_recovery,
                "request_sha256": _sha256(validated_recovery),
                "derived_from_same_session_boundary": True,
            }
        )
        recovered_item.update(
            {
                "statement": validated_recovery,
                "payload": recovered_payload,
            }
        )
        goals = [recovered_item]
        recovered_goal_evidence = _item_evidence_keys(recovered_item)
    if not goals:
        return (
            {category: [] for category in CHECKPOINT_CATEGORIES},
            {
                "valid": False,
                "state": "missing_substantive_goal",
                "reason": (
                    "The stored checkpoint had no substantive user goal; continuation "
                    "controls and runtime instructions were excluded."
                ),
                "stored_schema_version": checkpoint.schema_version,
            },
        )

    goal = goals[-1]
    projected["goal"] = [goal]
    goal_sequence = _item_sequence(goal)
    latest_progress_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    latest_completion_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if _positive_completion_claim(str(item.get("statement") or ""))
            and (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    derived_fallback_superseded = False
    for category in CHECKPOINT_CATEGORIES:
        if category == "goal":
            continue
        safe_items: list[dict[str, Any]] = []
        for item in projected[category]:
            statement = str(item.get("statement") or "")
            sequence = _item_sequence(item)
            if (
                synthesized_missing_goal
                and category == "exact_next_action"
                and _GENERIC_CONTINUATION_RE.match(statement.strip())
            ):
                item = {
                    **item,
                    "payload": {
                        **(item.get("payload") or {}),
                        "derived_from_recovered_goal": True,
                    },
                }
            sourced_only_from_recovered_goal = (
                recovered_goal_projection
                and _item_is_sourced_only_from(item, recovered_goal_evidence)
            )
            if category == "decisions" and sourced_only_from_recovered_goal:
                # Historical checkpoint releases derived decisions from the raw
                # user transport. If that transport was truncated, referenced
                # conversation text cannot be distinguished from user authority.
                # Keep later assistant-sourced decisions, but drop this unsafe
                # goal-event projection.
                continue
            if (
                category == "exact_next_action"
                and sourced_only_from_recovered_goal
                and "[output truncated]" in statement.casefold()
            ):
                item = {
                    **item,
                    "statement": (
                        "Continue the complete recovered request shown under “Current main goal.”"
                    ),
                    "payload": {
                        **(item.get("payload") or {}),
                        "derived_from_recovered_goal": True,
                    },
                }
                statement = str(item["statement"])
            if (
                category == "exact_next_action"
                and bool((item.get("payload") or {}).get("derived_from_recovered_goal"))
                and latest_completion_sequence is not None
                and sequence is not None
                and sequence < latest_completion_sequence
            ):
                # A fallback copied from the original lead is not a later
                # instruction to reopen work. Newer scoped completion
                # evidence supersedes it.
                derived_fallback_superseded = True
                continue
            if is_session_instruction_noise(statement):
                continue
            if (
                category == "blockers"
                and str(item.get("truth_state") or "").strip().lower() == "reported"
                and latest_progress_sequence is not None
                and sequence is not None
                and sequence < latest_progress_sequence
            ):
                # Intermediate agent commentary often announces a blocker and
                # later reports successful progress. Preserve the earlier
                # statement as history, but never present it as live authority.
                item = {**item, "state": "historical"}
            if (
                filter_presentation_noise
                and category == "blockers"
                and _DERIVED_COMMAND_BLOCKER.fullmatch(statement.strip())
                and str(item.get("payload", {}).get("command") or "").strip()
            ):
                # A failed command is execution history, not proof that a new
                # agent cannot start. It remains available under failed_attempts
                # and verification evidence.
                continue
            if (
                filter_presentation_noise
                and category == "failed_attempts"
                and _is_low_signal_failed_attempt(item)
            ):
                # Read-only discovery failures and harness transport errors do
                # not describe a failed implementation approach. Keep genuine
                # test, build, lint, and mutation failures.
                continue
            if (
                filter_presentation_noise
                and category == "verification"
                and _is_low_signal_failed_attempt(item)
            ):
                # Environment probes are not task verification even when the
                # harness recorded them in a verification-shaped event.
                continue
            if (
                filter_presentation_noise
                and category == "exact_next_action"
                and _INTERNAL_TOOL_NEXT_ACTION.fullmatch(statement.strip())
            ):
                # Harness plumbing failures such as tool:write_stdin are not a
                # user task and must never become the next agent's instruction.
                continue
            if (
                filter_presentation_noise
                and category == "exact_next_action"
                and _DERIVED_BLOCKER_NEXT_ACTION.match(statement.strip())
                and latest_progress_sequence is not None
                and sequence is not None
                and sequence < latest_progress_sequence
            ):
                # This instruction was synthesized from a reported blocker that
                # newer progress has already superseded.
                continue
            if (
                checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION
                and goal_sequence is not None
                and (sequence is None or sequence < goal_sequence)
            ):
                continue
            safe_items.append(item)
        projected[category] = safe_items

    if derived_fallback_superseded and not projected["exact_next_action"]:
        # Historical compaction rows sometimes contain only an original
        # "continue the request" fallback. Once later completion evidence
        # supersedes that fallback, leaving the projection empty makes list
        # consumers skip this newest boundary and copy an older task. Preserve
        # chronology without trusting the completion claim by deriving a
        # read-safe reconciliation action for either stored or recovered goals.
        projected["exact_next_action"] = [
            {
                "id": None,
                "item_key": "exact_next_action:reconcile-goal",
                "statement": (
                    "Inspect the current repository and verify the carried goal's "
                    "current status before acting on any historical completion claim."
                ),
                "state": "active",
                "truth_state": "derived",
                "payload": {
                    "derived_from_reconciliation": True,
                    "source_completion_sequence": latest_completion_sequence,
                },
                "evidence": [],
            }
        ]
    elif recovered_goal_projection and not projected["exact_next_action"]:
        projected["exact_next_action"] = [
            {
                "id": None,
                "item_key": "exact_next_action:continue-recovered-goal",
                "statement": (
                    "Continue the complete recovered request shown under “Current main goal.”"
                ),
                "state": "active",
                "truth_state": "derived",
                "payload": {
                    "derived_from_recovered_goal": True,
                },
                "evidence": [],
            }
        ]

    valid = bool(projected["exact_next_action"])
    return projected, {
        "valid": valid,
        "state": "safe" if valid else "missing_scoped_next_action",
        "reason": (
            "All displayed items belong to the substantive goal at this boundary."
            if valid
            else "No evidence-linked next action belongs to the displayed goal."
        ),
        "stored_schema_version": checkpoint.schema_version,
    }


def _checkpoint_activity(
    checkpoint: WorkCheckpoint,
    sections: dict[str, list[dict[str, Any]]],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    goals = sections.get("goal") or []
    raw_goal = goals[0].get("statement") if goals else None
    request = normalize_substantive_user_request(raw_goal)
    goal_sequence = _item_sequence(goals[0]) if goals else None
    boundary_sequence = boundary.get("sequence_number")

    def in_goal_scope(item: dict[str, Any]) -> bool:
        sequence = _item_sequence(item)
        if goal_sequence is None or sequence is None:
            return checkpoint.schema_version == CHECKPOINT_SCHEMA_VERSION
        if sequence < goal_sequence:
            return False
        return not isinstance(boundary_sequence, int) or sequence <= boundary_sequence

    progress = [
        item
        for item in sections.get("progress") or []
        if in_goal_scope(item)
        and not is_session_instruction_noise(str(item.get("statement") or ""))
    ]
    latest_progress = max(progress, key=lambda item: _item_sequence(item) or -1, default=None)
    latest_update = str(latest_progress.get("statement") or "").strip() if latest_progress else None
    files = [
        str(item.get("statement") or "").strip()
        for item in sections.get("relevant_files") or []
        if in_goal_scope(item) and str(item.get("statement") or "").strip()
    ]
    checks = [item for item in sections.get("verification") or [] if in_goal_scope(item)]
    passed = sum(item.get("payload", {}).get("passed") is True for item in checks)
    failed = sum(item.get("payload", {}).get("passed") is False for item in checks)
    return {
        "id": f"checkpoint:{checkpoint.id}",
        "kind": "checkpoint_boundary",
        "state": boundary["currentness"]["state"],
        "live": False,
        "evidence_level": "checkpoint_boundary",
        "title": request or "No substantive goal captured at this checkpoint",
        "request": request,
        "latest_update": latest_update,
        "rationale": None,
        "provider": checkpoint.provider,
        "session_id": checkpoint.session_id,
        "tool": checkpoint.provider,
        "model": None,
        "branch": checkpoint.branch,
        "started_at": None,
        "updated_at": boundary.get("occurred_at"),
        "ended_at": boundary.get("occurred_at"),
        "boundary": boundary,
        "currentness": boundary["currentness"],
        "changed_files": files,
        "verification": {
            "observed": len(checks),
            "passed": passed,
            "failed": failed,
        },
        "outcome": None,
        "source_card_id": None,
        "source_document_id": str(checkpoint.source_document_id),
    }


def _item_sequence(item: dict[str, Any]) -> int | None:
    values = [
        evidence.get("locator", {}).get("sequence_number")
        for evidence in item.get("evidence") or []
    ]
    values = [value for value in values if isinstance(value, int)]
    return max(values) if values else None


def _item_evidence_keys(item: dict[str, Any]) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    for evidence in item.get("evidence") or []:
        session_event_id = str(evidence.get("session_event_id") or "").strip()
        if session_event_id:
            keys.add(("session_event_id", session_event_id))
        locator = evidence.get("locator")
        locator = locator if isinstance(locator, dict) else {}
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if provider_event_id:
            keys.add(
                (
                    "provider_event_id",
                    str(evidence.get("source_document_id") or ""),
                    provider_event_id,
                )
            )
    return keys


def _item_is_sourced_only_from(
    item: dict[str, Any],
    source_keys: set[tuple[str, ...]],
) -> bool:
    evidence = [entry for entry in item.get("evidence") or [] if entry.get("supports") is not False]
    return bool(
        evidence
        and source_keys
        and all(_item_evidence_keys({"evidence": [entry]}) & source_keys for entry in evidence)
    )


def _is_low_signal_failed_attempt(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    command = str(payload.get("command") or "").strip()
    if not command:
        statement = str(item.get("statement") or "").strip()
        match = re.match(r"^`([^`]+)`\s+failed\b", statement, re.IGNORECASE)
        command = match.group(1).strip() if match is not None else ""
    if not command:
        return False
    lowered = command.casefold()
    if lowered in {
        "js",
        "node_repl.js",
        "write_stdin",
    } or lowered.startswith(
        (
            "tool:",
            "functions.",
            "mcp__",
        )
    ):
        return True
    if re.fullmatch(
        r"(?:python\d*(?:\.\d+)?|node|npm|pnpm|yarn|git|ruff)"
        r"\s+(?:--version|-v|version)",
        lowered,
    ):
        return True
    if _is_compound_discovery_command(command):
        return True
    return _is_read_only_inspection_command(command)


def _is_tool_selection_statement(statement: str) -> bool:
    return bool(_TOOL_SELECTION_DECISION_RE.search(statement))


def _is_compound_discovery_command(command: str) -> bool:
    lines = [re.sub(r"\s+", " ", line).strip() for line in command.splitlines() if line.strip()]
    if len(lines) >= 2:
        version_probe = re.compile(
            r"(?:which|command\s+-v)\s+[A-Za-z0-9_.+-]+|"
            r"(?:python\d*(?:\.\d+)?|node|npm|pnpm|yarn|git|ruff|pytest)"
            r"\s+(?:--version|-v|version)",
            re.IGNORECASE,
        )
        if all(version_probe.fullmatch(line) for line in lines):
            return True

        heredoc = re.fullmatch(
            r"sqlite3\s+[^\s;&|<>]+\s+<<-?\s*"
            r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
            lines[0],
            re.IGNORECASE,
        )
        sqlite_lines = lines
        if heredoc is not None:
            terminator = heredoc.group(1)
            if len(lines) < 3 or lines[-1] != terminator:
                return False
            sqlite_lines = lines[1:-1]
        if all(_is_read_only_sqlite_probe(line) for line in sqlite_lines):
            return True

    segments = _shell_command_segments(command)
    return bool(
        segments is not None
        and len(segments) >= 2
        and all(_is_read_only_discovery_segment(segment) for segment in segments)
    )


def _shell_command_segments(command: str) -> list[list[str]] | None:
    if (
        not command.strip()
        or "\x00" in command
        or "\n" in command
        or "\r" in command
        or "$(" in command
        or "`" in command
    ):
        return None
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "||", ";", "|"}:
            if not segments[-1]:
                return None
            segments.append([])
            continue
        if token and set(token) <= set(";&|<>"):
            # Redirection, background execution, and malformed compound
            # operators are not safe discovery.
            return None
        segments[-1].append(token)
    if not segments or any(not segment for segment in segments):
        return None
    return segments


def _command_token_references_sensitive_material(value: str) -> bool:
    candidates = [value]
    if "=" in value:
        candidates.append(value.split("=", 1)[1])
    for candidate in candidates:
        normalized = candidate.strip(" \t\"'").replace("\\", "/").rstrip(",;")
        if not normalized:
            continue
        lowered = normalized.casefold()
        basename = lowered.rsplit("/", 1)[-1]
        if (
            basename in _SENSITIVE_COMMAND_PATH_BASENAMES
            or basename.startswith(".env.")
            or basename.startswith(".env-")
            or basename.endswith(_SENSITIVE_COMMAND_PATH_SUFFIXES)
            or ("/proc/" in f"/{lowered.lstrip('/')}" and basename in {"cmdline", "environ"})
            or re.fullmatch(
                r"(?:credentials?|secrets?)(?:\.[a-z0-9_-]+)?",
                basename,
                re.IGNORECASE,
            )
        ):
            return True
    return False


def _segment_references_sensitive_material(segment: list[str]) -> bool:
    return any(_command_token_references_sensitive_material(value) for value in segment)


def _git_subcommand_and_arguments(
    segment: list[str],
) -> tuple[str, list[str]] | None:
    if not segment or Path(segment[0]).name.casefold() != "git":
        return None
    index = 1
    while index < len(segment):
        token = segment[index]
        if token in _GIT_READ_ONLY_GLOBAL_FLAGS:
            index += 1
            continue
        if token == "-C":
            if index + 1 >= len(segment):
                return None
            index += 2
            continue
        if token.startswith("-C") and len(token) > 2:
            index += 1
            continue
        if token.startswith("-"):
            # Git's remaining global options can alter configuration, source
            # values from the environment, or replace the executable path.
            return None
        return token.casefold(), segment[index + 1 :]
    return None


def _is_safe_git_branch_inspection(arguments: list[str]) -> bool:
    safe_exact = {
        "-a",
        "-r",
        "-v",
        "-vv",
        "--all",
        "--color",
        "--list",
        "--no-color",
        "--remotes",
        "--show-current",
        "--verbose",
    }
    safe_value_prefixes = (
        "--abbrev=",
        "--color=",
        "--column=",
        "--contains=",
        "--format=",
        "--list=",
        "--merged=",
        "--no-contains=",
        "--no-merged=",
        "--points-at=",
        "--sort=",
    )
    for argument in arguments:
        if argument in _GIT_MUTATING_BRANCH_FLAGS or any(
            argument.startswith(f"{flag}=")
            for flag in _GIT_MUTATING_BRANCH_FLAGS
            if flag.startswith("--")
        ):
            return False
        if (
            argument in safe_exact
            or argument.startswith(safe_value_prefixes)
            or re.fullmatch(r"-[arv]+", argument)
        ):
            continue
        # A positional branch name creates a branch; unknown switches are
        # rejected rather than guessed to be observational.
        return False
    return True


def _is_safe_git_inspection_segment(segment: list[str]) -> bool:
    parsed = _git_subcommand_and_arguments(segment)
    if parsed is None:
        return False
    subcommand, arguments = parsed
    if subcommand in {"status", "ls-files", "rev-parse"}:
        return True
    if subcommand == "branch":
        return _is_safe_git_branch_inspection(arguments)
    # Raw diffs and history are intentionally omitted from task memory, while
    # all state-changing Git subcommands fail closed.
    return False


def _is_read_only_inspection_segment(segment: list[str]) -> bool:
    if not segment or _segment_references_sensitive_material(segment):
        return False
    executable = Path(segment[0]).name.casefold()
    if executable == "git":
        return _is_safe_git_inspection_segment(segment)
    if executable not in _READ_ONLY_INSPECTION_COMMANDS:
        return False
    arguments = [value.casefold() for value in segment[1:]]
    if executable == "sed" and any(
        argument == "--in-place"
        or argument.startswith("--in-place=")
        or (argument.startswith("-") and not argument.startswith("--") and "i" in argument[1:])
        for argument in arguments
    ):
        return False
    if executable == "find" and any(
        argument == "-delete"
        or argument.startswith("-exec")
        or argument.startswith("-ok")
        or argument.startswith("-fprint")
        or argument == "-fls"
        for argument in arguments
    ):
        return False
    if executable == "rg" and any(
        argument == "--pre" or argument.startswith("--pre=") for argument in arguments
    ):
        return False
    return True


def _is_read_only_discovery_segment(segment: list[str]) -> bool:
    if not segment or _segment_references_sensitive_material(segment):
        return False
    executable = Path(segment[0]).name.casefold()
    arguments = [value.casefold() for value in segment[1:]]
    if executable == "node":
        return _is_safe_package_script_probe(segment)
    if executable.startswith("python"):
        return bool(
            len(arguments) >= 3
            and arguments[:2] == ["-m", "pytest"]
            and "--collect-only" in arguments[2:]
        )
    if executable in {"pytest", "py.test"}:
        return "--collect-only" in arguments
    if executable in {"npm", "pnpm"}:
        return arguments in (["run"], ["pkg", "get", "scripts"])
    if executable == "yarn":
        return arguments == ["run"]
    return _is_read_only_inspection_segment(segment)


def _is_safe_verification_segment(segment: list[str]) -> bool:
    if not segment or _segment_references_sensitive_material(segment):
        return False
    executable = Path(segment[0]).name.casefold()
    arguments = [value.casefold() for value in segment[1:]]
    if any(
        argument in {"--fix", "--write"} or argument.startswith(("--fix=", "--output="))
        for argument in arguments
    ):
        return False
    if executable in {"pytest", "py.test"}:
        return "--collect-only" not in arguments
    if executable.startswith("python"):
        return bool(
            len(arguments) >= 2
            and arguments[:2] == ["-m", "pytest"]
            and "--collect-only" not in arguments[2:]
        )
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        if not arguments:
            return False
        if arguments[0] == "test":
            return True
        if arguments[0] == "run" and len(arguments) >= 2:
            script = arguments[1]
        elif executable in {"pnpm", "yarn", "bun"}:
            script = arguments[0]
        else:
            return False
        return script.split(":", 1)[0] in {
            "build",
            "check",
            "lint",
            "test",
            "typecheck",
        }
    if executable == "ruff":
        if arguments and arguments[0] == "format":
            return "--check" in arguments or "--diff" in arguments
        return not arguments or arguments[0] == "check"
    if executable in {
        "eslint",
        "jest",
        "mypy",
        "pyright",
        "tsc",
        "vitest",
    }:
        return True
    if executable == "cargo":
        return bool(arguments and arguments[0] in {"check", "clippy", "test"})
    if executable == "go":
        return bool(arguments and arguments[0] in {"test", "vet"})
    if executable == "swift":
        return bool(arguments and arguments[0] in {"build", "test"})
    if executable == "dotnet":
        return bool(arguments and arguments[0] in {"build", "test"})
    return False


def _is_useful_verification_command(command: str) -> bool:
    segments = _shell_command_segments(command)
    if segments is None:
        return False
    found_verification = False
    for segment in segments:
        if _is_safe_verification_segment(segment):
            found_verification = True
            continue
        if _is_read_only_discovery_segment(segment):
            continue
        return False
    return found_verification


def _is_safe_package_script_probe(segment: list[str]) -> bool:
    if len(segment) != 3 or segment[1].casefold() not in {"-e", "--eval"}:
        return False
    script = segment[2]
    lowered = script.casefold()
    if "package.json" not in lowered or "scripts" not in lowered:
        return False
    if re.search(
        r"\b(?:child_process|exec|spawn|fork|eval|function|fetch|"
        r"https?|write|append|unlink|rename|mkdir|rmdir|chmod|chown|"
        r"truncate|rm)\b|process\s*\.",
        lowered,
    ):
        return False
    required_modules = re.findall(
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        script,
        re.IGNORECASE,
    )
    return bool(required_modules) and all(
        _is_safe_relative_package_json_path(module) for module in required_modules
    )


def _is_safe_relative_package_json_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if (
        not normalized
        or normalized.startswith(("/", "~"))
        or "\x00" in normalized
        or ":" in normalized
    ):
        return False
    parts = normalized.split("/")
    return bool(parts[-1] == "package.json" and all(part not in {"", ".", ".."} for part in parts))


def _has_definitive_verification_outcome(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    passed = payload.get("passed")
    exit_code = payload.get("exit_code")
    if isinstance(passed, bool):
        return True
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return True
    states = {
        str(item.get("state") or "").strip().casefold(),
        str(payload.get("status") or "").strip().casefold(),
        str(payload.get("state") or "").strip().casefold(),
    }
    return bool(
        states
        & {
            "pass",
            "passed",
            "success",
            "succeeded",
            "fail",
            "failed",
            "failure",
            "error",
        }
    )


def _is_read_only_sqlite_probe(line: str) -> bool:
    candidate = line.strip()
    if candidate.casefold().startswith("sqlite3 "):
        if any(
            token in candidate.casefold()
            for token in (
                "--init",
                "-init",
                ".read",
                ".import",
                ".restore",
                ".dump",
            )
        ):
            return False
        try:
            arguments = shlex.split(candidate)
        except ValueError:
            return False
        if len(arguments) < 3 or arguments[0].casefold() != "sqlite3":
            return False
        candidate = arguments[-1].strip()
    return bool(
        re.match(
            r"^(?:\.schema(?:\s|$)|\.tables(?:\s|$)|select\b)",
            candidate,
            re.IGNORECASE,
        )
        or re.fullmatch(
            r"pragma\s+[A-Za-z0-9_.]+(?:\s*\([^;]*\))?\s*;?",
            candidate,
            re.IGNORECASE,
        )
    )


def _command_observation_key(
    item: dict[str, Any],
) -> tuple[str, str] | None:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    command = re.sub(
        r"\s+",
        " ",
        str(payload.get("command") or "").strip(),
    )
    if not command:
        return None
    cwd = str(payload.get("cwd") or "").strip()
    return cwd, command


def _dedupe_command_observations(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the newest observation for each command/cwd pair."""

    values = list(items)
    seen: set[tuple[str, str] | tuple[str, str, str]] = set()
    retained: list[dict[str, Any]] = []
    for item in reversed(values):
        command_key = _command_observation_key(item)
        key: tuple[str, str] | tuple[str, str, str] = (
            command_key
            if command_key is not None
            else (
                "statement",
                re.sub(
                    r"\W+",
                    " ",
                    str(item.get("statement") or "").casefold(),
                ).strip(),
                str(item.get("truth_state") or ""),
            )
        )
        if key in seen:
            continue
        seen.add(key)
        retained.append(item)
    return list(reversed(retained))


def _dedupe_presentation_items(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = list(items)
    seen: set[str] = set()
    retained: list[dict[str, Any]] = []
    for item in reversed(values):
        key = re.sub(
            r"\W+",
            " ",
            str(item.get("statement") or "").casefold(),
        ).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        retained.append(item)
    return list(reversed(retained))


def _is_read_only_inspection_command(command: str) -> bool:
    segments = _shell_command_segments(command)
    return bool(
        segments is not None
        and all(_is_read_only_inspection_segment(segment) for segment in segments)
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if hasattr(value, "year"):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _first_datetime(*values: Any) -> datetime | None:
    return next((parsed for value in values if (parsed := _parse_datetime(value))), None)


def render_resume_bundle(checkpoint: WorkCheckpoint) -> str:
    data = checkpoint_to_dict(checkpoint)
    sections = _handoff_presentation_sections(data["sections"])
    lines = [
        "# Resume from verified work checkpoint",
        "",
        f"Checkpoint: {data['id']}",
        f"Session: {data['provider']} / {data['session_id']}",
        f"Boundary time: {data['boundary']['occurred_at'] or 'unavailable'}",
        f"Snapshot phase: {data['boundary']['snapshot_phase_label']}",
        f"Boundary state: {data['currentness']['label']}",
        f"Capture status: {data['capture_status']}",
        f"Continuation status: {data['continuation_status']}",
        f"Verification status: {(data['verification'] or {}).get('status', 'not_run')}",
        "",
    ]
    titles = {
        "goal": "Goal",
        "progress": "Progress",
        "decisions": "Decisions",
        "failed_attempts": "Failed attempts",
        "discoveries": "Relevant discoveries",
        "useful_commands": "Useful commands",
        "open_items": "Risks, assumptions, constraints, and open questions",
        "relevant_files": "Relevant files",
        "blockers": "Blockers",
        "verification": "Verification evidence",
        "exact_next_action": "Exact next action",
    }
    for category in CHECKPOINT_CATEGORIES:
        lines.extend([f"## {titles[category]}", ""])
        items = sections[category]
        if not items:
            lines.extend(["- None captured.", ""])
            continue
        for item in items:
            evidence_ids = ", ".join(
                str(entry["locator"].get("provider_event_id") or entry["session_event_id"])
                for entry in item["evidence"]
            )
            lines.append(
                f"- [{item['truth_state']}] {item['statement']} (evidence: {evidence_ids})"
            )
        lines.append("")
    lines.extend(
        [
            "Continue only from the exact next action. Re-check repository freshness before "
            "claiming any item is still true.",
            "",
        ]
    )
    return "\n".join(lines)


async def resolve_session_handoff_request_verbatim(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    access_scope: AccessScope | None = None,
) -> str | None:
    """Resolve the lossless goal, including for historical v5 checkpoints."""

    data = checkpoint_to_dict(checkpoint)
    goals = data["sections"]["goal"]
    goal = goals[0] if goals else {}
    projected_goal_key = goal.get("item_key")
    raw_goal_items = sorted(
        (item for item in checkpoint.items if item.category == "goal"),
        key=lambda item: (item.ordinal, item.id),
    )
    goal_item = next(
        (
            item
            for item in raw_goal_items
            if projected_goal_key and item.item_key == projected_goal_key
        ),
        raw_goal_items[0] if len(raw_goal_items) == 1 else None,
    )
    if goal_item is None:
        return await _nearest_authoritative_session_request(
            session,
            checkpoint,
            boundary_sequence=data["boundary"].get("sequence_number"),
            access_scope=access_scope,
        )
    goal_payload = _json_object(goal_item.payload_json)
    stored_verbatim = goal_payload.get("request_verbatim")
    stored_goal_is_intact_but_non_substantive = False
    if isinstance(stored_verbatim, str) and stored_verbatim.strip():
        expected_sha256 = str(goal_payload.get("request_sha256") or "").strip()
        stored_is_intact = not expected_sha256 or _sha256(stored_verbatim) == expected_sha256
        if stored_is_intact:
            request = _validated_session_request(stored_verbatim)
            if request is not None:
                return request
            stored_goal_is_intact_but_non_substantive = True

    goal_evidence = [
        evidence
        for evidence in goal_item.evidence
        if evidence.supports and evidence.evidence_type == "session_event"
    ]
    evidence_event_ids = {
        evidence.session_event_id
        for evidence in goal_evidence
        if evidence.session_event_id is not None
    }
    evidence_source_ids = {
        evidence.source_document_id
        for evidence in goal_evidence
        if evidence.source_document_id is not None
    }
    reference_predicates = [SessionEvent.id == event_id for event_id in evidence_event_ids]
    for evidence in goal_evidence:
        locator = _json_object(evidence.locator_json)
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if not provider_event_id:
            continue
        predicate = SessionEvent.provider_event_id == provider_event_id
        if evidence.source_document_id is not None:
            predicate = and_(
                predicate,
                SessionEvent.source_document_id == evidence.source_document_id,
            )
        reference_predicates.append(predicate)

    normalized_session = normalize_session_key(checkpoint.provider, checkpoint.session_id) or (
        checkpoint.provider,
        checkpoint.session_id,
    )
    provider, session_id = normalized_session
    boundary_sequence = data["boundary"].get("sequence_number")
    effective_scope = access_scope or AccessScope.local()
    events: list[SessionEvent] = []
    if reference_predicates:
        conditions = [
            or_(*reference_predicates),
            SessionEvent.workspace_id == checkpoint.workspace_id,
            SessionEvent.provider.in_(session_provider_values(provider)),
            SessionEvent.session_id == session_id,
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        ]
        if isinstance(boundary_sequence, int):
            conditions.append(SessionEvent.sequence_number <= boundary_sequence)
        events = list(
            await session.scalars(
                select(SessionEvent)
                .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
                .where(*conditions)
                .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
            )
        )

    recovery_prefixes: set[tuple[str, str]] = set()
    if isinstance(stored_verbatim, str) and (
        not str(goal_payload.get("request_sha256") or "").strip()
        or _sha256(stored_verbatim) == str(goal_payload.get("request_sha256") or "").strip()
    ):
        prefix = _truncated_request_prefix(stored_verbatim)
        if prefix is not None:
            recovery_prefixes.add((prefix, "user_request"))

    for event in events:
        request_verbatim = _checkpoint_request_verbatim(event)
        if request_verbatim:
            request = _validated_session_request(request_verbatim)
            if request is not None:
                return request
        prefix = _truncated_request_prefix(event.content)
        if prefix is not None:
            recovery_prefixes.add((prefix, event.event_type))
        evidence_source_ids.add(event.source_document_id)

    if recovery_prefixes:
        # Historical releases capped normalized events, but the immutable source
        # transcript still contains the complete turn. Search only source revisions
        # attached to this checkpoint/evidence and require an exact, long prefix
        # match. Never select the "latest" turn: the source can include later work.
        source_ids = {*evidence_source_ids, checkpoint.source_document_id}
        source_documents = list(
            await session.scalars(
                select(SourceDocument).where(
                    SourceDocument.id.in_(source_ids),
                    source_access_predicate(
                        effective_scope,
                        workspace_id=checkpoint.workspace_id,
                    ),
                )
            )
        )
        recovered = _recover_truncated_request_from_sources(
            source_documents,
            recovery_prefixes=recovery_prefixes,
        )
        if len(recovered) == 1:
            return next(iter(recovered))

    if stored_goal_is_intact_but_non_substantive:
        # Older compilers could persist acknowledgements such as "done" as the
        # goal itself. Recover the nearest earlier executable request from the
        # same access-checked session instead of making that immutable bad row
        # permanently poison the floating Session Context action. The helper
        # still fails closed at ambiguous/truncated turns.
        return await _nearest_authoritative_session_request(
            session,
            checkpoint,
            boundary_sequence=boundary_sequence,
            access_scope=access_scope,
        )
    return None


async def _nearest_authoritative_session_request(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    boundary_sequence: Any,
    access_scope: AccessScope | None,
) -> str | None:
    """Recover a missing goal only from this session at/before its boundary."""

    if not isinstance(boundary_sequence, int):
        return None
    normalized_session = normalize_session_key(checkpoint.provider, checkpoint.session_id) or (
        checkpoint.provider,
        checkpoint.session_id,
    )
    provider, session_id = normalized_session
    effective_scope = access_scope or AccessScope.local()
    events = list(
        await session.scalars(
            select(SessionEvent)
            .join(
                SourceDocument,
                SessionEvent.source_document_id == SourceDocument.id,
            )
            .where(
                SessionEvent.workspace_id == checkpoint.workspace_id,
                SessionEvent.provider.in_(session_provider_values(provider)),
                SessionEvent.session_id == session_id,
                SessionEvent.sequence_number <= boundary_sequence,
                or_(
                    SessionEvent.event_type == "user_request",
                    and_(
                        SessionEvent.event_type == "runtime_instruction",
                        SessionEvent.role == "user",
                    ),
                ),
                source_access_predicate(
                    effective_scope,
                    workspace_id=checkpoint.workspace_id,
                ),
            )
            .order_by(
                SessionEvent.sequence_number.desc(),
                SessionEvent.id.desc(),
            )
        )
    )
    for event in events:
        raw_request = _checkpoint_request_verbatim(event)
        request = _validated_session_request(raw_request)
        if request is not None:
            return request

        # A recognized historical truncation is the nearest authoritative
        # turn, but it does not authorize silently falling back to older work.
        # Recover it from that event's access-checked source revision or fail
        # closed when the prefix is ambiguous/unavailable.
        if _truncated_request_prefix(event.content) is not None:
            source = await session.get(SourceDocument, event.source_document_id)
            if source is None:
                return None
            recognized, recovered = recover_truncated_session_request_from_source(
                source,
                event_content=event.content,
                event_type=event.event_type,
            )
            if recognized:
                return _validated_session_request(recovered)
    return None


async def resolve_session_handoff_supporting_context(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    access_scope: AccessScope | None = None,
) -> list[dict[str, str]]:
    """Materialize referenced conversation context when the goal depends on it.

    A self-contained request needs no historical background. When the request
    explicitly points at a previous prompt or a ChatGPT conversation, carry the
    relevant embedded turns into the checkpoint handoff instead of leaving the
    receiving harness dependent on an app-specific link.
    """

    if not _request_requires_materialized_context(request_verbatim):
        return []

    data = checkpoint_to_dict(checkpoint)
    goals = data["sections"]["goal"]
    projected_goal_key = goals[0].get("item_key") if goals else None
    raw_goal_items = sorted(
        (item for item in checkpoint.items if item.category == "goal"),
        key=lambda item: (item.ordinal, item.id),
    )
    goal_item = next(
        (
            item
            for item in raw_goal_items
            if projected_goal_key and item.item_key == projected_goal_key
        ),
        raw_goal_items[0] if len(raw_goal_items) == 1 else None,
    )
    if goal_item is None:
        return []

    goal_payload = _json_object(goal_item.payload_json)
    stored = _normalize_supporting_context(goal_payload.get("supporting_context"))
    expected_sha256 = str(goal_payload.get("supporting_context_sha256") or "").strip()
    if stored and (not expected_sha256 or _sha256(_canonical_json(stored)) == expected_sha256):
        return stored

    effective_scope = access_scope or AccessScope.local()
    normalized_session = normalize_session_key(checkpoint.provider, checkpoint.session_id) or (
        checkpoint.provider,
        checkpoint.session_id,
    )
    provider, session_id = normalized_session
    boundary_sequence = data["boundary"].get("sequence_number")
    event_ids = {
        evidence.session_event_id
        for evidence in goal_item.evidence
        if evidence.supports and evidence.session_event_id is not None
    }
    reference_predicates = [SessionEvent.id == event_id for event_id in event_ids]
    for evidence in goal_item.evidence:
        if not evidence.supports:
            continue
        locator = _json_object(evidence.locator_json)
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if provider_event_id:
            reference_predicates.append(SessionEvent.provider_event_id == provider_event_id)
    conditions = [
        SessionEvent.workspace_id == checkpoint.workspace_id,
        SessionEvent.provider.in_(session_provider_values(provider)),
        SessionEvent.session_id == session_id,
        source_access_predicate(
            effective_scope,
            workspace_id=checkpoint.workspace_id,
        ),
    ]
    if reference_predicates:
        conditions.append(
            or_(*reference_predicates),
        )
    if isinstance(boundary_sequence, int):
        conditions.append(SessionEvent.sequence_number <= boundary_sequence)
    events = list(
        await session.scalars(
            select(SessionEvent)
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(*conditions)
            .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
        )
    )
    candidates: dict[str, list[dict[str, str]]] = {}
    for event in events:
        materialized = _materialized_referenced_context(
            event.content,
            request_verbatim=request_verbatim,
        )
        if materialized:
            candidates[_canonical_json(materialized)] = materialized

    source_ids = {
        checkpoint.source_document_id,
        *(
            evidence.source_document_id
            for evidence in goal_item.evidence
            if evidence.supports and evidence.source_document_id is not None
        ),
    }
    sources = list(
        await session.scalars(
            select(SourceDocument).where(
                SourceDocument.id.in_(source_ids),
                source_access_predicate(
                    effective_scope,
                    workspace_id=checkpoint.workspace_id,
                ),
            )
        )
    )
    for source in sources:
        materialized = _materialized_referenced_context(
            source.content,
            request_verbatim=request_verbatim,
        )
        if materialized:
            candidates[_canonical_json(materialized)] = materialized
    external_dependency = bool(_EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim))
    if not external_dependency:
        goal_sequences = [
            value
            for evidence in goal_item.evidence
            if evidence.supports
            for value in [_json_object(evidence.locator_json).get("sequence_number")]
            if isinstance(value, int)
        ]
        goal_sequence = max(goal_sequences) if goal_sequences else None
        if goal_sequence is not None:
            prior_events = list(
                await session.scalars(
                    select(SessionEvent)
                    .join(
                        SourceDocument,
                        SessionEvent.source_document_id == SourceDocument.id,
                    )
                    .where(
                        SessionEvent.workspace_id == checkpoint.workspace_id,
                        SessionEvent.provider.in_(session_provider_values(provider)),
                        SessionEvent.session_id == session_id,
                        SessionEvent.sequence_number < goal_sequence,
                        SessionEvent.event_type.in_(
                            (
                                "user_request",
                                "assistant_update",
                            )
                        ),
                        source_access_predicate(
                            effective_scope,
                            workspace_id=checkpoint.workspace_id,
                        ),
                    )
                    .order_by(
                        SessionEvent.sequence_number.desc(),
                        SessionEvent.id.desc(),
                    )
                    .limit(12)
                )
            )
            materialized = _materialized_prior_session_context(prior_events)
            if materialized:
                candidates[_canonical_json(materialized)] = materialized
    return next(iter(candidates.values())) if len(candidates) == 1 else []


def _validated_session_request(value: str | None) -> str | None:
    request = extract_user_authored_request(value)
    if request is None or not is_substantive_user_request(request):
        return None
    return request


def _truncated_request_prefix(value: str | None) -> str | None:
    text = str(value or "")
    for suffix in _TRUNCATED_OUTPUT_SUFFIXES:
        if not text.endswith(suffix):
            continue
        prefix = text[: -len(suffix)] if suffix else text
        if len(prefix) >= _MIN_RECOVERY_PREFIX_CHARS:
            return prefix
    return None


def recover_truncated_session_request_from_source(
    source_document: SourceDocument,
    *,
    event_content: str | None,
    event_type: str,
) -> tuple[bool, str | None]:
    """Recover one historical truncated request from its exact source revision.

    The boolean distinguishes ordinary event content from a recognized
    historical truncation. A recognized truncation with no unique exact-prefix
    match must fail closed instead of allowing callers to select older work.
    """

    prefix = _truncated_request_prefix(event_content)
    if prefix is None:
        return False, None
    recovered = _recover_truncated_request_from_sources(
        (source_document,),
        recovery_prefixes={(prefix, event_type)},
    )
    if len(recovered) != 1:
        return True, None
    return True, next(iter(recovered))


def _recover_truncated_request_from_sources(
    source_documents: Iterable[SourceDocument],
    *,
    recovery_prefixes: set[tuple[str, str]],
) -> set[str]:
    recovered: set[str] = set()
    for source_document in source_documents:
        turns = [
            match.group(1).rstrip("\r\n")
            for match in _SESSION_USER_TURN_RE.finditer(source_document.content or "")
        ]
        for turn in turns:
            for prefix, event_type in recovery_prefixes:
                if not turn.startswith(prefix):
                    continue
                request = (
                    extract_delegated_user_request(turn)
                    if event_type == "runtime_instruction"
                    else extract_user_authored_request(turn)
                )
                if request is not None and is_substantive_user_request(request):
                    recovered.add(request)
    return recovered


def _request_requires_materialized_context(request_verbatim: str) -> bool:
    return bool(
        _EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
        or _DEICTIC_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
    )


def _continuation_lead_requires_unbound_evidence(
    request_verbatim: str,
) -> bool:
    """Return whether a fresh lead needs evidence not bound to its user turn."""

    return bool(
        _request_requires_materialized_context(request_verbatim)
        or _SESSION_IMAGE_TAG_RE.search(request_verbatim)
        or _CONTINUATION_LEAD_ATTACHMENT_DEPENDENCY_RE.search(request_verbatim)
        or _CONTINUATION_LEAD_DEICTIC_VISUAL_RE.search(request_verbatim)
    )


def session_request_requires_materialized_context(request_verbatim: str) -> bool:
    """Return whether a portable handoff must embed referenced session material."""

    return _request_requires_materialized_context(request_verbatim)


def _request_accepts_materialized_reference(request_verbatim: str) -> bool:
    if _NEGATED_REFERENCE_ADOPTION_RE.search(request_verbatim):
        return False
    return bool(_POSITIVE_REFERENCE_ADOPTION_RE.search(request_verbatim))


def _materialized_referenced_context(
    value: str | None,
    *,
    request_verbatim: str | None,
) -> list[dict[str, str]]:
    """Extract the final relevant turns from an embedded ChatGPT export."""

    if not request_verbatim or not _request_requires_materialized_context(request_verbatim):
        return []
    text = str(value or "")
    marker = _REFERENCED_CONVERSATION_MARKER_RE.search(text)
    if marker is None:
        return []
    request_marker = _CURRENT_CODEX_REQUEST_MARKER_RE.search(text, marker.end())
    payload_region = text[marker.end() : request_marker.start() if request_marker else None]
    parsed: dict[str, Any] | None = None
    decoder = json.JSONDecoder()
    requested_conversation_ids = set(_CHATGPT_CONVERSATION_ID_RE.findall(request_verbatim))
    if (
        _EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
        and not requested_conversation_ids
    ):
        # Never bind an unqualified external reference to the first embedded
        # conversation found in a larger source document.
        return []
    for candidate in re.finditer(r"\{", payload_region):
        try:
            value, _ = decoder.raw_decode(payload_region[candidate.start() :])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("conversation"), list):
            continue
        embedded_conversation_id = str(value.get("conversationId") or "").strip()
        if (
            requested_conversation_ids
            and embedded_conversation_id not in requested_conversation_ids
        ):
            continue
        if embedded_conversation_id or not requested_conversation_ids:
            parsed = value
            break
    if parsed is None:
        return []

    turns: list[dict[str, str]] = []
    for raw_turn in parsed.get("conversation") or []:
        if not isinstance(raw_turn, dict):
            continue
        role = str(raw_turn.get("role") or "").strip().lower()
        if role not in {"assistant", "user"}:
            continue
        turn_text = _conversation_turn_text(raw_turn.get("content"))
        if not turn_text:
            continue
        turns.append(
            {
                "role": role,
                "text": turn_text,
                "source": "embedded_referenced_conversation",
                "truth_state": "historical_data",
            }
        )
    if not turns:
        return []

    final_assistant_index = next(
        (index for index in range(len(turns) - 1, -1, -1) if turns[index]["role"] == "assistant"),
        len(turns) - 1,
    )
    selected = [turns[final_assistant_index]]
    preceding_user = next(
        (
            turns[index]
            for index in range(final_assistant_index - 1, -1, -1)
            if turns[index]["role"] == "user"
        ),
        None,
    )
    if preceding_user is not None:
        selected.insert(0, preceding_user)
    return selected


def _conversation_turn_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            candidate = item.get("text")
            if not isinstance(candidate, str):
                candidate = item.get("content")
            if isinstance(candidate, str):
                parts.append(candidate)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(value, dict):
        candidate = value.get("text")
        if not isinstance(candidate, str):
            candidate = value.get("content")
        return str(candidate or "").strip()
    return ""


def _materialized_prior_session_context(
    events: Iterable[SessionEvent],
) -> list[dict[str, str]]:
    ordered = sorted(events, key=lambda item: (item.sequence_number, item.id))
    final_assistant_index = next(
        (
            index
            for index in range(len(ordered) - 1, -1, -1)
            if ordered[index].event_type == "assistant_update"
            and str(ordered[index].content or "").strip()
        ),
        None,
    )
    if final_assistant_index is None:
        return []
    selected = [ordered[final_assistant_index]]
    preceding_user = next(
        (
            ordered[index]
            for index in range(final_assistant_index - 1, -1, -1)
            if ordered[index].event_type == "user_request"
            and extract_user_authored_request(ordered[index].content)
        ),
        None,
    )
    if preceding_user is not None:
        selected.insert(0, preceding_user)
    result: list[dict[str, str]] = []
    for event in selected:
        role = "user" if event.event_type == "user_request" else "assistant"
        text = (
            extract_user_authored_request(event.content)
            if role == "user"
            else str(event.content or "").strip()
        )
        if not text:
            continue
        result.append(
            {
                "role": role,
                "text": text,
                "source": "prior_session_turn",
                "truth_state": "historical_data",
            }
        )
    return result


def _normalize_supporting_context(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            return []
        role = str(raw.get("role") or "").strip().lower()
        text = str(raw.get("text") or "").strip()
        source = str(raw.get("source") or "").strip()
        if role not in {"assistant", "user"} or not text:
            return []
        if source not in {
            "embedded_referenced_conversation",
            "prior_session_turn",
        }:
            return []
        result.append(
            {
                "role": role,
                "text": text,
                "source": source,
                "truth_state": "historical_data",
            }
        )
    return result


def _self_contained_goal(request_verbatim: str) -> str:
    without_links = _CHATGPT_MARKDOWN_LINK_RE.sub(
        lambda match: f"{match.group(1)} (materialized below)",
        request_verbatim,
    )
    return re.sub(
        r"[ \t]+\n",
        "\n",
        _SESSION_IMAGE_TAG_RE.sub(" ", without_links),
    ).strip()


def _session_attachment_dependency_role(request_verbatim: str) -> str:
    """Classify whether the next agent still needs the visual itself."""

    goal_without_markup = _self_contained_goal(request_verbatim)
    words = re.findall(r"[a-z0-9]+", goal_without_markup.casefold())
    if _SESSION_ATTACHMENT_EXACT_DEPENDENCY_RE.search(goal_without_markup):
        return "active_input"
    if len(words) <= 30 and _SESSION_ATTACHMENT_VISUAL_DEPENDENCY_RE.search(goal_without_markup):
        return "active_input"
    if len(words) <= 16 and _REQUIREMENT_ACTION_RE.search(goal_without_markup):
        # Short deictic requests such as "fix this" do not contain enough
        # durable text to replace the visual input.
        return "active_input"
    return "historical_evidence"


def _session_attachment_request_fragment(
    request_verbatim: str,
    *,
    attachment_offset: int,
) -> str:
    """Return the root/follow-up fragment that declared one attachment."""

    value = str(request_verbatim or "")
    start = 0
    end = len(value)
    for heading in _SESSION_COMPOSITE_REQUEST_HEADING_RE.finditer(value):
        if heading.start() <= attachment_offset:
            start = heading.end()
            continue
        end = heading.start()
        break
    return value[start:end].strip()


def _session_attachment_dependencies(
    request_verbatim: str,
    *,
    trusted_descriptors: Iterable[TrustedRequestImageDescriptor] = (),
    allow_local_files: bool = False,
) -> list[dict[str, Any]]:
    """Describe exact-turn images without treating request markup as authority."""

    fragment_roles = [
        _session_attachment_dependency_role(fragment)
        for fragment in _SESSION_COMPOSITE_REQUEST_HEADING_RE.split(str(request_verbatim or ""))
        if fragment.strip()
    ]
    fallback_dependency_role = (
        "active_input" if "active_input" in fragment_roles else "historical_evidence"
    )
    descriptor_values = tuple(trusted_descriptors)
    descriptors_by_path = {
        descriptor.path: descriptor for descriptor in descriptor_values if descriptor.path
    }
    declarations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    request_tag_paths: set[str] = set()
    for match in _SESSION_IMAGE_TAG_RE.finditer(str(request_verbatim or "")):
        attributes_text = (
            match.group("attributes")
            if match.group("attributes") is not None
            else match.group("self_closing_attributes") or ""
        )
        attributes: dict[str, str] = {}
        for attribute in _SESSION_IMAGE_ATTRIBUTE_RE.finditer(attributes_text):
            key = attribute.group(1).casefold()
            value = next(
                (group for group in attribute.groups()[1:] if group is not None),
                "",
            ).strip()
            attributes[key] = value
        for attribute in _SESSION_IMAGE_BRACKET_ATTRIBUTE_RE.finditer(attributes_text):
            attributes[attribute.group(1).casefold()] = attribute.group(2).strip()
        path = str(attributes.get("path") or attributes.get("src") or "").strip()
        name = str(
            attributes.get("name") or attributes.get("alt") or f"Image {len(declarations) + 1}"
        ).strip()
        identity = (path, name)
        if identity in seen:
            continue
        seen.add(identity)
        if path:
            request_tag_paths.add(path)
        declarations.append(
            {
                "name": name,
                "path": path or None,
                "source": "user_request_attachment_markup",
                "declaration_sha256": _sha256(match.group(0)),
                "dependency_role": _session_attachment_dependency_role(
                    _session_attachment_request_fragment(
                        request_verbatim,
                        attachment_offset=match.start(),
                    )
                ),
            }
        )

    declared_paths = {str(item.get("path") or "") for item in declarations if item.get("path")}
    for descriptor in descriptor_values:
        if not descriptor.path or descriptor.path in declared_paths:
            continue
        declarations.append(
            {
                "name": f"[Image #{len(declarations) + 1}]",
                "path": descriptor.path,
                "source": "structured_provider_attachment",
                "declaration_sha256": None,
                "dependency_role": fallback_dependency_role,
            }
        )
        declared_paths.add(descriptor.path)

    resolver_request = str(request_verbatim or "")
    synthetic_tags = [
        tag
        for path in descriptors_by_path
        if path not in request_tag_paths
        if (tag := _trusted_image_resolver_tag(path)) is not None
    ]
    if synthetic_tags:
        resolver_request = "\n".join((resolver_request, *synthetic_tags))
    resolved = resolve_trusted_request_image_artifacts(
        resolver_request,
        trusted_descriptors=descriptor_values,
        allow_local_files=allow_local_files,
    )
    artifacts_by_path: dict[str, ArtifactReference] = {}
    for artifact in resolved:
        artifacts_by_path[artifact.path] = artifact
        if artifact.source_path:
            artifacts_by_path[artifact.source_path] = artifact

    dependencies: list[dict[str, Any]] = []
    for declaration in declarations:
        attachment_id = f"A{len(dependencies) + 1}"
        dependency_role = str(declaration.get("dependency_role") or fallback_dependency_role)
        path = str(declaration.get("path") or "")
        artifact = artifacts_by_path.get(path)
        descriptor = descriptors_by_path.get(path)
        trusted = path in descriptors_by_path
        available = bool(artifact and artifact.available and artifact.sha256)
        visual_inspection = (
            validated_trusted_image_inspection(descriptor)
            if descriptor is not None and available
            else None
        )
        resolution = (
            "hash_verified_exact_provider_attachment"
            if available
            else "trusted_provider_attachment_unavailable"
            if trusted
            else "trusted_attachment_descriptor_required"
        )
        resolved_path = artifact.path if available and artifact is not None else path or None
        captured_path = artifact.path if available and artifact is not None else None
        dependencies.append(
            {
                "id": attachment_id,
                "kind": "image",
                "name": declaration["name"],
                "path": resolved_path,
                "captured_path": captured_path,
                "source_path": (
                    path if resolved_path is not None and resolved_path != path else None
                ),
                "portable_reference": f"handoff://attachments/{attachment_id}",
                "required": dependency_role == "active_input",
                "dependency_role": dependency_role,
                "available": available,
                "available_at_capture": available,
                "sha256": artifact.sha256 if artifact else None,
                "content_hash": artifact.sha256 if artifact else None,
                "mime_type": artifact.mime_type if artifact else None,
                "media_type": artifact.mime_type if artifact else None,
                "source": ("exact_provider_event" if trusted else declaration["source"]),
                "resolution": resolution,
                "capture_status": "hash_verified" if available else "not_captured",
                "integrity_status": (
                    "available_and_verified" if available else "missing_or_corrupted"
                ),
                "integrity_verification_owner": "infrastructure",
                "materialization_owner": "infrastructure",
                "delivery_policy": "runtime_bundle_hash_verified",
                "receiver_availability": "unknown",
                "inspection_status": (
                    "inspected"
                    if visual_inspection is not None
                    else "not_inspected_for_target_resolution"
                    if dependency_role == "active_input" and available
                    else "unavailable_at_capture"
                    if dependency_role == "active_input"
                    else "historical_evidence_only"
                ),
                "unavailable_reason": (
                    artifact.visual_summary if artifact is not None and not available else None
                ),
                "declaration_sha256": declaration["declaration_sha256"],
                "requirement_ids": [],
                "visual_inspection": visual_inspection,
                "visual_anchors": [
                    str(item.get("text") or "")
                    for item in (visual_inspection or {}).get("anchors") or []
                    if str(item.get("text") or "").strip()
                ],
                "suspected_surface": (visual_inspection or {}).get("suspected_surface"),
                "candidate_route": (visual_inspection or {}).get("candidate_route"),
                "visual_candidate_files": list(
                    (visual_inspection or {}).get("candidate_files") or []
                ),
            }
        )
    return dependencies


def _apply_session_attachment_receiver_deliveries(
    attachments: list[dict[str, Any]],
    deliveries: dict[str, dict[str, str]],
) -> None:
    """Overlay receiver-owned copies without changing capture provenance."""

    for attachment in attachments:
        attachment_id = str(attachment.get("id") or "")
        delivery = deliveries.get(attachment_id)
        if delivery is None:
            continue
        expected_sha256 = str(attachment.get("content_hash") or attachment.get("sha256") or "")
        expected_media_type = str(
            attachment.get("media_type") or attachment.get("mime_type") or ""
        ).casefold()
        receiver_reference = str(delivery.get("receiver_local_reference") or "").strip()
        if (
            not receiver_reference
            or not Path(receiver_reference).is_absolute()
            or str(delivery.get("sha256") or "").casefold() != expected_sha256.casefold()
            or str(delivery.get("media_type") or "").casefold() != expected_media_type
        ):
            raise ValueError(
                f"Receiver delivery for attachment {attachment_id or 'unknown'} "
                "does not match its captured content identity."
            )
        attachment.update(
            {
                "receiver_availability": "available",
                "receiver_local_reference": receiver_reference,
                "receiver_integrity_status": "available_and_verified",
                "receiver_content_hash": expected_sha256,
            }
        )


def _apply_repository_baseline_receiver_delivery(
    repository: dict[str, Any],
    delivery: dict[str, str] | None,
) -> None:
    """Overlay a receiver-local exact baseline without changing provenance."""

    if delivery is None:
        return
    manifest = repository.get("protected_baseline_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("Protected baseline manifest is unavailable.")
    expected_sha256 = str(manifest.get("manifest_sha256") or "").casefold()
    expected_reference = str(manifest.get("portable_reference") or "")
    receiver_reference = str(delivery.get("receiver_local_reference") or "").strip()
    if (
        manifest.get("complete") is not True
        or manifest.get("integrity_valid") is not True
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or not receiver_reference
        or not Path(receiver_reference).is_absolute()
        or str(delivery.get("portable_reference") or "") != expected_reference
        or str(delivery.get("manifest_sha256") or "").casefold() != expected_sha256
    ):
        raise ValueError("Receiver delivery does not match the exact protected baseline identity.")
    manifest.update(
        {
            "receiver_availability": "available",
            "receiver_local_reference": receiver_reference,
            "receiver_integrity_status": "available_and_verified",
            "receiver_manifest_sha256": expected_sha256,
        }
    )


def _link_session_attachments_to_requirements(
    attachments: list[dict[str, Any]],
    *,
    requirements: list[dict[str, Any]],
) -> None:
    """Link active evidence to user outcomes without inventing requirements.

    Inspecting an attachment is an evidence prerequisite, not a separate user
    outcome.  Keeping that distinction prevents a one-requirement visual task
    from turning into a generic multi-requirement goal.
    """

    outcomes = [
        requirement
        for requirement in requirements
        if str(requirement.get("id") or "")
        and not requirement.get("explicit_acceptance")
        and requirement.get("completion_relevant") is not False
    ]
    visual_outcomes = [
        requirement
        for requirement in outcomes
        if re.search(
            r"\b(?:attachment|image|screenshot|mockup|wireframe|visual|photo|picture|reference)\b",
            str(requirement.get("text") or ""),
            flags=re.IGNORECASE,
        )
    ]
    linked_ids = (
        [str(outcomes[0]["id"])]
        if len(outcomes) == 1
        else [str(visual_outcomes[0]["id"])]
        if len(visual_outcomes) == 1
        else []
    )
    for attachment in attachments:
        attachment["requirement_ids"] = (
            list(linked_ids) if attachment.get("required") is True else []
        )


def _trusted_image_resolver_tag(path: str) -> str | None:
    """Create internal-only resolver markup for structured provider images."""

    if "<" in path or ">" in path:
        return None
    if '"' not in path:
        return f'<image path="{path}"></image>'
    if "'" not in path:
        return f"<image path='{path}'></image>"
    return None


def resolve_handoff_attachment_reference(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    portable_reference: str,
    expected_sha256: str,
    expected_media_type: str,
    access_scope: AccessScope,
) -> ArtifactReference:
    """Resolve one contract-local handoff URI through checkpoint-bound bytes."""

    if access_scope.principal_id != "local":
        raise ValueError("handoff attachments require local workspace access")
    match = re.fullmatch(r"handoff://attachments/A([1-9][0-9]*)", portable_reference)
    if match is None:
        raise ValueError("invalid handoff attachment reference")
    checkpoint_bound, descriptors = _checkpoint_bound_image_descriptors(
        checkpoint,
        request_verbatim=request_verbatim,
    )
    if not checkpoint_bound:
        raise ValueError("handoff attachment is not bound to this checkpoint")
    expected_digest = str(expected_sha256 or "").casefold()
    expected_mime = str(expected_media_type or "").casefold()
    dependency = next(
        (
            item
            for item in _session_attachment_dependencies(
                request_verbatim,
                trusted_descriptors=descriptors,
                allow_local_files=True,
            )
            if item.get("portable_reference") == portable_reference
        ),
        None,
    )
    if (
        dependency is None
        or str(dependency.get("sha256") or "").casefold() != expected_digest
        or str(dependency.get("mime_type") or "").casefold() != expected_mime
        or dependency.get("available") is not True
    ):
        raise ValueError("handoff attachment metadata does not match the checkpoint")
    descriptor = next(
        (
            item
            for item in descriptors
            if item.sha256 is not None
            and item.sha256.casefold() == expected_digest
            and item.mime_type is not None
            and item.mime_type.casefold() == expected_mime
            and item.resolved_path
            and item.binding_valid
        ),
        None,
    )
    if descriptor is None:
        raise ValueError("handoff attachment metadata does not match the checkpoint")
    tag = _trusted_image_resolver_tag(descriptor.path)
    if tag is None:
        raise ValueError("handoff attachment path cannot be safely resolved")
    resolved = resolve_trusted_request_image_artifacts(
        tag,
        trusted_descriptors=(descriptor,),
        allow_local_files=True,
    )
    if (
        len(resolved) != 1
        or resolved[0].available is not True
        or resolved[0].sha256 != expected_digest
        or str(resolved[0].mime_type or "").casefold() != expected_mime
    ):
        raise ValueError("handoff attachment is missing or corrupted")
    return resolved[0]


async def resolve_session_handoff_attachment_descriptors(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    access_scope: AccessScope | None = None,
) -> tuple[TrustedRequestImageDescriptor, ...]:
    """Resolve images only from the exact authoritative local provider turn.

    Request markup is never filesystem authority. New imports retain structured
    provider attachment metadata on the normalized user event. For legacy Codex
    imports, recover the same metadata from a bounded window of the immutable
    raw rollout only when both provider records match this exact request.
    """

    if access_scope is None or access_scope.principal_id != "local":
        return ()
    checkpoint_bound, checkpoint_descriptors = _checkpoint_bound_image_descriptors(
        checkpoint,
        request_verbatim=request_verbatim,
    )
    if checkpoint_bound:
        return checkpoint_descriptors
    effective_scope = access_scope
    data = checkpoint_to_dict(checkpoint)
    boundary_sequence = data["boundary"].get("sequence_number")
    if not isinstance(boundary_sequence, int):
        return ()
    normalized_session = normalize_session_key(checkpoint.provider, checkpoint.session_id) or (
        checkpoint.provider,
        checkpoint.session_id,
    )
    provider, session_id = normalized_session
    expected_request = " ".join(str(request_verbatim or "").split())
    if not expected_request:
        return ()
    events = list(
        await session.scalars(
            select(SessionEvent)
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(
                SessionEvent.workspace_id == checkpoint.workspace_id,
                SessionEvent.provider.in_(session_provider_values(provider)),
                SessionEvent.session_id == session_id,
                SessionEvent.sequence_number <= boundary_sequence,
                or_(
                    SessionEvent.event_type == "user_request",
                    and_(
                        SessionEvent.event_type == "runtime_instruction",
                        SessionEvent.role == "user",
                    ),
                ),
                source_access_predicate(
                    effective_scope,
                    workspace_id=checkpoint.workspace_id,
                ),
            )
            .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
        )
    )
    for event in events:
        candidate = _checkpoint_request_verbatim(event)
        candidate_request = _validated_session_request(candidate)
        exact_match = (
            candidate_request is not None
            and " ".join(candidate_request.split()) == expected_request
        )
        prefix = _truncated_request_prefix(event.content)
        prefix_match = bool(prefix and str(request_verbatim).startswith(prefix))
        if not exact_match and not prefix_match:
            continue

        descriptors = trusted_request_image_descriptors_from_payload(event_payload(event))
        if descriptors and all(
            descriptor.resolved_path or not descriptor.binding_valid for descriptor in descriptors
        ):
            return tuple(
                materialize_trusted_request_image_descriptor(
                    descriptor,
                    data_dir=settings.data_dir,
                )
                for descriptor in descriptors
            )
        if provider != "codex":
            return tuple(
                materialize_trusted_request_image_descriptor(
                    descriptor,
                    data_dir=settings.data_dir,
                )
                for descriptor in descriptors
            )

        source = await session.get(SourceDocument, event.source_document_id)
        metadata = _json_object(source.metadata_json if source else None)
        source_path = str(metadata.get("source_path") or "").strip()
        if not source_path:
            return ()
        configured_root = (
            Path(settings.codex_home).expanduser()
            if settings.codex_home
            else Path.home() / ".codex"
        )
        recovered = recover_codex_request_image_descriptors(
            source_path=source_path,
            source_sequence_number=event.sequence_number,
            request_verbatim=request_verbatim,
            codex_sessions_root=configured_root / "sessions",
            artifact_data_dir=settings.data_dir,
        )
        if recovered and (not descriptors or _same_descriptor_binding(descriptors, recovered)):
            return recovered
        return tuple(
            materialize_trusted_request_image_descriptor(
                descriptor,
                data_dir=settings.data_dir,
            )
            for descriptor in descriptors
        )
    return ()


def _checkpoint_bound_image_descriptors(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
) -> tuple[bool, tuple[TrustedRequestImageDescriptor, ...]]:
    """Read only integrity-checked descriptors frozen into current checkpoints."""

    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        return False, ()
    raw_payload = str(checkpoint.payload_json or "")
    if (
        not raw_payload
        or not checkpoint.payload_sha256
        or _sha256(raw_payload) != checkpoint.payload_sha256
    ):
        return True, ()
    payload = _json_object(raw_payload)
    sections = payload.get("sections")
    goals = sections.get("goal") if isinstance(sections, dict) else None
    if not isinstance(goals, list) or len(goals) != 1:
        return True, ()
    goal_payload = goals[0].get("payload")
    if not isinstance(goal_payload, dict):
        return True, ()
    if str(goal_payload.get("request_sha256") or "") != _sha256(request_verbatim):
        return True, ()
    raw_descriptors = goal_payload.get("trusted_image_descriptors")
    expected_digest = str(goal_payload.get("trusted_image_descriptors_sha256") or "")
    if (
        not isinstance(raw_descriptors, list)
        or not expected_digest
        or _sha256(_canonical_json(raw_descriptors)) != expected_digest
    ):
        return True, ()
    descriptors: list[TrustedRequestImageDescriptor] = []
    for raw in raw_descriptors:
        if not isinstance(raw, dict):
            return True, ()
        path = str(raw.get("path") or "").strip()
        if not path:
            return True, ()
        ordinal = raw.get("ordinal")
        size_bytes = raw.get("size_bytes")
        descriptors.append(
            TrustedRequestImageDescriptor(
                path=path,
                sha256=str(raw.get("sha256") or "").strip() or None,
                mime_type=str(raw.get("mime_type") or "").strip() or None,
                resolved_path=(
                    str(raw.get("resolved_path") or raw.get("stored_path") or "").strip() or None
                ),
                ordinal=(
                    ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) else None
                ),
                size_bytes=(
                    size_bytes
                    if isinstance(size_bytes, int) and not isinstance(size_bytes, bool)
                    else None
                ),
                binding_valid=raw.get("binding_valid") is not False,
                binding_error=(str(raw.get("binding_error") or "").strip() or None),
                visual_inspection=(
                    raw.get("visual_inspection")
                    if isinstance(raw.get("visual_inspection"), dict)
                    else None
                ),
                visual_inspection_attested=raw.get("visual_inspection_attested") is True,
            )
        )
    return True, tuple(descriptors)


def _derive_session_requirements(
    request_verbatim: str,
    *,
    supporting_context: Iterable[dict[str, str]] = (),
    allow_fallback: bool = True,
) -> list[dict[str, Any]]:
    candidates = _requirement_candidates(
        _self_contained_goal(request_verbatim),
        source="user_request",
        authority="user_authored",
    )
    if _request_accepts_materialized_reference(
        request_verbatim
    ) and _request_requires_materialized_context(request_verbatim):
        for item in supporting_context:
            if str(item.get("role") or "") != "assistant":
                continue
            candidates.extend(
                _requirement_candidates(
                    str(item.get("text") or ""),
                    source="materialized_reference",
                    authority="accepted_by_user_reference",
                )
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = re.sub(r"\s+", " ", str(candidate["text"])).strip()
        key = re.sub(r"\W+", " ", text.casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        explicit_acceptance = bool(candidate.get("explicit_acceptance"))
        execution_guidance = not explicit_acceptance and is_non_verifiable_execution_guidance(text)
        deduped.append(
            {
                "id": f"R{len(deduped) + 1}",
                "text": text,
                "source": candidate["source"],
                "authority": candidate["authority"],
                "source_heading": candidate.get("source_heading"),
                "explicit_acceptance": explicit_acceptance,
                "kind": ("execution_guidance" if execution_guidance else "requirement"),
                "completion_relevant": not execution_guidance,
            }
        )
    if deduped:
        return deduped
    if not allow_fallback:
        return []
    fallback_text = re.sub(
        r"\s+",
        " ",
        _self_contained_goal(request_verbatim),
    ).strip()
    execution_guidance = is_non_verifiable_execution_guidance(fallback_text)
    return [
        {
            "id": "R1",
            "text": fallback_text,
            "source": "user_request",
            "authority": "user_authored",
            "source_heading": None,
            "explicit_acceptance": False,
            "kind": ("execution_guidance" if execution_guidance else "requirement"),
            "completion_relevant": not execution_guidance,
        }
    ]


def _derive_session_requirements_from_fragments(
    request_verbatim: str,
    *,
    request_fragments: Iterable[str] = (),
    supporting_context: Iterable[dict[str, str]] = (),
) -> list[dict[str, Any]]:
    """Keep requirements from separate user turns separate in the handoff."""

    fragments = [str(fragment) for fragment in request_fragments if str(fragment).strip()]
    if len(fragments) <= 1:
        return _derive_session_requirements(
            request_verbatim,
            supporting_context=supporting_context,
        )

    normalized_supporting = list(supporting_context)
    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fragment in fragments:
        for requirement in _derive_session_requirements(
            fragment,
            supporting_context=normalized_supporting,
            allow_fallback=False,
        ):
            text = re.sub(r"\s+", " ", str(requirement.get("text") or "")).strip()
            key = re.sub(r"\W+", " ", text.casefold()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            requirements.append(
                {
                    **requirement,
                    "id": f"R{len(requirements) + 1}",
                    "text": text,
                }
            )
    return requirements or _derive_session_requirements(
        request_verbatim,
        supporting_context=normalized_supporting,
    )


def _stored_session_request_fragments(
    sections: dict[str, list[dict[str, Any]]],
    *,
    request_verbatim: str,
) -> list[str]:
    """Return source-bound fragments only when they match the active request."""

    goals = sections.get("goal") or []
    if not goals:
        return []
    payload = goals[-1].get("payload") or {}
    stored_request = str(payload.get("request_verbatim") or "")
    stored_request_sha256 = str(payload.get("request_sha256") or "")
    if stored_request != request_verbatim and stored_request_sha256 != _sha256(request_verbatim):
        return []

    raw_fragments = payload.get("request_fragments")
    if not isinstance(raw_fragments, list):
        return []
    fragments: list[str] = []
    for raw_fragment in raw_fragments:
        if not isinstance(raw_fragment, dict):
            return []
        fragment = str(raw_fragment.get("request_verbatim") or "")
        fragment_sha256 = str(raw_fragment.get("request_sha256") or "")
        if not fragment or (fragment_sha256 and fragment_sha256 != _sha256(fragment)):
            return []
        fragments.append(fragment)
    return fragments


def derive_session_handoff_requirements(
    request_verbatim: str,
    *,
    supporting_context: Iterable[dict[str, str]] = (),
) -> list[dict[str, Any]]:
    """Expose the authority-aware requirement projection to both context products."""

    return _derive_session_requirements(
        request_verbatim,
        supporting_context=supporting_context,
    )


def _unfold_requirement_lines(value: str) -> list[str]:
    """Join indented Markdown continuation lines before extracting clauses."""

    logical_lines: list[str] = []
    for raw_line in value.splitlines():
        stripped = raw_line.strip()
        if not stripped or not logical_lines:
            logical_lines.append(raw_line)
            continue
        previous = logical_lines[-1]
        previous_indent = len(previous) - len(previous.lstrip())
        current_indent = len(raw_line) - len(raw_line.lstrip())
        is_structural = bool(
            _REQUIREMENT_BULLET_RE.match(raw_line)
            or re.match(r"^#{1,6}\s+", stripped)
            or re.match(r"^(`{3,}|~{3,})", stripped)
            or stripped.startswith(">")
            or _PLAIN_REQUIREMENT_SECTION_HEADING_RE.fullmatch(stripped)
        )
        if (
            not is_structural
            and _REQUIREMENT_BULLET_RE.match(previous)
            and current_indent > previous_indent
        ):
            logical_lines[-1] = f"{previous.rstrip()} {stripped}"
            continue
        logical_lines.append(raw_line)
    return logical_lines


def _requirement_candidates(
    value: str,
    *,
    source: str,
    authority: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    heading: str | None = None
    ignore_section = False
    fence_marker: str | None = None
    prose_lines: list[str] = []
    quoted_acceptance_list = False
    for raw_line in _unfold_requirement_lines(value):
        stripped = raw_line.strip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            quoted_acceptance_list = False
            continue
        if fence_marker is not None:
            continue
        quoted_item = stripped.startswith(">")
        if quoted_item:
            if authority != "accepted_by_user_reference":
                continue
            raw_line = re.sub(r"^\s*>\s?", "", raw_line, count=1)
            stripped = raw_line.strip()
        raw_line = _strip_historical_quoted_report(raw_line)
        stripped = raw_line.strip()
        if not stripped:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            heading = heading_match.group(1).strip()
            ignore_section = bool(_NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE.search(heading))
            quoted_acceptance_list = False
            continue
        if _PLAIN_REQUIREMENT_SECTION_HEADING_RE.fullmatch(stripped):
            heading = stripped[:-1].strip()
            ignore_section = bool(_NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE.search(heading))
            quoted_acceptance_list = False
            continue
        if ignore_section:
            continue
        if _HISTORICAL_QUOTED_SPEECH_RE.search(stripped):
            continue
        bullet_match = _REQUIREMENT_BULLET_RE.match(raw_line)
        if quoted_item and not quoted_acceptance_list:
            continue
        if bullet_match is None:
            if quoted_item and quoted_acceptance_list and len(stripped) >= 4:
                candidates.append(
                    {
                        "text": stripped,
                        "source": source,
                        "authority": authority,
                        "source_heading": heading,
                        "explicit_acceptance": True,
                    }
                )
                continue
            if stripped.endswith(":") and re.search(
                r"\b(?:contain|include|carry|have|consist of)\b",
                stripped,
                re.IGNORECASE,
            ):
                lead_in = re.search(
                    r"\b(?:it|this|the\s+(?:handoff|context))\s+"
                    r"(?:should|must|will)\s+"
                    r"(?:contain|include|carry|have|consist of)\b[^:]*:$",
                    stripped,
                    re.IGNORECASE,
                )
                if lead_in is not None:
                    prefix = stripped[: lead_in.start()].strip()
                    if prefix:
                        prose_lines.append(prefix)
                quoted_acceptance_list = True
                continue
            if stripped.endswith(":"):
                quoted_acceptance_list = False
                continue
            if stripped and not stripped.endswith(":"):
                prose_lines.append(re.sub(r"`[^`\n]*`", " ", stripped))
                quoted_acceptance_list = False
            continue
        statement = bullet_match.group(1).strip()
        if len(statement) < 4:
            continue
        inline_acceptance = _is_inline_observable_acceptance_clause(statement)
        candidates.append(
            {
                "text": statement,
                "source": source,
                "authority": authority,
                "source_heading": heading,
                "explicit_acceptance": bool(
                    inline_acceptance
                    or (
                        heading
                        and re.search(
                            r"\b(?:acceptance|definition of done|requirements?|must have)\b",
                            heading,
                            re.IGNORECASE,
                        )
                    )
                ),
            }
        )

    # Keep pure working-style directives as their own source-backed clauses.
    # Joining them to a preceding line would turn urgency or "quality over
    # quantity" into part of that outcome's proof contract.
    statements: list[str] = []
    prose_group: list[str] = []
    for prose_line in prose_lines:
        if is_non_verifiable_execution_guidance(prose_line):
            if prose_group:
                statements.extend(_sentences("\n".join(prose_group)))
                prose_group = []
            statements.extend(_sentences(prose_line))
        else:
            prose_group.append(prose_line)
    if prose_group:
        statements.extend(_sentences("\n".join(prose_group)))
    statements = [
        atomic for statement in statements for atomic in _atomic_requirement_statements(statement)
    ]
    actionable = [
        statement
        for statement in statements
        if (
            _is_inline_observable_acceptance_clause(statement)
            or _REQUIREMENT_ACTION_RE.search(statement)
            or statement.rstrip().endswith("?")
        )
        and not _NON_ACTIONABLE_STATE_CLAUSE_RE.match(statement)
    ]
    prose_candidates = [
        {
            "text": statement,
            "source": source,
            "authority": authority,
            "source_heading": None,
            "explicit_acceptance": _is_inline_observable_acceptance_clause(statement),
        }
        for statement in actionable
    ]
    if prose_candidates:
        return [*prose_candidates, *candidates]
    if candidates:
        return candidates
    if statements:
        return [
            {
                "text": statements[0],
                "source": source,
                "authority": authority,
                "source_heading": None,
                "explicit_acceptance": False,
            }
        ]
    return []


_ATOMIC_REQUIREMENT_JOIN_RE = re.compile(
    r"\s*(?:;|,?\s+\b(?:and\s+then|then|and|but)\b)\s+"
    r"(?=(?:please\s+)?(?:"
    r"(?:do\s+not|don['’]?t|never)\s+let\b|"
    r"add|allow|audit|build|change|check|create|debug|diagnose|edit|ensure|"
    r"explain|fix|implement|inspect|make|modify|prevent|remove|repair|replace|"
    r"review|ship|skip|summari[sz]e|update|verify|write)\b)",
    re.IGNORECASE,
)
_NON_ACTIONABLE_STATE_CLAUSE_RE = re.compile(
    r"^(?:the|this|that|an?)\s+.{1,100}\s+"
    r"(?:is|are|was|were)\s+not\s+(?:available|complete|ready|working)\b",
    re.IGNORECASE,
)


def _atomic_requirement_statements(value: str) -> list[str]:
    parts = [part.strip(" ,;-") for part in _ATOMIC_REQUIREMENT_JOIN_RE.split(str(value or ""))]
    return [part for part in parts if len(part) >= 4]


def _strip_historical_quoted_report(value: str) -> str:
    cleaned = _HISTORICAL_QUOTED_REPORT_RE.sub(" ", value)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    # Preserve Markdown bullets and acceptance-list punctuation. This helper
    # removes a provenance-marked quoted report, not the line's structure.
    return cleaned.strip()


def _infer_session_task_mode(request_verbatim: str) -> str:
    """Classify handoff authority with the shared execution classifier."""

    directive = _session_task_directive_text(request_verbatim)
    return infer_task_mode(directive).value


def _normalized_session_requirement(value: Any, *, task_mode: str) -> str:
    """Compile a user sentence into an executable display requirement.

    The source sentence remains untouched in ``text`` and ``current_goal``.
    This projection exists so terse desired-state complaints do not become the
    only instruction a receiving agent sees.
    """

    source = re.sub(r"\s+", " ", str(value or "")).strip()
    if not source:
        return source
    if task_mode != "change":
        return source
    transparent = _NEGATED_TRANSPARENCY_REQUIREMENT_RE.search(source)
    if transparent is None:
        transparent = _PROHIBITED_TRANSPARENCY_STATE_RE.search(source)
    if transparent is not None:
        target = _normalized_target_phrase(transparent.group("target"))
        if target:
            scope = re.sub(
                r"\s+",
                " ",
                " ".join(
                    str(transparent.groupdict().get(key) or "") for key in ("pre_scope", "scope")
                ),
            ).strip(" .,!?:;")
            scope_suffix = f" {scope}" if scope else ""
            return f"Make the {target} fully opaque{scope_suffix}."
    negated_state = _NEGATED_STATE_REQUIREMENT_RE.search(source)
    if negated_state is not None:
        target = _normalized_target_phrase(negated_state.group("target"))
        state = re.sub(
            r"\s+",
            " ",
            negated_state.group("state"),
        ).strip(" .,!?:;")
        if target and state:
            return f"Prevent the {target} from being {state}."
    if _request_requires_opaque_outcome(source):
        target_match = _AMBIGUOUS_PRODUCT_TARGET_RE.search(_session_task_directive_text(source))
        if target_match is not None:
            target = _normalized_target_phrase(target_match.group(0))
            scope = _transparent_outcome_scope(source)
            scope_suffix = f" {scope}" if scope else ""
            return f"Make the {target} fully opaque{scope_suffix}."
    return source


def _normalized_target_phrase(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip(" .,!?:;")
    normalized = re.sub(
        r"^(?:a|an|the)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    if _AMBIGUOUS_PRODUCT_TARGET_RE.fullmatch(normalized):
        return normalized.casefold()
    return normalized


def _opaque_outcome_target(value: str) -> str:
    """Return the concrete UI noun governed by an opacity requirement."""

    directive = _session_task_directive_text(value)
    for pattern in (
        _NEGATED_TRANSPARENCY_REQUIREMENT_RE,
        _PROHIBITED_TRANSPARENCY_STATE_RE,
    ):
        match = pattern.search(directive)
        if match is not None:
            target = _normalized_target_phrase(match.group("target"))
            if target:
                return target
    target_match = _AMBIGUOUS_PRODUCT_TARGET_RE.search(directive)
    if target_match is not None:
        target = _normalized_target_phrase(target_match.group(0))
        if target:
            return target
    return "surface"


def _opaque_target_grammar(target: str) -> tuple[bool, str, str]:
    """Return plural flag, pronoun, and state verb for a UI target."""

    plural = target.casefold().endswith("s")
    return (
        plural,
        "them" if plural else "it",
        "become" if plural else "becomes",
    )


def _session_handoff_intent(
    request_verbatim: str,
    *,
    task_mode: str,
    requirements: list[dict[str, Any]],
    files: dict[str, Any],
    attachment_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    outcome_requirements = [
        item
        for item in requirements
        if not item.get("explicit_acceptance") and item.get("completion_relevant") is not False
    ]
    normalized_requirements = [
        str(
            item.get("normalized_text")
            or _normalized_session_requirement(
                item.get("text"),
                task_mode=task_mode,
            )
        ).strip()
        for item in outcome_requirements
        if str(item.get("text") or "").strip()
    ]
    target_source = request_verbatim
    if task_mode == "change":
        actionable_target_clauses = [
            str(item.get("text") or "").strip()
            for item in requirements
            if not item.get("explicit_acceptance")
            and str(item.get("text") or "").strip()
            and infer_task_mode(_session_task_directive_text(str(item.get("text") or ""))).value
            == "change"
        ]
        if actionable_target_clauses:
            target_source = ". ".join(actionable_target_clauses)
    targets = _session_handoff_targets(target_source, files=files)
    required_attachments = [
        item for item in attachment_dependencies if item.get("required") is True
    ]
    known_paths = {
        str(item.get("path") or "")
        for category in ("modified", "relevant", "pre_existing_at_handoff")
        for item in files.get(category) or []
        if str(item.get("path") or "") != ""
    }
    for target in targets.get("items") or []:
        existing_paths = {str(item.get("path") or "") for item in target.get("candidates") or []}
        for attachment in required_attachments:
            for candidate in attachment.get("visual_candidate_files") or []:
                path = str(candidate.get("path") or "")
                reason = str(candidate.get("reason") or "").strip()
                if not path or path not in known_paths or path in existing_paths:
                    continue
                target.setdefault("candidates", []).append(
                    {
                        "path": path,
                        "source": "hash_bound_visual_inspection",
                        "confidence": 0.65,
                        "evidence_level": "model_observed_candidate",
                        "evidence": (
                            "Hash-bound source-time visual inspection suggested this "
                            f"candidate: {reason}"
                        ),
                    }
                )
                existing_paths.add(path)
        target["candidates"] = sorted(
            target.get("candidates") or [],
            key=lambda item: (-float(item.get("confidence") or 0.0), str(item.get("path") or "")),
        )[:5]
        if target.get("status") == "unresolved" and target.get("candidates"):
            target["status"] = "candidate"
            target["confidence"] = float(target["candidates"][0].get("confidence") or 0.0)
    if any(item.get("status") == "candidate" for item in targets.get("items") or []):
        targets["status"] = (
            "unresolved"
            if any(item.get("status") == "unresolved" for item in targets.get("items") or [])
            else "candidate"
        )
        targets["confidence"] = min(
            float(item.get("confidence") or 0.0) for item in targets.get("items") or []
        )
    if len(normalized_requirements) == 1:
        normalized_goal = normalized_requirements[0]
    elif normalized_requirements:
        normalized_goal = "Deliver these outcomes: " + "; ".join(normalized_requirements)
    else:
        normalized_goal = re.sub(
            r"\s+",
            " ",
            _self_contained_goal(request_verbatim),
        ).strip()
    if (
        task_mode == "change"
        and len(normalized_requirements) == 1
        and required_attachments
        and _request_requires_opaque_outcome(request_verbatim)
    ):
        target_phrase = str(
            ((targets.get("items") or [{}])[0]).get("phrase") or "affected surface"
        ).strip()
        attachment_ids = [str(item.get("id") or "") for item in required_attachments]
        evidence_label = (
            f"attachment {attachment_ids[0]}"
            if len(attachment_ids) == 1
            else "attachments " + ", ".join(attachment_ids)
        )
        pronoun = "them" if target_phrase.casefold().endswith("s") else "it"
        normalized_goal = (
            f"Make the {target_phrase} shown in {evidence_label} fully opaque so "
            f"the page background cannot be seen through {pronoun}."
        )
    acceptance = _session_handoff_acceptance_criteria(
        request_verbatim,
        requirements=requirements,
        infer_outcomes=task_mode == "change",
    )
    return {
        "task_type": task_mode,
        "normalized_requirement": normalized_goal,
        "normalized_requirements": normalized_requirements,
        "source_request_sha256": _sha256(request_verbatim),
        "targets": targets["items"],
        "target_resolution": {
            "required": targets["required"],
            "status": targets["status"],
            "confidence": targets["confidence"],
            "evidence_available": [
                {
                    "attachment_id": item.get("id"),
                    "portable_reference": item.get("portable_reference"),
                    "role": "target_identification_and_visual_acceptance",
                    "inspection_status": item.get("inspection_status"),
                    "receiver_availability": item.get("receiver_availability"),
                    "receiver_local_reference": item.get("receiver_local_reference"),
                    "integrity_status": item.get("integrity_status"),
                    "integrity_verification_owner": item.get("integrity_verification_owner"),
                    "materialization_owner": item.get("materialization_owner"),
                    "visual_anchors": list(item.get("visual_anchors") or []),
                    "suspected_surface": item.get("suspected_surface"),
                    "candidate_route": item.get("candidate_route"),
                    "candidate_files": list(item.get("visual_candidate_files") or []),
                }
                for item in required_attachments
            ],
        },
        "acceptance_criteria": acceptance,
    }


def _session_handoff_targets(
    request_verbatim: str,
    *,
    files: dict[str, Any],
) -> dict[str, Any]:
    source = _session_task_directive_text(_self_contained_goal(request_verbatim))
    phrases: list[str] = []
    explicit_paths = _extract_paths(source)
    explicit_path_spans = [
        (match.start(), match.end())
        for path in explicit_paths
        for match in re.finditer(re.escape(path), source)
    ]
    phrases.extend(explicit_paths)
    state_matches = [
        *list(_NEGATED_TRANSPARENCY_REQUIREMENT_RE.finditer(source)),
        *list(_PROHIBITED_TRANSPARENCY_STATE_RE.finditer(source)),
    ]
    if not state_matches:
        generic_state = _NEGATED_STATE_REQUIREMENT_RE.search(source)
        if generic_state is not None:
            state_matches = [generic_state]
    state_spans = [(match.start(), match.end()) for match in state_matches]
    for state_match in state_matches:
        target = _normalized_target_phrase(state_match.group("target"))
        if target:
            phrases.append(target)
    phrases.extend(
        match.group(0)
        for match in _AMBIGUOUS_PRODUCT_TARGET_RE.finditer(source)
        if not any(
            match.start() < blocked_end and match.end() > blocked_start
            for blocked_start, blocked_end in [
                *explicit_path_spans,
                *state_spans,
            ]
        )
    )
    if not phrases:
        deictic = _DEICTIC_PRODUCT_TARGET_RE.search(source)
        if deictic is not None:
            phrases.append(deictic.group(0))

    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = re.sub(r"\s+", " ", phrase).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            deduped.append(normalized)
    if not deduped:
        return {
            "required": False,
            "status": "not_required",
            "confidence": 1.0,
            "items": [],
        }

    file_records: list[tuple[str, str]] = []
    for category in ("modified", "relevant", "pre_existing_at_handoff"):
        for item in files.get(category) or []:
            path = str(item.get("path") or "")
            if path != "" and all(existing[0] != path for existing in file_records):
                file_records.append((path, category))

    items: list[dict[str, Any]] = []
    for phrase in deduped:
        phrase_key = phrase.casefold()
        explicit_path = phrase in explicit_paths
        phrase_tokens = _target_match_tokens(phrase_key)
        candidates: list[dict[str, Any]] = []
        for path, category in file_records:
            entity_tokens = _target_match_tokens(Path(path).stem)
            path_match = bool(phrase_tokens and phrase_tokens <= _target_match_tokens(path))
            entity_match = bool(phrase_tokens and phrase_tokens <= entity_tokens)
            exact_entity_match = bool(phrase_tokens and phrase_tokens == entity_tokens)
            generic_ui_target = bool(phrase_tokens and phrase_tokens <= _GENERIC_UI_TARGET_TOKENS)
            ui_implementation_evidence = _path_has_ui_implementation_evidence(path)
            exact_entity_supported = bool(
                exact_entity_match and (not generic_ui_target or ui_implementation_evidence)
            )
            if (
                category == "pre_existing_at_handoff"
                and not path_match
                and not (explicit_path and path == phrase)
            ):
                continue
            confidence = (
                0.99
                if explicit_path and path == phrase
                else 0.9
                if exact_entity_supported
                else 0.7
                if entity_match
                else 0.55
                if path_match
                else 0.5
                if category == "modified"
                else 0.4
            )
            candidates.append(
                {
                    "path": path,
                    "confidence": confidence,
                    "evidence": (
                        "Explicitly named by the current user."
                        if explicit_path and path == phrase
                        else "Target phrase exactly matches the current file entity name."
                        if exact_entity_supported
                        else "A file entity contains only the generic target phrase; inspect before relying on it."
                        if entity_match
                        else "Target phrase matches only the file's directory path; inspect before relying on it."
                        if path_match
                        else "Historically linked to this task; inspect before relying on it."
                    ),
                }
            )
        candidates.sort(
            key=lambda item: (-float(item["confidence"]), str(item["path"])),
        )
        strong = [item for item in candidates if float(item["confidence"]) >= 0.85]
        resolved = (
            candidates[0]
            if explicit_path and candidates and candidates[0]["path"] == phrase
            else strong[0]
            if len(strong) == 1
            else None
        )
        status = "resolved" if resolved else "candidate" if candidates else "unresolved"
        confidence = (
            float(resolved["confidence"])
            if resolved
            else float(candidates[0]["confidence"])
            if candidates
            else 0.0
        )
        items.append(
            {
                "phrase": phrase,
                "status": status,
                "confidence": confidence,
                "resolved_entity": resolved["path"] if resolved else None,
                "candidates": candidates[:5],
            }
        )

    statuses = {item["status"] for item in items}
    overall = (
        "unresolved"
        if "unresolved" in statuses
        else "candidate"
        if "candidate" in statuses
        else "resolved"
    )
    return {
        "required": True,
        "status": overall,
        "confidence": min(float(item["confidence"]) for item in items),
        "items": items,
    }


def _target_match_tokens(value: str) -> set[str]:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return {
        token.removesuffix("s")
        for token in re.findall(r"[A-Za-z0-9]+", camel_split.casefold())
        if token not in {"a", "an", "the", "this", "that", "these", "those"}
    }


def _path_has_ui_implementation_evidence(value: str) -> bool:
    path = Path(str(value or ""))
    parts = {part.casefold() for part in path.parts[:-1]}
    non_runtime_filename = re.search(
        r"(?:^|[._-])(?:snapshot|spec|stories|story|test)(?:[._-]|$)",
        path.name.casefold(),
    )
    if parts & _NON_UI_IMPLEMENTATION_PATH_PARTS or non_runtime_filename:
        return False
    if path.suffix.casefold() in _UI_IMPLEMENTATION_SUFFIXES:
        return True
    return bool(parts & _UI_IMPLEMENTATION_PATH_PARTS) and path.suffix.casefold() in {
        ".js",
        ".ts",
    }


def _session_handoff_acceptance_criteria(
    request_verbatim: str,
    *,
    requirements: list[dict[str, Any]],
    infer_outcomes: bool,
) -> list[dict[str, Any]]:
    outcome_requirements = [
        item
        for item in requirements
        if str(item.get("id") or "")
        and not item.get("explicit_acceptance")
        and item.get("source") != "attachment_dependency"
    ]
    criteria: list[dict[str, Any]] = []
    for item_index, item in enumerate(requirements):
        if not item.get("explicit_acceptance") or not str(item.get("text") or "").strip():
            continue
        criterion_text = str(item.get("normalized_text") or item.get("text") or "").strip()
        linked_candidates = [
            candidate
            for candidate in outcome_requirements
            if _acceptance_criterion_matches_requirement(
                criterion_text,
                str(candidate.get("text") or ""),
            )
        ]
        if len(linked_candidates) > 1:
            criterion_tokens = _status_tokens(criterion_text)
            scored_candidates = [
                (
                    len(
                        (criterion_tokens & _status_tokens(str(candidate.get("text") or "")))
                        - _GENERIC_UI_TARGET_TOKENS
                    ),
                    candidate,
                )
                for candidate in linked_candidates
            ]
            scored_candidates.sort(key=lambda pair: pair[0], reverse=True)
            if scored_candidates[0][0] > 0 and scored_candidates[0][0] > scored_candidates[1][0]:
                linked_candidates = [scored_candidates[0][1]]
            else:
                linked_candidates = []
        linked_ids = [str(candidate.get("id") or "") for candidate in linked_candidates]
        if not linked_ids and _is_inline_observable_acceptance_clause(criterion_text):
            for candidate in reversed(requirements[:item_index]):
                candidate_id = str(candidate.get("id") or "")
                if (
                    candidate_id
                    and not candidate.get("explicit_acceptance")
                    and candidate.get("source") != "attachment_dependency"
                    and infer_task_mode(
                        _session_task_directive_text(str(candidate.get("text") or ""))
                    ).value
                    == "change"
                ):
                    linked_ids = [candidate_id]
                    break
        criteria.append(
            {
                "text": criterion_text,
                "requirement_ids": linked_ids,
                "authority": "user_authored",
                "source": "explicit_acceptance",
            }
        )
    if not infer_outcomes:
        return criteria
    for item in requirements:
        requirement_text = str(item.get("text") or "").strip()
        requirement_id = str(item.get("id") or "").strip()
        if (
            not requirement_id
            or infer_task_mode(_session_task_directive_text(requirement_text)).value != "change"
            or not _request_requires_opaque_outcome(requirement_text)
        ):
            continue
        target = _opaque_outcome_target(requirement_text)
        plural, pronoun, state_verb = _opaque_target_grammar(target)
        inferred = (
            f"The affected {target} "
            f"{'have fully opaque backgrounds' if plural else 'has a fully opaque background'}; "
            f"the page beneath {pronoun} "
            f"is not visible through {pronoun}."
        )
        scope = _transparent_outcome_scope(requirement_text)
        if scope:
            inferred = f"{inferred} This criterion applies {scope}."
        criteria.append(
            {
                "text": inferred,
                "requirement_ids": [requirement_id],
                "authority": "inferred_acceptance",
                "source": "intent_compiler",
            }
        )
        criteria.extend(
            [
                {
                    "text": (
                        "Existing layout, spacing, typography, borders, shadows, and "
                        "content remain unchanged unless an opacity fix requires it."
                    ),
                    "requirement_ids": [requirement_id],
                    "authority": "derived_preservation",
                    "source": "session_handoff_policy",
                },
                {
                    "text": (
                        "Text and icon contrast remain readable after the affected "
                        f"{target} {state_verb} opaque."
                    ),
                    "requirement_ids": [requirement_id],
                    "authority": "derived_preservation",
                    "source": "session_handoff_policy",
                },
            ]
        )
    return criteria


_ACCEPTANCE_LINK_GENERIC_TOKENS = frozenset(
    {
        "add",
        "allow",
        "build",
        "change",
        "create",
        "delete",
        "edit",
        "ensure",
        "fix",
        "implement",
        "make",
        "modify",
        "remove",
        "repair",
        "replace",
        "update",
    }
)


def _acceptance_criterion_matches_requirement(
    criterion_text: str,
    requirement_text: str,
) -> bool:
    criterion_tokens = _status_tokens(criterion_text)
    requirement_tokens = _status_tokens(requirement_text)
    paths = _extract_paths(requirement_text)
    path_tokens = {token for path in paths for token in _target_match_tokens(path)}
    specific_requirement_tokens = (
        requirement_tokens
        - path_tokens
        - _ACCEPTANCE_LINK_GENERIC_TOKENS
        - _GENERIC_UI_TARGET_TOKENS
    )
    if specific_requirement_tokens:
        return bool(specific_requirement_tokens & criterion_tokens)
    return bool(
        _statements_overlap(criterion_text, requirement_text)
        or any(
            _target_match_tokens(Path(path).stem) <= _target_match_tokens(criterion_text)
            for path in paths
        )
    )


_GENERIC_UNTESTABLE_ACCEPTANCE_RE = re.compile(
    r"^(?:make\s+(?:it|this|things?)\s+better|"
    r"(?:(?:the|this)\s+[a-z0-9_-]+\s+)?works?\s+as\s+expected|"
    r"(?:(?:the|this)\s+[a-z0-9_-]+\s+)?looks?\s+good|"
    r"(?:it|this|everything)\s+(?:is|looks?|works?)\s+(?:correct|good|fine)|"
    r"everything\s+(?:behaves?|displays?|renders?|works?)\s+"
    r"(?:correctly|properly)(?:\s+in\s+production)?|"
    r"users?\s+can\s+(?:access|use)\s+(?:it|this|the\s+product)|"
    r"(?:it|this|the\s+product)\s+(?:behaves?|displays?|renders?|works?)\s+"
    r"(?:correctly|properly|without\s+(?:any\s+)?problems?)|"
    r"users?\s+can\s+tell\s+(?:it|this)\s+is\s+better|"
    r"(?:(?:it|this|the\s+page|the\s+app|app)\s+)?"
    r"(?:loads?|renders?)\s+(?:better|nicely|well)|"
    r"(?:the\s+)?[a-z0-9_-]+\s+passes?\s+review|"
    r"no\s+issues?)$",
    re.IGNORECASE,
)
_CONCRETE_ACCEPTANCE_OUTCOME_RE = re.compile(
    r"\b(?:no|without)\s+(?:errors?|exceptions?|failures?|regressions?|"
    r"warnings?)\b|"
    r"\b(?:is|are|becomes?|remains?|stays?)\s+(?:absent|disabled|empty|"
    r"enabled|hidden|non[- ]?empty|opaque|present|readable|responsive|"
    r"transparent|visible)\b|"
    r"\b(?:contains?|creates?|deletes?|displays?|emits?|returns?|saves?|"
    r"shows?|writes?)\s+(?:(?:an?|the)\s+)?"
    r"(?!(?:anything|correctly|everything|it|properly|quality|something|"
    r"this|well)\b)[a-z0-9][a-z0-9_/-]{2,}\b|"
    r"\b(?:loads?|opens?)\s+(?:(?:an?|the)\s+)?"
    r"(?!(?:correctly|fast|nicely|properly|quickly|smoothly|well)\b)"
    r"[a-z0-9][a-z0-9_/-]{2,}\b|"
    r"\b(?:file|record|row|element|button|card|dialog|page|screen)\s+"
    r"(?:exists?|persists?)\b|"
    r"\b(?:admins?|users?)\s+can\s+(?:create|delete|download|edit|open|"
    r"reset|save|submit|upload|view)\s+[a-z0-9][a-z0-9_/-]{2,}\b|"
    r"\b(?:coverage|count|duration|latency|load\s+time|response\s+time|size)\b"
    r".{0,24}(?:<=|>=|=|at\s+(?:least|most)|less\s+than|more\s+than|"
    r"under|over)\s*\d+(?:\.\d+)?(?:%|ms|s)?\b|"
    r"\bhttp\s+status(?:\s+code)?\s+(?:is|equals?)\s+\d{3}\b",
    re.IGNORECASE,
)


def _acceptance_criterion_is_testable(item: dict[str, Any]) -> bool:
    text = re.sub(
        r"\s+",
        " ",
        str(item.get("text") or ""),
    ).strip(" .,!?:;")
    if not text or _GENERIC_UNTESTABLE_ACCEPTANCE_RE.fullmatch(text):
        return False
    if item.get("source") == "intent_compiler":
        return True
    if _is_inline_observable_acceptance_clause(text) or _INLINE_TEST_PASS_OUTCOME_RE.search(text):
        return True
    return _CONCRETE_ACCEPTANCE_OUTCOME_RE.search(text) is not None


def _request_requires_opaque_outcome(value: str) -> bool:
    directive = _session_task_directive_text(value)
    if not directive:
        return False
    if _PARTIAL_TRANSPARENCY_OUTCOME_RE.search(directive):
        return False
    negative_transparency = bool(
        re.search(
            r"\b(?:do\s+not|don['’]?t|never)\b.{0,140}\btransparent\b|"
            r"\b(?:must|should)(?:n['’]?t|\s+not)\b.{0,80}\btransparent\b|"
            r"\bprevent\b.{0,140}\btransparent\b|"
            r"\b(?:no|without)\s+transparen(?:cy|t\s+backgrounds?)\b",
            directive,
            re.IGNORECASE,
        )
    )
    if negative_transparency:
        return True
    if _NEGATED_OPAQUE_OUTCOME_RE.search(directive) or _PARTIAL_OPACITY_OUTCOME_RE.search(
        directive
    ):
        return False
    return bool(_OPAQUE_OUTCOME_INTENT_RE.search(directive))


def _transparent_outcome_scope(value: str) -> str:
    directive = _session_task_directive_text(value)
    for pattern in (
        _NEGATED_TRANSPARENCY_REQUIREMENT_RE,
        _PROHIBITED_TRANSPARENCY_STATE_RE,
    ):
        match = pattern.search(directive)
        if match is None:
            continue
        scope = re.sub(
            r"\s+",
            " ",
            " ".join(str(match.groupdict().get(key) or "") for key in ("pre_scope", "scope")),
        ).strip(" .,!?:;")
        if scope:
            return scope
    return ""


def _session_handoff_readiness(
    *,
    intent: dict[str, Any],
    requirements: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    files: dict[str, Any],
    fresh_user_lead: bool = False,
    handoff_boundary_current: bool = True,
    repository_baseline_ready: bool = True,
) -> dict[str, Any]:
    statuses = [str(item.get("status") or "unknown") for item in requirements]
    target = intent["target_resolution"]
    task_type = str(intent.get("task_type") or "report")
    resolved_target = any(item.get("resolved_entity") for item in intent.get("targets") or [])
    implementation_known = bool(
        resolved_target
        or (
            not fresh_user_lead and ((files.get("modified") or []) or (files.get("relevant") or []))
        )
    )
    completed_evidence_backed = not any(status in {"reported_done", "done"} for status in statuses)
    acceptance_items = [
        item
        for item in intent.get("acceptance_criteria") or []
        if _acceptance_criterion_is_testable(item)
    ]
    acceptance_covered_ids = {
        str(requirement_id)
        for item in acceptance_items
        for requirement_id in item.get("requirement_ids") or []
        if str(requirement_id)
    }
    acceptance_required_ids = {
        str(item.get("id") or "")
        for item in requirements
        if str(item.get("id") or "")
        and not item.get("explicit_acceptance")
        and item.get("source") != "attachment_dependency"
        and str(item.get("status") or "remaining") != "done"
    }
    acceptance_ready = bool(acceptance_items and acceptance_required_ids <= acceptance_covered_ids)
    required_evidence = list(target.get("evidence_available") or [])
    required_evidence_ready = all(
        str(item.get("inspection_status") or "") == "inspected"
        and str(item.get("receiver_availability") or "") == "available"
        for item in required_evidence
    )
    no_active_blockers = not bool(reconciliation.get("active_reported_blockers"))
    checks = [
        ("goal_normalized", 15, bool(intent.get("normalized_requirement"))),
        (
            "task_type_correct",
            10,
            intent.get("task_type")
            in {"change", "diagnose", "plan", "report", "review", "test_only"},
        ),
        (
            "target_resolved",
            20,
            not target["required"] or target["status"] == "resolved",
        ),
        (
            "current_implementation_known",
            15,
            task_type != "change" or implementation_known,
        ),
        ("completed_work_evidence_backed", 15, completed_evidence_backed),
        ("remaining_work_explicit", 10, bool(requirements)),
        (
            "acceptance_testable",
            10,
            task_type != "change" or acceptance_ready,
        ),
        (
            "required_evidence_ready_in_receiver",
            0,
            not required_evidence or required_evidence_ready,
        ),
        (
            "repository_baseline_ready",
            0,
            task_type != "change" or repository_baseline_ready,
        ),
        (
            "no_internal_contradictions",
            5,
            not bool(reconciliation.get("conflicts"))
            and no_active_blockers
            and handoff_boundary_current,
        ),
    ]
    score = sum(weight for _code, weight, passed in checks if passed)
    counts = reconciliation.get("counts") or {}
    hard_prerequisites_met = bool(
        requirements
        and (not target["required"] or target["status"] == "resolved")
        and (task_type != "change" or implementation_known)
        and (task_type != "change" or acceptance_ready)
        and (task_type != "change" or not required_evidence or required_evidence_ready)
        and (task_type != "change" or repository_baseline_ready)
        and not reconciliation.get("conflicts")
        and no_active_blockers
        and handoff_boundary_current
        and not any(
            int(counts.get(state) or 0) for state in ("unknown", "reported_done", "contradicted")
        )
    )
    if score >= 80 and hard_prerequisites_met:
        status = "execution_ready"
    elif score >= 50:
        status = "discovery_required"
    else:
        status = "insufficient_recovery"
    target_items = intent.get("targets") or []
    candidate_paths = [
        str(candidate.get("path") or "")
        for item in target_items
        for candidate in item.get("candidates") or []
        if str(candidate.get("path") or "")
    ]
    target_phrase = str((target_items[0] if target_items else {}).get("phrase") or "")
    if status != "execution_ready":
        candidate_suffix = (
            " Start with " + ", ".join(f"`{path}`" for path in candidate_paths[:3]) + "."
            if candidate_paths
            else ""
        )
        if not handoff_boundary_current:
            next_action = (
                "Refresh the Session Context from the current session boundary "
                "and repository state before relying on recovered work."
            )
        elif not no_active_blockers:
            next_action = (
                "Validate whether each reported blocker still exists in the "
                "current runtime, record the evidence, and resolve or explicitly "
                "carry the blocker before continuing."
            )
        elif task_type == "change" and not repository_baseline_ready:
            next_action = (
                "Recapture a complete current repository snapshot with exact Git "
                "index objects, worktree hashes, and staged/unstaged status before editing."
            )
        elif task_type == "change" and required_evidence and not required_evidence_ready:
            attachment_ids = [
                str(item.get("attachment_id") or "")
                for item in required_evidence
                if str(item.get("attachment_id") or "")
            ]
            evidence_verified = all(
                str(item.get("integrity_status") or "") == "available_and_verified"
                for item in required_evidence
            )
            evidence_available = all(
                str(item.get("receiver_availability") or "") == "available"
                for item in required_evidence
            )
            next_action = (
                "Inspect infrastructure-verified attachment "
                + ", ".join(attachment_ids)
                + " through its receiver-local reference and record the visual "
                "anchors needed to identify and validate the affected target."
                if evidence_verified and evidence_available
                else (
                    "Wait for the artifact infrastructure to materialize attachment "
                    + ", ".join(attachment_ids)
                    + " in the receiving session and report it available with a "
                    "verified hash, then inspect it before editing."
                )
            )
        elif task_type == "change" and not acceptance_ready:
            missing_ids = sorted(acceptance_required_ids - acceptance_covered_ids)
            requirement_suffix = f" for {', '.join(missing_ids)}" if missing_ids else ""
            next_action = (
                "Define observable, requirement-linked acceptance criteria"
                f"{requirement_suffix} before editing, then identify the exact "
                "verification method for each criterion."
            )
        elif target["required"] and target["status"] != "resolved" and task_type == "change":
            attachment_ids = [
                str(item.get("attachment_id") or "")
                for item in target.get("evidence_available") or []
                if str(item.get("attachment_id") or "")
            ]
            evidence_prefix = (
                "Inspect infrastructure-verified attachment "
                + ", ".join(attachment_ids)
                + " using its portable handoff reference and record the visual "
                "anchors needed to identify the affected target."
                if attachment_ids
                else None
            )
            next_action = evidence_prefix or (
                "Resolve the exact component or surface meant by "
                f"`{target_phrase}` by matching current UI candidates against the "
                "repository state before editing."
                f"{candidate_suffix}"
            )
        elif task_type == "change" and not implementation_known:
            normalized_goal = str(intent.get("normalized_requirement") or "the requested change")
            next_action = (
                "Inspect live `git status --short`, then locate the current "
                f"implementation and verification surface for `{normalized_goal}` "
                "using repository search before editing."
                f"{candidate_suffix}"
            )
        elif target["required"] and target["status"] != "resolved" and target_phrase:
            next_action = (
                "Inspect the live repository, then resolve the exact component "
                f"or surface meant by `{target_phrase}` from current evidence. "
                f"Complete the requested {task_type} without editing files."
                f"{candidate_suffix}"
            )
        else:
            next_action = str(
                (reconciliation.get("exact_next_action") or {}).get("text")
                or (
                    "Inspect the live repository and gather current evidence. "
                    f"Complete the requested {task_type} without editing files."
                )
            )
    else:
        next_action = str(
            (reconciliation.get("exact_next_action") or {}).get("text")
            or "Complete and verify the remaining requirements."
        )
    return {
        "status": status,
        "label": status.replace("_", " ").title(),
        "score": score,
        "checks": [
            {"code": code, "weight": weight, "passed": passed} for code, weight, passed in checks
        ],
        "next_action": next_action,
    }


def _session_task_directive_text(request_verbatim: str) -> str:
    """Return only user directive text that may grant task authority."""

    value = str(request_verbatim or "")
    lines: list[str] = []
    fence_marker: str | None = None
    ignore_section = False
    for raw_line in value.splitlines():
        stripped = raw_line.strip()
        if _HISTORICAL_SPEECH_LINE_RE.search(stripped):
            continue
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker_char = fence_match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker_char
            elif marker_char == fence_marker:
                fence_marker = None
            continue
        if fence_marker is not None or stripped.startswith(">"):
            continue
        marker = _CURRENT_CODEX_REQUEST_MARKER_RE.search(raw_line)
        if marker is not None and not raw_line[: marker.start()].strip():
            lines = []
            ignore_section = False
            raw_line = raw_line[marker.end() :]
            stripped = raw_line.strip()
            if not stripped:
                continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            heading = heading_match.group(1).strip()
            ignore_section = bool(_NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE.search(heading))
            continue
        if ignore_section:
            continue
        without_inline_code = _strip_historical_quoted_report(re.sub(r"`[^`\n]*`", " ", raw_line))
        # Quoted transcript snippets describe text to inspect; they do not
        # independently grant write authority.
        without_quoted_history = re.sub(
            r'"[^"\n]{1,500}"|“[^”\n]{1,500}”|'
            r"(?<!\w)'[^'\n]{1,500}'(?!\w)|‘[^’\n]{1,500}’",
            " ",
            without_inline_code,
        )
        if without_quoted_history.strip():
            lines.append(without_quoted_history)
    return "\n".join(lines)


def validate_continuation_lead(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value)
    if len(raw) > MAX_CONTINUATION_LEAD_CHARS:
        raise ValueError(
            f"The continuation lead must be at most {MAX_CONTINUATION_LEAD_CHARS:,} characters."
        )
    normalized = normalize_substantive_user_request(raw)
    if not raw.strip() or not is_substantive_user_request(normalized):
        raise ValueError("The continuation lead must be a substantive user instruction.")
    return raw


def build_session_handoff_contract(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    continuation_lead: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    trusted_attachment_descriptors: Iterable[TrustedRequestImageDescriptor] = (),
    allow_local_artifacts: bool = False,
    checkpoint_data: dict[str, Any] | None = None,
    repository_comparison: dict[str, Any] | None = None,
    receiver_attachment_deliveries: dict[str, dict[str, str]] | None = None,
    receiver_baseline_delivery: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the typed, reconciled contract used by the copyable rendering."""

    normalized_continuation_lead = validate_continuation_lead(continuation_lead)
    effective_request = normalized_continuation_lead or request_verbatim
    trusted_descriptor_values = tuple(trusted_attachment_descriptors)
    lead_matches_historical_request = bool(
        normalized_continuation_lead
        and _sha256(normalized_continuation_lead) == _sha256(request_verbatim)
    )
    if (
        normalized_continuation_lead
        and _continuation_lead_requires_unbound_evidence(effective_request)
        and not (lead_matches_historical_request and trusted_descriptor_values)
    ):
        raise ValueError(
            "The continuation lead depends on referenced conversation or "
            "attachment evidence that is not bound to this lead. Capture the "
            "evidence in a new user turn or rewrite the lead so it is "
            "self-contained."
        )
    normalized_supporting = _normalize_supporting_context(list(supporting_context))
    dependency_required = _request_requires_materialized_context(effective_request)
    if dependency_required and not normalized_supporting:
        raise ValueError(
            "The session goal depends on referenced conversation context that "
            "could not be materialized into a self-contained handoff."
        )

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    sections = _handoff_presentation_sections(data["sections"])
    derived_requirements = _derive_session_requirements_from_fragments(
        effective_request,
        request_fragments=(
            []
            if normalized_continuation_lead
            else _stored_session_request_fragments(
                sections,
                request_verbatim=request_verbatim,
            )
        ),
        supporting_context=normalized_supporting,
    )
    requirements: list[dict[str, Any]] = []
    execution_guidance: list[dict[str, Any]] = []
    for item in derived_requirements:
        if item.get("completion_relevant") is False:
            execution_guidance.append(
                {
                    **item,
                    "id": f"C{len(execution_guidance) + 1}",
                }
            )
            continue
        requirements.append(
            {
                **item,
                "id": f"R{len(requirements) + 1}",
            }
        )
    attachment_dependencies = _session_attachment_dependencies(
        effective_request,
        trusted_descriptors=(
            trusted_descriptor_values
            if not normalized_continuation_lead or lead_matches_historical_request
            else ()
        ),
        allow_local_files=allow_local_artifacts,
    )
    _apply_session_attachment_receiver_deliveries(
        attachment_dependencies,
        receiver_attachment_deliveries or {},
    )
    _link_session_attachments_to_requirements(
        attachment_dependencies,
        requirements=requirements,
    )
    task_mode = _infer_session_task_mode(effective_request)
    effective_progress = [] if normalized_continuation_lead else sections["progress"]
    effective_next_actions = [] if normalized_continuation_lead else sections["exact_next_action"]
    effective_blockers = [] if normalized_continuation_lead else sections["blockers"]
    effective_verification = [] if normalized_continuation_lead else sections["verification"]
    verification = _session_handoff_verification(
        effective_verification,
        requirements=requirements,
        progress=effective_progress,
    )
    reconciliation = _reconcile_session_handoff(
        requirements=requirements,
        progress=effective_progress,
        next_actions=effective_next_actions,
        blockers=effective_blockers,
        verification=verification,
        task_mode=task_mode,
        fresh_user_lead=normalized_continuation_lead is not None,
    )
    requirement_status = {item["requirement_id"]: item for item in reconciliation["requirements"]}
    verification_by_requirement: dict[str, list[str]] = {}
    for item in verification:
        for requirement_id in item["requirement_ids"]:
            verification_by_requirement.setdefault(requirement_id, []).append(item["id"])
    enriched_requirements = [
        {
            **requirement,
            "normalized_text": _normalized_session_requirement(
                requirement["text"],
                task_mode=(
                    _infer_session_task_mode(requirement["text"])
                    if task_mode == "change"
                    else task_mode
                ),
            ),
            "status": requirement_status[requirement["id"]]["status"],
            "status_basis": requirement_status[requirement["id"]]["basis"],
            "status_authority": requirement_status[requirement["id"]]["authority"],
            "status_confirmed": False,
            "verification_ids": verification_by_requirement.get(requirement["id"], []),
            "reported_scope_hints": _reported_requirement_scope_hints(
                requirement["text"],
                progress=effective_progress,
            ),
            "attachment_ids": [
                attachment["id"]
                for attachment in attachment_dependencies
                if requirement["id"] in attachment["requirement_ids"]
            ],
        }
        for requirement in requirements
    ]
    repository = _session_handoff_repository(
        data,
        repository_comparison=repository_comparison,
    )
    _apply_repository_baseline_receiver_delivery(
        repository,
        receiver_baseline_delivery,
    )
    files = _session_handoff_files(
        sections["relevant_files"],
        sections["progress"],
        repository=repository,
    )
    intent = _session_handoff_intent(
        effective_request,
        task_mode=task_mode,
        requirements=enriched_requirements,
        files=files,
        attachment_dependencies=attachment_dependencies,
    )
    readiness = _session_handoff_readiness(
        intent=intent,
        requirements=enriched_requirements,
        reconciliation=reconciliation,
        files=files,
        fresh_user_lead=normalized_continuation_lead is not None,
        handoff_boundary_current=not bool(
            (data.get("boundary") or {}).get("has_newer_events") is True
            or (data.get("currentness") or {}).get("state") == "superseded"
        ),
        repository_baseline_ready=bool(
            repository.get("root")
            and repository.get("status_truncated") is False
            and (
                not repository.get("dirty")
                or (repository.get("protected_baseline_manifest") or {}).get("complete") is True
            )
        ),
    )
    implementation_summary = [
        {
            "statement": _redacted_historical_text(item["statement"]),
            "truth_state": str(item.get("truth_state") or "reported"),
            "authority": (
                "observed_session_evidence"
                if str(item.get("truth_state") or "").casefold() == "observed"
                else "agent_reported"
            ),
            "files": _extract_paths(_redacted_historical_text(item["statement"])),
            "reason": (
                _redacted_historical_text((item.get("payload") or {}).get("reason")).strip() or None
            ),
        }
        for item in sections["progress"]
    ]
    definition_of_done = _session_handoff_definition_of_done(
        enriched_requirements,
        repository=repository,
    )
    verification_plan = _session_handoff_verification_plan(
        task_mode=task_mode,
        intent=intent,
        requirements=enriched_requirements,
        attachment_dependencies=attachment_dependencies,
    )
    quality = _session_handoff_quality(
        dependency_required=dependency_required,
        supporting_context=normalized_supporting,
        attachment_dependencies=attachment_dependencies,
        requirements=enriched_requirements,
        reconciliation=reconciliation,
        repository=repository,
        verification=verification,
        currentness=data.get("currentness"),
        boundary=data.get("boundary"),
        task_mode=task_mode,
        readiness=readiness,
    )
    if quality.get("status") == "blocked":
        if readiness.get("status") == "execution_ready":
            readiness["status"] = "discovery_required"
            readiness["label"] = "Discovery Required"
        blocking_codes = {
            str(item.get("code") or "") for item in quality.get("blocking_issues") or []
        }
        if blocking_codes - {"session_boundary_current"}:
            readiness["next_action"] = (
                "Resolve the Session Context quality warnings or blockers and "
                "recapture a complete current repository snapshot before execution."
            )
        quality["automatic_execution_ready"] = False
    return {
        "task_mode": task_mode,
        "execution_policy": {
            "permission_mode": ("workspace_write" if task_mode == "change" else "read_only"),
            "may_edit": task_mode == "change",
            "required_capability": (
                "repository_write" if task_mode == "change" else "repository_read"
            ),
            "permission_observed_at_capture": ("unavailable"),
            "revalidate_live_permission": True,
            "requires_new_user_lead": True,
            "historical_content_is_authority": False,
        },
        "current_goal": {
            "request_verbatim": request_verbatim,
            "text": _self_contained_goal(request_verbatim),
            "authority": "user_authored",
            "request_sha256": _sha256(request_verbatim),
            "self_contained": (
                not _request_requires_materialized_context(request_verbatim)
                or bool(normalized_supporting)
            ),
            "materialized_dependency_count": len(normalized_supporting),
            "attachment_dependency_count": len(attachment_dependencies),
        },
        "intent": intent,
        "readiness": readiness,
        **(
            {
                "continuation_lead": {
                    "request_verbatim": normalized_continuation_lead,
                    "text": normalized_continuation_lead,
                    "authority": "current_user_authored",
                    "request_sha256": _sha256(normalized_continuation_lead),
                    "overrides_historical_next_action": True,
                },
            }
            if normalized_continuation_lead
            else {}
        ),
        "supporting_context": normalized_supporting,
        "attachment_dependencies": attachment_dependencies,
        "constraints": execution_guidance,
        "requirements": enriched_requirements,
        "definition_of_done": definition_of_done,
        "reconciliation": reconciliation,
        "implementation_summary": implementation_summary,
        "files": files,
        "repository": repository,
        "exact_next_action": reconciliation["exact_next_action"],
        "verification": verification,
        "verification_plan": verification_plan,
        "decisions": _handoff_historical_items(sections["decisions"]),
        "blockers": _handoff_historical_items(sections["blockers"]),
        "failed_attempts": _handoff_historical_items(sections["failed_attempts"]),
        "discoveries": _handoff_historical_items(sections["discoveries"]),
        "useful_commands": _session_handoff_commands(sections["useful_commands"]),
        "open_items": _handoff_historical_items(sections["open_items"]),
        "quality_report": quality,
    }


def _session_handoff_verification(
    items: Iterable[dict[str, Any]],
    *,
    requirements: list[dict[str, Any]],
    progress: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    progress_items = tuple(progress)
    reported_completion_requirement_ids = {
        requirement["id"]
        for requirement in requirements
        if any(
            _positive_completion_claim(str(progress_item.get("statement") or ""))
            and _statements_overlap(
                requirement["text"],
                str(progress_item.get("statement") or ""),
            )
            for progress_item in progress_items
        )
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        statement = str(item.get("statement") or "").strip()
        payload = item.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        command = str(payload.get("command") or "").strip()
        requirement_ids = [
            requirement["id"]
            for requirement in requirements
            if _verification_matches_requirement(
                command or statement,
                requirement["text"],
            )
        ]
        passed = payload.get("passed")
        exit_code = payload.get("exit_code")
        status = (
            "passed"
            if passed is True
            else "failed"
            if passed is False
            else str(item.get("state") or "").strip().lower() or "observed"
        )
        observed_at = payload.get("observed_at")
        if observed_at is None:
            observed_at = next(
                (
                    evidence.get("observed_at")
                    for evidence in reversed(item.get("evidence") or [])
                    if evidence.get("observed_at") is not None
                ),
                None,
            )
        scope = next(
            (
                payload.get(key)
                for key in ("scope", "test_scope", "verification_scope", "target")
                if payload.get(key) not in (None, "")
            ),
            None,
        )
        scope_kind = _verification_scope_kind(
            command=command,
            scope=_handoff_scalar(scope),
        )
        link_kind = "direct" if requirement_ids else "unmapped"
        if (
            not requirement_ids
            and len(reported_completion_requirement_ids) == 1
            and scope_kind in {"focused", "regression_safety"}
        ):
            # A component test or broad regression check can support the one
            # reported implementation scope without becoming direct proof of
            # the original user wording. Keep that distinction explicit.
            requirement_ids = sorted(reported_completion_requirement_ids)
            link_kind = "reported_scope_support" if scope_kind == "focused" else "regression_safety"
        result.append(
            {
                "id": f"V{index}",
                "statement": _redacted_historical_text(statement),
                "command": _redacted_historical_text(command).strip() or None,
                "cwd": (_redacted_historical_text(payload.get("cwd")).strip() or None),
                "exit_code": exit_code if isinstance(exit_code, int) else None,
                "passed": passed if isinstance(passed, bool) else None,
                "status": status,
                "observed_at": _handoff_scalar(observed_at),
                "scope": (_redacted_historical_text(_handoff_scalar(scope)).strip() or None),
                "truth_state": str(item.get("truth_state") or "observed"),
                "requirement_ids": requirement_ids,
                "link_kind": link_kind,
                "scope_kind": scope_kind,
            }
        )
    return result


def _verification_scope_kind(
    *,
    command: str,
    scope: str | None,
) -> str:
    """Classify check breadth without pretending it proves a requirement."""

    if scope:
        return "focused"
    normalized = re.sub(r"\s+", " ", command.casefold()).strip()
    if not normalized:
        return "observed"
    if (
        "::" in normalized
        or re.search(
            r"(?:^|\s)(?:[^ ]+/)?(?:test_[^ ]+|[^ ]+\.test\.[^ ]+|"
            r"[^ ]+\.spec\.[^ ]+)(?:$|\s)",
            normalized,
        )
        or re.search(r"\s--\s+\S+", normalized)
    ):
        return "focused"
    if re.fullmatch(
        r"(?:(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:build|lint|test)|"
        r"(?:python3?\s+-m\s+)?pytest(?:\s+-[a-z]+)*)",
        normalized,
    ):
        return "regression_safety"
    return "focused"


def _handoff_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return _canonical_json(value)
    rendered = str(value).strip()
    return rendered or None


def _verification_matches_requirement(
    verification_text: str,
    requirement_text: str,
) -> bool:
    verification_tokens = _status_tokens(verification_text)
    requirement_tokens = _status_tokens(requirement_text)
    shared = verification_tokens & requirement_tokens
    if len(shared) >= 2:
        return True
    requirement_paths = set(_extract_paths(requirement_text))
    verification_paths = set(_extract_paths(verification_text))
    if requirement_paths & verification_paths:
        return True
    return bool(
        shared
        and re.search(r"\b(?:test|tests|verify|verification|lint|build)\b", requirement_text, re.I)
    )


def _reconcile_session_handoff(
    *,
    requirements: list[dict[str, Any]],
    progress: Iterable[dict[str, Any]],
    next_actions: Iterable[dict[str, Any]],
    blockers: Iterable[dict[str, Any]],
    verification: list[dict[str, Any]],
    task_mode: str,
    fresh_user_lead: bool = False,
) -> dict[str, Any]:
    progress_items = list(progress)
    all_next_items = list(next_actions)
    next_items = [
        item
        for item in all_next_items
        if not _recovered_next_action_superseded_by_progress(
            item,
            progress_items=progress_items,
        )
    ]
    status_next_items = [
        item
        for item in next_items
        if (item.get("payload") or {}).get("derived_from_reconciliation") is not True
    ]
    superseded_next_items = [item for item in all_next_items if item not in next_items]
    blocker_items = [
        item
        for item in blockers
        if str(item.get("state") or "active").casefold() not in _INACTIVE_BLOCKER_STATES
    ]
    generic_completion = any(
        _GENERIC_COMPLETION_CLAIM_RE.fullmatch(str(item.get("statement") or "").strip())
        and _positive_completion_claim(str(item.get("statement") or ""))
        for item in progress_items
    )
    generic_next_items = [
        item
        for item in status_next_items
        if _GENERIC_CONTINUATION_RE.match(str(item.get("statement") or "").strip())
    ]
    generic_continuation = bool(generic_next_items)
    statuses: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    if generic_completion and generic_continuation:
        conflicts.append(
            {
                "code": "generic_completion_continuation_conflict",
                "requirement_id": None,
                "done_claims": [
                    str(item.get("statement") or "")
                    for item in progress_items
                    if _GENERIC_COMPLETION_CLAIM_RE.fullmatch(
                        str(item.get("statement") or "").strip()
                    )
                ],
                "remaining_claims": [
                    str(item.get("statement") or "")
                    for item in next_items
                    if _GENERIC_CONTINUATION_RE.match(str(item.get("statement") or "").strip())
                ],
                "failed_verification_ids": [],
            }
        )
    for requirement in requirements:
        done_claims = [
            item
            for item in progress_items
            if (
                _positive_completion_claim(str(item.get("statement") or ""))
                and _statements_overlap(
                    str(item.get("statement") or ""),
                    requirement["text"],
                )
            )
        ]
        scoped_remaining_claims = [
            item
            for item in status_next_items
            if (
                item not in generic_next_items
                and _statements_overlap(
                    str(item.get("statement") or ""),
                    requirement["text"],
                )
            )
        ]
        failed_verifiers = [
            item
            for item in verification
            if requirement["id"] in item["requirement_ids"] and item["passed"] is False
        ]
        if generic_completion and generic_continuation and not done_claims:
            status = "unknown"
            authority = "conflicting_agent_report"
            basis = (
                "A generic completion claim conflicts with a generic continuation "
                "instruction; neither is scoped enough to classify this requirement."
            )
        elif done_claims and (scoped_remaining_claims or failed_verifiers):
            status = "contradicted"
            authority = "mixed_reported_and_observed"
            basis = (
                "Agent-reported completion conflicts with a continuation action "
                "or failed observed check."
            )
            conflicts.append(
                {
                    "code": "completion_continuation_conflict",
                    "requirement_id": requirement["id"],
                    "done_claims": [str(item.get("statement") or "") for item in done_claims],
                    "remaining_claims": [
                        str(item.get("statement") or "") for item in scoped_remaining_claims
                    ],
                    "failed_verification_ids": [item["id"] for item in failed_verifiers],
                }
            )
        elif failed_verifiers or scoped_remaining_claims:
            status = "remaining"
            authority = "observed_verification" if failed_verifiers else "agent_reported"
            basis = "A scoped continuation action or failed observed check remains."
        elif done_claims:
            status = "reported_done"
            authority = "agent_reported"
            basis = (
                "Reported complete by the prior agent; repository confirmation is still required."
            )
        elif generic_continuation:
            status = "remaining"
            authority = "agent_reported"
            basis = (
                "A generic continuation fallback applies because no scoped "
                "completion evidence was captured for this requirement."
            )
        elif fresh_user_lead:
            status = "remaining"
            authority = "current_user_authored"
            basis = "The current user-authored continuation lead requests this work."
        else:
            status = "unknown"
            authority = "none"
            basis = "No captured evidence proves completion or remaining work."
        statuses.append(
            {
                "requirement_id": requirement["id"],
                "status": status,
                "basis": basis,
                "authority": authority,
            }
        )

    counts = {
        state: sum(item["status"] == state for item in statuses)
        for state in (
            "done",
            "reported_done",
            "remaining",
            "unknown",
            "contradicted",
        )
    }
    if conflicts:
        state = "needs_reconciliation"
        affected_requirement_ids = [
            item["requirement_id"] for item in statuses if item["status"] == "contradicted"
        ] or [item["requirement_id"] for item in statuses]
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Inspect the current repository and reconcile the conflicting "
                    "completion and continuation claims against "
                    f"{', '.join(affected_requirement_ids)}. "
                    "Then implement and verify only the requirements still unmet."
                ),
                read_only_text=(
                    "Inspect the current repository and reconcile the conflicting "
                    "completion and continuation claims against "
                    f"{', '.join(affected_requirement_ids)}. Complete the requested "
                    f"{task_mode} without editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif blocker_items:
        state = "blocked_reported"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Confirm whether the reported blocker still exists in the current "
                    "runtime; resolve it if possible, then continue the unmet requirements."
                ),
                read_only_text=(
                    "Confirm whether the reported blocker still affects the requested "
                    f"{task_mode}; document the evidence without editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif counts["remaining"]:
        state = "in_progress"
        reported_done_ids = [
            item["requirement_id"] for item in statuses if item["status"] == "reported_done"
        ]
        remaining_ids = [
            item["requirement_id"] for item in statuses if item["status"] == "remaining"
        ]
        unknown_ids = [item["requirement_id"] for item in statuses if item["status"] == "unknown"]
        reported_done_text = ", ".join(reported_done_ids)
        remaining_text = ", ".join(remaining_ids)
        unknown_suffix = (
            f" Classify {', '.join(unknown_ids)} from current evidence as well."
            if unknown_ids
            else ""
        )
        if reported_done_ids:
            change_text = (
                f"Verify {reported_done_text} against the current repository, "
                f"then complete and verify {remaining_text}."
                f"{unknown_suffix}"
            )
            read_only_text = (
                f"Validate {reported_done_text} against the current repository, "
                f"then complete the requested {task_mode} for {remaining_text} "
                f"without editing files.{unknown_suffix}"
            )
        else:
            change_text = f"Complete and verify {remaining_text}.{unknown_suffix}"
            read_only_text = (
                f"Complete the requested {task_mode} for {remaining_text} "
                f"without editing files.{unknown_suffix}"
            )
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=change_text,
                read_only_text=read_only_text,
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif counts["unknown"]:
        state = "unknown"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Inspect the current repository, verify every reported-done "
                    "requirement, classify every unknown requirement as done or "
                    "remaining using observed evidence, then complete and verify "
                    "the unmet work."
                ),
                read_only_text=(
                    "Inspect the current repository, validate every reported-done "
                    "conclusion, and classify every unknown requirement using "
                    f"observed evidence. Complete the requested {task_mode} without "
                    "editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    else:
        state = "complete_reported"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Verify every reported-complete requirement against the current "
                    "repository and linked checks before declaring the task complete."
                ),
                read_only_text=(
                    "Validate every reported conclusion against the current repository "
                    f"before completing the requested {task_mode}; do not edit files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    return {
        "state": state,
        "counts": counts,
        "requirements": statuses,
        "conflicts": conflicts,
        "superseded_next_actions": _handoff_historical_items(superseded_next_items),
        "active_reported_blockers": _handoff_historical_items(blocker_items),
        "exact_next_action": next_action,
    }


def _recovered_next_action_superseded_by_progress(
    item: dict[str, Any],
    *,
    progress_items: Iterable[dict[str, Any]],
) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("derived_from_recovered_goal") is not True:
        return False
    next_sequence = _item_sequence(item)
    if next_sequence is None:
        return False
    return any(
        progress_sequence > next_sequence
        and _positive_completion_claim(str(progress_item.get("statement") or ""))
        for progress_item in progress_items
        if (progress_sequence := _item_sequence(progress_item)) is not None
    )


def _mode_safe_next_action(
    task_mode: str,
    *,
    change_text: str,
    read_only_text: str,
) -> str:
    return change_text if task_mode == "change" else read_only_text


def _positive_completion_claim(statement: str) -> bool:
    return bool(
        _COMPLETION_CLAIM_RE.search(statement) and not _NEGATED_COMPLETION_RE.search(statement)
    )


def _statements_overlap(first: str, second: str) -> bool:
    first_tokens = _status_tokens(first)
    second_tokens = _status_tokens(second)
    shared = first_tokens & second_tokens
    if len(shared) >= 2:
        return True
    if shared and set(_extract_paths(first)) & set(_extract_paths(second)):
        return True
    # A single distinctive token is enough only when one side has no other
    # semantic token. Otherwise broad words such as "context", "preview", or
    # "session" can falsely promote a sibling requirement to done.
    return bool(len(shared) == 1 and min(len(first_tokens), len(second_tokens)) == 1)


def _status_tokens(value: str) -> set[str]:
    tokens = {
        _STATUS_TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9][a-z0-9_]{2,}", value.casefold())
    }
    return {token for token in tokens if token not in _STATUS_MATCH_STOPWORDS}


def _reported_requirement_scope_hints(
    requirement_text: str,
    *,
    progress: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep prior-agent scope interpretations visible without promoting them."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in progress:
        statement = str(item.get("statement") or "").strip()
        if (
            not statement
            or not _positive_completion_claim(statement)
            or not _statements_overlap(statement, requirement_text)
        ):
            continue
        key = re.sub(r"\W+", " ", statement.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "text": statement,
                "authority": "agent_reported",
                "verified": False,
            }
        )
    return result


def _repository_snapshot_time(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    normalized = str(value or "").strip()
    return normalized or None


def _protected_baseline_entries_valid(
    entries: list[Any],
    *,
    object_format: str,
    changed_files: Iterable[Any],
) -> bool:
    oid_length = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    if not oid_length:
        return False
    oid_pattern = re.compile(rf"[0-9a-f]{{{oid_length}}}")
    sha256_pattern = re.compile(r"[0-9a-f]{64}")
    seen_records: set[tuple[str, str]] = set()
    manifest_paths: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            return False
        path = str(raw.get("path") or "")
        xy = str(raw.get("xy") or "")
        if (
            not path
            or len(xy) != 2
            or any(character not in " MTADRCU?!" for character in xy)
            or (path, xy) in seen_records
            or str(raw.get("index_status") or "") != xy[0]
            or str(raw.get("worktree_status") or "") != xy[1]
        ):
            return False
        seen_records.add((path, xy))
        manifest_paths.add(path)
        head = raw.get("head")
        index = raw.get("index")
        worktree = raw.get("worktree")
        if not all(isinstance(layer, dict) for layer in (head, index, worktree)):
            return False
        if head.get("state") == "present":
            if oid_pattern.fullmatch(str(head.get("object_id") or "")) is None:
                return False
        elif head.get("state") != "absent":
            return False
        stages = index.get("stages")
        if not isinstance(stages, list):
            return False
        if index.get("state") == "present":
            if (
                not stages
                or any(
                    not isinstance(stage, dict)
                    or stage.get("stage") not in {0, 1, 2, 3}
                    or oid_pattern.fullmatch(str(stage.get("object_id") or "")) is None
                    for stage in stages
                )
                or len({stage["stage"] for stage in stages}) != len(stages)
            ):
                return False
        elif index.get("state") != "absent" or stages:
            return False
        if worktree.get("state") == "present":
            file_type = str(worktree.get("file_type") or "")
            if file_type in {"file", "symlink"}:
                if sha256_pattern.fullmatch(str(worktree.get("content_sha256") or "")) is None:
                    return False
            elif file_type == "submodule":
                if oid_pattern.fullmatch(str(worktree.get("object_id") or "")) is None:
                    return False
            else:
                return False
        elif worktree.get("state") != "absent":
            return False
    expected_paths = {str(path) for path in changed_files if str(path) != ""}
    return not expected_paths or manifest_paths == expected_paths


def _repository_baseline_manifest(
    repository: dict[str, Any],
    *,
    captured_at: Any,
) -> dict[str, Any]:
    """Embed an exact, portable description of the protected dirty baseline."""

    exact = repository.get("protected_baseline")
    if isinstance(exact, dict) and isinstance(exact.get("entries"), list):
        exact_unsigned = {
            "schema_version": exact.get("schema_version"),
            "complete": exact.get("complete"),
            "entry_count": exact.get("entry_count"),
            "git_object_format": exact.get("git_object_format"),
            "head_commit": exact.get("head_commit"),
            "entries": exact.get("entries"),
        }
        computed_manifest_sha256 = hashlib.sha256(
            json.dumps(
                exact_unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8", errors="surrogateescape")
        ).hexdigest()
        exact_entries: list[dict[str, Any]] = []
        for item in exact.get("entries") or []:
            if not isinstance(item, dict) or str(item.get("path") or "") == "":
                continue
            xy = str(item.get("xy") or "")
            safe_xy = xy if len(xy) == 2 else "??"
            exact_entries.append(
                {
                    **item,
                    "index_status": str(item.get("index_status") or safe_xy[0]),
                    "worktree_status": str(item.get("worktree_status") or safe_xy[1]),
                    "content_hash": (
                        (item.get("worktree") or {}).get("content_sha256")
                        if isinstance(item.get("worktree"), dict)
                        else None
                    ),
                }
            )
        exact_entries.sort(key=lambda item: str(item.get("path") or ""))
        manifest_sha256 = str(exact.get("manifest_sha256") or "").strip()
        object_format = str(exact.get("git_object_format") or "")
        expected_manifest_id = (
            f"PB-{computed_manifest_sha256[:12]}" if computed_manifest_sha256 else "PB-unavailable"
        )
        stored_manifest_id = str(exact.get("id") or "").strip()
        integrity_valid = bool(
            manifest_sha256
            and manifest_sha256 == computed_manifest_sha256
            and exact.get("schema_version") == "protected_baseline.v1"
            and exact.get("complete") is True
            and int(exact.get("entry_count") or 0) == len(exact_entries)
            and str(exact.get("head_commit") or "") == str(repository.get("head_commit") or "")
            and repository.get("status_truncated") is False
            and (not stored_manifest_id or stored_manifest_id == expected_manifest_id)
            and _protected_baseline_entries_valid(
                list(exact.get("entries") or []),
                object_format=object_format,
                changed_files=repository.get("changed_files") or [],
            )
        )
        manifest_id = expected_manifest_id
        return {
            **exact,
            "id": manifest_id,
            "portable_reference": f"handoff://repository-snapshots/{manifest_id}",
            "captured_branch": repository.get("branch"),
            "captured_head": repository.get("head_commit"),
            "captured_at": _repository_snapshot_time(captured_at),
            "status_fingerprint": repository.get("status_fingerprint"),
            "status_truncated": bool(repository.get("status_truncated", False)),
            "complete": bool(
                exact.get("complete") is True
                and repository.get("status_truncated") is not True
                and integrity_valid
            ),
            "integrity_valid": integrity_valid,
            "entry_count": len(exact_entries),
            "working_tree": exact_entries,
            "path_semantics": "repository_relative",
            "status_semantics": "git_porcelain_v1_xy",
            "content_hash_semantics": "exact_sha256_of_captured_worktree_bytes",
            "index_identity_semantics": "git_object_id_and_stage",
        }

    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw in repository.get("changed_file_entries") or []:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        if not path or path in seen_paths:
            continue
        xy = str(raw.get("xy") or raw.get("status") or "")
        if len(xy) == 1:
            xy = f" {xy}"
        if len(xy) != 2:
            xy = "??"
        digest = str(raw.get("content_hash") or raw.get("sha256") or "").strip()
        entries.append(
            {
                "path": path,
                "xy": xy,
                "index_status": str(raw.get("index_status") or xy[0]),
                "worktree_status": str(raw.get("worktree_status") or xy[1]),
                "change_kind": str(raw.get("change_kind") or "changed"),
                "content_hash": digest or None,
            }
        )
        seen_paths.add(path)
    entries.sort(key=lambda item: str(item["path"]))
    capture_time = _repository_snapshot_time(captured_at)
    # Legacy snapshots bind only a bounded worktree digest. They remain useful
    # provenance, but are not an exact index/worktree baseline.
    complete = False
    manifest_payload = {
        "root": repository.get("root"),
        "captured_branch": repository.get("branch"),
        "captured_head": repository.get("head_commit"),
        "captured_at": capture_time,
        "status_fingerprint": repository.get("status_fingerprint"),
        "complete": complete,
        "working_tree": entries,
    }
    manifest_sha256 = _sha256(
        json.dumps(
            manifest_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    snapshot_id = f"WT-{manifest_sha256[:12]}"
    return {
        "schema_version": "repository_baseline_manifest.v1",
        "id": snapshot_id,
        "portable_reference": f"handoff://repository-snapshots/{snapshot_id}",
        "manifest_sha256": manifest_sha256,
        "captured_branch": repository.get("branch"),
        "captured_head": repository.get("head_commit"),
        "captured_at": capture_time,
        "status_fingerprint": repository.get("status_fingerprint"),
        "status_truncated": bool(repository.get("status_truncated", False)),
        "complete": complete,
        "entry_count": len(entries),
        "working_tree": entries,
        "path_semantics": "repository_relative",
        "status_semantics": "git_porcelain_v1_xy",
        "content_hash_semantics": "sha256_of_captured_worktree_file_when_readable",
    }


def _session_handoff_repository(
    data: dict[str, Any],
    *,
    repository_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = data.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    payload_repo = payload.get("repo")
    payload_repo = payload_repo if isinstance(payload_repo, dict) else {}
    stable_repo = data.get("repo")
    stable_repo = stable_repo if isinstance(stable_repo, dict) else {}
    captured = {
        "root": stable_repo.get("root") or payload_repo.get("root"),
        "branch": stable_repo.get("branch") or payload_repo.get("branch"),
        "head_commit": (stable_repo.get("head_commit") or payload_repo.get("head_commit")),
        "status_fingerprint": (
            stable_repo.get("worktree_fingerprint") or payload_repo.get("status_fingerprint")
        ),
        "dirty": payload_repo.get("dirty"),
        "changed_files": list(payload_repo.get("changed_files") or []),
        "changed_file_entries": list(payload_repo.get("changed_file_entries") or []),
        "protected_baseline": payload_repo.get("protected_baseline"),
        "captured_at": payload_repo.get("captured_at"),
        "diff_summary": payload_repo.get("diff_summary"),
        "status_truncated": payload_repo.get("status_truncated"),
        "snapshot_authority": "observed_at_checkpoint",
    }
    comparison = repository_comparison if isinstance(repository_comparison, dict) else {}
    current = comparison.get("current")
    current = current if isinstance(current, dict) else None
    freshness_status = str(comparison.get("status") or "unavailable").strip().lower()
    active = current or captured
    captured_at = (
        current.get("captured_at") or comparison.get("checked_at")
        if current is not None
        else captured.get("captured_at")
        or (data.get("boundary") or {}).get("captured_at")
        or (data.get("boundary") or {}).get("occurred_at")
    )
    baseline_manifest = _repository_baseline_manifest(
        active,
        captured_at=captured_at,
    )
    return {
        **active,
        "captured_at": _repository_snapshot_time(captured_at),
        "snapshot_authority": (
            "observed_at_handoff" if current is not None else "observed_at_checkpoint"
        ),
        "protected_baseline_manifest": baseline_manifest,
        "freshness": {
            "status": freshness_status,
            "reason": str(comparison.get("reason") or "").strip() or None,
            "checked_at": comparison.get("checked_at"),
            "captured_head_commit": captured.get("head_commit"),
            "current_head_commit": (current.get("head_commit") if current is not None else None),
        },
        "captured_snapshot": captured,
    }


def _session_handoff_files(
    relevant_items: Iterable[dict[str, Any]],
    progress_items: Iterable[dict[str, Any]],
    *,
    repository: dict[str, Any],
) -> dict[str, Any]:
    relevant_entries = list(relevant_items)
    progress_paths = {
        path for item in progress_items for path in _extract_paths(str(item.get("statement") or ""))
    }
    changed_paths = {str(path) for path in repository.get("changed_files") or [] if str(path) != ""}
    baseline_manifest = repository.get("protected_baseline_manifest") or {}
    manifest_records_by_path: dict[str, list[dict[str, Any]]] = {}
    for item in baseline_manifest.get("working_tree") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path != "":
            manifest_records_by_path.setdefault(path, []).append(item)
    modified = sorted(progress_paths & changed_paths)
    relevant = sorted(
        {
            str(item.get("payload", {}).get("path") or item.get("statement") or "").strip()
            for item in relevant_entries
            if str(item.get("payload", {}).get("path") or item.get("statement") or "").strip()
        }
        - set(modified)
    )
    return {
        "modified": [
            {
                "path": path,
                "truth_state": "reported_plus_dirty_snapshot",
                "note": (
                    "The prior agent reported implementation work here and the "
                    "file was changed at capture; authorship is not independently proven."
                ),
            }
            for path in modified
        ],
        "relevant": [
            {
                "path": path,
                "truth_state": next(
                    (
                        str(item.get("truth_state") or "reported")
                        for item in relevant_entries
                        if str(
                            item.get("payload", {}).get("path") or item.get("statement") or ""
                        ).strip()
                        == path
                    ),
                    "reported",
                ),
            }
            for path in relevant
        ],
        "pre_existing_at_handoff": [
            {
                "path": path,
                "truth_state": "observed",
                "preservation_rule": (
                    "Preserve every captured index and worktree change. If this is the "
                    "affected target, add only the minimum requirement-specific delta "
                    "without staging, unstaging, reverting, or reformatting the whole file."
                ),
                "status": (manifest_records_by_path.get(path) or [{}])[0].get("xy"),
                "xy": (manifest_records_by_path.get(path) or [{}])[0].get("xy"),
                "statuses": [
                    str(item.get("xy") or "") for item in manifest_records_by_path.get(path, [])
                ],
                "records": [
                    {
                        "xy": item.get("xy"),
                        "index_status": item.get("index_status"),
                        "worktree_status": item.get("worktree_status"),
                        "change_kind": item.get("change_kind"),
                        "content_hash": item.get("content_hash"),
                    }
                    for item in manifest_records_by_path.get(path, [])
                ],
                "index_status": (manifest_records_by_path.get(path) or [{}])[0].get("index_status"),
                "worktree_status": (manifest_records_by_path.get(path) or [{}])[0].get(
                    "worktree_status"
                ),
                "change_kind": (manifest_records_by_path.get(path) or [{}])[0].get("change_kind"),
                "content_hash": (manifest_records_by_path.get(path) or [{}])[0].get("content_hash"),
                "sha256": (manifest_records_by_path.get(path) or [{}])[0].get("content_hash"),
            }
            for path in sorted(changed_paths)
        ],
        "classification_note": (
            "Pre-existing means changed before the receiving session starts. It "
            "does not prove whether the prior session or the user authored the change."
        ),
    }


def _session_handoff_rendered_files(
    files: dict[str, Any],
    *,
    limit: int = SESSION_HANDOFF_RENDERED_FILE_LIMIT,
) -> dict[str, Any]:
    """Build a compact view without mutating or truncating the typed contract."""

    records: dict[str, dict[str, Any]] = {}

    def include(
        item: dict[str, Any],
        *,
        classification: str,
        preserve: bool = False,
    ) -> None:
        path = str(item.get("path") or "").strip()
        if not path:
            return
        record = records.setdefault(
            path,
            {
                "path": path,
                "classifications": [],
                "preserve": False,
            },
        )
        if classification not in record["classifications"]:
            record["classifications"].append(classification)
        record["preserve"] = bool(record["preserve"] or preserve)

    for item in files.get("modified") or []:
        include(
            item,
            classification=(
                "reported modified + observed dirty"
                if item.get("truth_state") == "reported_plus_dirty_snapshot"
                else f"modified ({item.get('truth_state') or 'reported'})"
            ),
        )
    for item in files.get("relevant") or []:
        include(
            item,
            classification=f"relevant ({item.get('truth_state') or 'reported'})",
        )
    for item in files.get("pre_existing_at_handoff") or []:
        include(
            item,
            classification="observed dirty at handoff",
            preserve=True,
        )

    bounded_limit = max(1, int(limit))
    materialized = list(records.values())
    return {
        "items": materialized[:bounded_limit],
        "unique_count": len(materialized),
        "shown_count": min(len(materialized), bounded_limit),
        "omitted_count": max(0, len(materialized) - bounded_limit),
    }


def _session_handoff_definition_of_done(
    requirements: list[dict[str, Any]],
    *,
    repository: dict[str, Any],
) -> dict[str, Any]:
    explicit = [
        {
            "text": requirement["text"],
            "requirement_ids": [requirement["id"]],
            "source": requirement["source"],
            "authority": requirement["authority"],
        }
        for requirement in requirements
        if requirement.get("explicit_acceptance")
    ]
    operational = [
        {
            "text": (
                "Every accepted requirement is observed complete or has an explicit "
                "non-recoverable blocker, with requirement-linked verification where applicable."
            ),
            "requirement_ids": [item["id"] for item in requirements],
            "source": "session_handoff_policy",
            "authority": "derived_policy",
        }
    ]
    if repository.get("changed_files"):
        operational.append(
            {
                "text": (
                    "Do not stage, unstage, revert, overwrite, or reformat unrelated "
                    "pre-existing changes. Preserve their captured index and "
                    "working-tree states."
                ),
                "requirement_ids": [],
                "source": "session_handoff_policy",
                "authority": "derived_policy",
            }
        )
    return {
        "explicit": explicit,
        "operational": operational,
        "explicitly_provided": bool(explicit),
    }


def _session_handoff_verification_plan(
    *,
    task_mode: str,
    intent: dict[str, Any],
    requirements: list[dict[str, Any]],
    attachment_dependencies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create future-facing checks without presenting them as completed proof."""

    requirement_ids = [
        str(item.get("id") or "")
        for item in requirements
        if str(item.get("id") or "")
        and not item.get("explicit_acceptance")
        and item.get("completion_relevant") is not False
    ]
    required_attachments = [
        item for item in attachment_dependencies if item.get("required") is True
    ]
    plan: list[dict[str, Any]] = []

    def add(text: str, *, links: list[str] | None = None) -> None:
        plan.append(
            {
                "id": f"PV{len(plan) + 1}",
                "text": text,
                "status": "planned",
                "requirement_ids": list(requirement_ids if links is None else links),
                "source": "session_handoff_policy",
            }
        )

    if required_attachments:
        attachment_ids = ", ".join(str(item.get("id") or "") for item in required_attachments)
        add(
            f"Inspect required attachment {attachment_ids} before choosing the affected "
            "component, and compare the finished result against that exact evidence."
        )
    opacity_requirements = [
        item
        for item in requirements
        if "opaque" in str(item.get("text") or "").casefold()
        or "transparent" in str(item.get("text") or "").casefold()
    ]
    if task_mode == "change" and opacity_requirements:
        opacity_target = _opaque_outcome_target(str(opacity_requirements[0].get("text") or ""))
        opacity_plural, opacity_pronoun, _state_verb = _opaque_target_grammar(opacity_target)
        add(
            f"Verify the affected {opacity_target} in the running UI and confirm "
            f"the page behind {opacity_pronoun} is not visible through "
            f"{'their backgrounds' if opacity_plural else 'its background'}."
        )
        add(
            "Check default, hover, selected, and focus states where those states "
            "exist; record any state that could not be exercised."
        )
    elif task_mode == "change":
        add(
            "Exercise every observable acceptance criterion against the current "
            "implementation and record the result."
        )
    if task_mode == "change":
        add(
            "Review the final diff and confirm it contains only changes necessary "
            "for the accepted requirements. If a shared component, token, or ancestor "
            "style changed, inspect and report every affected usage. Preserve the "
            "captured index and working-tree state of unrelated work.",
            links=[],
        )
        add(
            "Report the exact files changed and the checks performed; do not claim "
            "completion for an uninspected state or unavailable artifact."
        )
    return plan


def _session_handoff_quality(
    *,
    dependency_required: bool,
    supporting_context: list[dict[str, str]],
    attachment_dependencies: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    repository: dict[str, Any],
    verification: list[dict[str, Any]],
    currentness: dict[str, Any] | None,
    boundary: dict[str, Any] | None,
    task_mode: str,
    readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readiness = readiness if isinstance(readiness, dict) else {}
    currentness = currentness if isinstance(currentness, dict) else {}
    boundary = boundary if isinstance(boundary, dict) else {}
    requirement_ids = {str(item.get("id") or "") for item in requirements if item.get("id")}
    verified_requirement_ids = {
        requirement_id for item in verification for requirement_id in item["requirement_ids"]
    }
    missing_verification_ids = sorted(requirement_ids - verified_requirement_ids)
    unavailable_required_attachments = [
        item
        for item in attachment_dependencies
        if item.get("required") is True
        and (item.get("available") is not True or not item.get("sha256"))
    ]
    unavailable_historical_attachments = [
        item
        for item in attachment_dependencies
        if item.get("required") is not True
        and (item.get("available") is not True or not item.get("sha256"))
    ]
    unmapped_required_attachments = [
        item
        for item in attachment_dependencies
        if item.get("required") is True and not item.get("requirement_ids")
    ]
    receiver_unavailable_required_attachments = [
        item
        for item in attachment_dependencies
        if item.get("required") is True
        and str(item.get("receiver_availability") or "") != "available"
    ]
    checks = [
        {
            "code": "goal_self_contained",
            "status": ("pass" if not dependency_required or supporting_context else "fail"),
        },
        {
            "code": "requirements_present",
            "status": "pass" if requirements else "fail",
        },
        {
            "code": "required_attachments_resolved",
            "status": ("fail" if unavailable_required_attachments else "pass"),
            "missing_attachment_ids": [
                str(item.get("id") or "") for item in unavailable_required_attachments
            ],
            "message": (
                "One or more user-declared attachments have no trusted, "
                "hash-verified descriptor; Session Context cannot safely "
                "carry the visual dependency."
                if unavailable_required_attachments
                else "All required attachments were captured and hash-verified."
            ),
        },
        {
            "code": "required_attachments_available_in_receiver",
            "status": "warning" if receiver_unavailable_required_attachments else "pass",
            "attachment_ids": [
                str(item.get("id") or "") for item in receiver_unavailable_required_attachments
            ],
            "message": (
                "Required attachments are not yet materialized and hash-verified "
                "in the receiving session."
                if receiver_unavailable_required_attachments
                else "Required attachments are available in the receiving session."
            ),
        },
        {
            "code": "required_attachment_requirement_linkage",
            "status": "fail" if unmapped_required_attachments else "pass",
            "unmapped_attachment_ids": [
                str(item.get("id") or "") for item in unmapped_required_attachments
            ],
            "message": (
                "Required attachment evidence could not be mapped to one unambiguous user outcome."
                if unmapped_required_attachments
                else "Every required attachment supports a user-authored outcome."
            ),
        },
        {
            "code": "status_reconciled",
            "status": "pass",
        },
        {
            "code": "exact_next_action_present",
            "status": (
                "pass" if reconciliation.get("exact_next_action", {}).get("text") else "fail"
            ),
        },
        {
            "code": "repository_snapshot_present",
            "status": (
                "pass" if repository.get("root") else "fail" if task_mode == "change" else "warning"
            ),
        },
        {
            "code": "repository_status_capture_complete",
            "status": (
                "warning"
                if not repository.get("root")
                else "fail"
                if repository.get("status_truncated") is True
                else "pass"
            ),
        },
        {
            "code": "repository_protected_baseline_exact",
            "status": (
                "pass"
                if not repository.get("dirty")
                or (repository.get("protected_baseline_manifest") or {}).get("complete") is True
                else "fail"
                if (repository.get("protected_baseline") or {}).get("schema_version")
                == "protected_baseline.v1"
                else "warning"
            ),
            "manifest_id": (repository.get("protected_baseline_manifest") or {}).get("id"),
            "message": (
                "The protected baseline binds exact Git index stages and worktree bytes."
                if (repository.get("protected_baseline_manifest") or {}).get("complete") is True
                else "The repository baseline is legacy or incomplete; recapture it before execution."
            ),
        },
        {
            "code": "repository_current_at_handoff",
            "status": (
                "pass"
                if repository.get("snapshot_authority") == "observed_at_handoff"
                else "warning"
            ),
            "freshness": repository.get("freshness", {}).get("status"),
        },
        {
            "code": "session_boundary_current",
            "status": (
                "fail"
                if boundary.get("has_newer_events") is True
                or currentness.get("state") == "superseded"
                else "pass"
            ),
        },
        {
            "code": "requirement_verification_linkage",
            "status": ("pass" if requirement_ids and not missing_verification_ids else "warning"),
            "covered_requirement_ids": sorted(verified_requirement_ids),
            "missing_requirement_ids": missing_verification_ids,
        },
        {
            "code": "execution_readiness",
            "status": ("pass" if readiness.get("status") == "execution_ready" else "warning"),
            "readiness_status": readiness.get("status") or "unknown",
            "score": readiness.get("score"),
        },
    ]
    blocking = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warning"]
    if unavailable_historical_attachments:
        warnings.append(
            {
                "code": "historical_attachment_unavailable",
                "status": "warning",
                "attachment_ids": [
                    str(item.get("id") or "") for item in unavailable_historical_attachments
                ],
                "message": (
                    "One or more historical visual references were not durably "
                    "captured. The synthesized Session Context remains copyable; "
                    "reattach the visual only if exact reinspection is needed."
                ),
            }
        )
    if reconciliation["conflicts"]:
        blocking.append(
            {
                "code": "completion_continuation_conflict_reconciled",
                "status": "fail",
                "count": len(reconciliation["conflicts"]),
                "message": (
                    "Reported completion conflicts with a continuation instruction; "
                    "inspect the preview and recapture after the conflict is resolved."
                ),
            }
        )
    if repository.get("freshness", {}).get("status") == "changed":
        warnings.append(
            {
                "code": "repository_changed_since_checkpoint",
                "status": "warning",
                "message": (
                    "The handoff includes the current repository snapshot, but "
                    "prior session completion claims require fresh confirmation."
                ),
            }
        )
    copy_ready = not blocking
    automatic_execution_ready = bool(
        copy_ready
        and not reconciliation["conflicts"]
        and reconciliation["counts"]["unknown"] == 0
        and reconciliation["counts"]["reported_done"] == 0
        and repository.get("root")
        and not warnings
        and readiness.get("status") == "execution_ready"
        and task_mode in {"change", "diagnose", "plan", "report", "review", "test_only"}
    )
    return {
        "status": ("blocked" if blocking else "review_required" if warnings else "ready"),
        "copy_ready": copy_ready,
        "automatic_execution_ready": automatic_execution_ready,
        "checks": checks,
        "blocking_issues": blocking,
        "warnings": warnings,
    }


def _redacted_historical_text(value: Any) -> str:
    redacted = redact_sensitive_text(str(value or "")) or ""
    return _SESSION_CONTEXT_EXTRA_SECRET.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]{match.group(3)}",
        redacted,
    )


def _redacted_historical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redacted_historical_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redacted_historical_value(child) for child in value]
    if isinstance(value, tuple):
        return [_redacted_historical_value(child) for child in value]
    if isinstance(value, str):
        return _redacted_historical_text(value)
    return value


def _handoff_historical_items(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        raw_payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
        payload = _redacted_historical_value(raw_payload)
        result.append(
            {
                "statement": _redacted_historical_text(item.get("statement")),
                "state": str(item.get("state") or "active"),
                "truth_state": str(item.get("truth_state") or "reported"),
                "payload": payload,
                "evidence": list(item.get("evidence") or []),
            }
        )
    return result


def _session_handoff_commands(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        command = _redacted_historical_text(payload.get("command")).strip() or None
        result.append(
            {
                "id": f"C{index}",
                "command": command,
                "cwd": (
                    _redacted_historical_text(_handoff_scalar(payload.get("cwd"))).strip() or None
                ),
                "purpose": (
                    "verification"
                    if command and _is_useful_verification_command(command)
                    else "discovery"
                ),
                "result_summary": (
                    _redacted_historical_text(payload.get("result_summary")).strip() or None
                ),
                "exit_code": (
                    payload.get("exit_code")
                    if isinstance(payload.get("exit_code"), int)
                    and not isinstance(payload.get("exit_code"), bool)
                    else None
                ),
                "passed": (
                    payload.get("passed") if isinstance(payload.get("passed"), bool) else None
                ),
                "status": str(item.get("state") or "observed"),
                "truth_state": str(item.get("truth_state") or "observed"),
            }
        )
    return result


def _handoff_presentation_sections(
    sections: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    projected = {category: list(sections.get(category) or []) for category in CHECKPOINT_CATEGORIES}
    projected["blockers"] = [
        item
        for item in projected["blockers"]
        if not (
            _DERIVED_COMMAND_BLOCKER.fullmatch(str(item.get("statement") or "").strip())
            and str(item.get("payload", {}).get("command") or "").strip()
        )
    ]
    goal_payload = (
        projected["goal"][-1].get("payload")
        if projected["goal"] and isinstance(projected["goal"][-1].get("payload"), dict)
        else {}
    )
    requirement_texts = [
        str(item.get("text") or "").strip()
        for item in goal_payload.get("requirements") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    cleaned_decisions: list[dict[str, Any]] = []
    for raw_item in projected["decisions"]:
        statement = _self_contained_goal(str(raw_item.get("statement") or ""))
        if (
            not statement
            or _is_tool_selection_statement(statement)
            or any(
                _presentation_duplicate(statement, requirement) for requirement in requirement_texts
            )
        ):
            continue
        cleaned_decisions.append({**raw_item, "statement": statement})
    projected["decisions"] = _dedupe_presentation_items(cleaned_decisions)
    projected["discoveries"] = _dedupe_presentation_items(projected["discoveries"])
    projected["open_items"] = _dedupe_presentation_items(projected["open_items"])
    projected["useful_commands"] = _dedupe_command_observations(
        [
            item
            for item in projected["useful_commands"]
            if _has_definitive_verification_outcome(item)
            and (
                _is_useful_verification_command(
                    str((item.get("payload") or {}).get("command") or "")
                )
                or _is_useful_discovery_command(
                    str((item.get("payload") or {}).get("command") or "")
                )
            )
        ]
    )
    projected["verification"] = _dedupe_command_observations(
        [
            item
            for item in projected["verification"]
            if not _is_low_signal_failed_attempt(item)
            and _has_definitive_verification_outcome(item)
            and (
                not str((item.get("payload") or {}).get("command") or "").strip()
                or _is_useful_verification_command(
                    str((item.get("payload") or {}).get("command") or "")
                )
            )
        ]
    )
    passing_verification_sequences: dict[tuple[str, str], int] = {}
    for item in projected["verification"]:
        key = _command_observation_key(item)
        sequence = _item_sequence(item)
        if (
            key is None
            or sequence is None
            or not (
                (item.get("payload") or {}).get("passed") is True
                or str(item.get("state") or "").casefold() == "passed"
                or (item.get("payload") or {}).get("exit_code") == 0
            )
        ):
            continue
        passing_verification_sequences[key] = max(
            sequence,
            passing_verification_sequences.get(key, sequence),
        )
    projected["failed_attempts"] = _dedupe_command_observations(
        [
            item
            for item in projected["failed_attempts"]
            if not _is_low_signal_failed_attempt(item)
            and not (
                (key := _command_observation_key(item)) is not None
                and (failed_sequence := _item_sequence(item)) is not None
                and (passing_sequence := passing_verification_sequences.get(key)) is not None
                and passing_sequence > failed_sequence
            )
        ]
    )
    latest_completion_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if _positive_completion_claim(str(item.get("statement") or ""))
            and (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    projected["exact_next_action"] = [
        item
        for item in projected["exact_next_action"]
        if not _INTERNAL_TOOL_NEXT_ACTION.fullmatch(str(item.get("statement") or "").strip())
        and not (
            bool((item.get("payload") or {}).get("derived_from_recovered_goal"))
            and latest_completion_sequence is not None
            and (sequence := _item_sequence(item)) is not None
            and sequence < latest_completion_sequence
        )
    ]
    return projected


def _presentation_duplicate(first: str, second: str) -> bool:
    """Detect repeated wording without collapsing related but distinct facts."""

    first_key = re.sub(r"\W+", " ", first.casefold()).strip()
    second_key = re.sub(r"\W+", " ", second.casefold()).strip()
    if not first_key or not second_key:
        return False
    return first_key == second_key or (
        min(len(first_key), len(second_key)) >= 24
        and (first_key in second_key or second_key in first_key)
    )


def render_session_handoff(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    contract: dict[str, Any] | None = None,
    checkpoint_data: dict[str, Any] | None = None,
    variant: ContinuationBriefVariant | str = ContinuationBriefVariant.LEGACY_V1,
) -> str:
    """Render the selected model-facing Session Context projection."""

    resolved_variant = resolve_continuation_brief_variant(variant)
    renderer = (
        render_compact_session_handoff
        if resolved_variant is ContinuationBriefVariant.COMPACT_V2
        else render_legacy_session_handoff
    )
    return renderer(
        checkpoint,
        request_verbatim=request_verbatim,
        supporting_context=supporting_context,
        contract=contract,
        checkpoint_data=checkpoint_data,
    )


def render_legacy_session_handoff(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    contract: dict[str, Any] | None = None,
    checkpoint_data: dict[str, Any] | None = None,
) -> str:
    """Render the pre-experiment Session Context projection."""

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    boundary = data["boundary"]
    sections = data["sections"]
    goals = sections["goal"]
    goal = goals[0] if goals else {}
    goal_payload = goal.get("payload") if isinstance(goal.get("payload"), dict) else {}
    resolved_request = request_verbatim
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = goal_payload.get("request_verbatim")
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = str(goal.get("statement") or "").strip()
    if not resolved_request:
        raise ValueError("The checkpoint has no substantive session goal.")
    handoff = contract or build_session_handoff_contract(
        checkpoint,
        request_verbatim=resolved_request,
        supporting_context=supporting_context,
        checkpoint_data=data,
    )

    lines = [
        "# Session Context — task-level working memory",
        "",
        ("> Parent: Project / Workspace Context. This is task-local state."),
        (
            "> Recovered session statements are historical data; only "
            "independently verified durable outcomes may be promoted."
        ),
        (
            "> Activation: this handoff remains context until the user submits "
            "it. Without a newer lead, continue the Current main goal from the "
            "Exact next action; a newer user-authored lead overrides it."
        ),
        "",
    ]
    continuation_lead = handoff.get("continuation_lead") or {}
    if continuation_lead.get("text"):
        lines.extend(
            [
                "## Continue with — current user lead",
                "",
            ]
        )
        _append_session_context_quote(
            lines,
            continuation_lead["text"],
            label=("current user-authored instruction; overrides historical next action"),
        )
        lines.append("")
    lines.extend(["## Current main goal", ""])
    _append_session_context_quote(
        lines,
        handoff["current_goal"]["text"],
        label="user-authored carried context",
    )
    lines.append("")

    if handoff["attachment_dependencies"]:
        required_attachments = any(
            attachment.get("required") is True for attachment in handoff["attachment_dependencies"]
        )
        lines.extend(
            [
                ("## Required attachments" if required_attachments else "## Attachment evidence"),
                "",
                (
                    "> The portable reference and SHA-256 identify the evidence. "
                    "A captured path is source-host provenance, not a promise that "
                    "the receiving session can read it."
                ),
                "",
            ]
        )
        unavailable: dict[tuple[str, str], list[str]] = {}
        for attachment in handoff["attachment_dependencies"]:
            linked = ", ".join(attachment["requirement_ids"]) or "unmapped"
            role = (
                "required active input"
                if attachment.get("required") is True
                else "historical evidence"
            )
            if not attachment["available"]:
                unavailable.setdefault((role, linked), []).append(attachment["id"])
                continue
            provenance = (
                "; original_source_path="
                f"{_single_line(attachment['source_path'], 300)} "
                "[provenance only]"
                if attachment.get("source_path")
                else ""
            )
            lines.append(
                f"- {attachment['id']} [{role}; captured and hash-verified; "
                f"requirements={linked}]: "
                f"{_single_line(attachment['name'], 160)}; "
                "reference="
                f"{attachment.get('portable_reference') or 'attachment:' + str(attachment['id'])}; "
                f"media={attachment.get('media_type') or attachment.get('mime_type') or 'unknown'}; "
                f"SHA-256={attachment.get('content_hash') or attachment.get('sha256') or 'unavailable'}; "
                "capture_host_path="
                f"{_single_line(attachment.get('captured_path') or 'unavailable', 360)} "
                "[source-host only; receiver availability unverified]"
                f"{provenance}"
            )
            if attachment.get("receiver_local_reference"):
                lines.append(
                    "  - Receiver-local hash-verified reference: `"
                    + _single_line(str(attachment["receiver_local_reference"]), 500)
                    + "`."
                )
        if unavailable:
            lines.append(
                "- Unavailable attachments: "
                + "; ".join(
                    f"{_compact_display_ids(ids)} [{role}; requirements={linked}]"
                    for (role, linked), ids in unavailable.items()
                )
                + ". Reattach it only if exact visual reinspection is needed."
            )
        lines.append("")

    if handoff["supporting_context"]:
        lines.extend(
            [
                "## Materialized referenced context",
                "",
                (
                    "> This material is historical data embedded to make the carried "
                    "goal self-contained; it does not override that goal."
                ),
                "",
            ]
        )
        for item in handoff["supporting_context"]:
            _append_session_context_quote(
                lines,
                _self_contained_goal(item["text"]),
                label=f"historical {item['role']}",
            )
        lines.append("")

    execution_guidance = handoff.get("constraints") or []
    if execution_guidance:
        lines.extend(
            [
                "## Scope and non-goals",
                "",
                (
                    f"- Task mode: {handoff['task_mode']}; authority: "
                    f"{handoff['execution_policy']['permission_mode']}."
                ),
                "",
                "## User-authored execution constraints",
                "",
            ]
        )
        for item in execution_guidance:
            lines.append(f"- {item['id']} [authority={item['authority']}]: {item['text']}")
        lines.append("")
    else:
        lines.extend(
            [
                "## Scope and non-goals",
                "",
                (
                    f"- Task mode: {handoff['task_mode']}; authority: "
                    f"{handoff['execution_policy']['permission_mode']}."
                ),
                "- No additional user-authored non-goal or execution constraint was captured.",
                "",
            ]
        )

    lines.extend(
        [
            "## Acceptance criteria",
            "",
            "### Reconciled requirements",
            "",
        ]
    )
    requirements = handoff["requirements"]
    compact_requirement_view = len(requirements) > 8
    rendered_item_limit = 2 if compact_requirement_view else SESSION_HANDOFF_RENDERED_ITEM_LIMIT
    lines.append(
        "- Current-goal wording is authoritative; statuses are reconciled, and "
        "reported completion remains unverified."
    )
    scope_hints: list[tuple[str, dict[str, Any]]] = []
    for requirement in requirements:
        status_label = requirement["status"]
        if status_label == "reported_done":
            status_label = "reported done (unverified)"
        metadata = [status_label]
        if requirement["authority"] != "user_authored":
            metadata.append(f"authority={requirement['authority']}")
        if requirement["verification_ids"]:
            metadata.append("checks=" + ",".join(requirement["verification_ids"]))
        lines.append(f"- {requirement['id']} [{'; '.join(metadata)}]: {requirement['text']}")
        for hint in requirement.get("reported_scope_hints") or []:
            scope_hints.append((requirement["id"], hint))
        if not compact_requirement_view and requirement.get("reported_scope_hints"):
            hint = requirement["reported_scope_hints"][-1]
            _append_session_context_quote(
                lines,
                _historical_single_line(hint["text"], 1_000),
                label=("historical data; Prior-agent scope interpretation (unverified)"),
            )
    if compact_requirement_view and scope_hints:
        lines.append(
            f"- {len(scope_hints)} unverified prior-agent scope claim"
            f"{'' if len(scope_hints) == 1 else 's'} remain in the structured "
            "handoff; recent change reports below are the compact summary."
        )
    lines.append("")

    definition = handoff.get("definition_of_done") or {}
    lines.extend(["### Definition of done", ""])
    explicit_definition = definition.get("explicit") or []
    operational_definition = definition.get("operational") or []
    if compact_requirement_view and explicit_definition:
        explicit_ids = list(
            dict.fromkeys(
                requirement_id
                for item in explicit_definition
                for requirement_id in item.get("requirement_ids") or []
            )
        )
        lines.append(
            "- Explicit completion criteria: "
            f"{_compact_display_ids(explicit_ids)}; wording retained above."
        )
    elif explicit_definition:
        for item in explicit_definition:
            links = ", ".join(item.get("requirement_ids") or []) or "all/task"
            lines.append(f"- [{links}] {_single_line(str(item.get('text') or ''), 1_000)}")
    for item in operational_definition:
        requirement_ids = item.get("requirement_ids") or []
        links = _compact_display_ids(requirement_ids) or "all/task"
        definition_text = _single_line(str(item.get("text") or ""), 1_000)
        if definition_text.startswith("Every accepted requirement is observed"):
            definition_text = (
                "Complete every requirement or record a non-recoverable blocker with linked proof."
            )
        elif definition_text.startswith("All pre-existing changes"):
            definition_text = "Preserve all pre-existing changes."
        lines.append(f"- [{links}] {definition_text}")
    if not explicit_definition and not operational_definition:
        lines.append("- Complete and verify every accepted requirement.")
    lines.append("")

    reconciliation = handoff["reconciliation"]
    lines.extend(
        [
            "## Current state",
            "",
            "### Reconciled status",
            "",
            (
                f"- State: {reconciliation['state']}; requirement counts: "
                + ", ".join(f"{state}={count}" for state, count in reconciliation["counts"].items())
            ),
        ]
    )
    if reconciliation["conflicts"]:
        lines.append(
            "- Prior completion and continuation claims conflict. Neither is "
            "treated as current truth until repository inspection resolves it."
        )
    completed_requirements = [
        item for item in handoff["requirements"] if item["status"] in {"done", "reported_done"}
    ]
    remaining_requirements = [
        item for item in handoff["requirements"] if item["status"] not in {"done", "reported_done"}
    ]
    confirmed_ids = [item["id"] for item in completed_requirements if item["status"] == "done"]
    reported_ids = [
        item["id"] for item in completed_requirements if item["status"] == "reported_done"
    ]
    remaining_ids = [item["id"] for item in remaining_requirements]
    lines.append(
        "- Confirmed complete: "
        + (_compact_display_ids(confirmed_ids) if confirmed_ids else "none")
        + "; reported complete, not independently verified: "
        + (_compact_display_ids(reported_ids) if reported_ids else "none")
        + "; remaining or unresolved: "
        + (_compact_display_ids(remaining_ids) if remaining_ids else "none")
        + "."
    )
    lines.extend(["", "## Exact next action", ""])
    _append_session_context_quote(
        lines,
        _historical_single_line(
            handoff["exact_next_action"]["text"],
            1_200,
        ),
        label=(f"historical data; {handoff['exact_next_action']['truth_state']}"),
    )
    lines.append("")

    lines.extend(["## Active decisions that still hold", ""])
    active_decisions = [
        item
        for item in handoff.get("decisions") or []
        if str(item.get("state") or "active").casefold() not in _INACTIVE_BLOCKER_STATES
    ]
    if active_decisions:
        for item in active_decisions[-rendered_item_limit:]:
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item["statement"],
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label=f"historical data; {item['truth_state']}; active",
            )
            reason = str((item.get("payload") or {}).get("reason") or "").strip()
            if reason:
                _append_session_context_quote(
                    lines,
                    _historical_single_line(
                        reason,
                        SESSION_HANDOFF_RENDERED_RESULT_CHARS,
                    ),
                    label="historical data; decision reason",
                )
    else:
        lines.append("- No active session decision was captured.")
    lines.append("")

    lines.extend(["## Failed or rejected attempts", "", "### Failed attempts", ""])
    failed_attempts = handoff.get("failed_attempts") or []
    selected_failed_indices: set[int] = set()
    for predicate in (
        lambda item: bool((item.get("payload") or {}).get("command")),
        lambda item: (item.get("payload") or {}).get("attempt_kind") == "rejected",
    ):
        matched_index = next(
            (
                index
                for index in range(len(failed_attempts) - 1, -1, -1)
                if predicate(failed_attempts[index])
            ),
            None,
        )
        if matched_index is not None:
            selected_failed_indices.add(matched_index)
    if not selected_failed_indices and failed_attempts:
        selected_failed_indices.add(len(failed_attempts) - 1)
    selected_failed_attempts = [
        failed_attempts[index] for index in sorted(selected_failed_indices)
    ][-2:]
    if selected_failed_attempts:
        for item in selected_failed_attempts:
            payload = item.get("payload") or {}
            statement = _historical_single_line(
                item["statement"],
                SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
            )
            command = _historical_single_line(
                payload.get("command"),
                SESSION_HANDOFF_RENDERED_COMMAND_CHARS,
            )
            if not command or not _presentation_duplicate(statement, command):
                _append_session_context_quote(
                    lines,
                    statement,
                    label=f"historical data; {item['truth_state']}",
                )
            reason = str(payload.get("reason") or "").strip()
            if reason:
                _append_session_context_quote(
                    lines,
                    _historical_single_line(
                        reason,
                        SESSION_HANDOFF_RENDERED_RESULT_CHARS,
                    ),
                    label="historical data; failure reason",
                )
            evidence_bits = []
            if command:
                evidence_bits.append(f"command=`{command}`")
            if payload.get("exit_code") is not None:
                evidence_bits.append(f"exit={payload['exit_code']}")
            if not evidence_bits and payload.get("evidence_summary"):
                _append_session_context_quote(
                    lines,
                    _historical_single_line(
                        payload["evidence_summary"],
                        SESSION_HANDOFF_RENDERED_RESULT_CHARS,
                    ),
                    label="historical data; failed-attempt evidence source",
                )
            if evidence_bits:
                _append_session_context_quote(
                    lines,
                    "; ".join(evidence_bits) + ".",
                    label="historical data; failed-attempt evidence metadata",
                )
            if payload.get("result_summary"):
                result_summary = _compact_command_result_text(payload["result_summary"])
            else:
                result_summary = None
            if result_summary:
                _append_session_context_quote(
                    lines,
                    result_summary,
                    label="historical data; observed command result",
                )
        if len(failed_attempts) > len(selected_failed_attempts):
            lines.append(
                "- … "
                f"{len(failed_attempts) - len(selected_failed_attempts)} "
                "earlier failed attempts remain in the structured handoff."
            )
    else:
        lines.append("- No failed or rejected attempt with meaningful evidence was captured.")
    lines.append("")

    lines.extend(["## Changes made", ""])
    implementation_summary = handoff.get("implementation_summary") or []
    if implementation_summary:
        for item in implementation_summary[-rendered_item_limit:]:
            paths = ", ".join(item.get("files") or [])
            suffix = f"; affected={paths}" if paths else ""
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item.get("statement"),
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label=(f"historical data; {item.get('truth_state') or 'reported'}{suffix}"),
            )
            if item.get("reason"):
                _append_session_context_quote(
                    lines,
                    _historical_single_line(
                        item["reason"],
                        SESSION_HANDOFF_RENDERED_RESULT_CHARS,
                    ),
                    label="historical data; change reason",
                )
    else:
        lines.append("- No implementation change was captured for this task.")
    lines.append("")

    lines.extend(["## Relevant discoveries", ""])
    discoveries = handoff.get("discoveries") or []
    if discoveries:
        for item in discoveries[-rendered_item_limit:]:
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item["statement"],
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label=f"historical data; {item['truth_state']}",
            )
    else:
        lines.append(
            "- No separate symbol, dependency, relationship, or implementation "
            "discovery was captured."
        )
    lines.append("")

    lines.extend(["## Useful commands executed", ""])
    commands = handoff.get("useful_commands") or []
    if commands:
        for item in commands[-SESSION_HANDOFF_RENDERED_COMMAND_LIMIT:]:
            details = [
                f"purpose={item.get('purpose') or 'discovery'}",
                f"status={item.get('status') or 'observed'}",
            ]
            if item.get("cwd"):
                details.append(f"cwd=`{_historical_single_line(item['cwd'], 240)}`")
            if item.get("exit_code") is not None:
                details.append(f"exit={item['exit_code']}")
            _append_session_context_quote(
                lines,
                (
                    f"{item['id']} [{'; '.join(details)}]: "
                    f"`{
                        _historical_single_line(
                            item.get('command'),
                            SESSION_HANDOFF_RENDERED_COMMAND_CHARS,
                        )
                    }`"
                ),
                label="historical data; observed command",
            )
            if item.get("result_summary") and item.get("passed") is not True:
                _append_session_context_quote(
                    lines,
                    _historical_single_line(
                        item["result_summary"],
                        SESSION_HANDOFF_RENDERED_RESULT_CHARS,
                    ),
                    label="historical data; observed command result",
                )
        if len(commands) > SESSION_HANDOFF_RENDERED_COMMAND_LIMIT:
            lines.append(
                "- … "
                f"{len(commands) - SESSION_HANDOFF_RENDERED_COMMAND_LIMIT} "
                "earlier commands remain in the structured handoff."
            )
    else:
        lines.append(
            "- No non-repetitive discovery or verification command with a "
            "meaningful result was captured."
        )
    lines.append("")

    lines.extend(
        [
            "## Latest blockers, risks, assumptions, constraints, and open questions",
            "",
        ]
    )
    if reconciliation["active_reported_blockers"]:
        lines.extend(["### Reported blockers", ""])
        for item in reconciliation["active_reported_blockers"][-rendered_item_limit:]:
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item["statement"],
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label="historical data; unverified blocker",
            )
    else:
        lines.extend(["### Reported blockers", "", "- None captured."])
    open_items = handoff.get("open_items") or []
    lines.extend(["", "### Risks, assumptions, constraints, and questions", ""])
    if open_items:
        for item in open_items[-rendered_item_limit:]:
            kind = str((item.get("payload") or {}).get("kind") or "open_item")
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item["statement"],
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label=f"historical data; {kind}; {item['truth_state']}",
            )
    else:
        lines.append("- No additional open item was captured.")
    if execution_guidance:
        lines.extend(["", "### User constraints still in force", ""])
        for item in execution_guidance:
            lines.append(f"- {item['id']}: {item['text']}")
    lines.append("")

    lines.extend(["## What was fixed and how it was confirmed", ""])
    fixed_items = [
        item
        for item in implementation_summary
        if re.search(
            r"\b(?:fixed|repaired|resolved|corrected)\b",
            str(item.get("statement") or ""),
            re.IGNORECASE,
        )
    ]
    if fixed_items:
        requirements = handoff.get("requirements") or []
        verification = handoff.get("verification") or []
        for item in fixed_items[-1:]:
            matched_requirement_ids = {
                requirement["id"]
                for requirement in requirements
                if _statements_overlap(
                    str(item.get("statement") or ""),
                    str(requirement.get("text") or ""),
                )
            }
            confirmation_ids = [
                check["id"]
                for check in verification
                if check.get("passed") is True
                and matched_requirement_ids & set(check.get("requirement_ids") or [])
            ]
            confirmation = (
                "confirmed by linked observed check(s) " + ", ".join(confirmation_ids)
                if confirmation_ids
                else "reported fixed; no linked current confirmation was captured"
            )
            _append_session_context_quote(
                lines,
                _historical_single_line(
                    item.get("statement"),
                    SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                ),
                label=(f"historical data; {item.get('truth_state') or 'reported'}; {confirmation}"),
            )
    elif completed_requirements:
        lines.append(
            "- Completion is recorded for "
            + ", ".join(item["id"] for item in completed_requirements)
            + "; authoritative wording remains in Acceptance criteria."
        )
    else:
        lines.append("- No distinct fix was captured or confirmed.")
    lines.append("")

    repository = handoff["repository"]
    lines.extend(
        [
            "## Current evidence",
            "",
            "### Current repository state",
            "",
            (
                "- Repository: "
                f"{repository.get('root') or 'unavailable'}; "
                f"branch={repository.get('branch') or 'unavailable'}; "
                f"HEAD={repository.get('head_commit') or 'unavailable'}; "
                "relation="
                f"{repository.get('freshness', {}).get('status') or 'unavailable'}; "
                f"mode={handoff['task_mode']}/"
                f"{handoff['execution_policy']['permission_mode']}; boundary="
                f"{data.get('currentness', {}).get('state') or 'unknown'}; "
                "newer session events="
                f"{'yes' if boundary.get('has_newer_events') else 'no'}."
            ),
        ]
    )
    protected_count = len(handoff["files"].get("pre_existing_at_handoff") or [])
    lines.append(
        f"- Protected baseline: {protected_count} pre-existing change"
        f"{'' if protected_count == 1 else 's'}. Preserve protected baseline "
        "state regardless of authorship; dirty="
        f"{repository.get('dirty') if repository.get('dirty') is not None else 'unknown'}; "
        "inspect live `git status --short` before editing."
    )
    baseline_manifest = repository.get("protected_baseline_manifest") or {}
    if baseline_manifest.get("receiver_availability") == "available":
        lines.append(
            "- Receiver-local protected-baseline manifest: `"
            + _single_line(
                str(baseline_manifest.get("receiver_local_reference") or ""),
                500,
            )
            + "`; manifest SHA-256 `"
            + str(baseline_manifest.get("receiver_manifest_sha256") or "")
            + "` (infrastructure verified)."
        )

    relevant_paths: list[str] = []
    for category in ("modified", "relevant"):
        for item in handoff["files"].get(category) or []:
            path = str(item.get("path") or "").strip()
            if path and path not in relevant_paths:
                relevant_paths.append(path)
    if relevant_paths:
        lines.extend(["", "### Affected areas and relevant files", ""])
        for path in relevant_paths[:6]:
            lines.append(f"- {_single_line(path, 500)}")
        if len(relevant_paths) > 6:
            lines.append(
                f"- … {len(relevant_paths) - 6} more task-relevant paths remain "
                "in the structured handoff."
            )

    else:
        lines.extend(
            [
                "",
                "### Affected areas and relevant files",
                "",
                "- No task-relevant path was captured.",
            ]
        )

    lines.extend(["", "## Verification state", "", "### Prior verification", ""])
    if handoff["verification"]:
        for item in handoff["verification"][-SESSION_HANDOFF_RENDERED_VERIFICATION_LIMIT:]:
            linked = ", ".join(item["requirement_ids"]) or "unmapped"
            details: list[str] = []
            if item.get("command"):
                details.append(
                    "command="
                    f"`{
                        _historical_single_line(
                            item['command'],
                            SESSION_HANDOFF_RENDERED_COMMAND_CHARS,
                        )
                    }`"
                )
            elif item.get("statement"):
                details.append(
                    "evidence="
                    f"{
                        _historical_single_line(
                            item['statement'],
                            SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
                        )
                    }"
                )
            if item.get("cwd"):
                details.append(f"cwd=`{_historical_single_line(item['cwd'], 240)}`")
            if item.get("exit_code") is not None:
                details.append(f"exit={item['exit_code']}")
            if item.get("scope"):
                details.append(f"scope={_historical_single_line(item['scope'], 240)}")
            _append_session_context_quote(
                lines,
                "; ".join(details) or "No verification detail was captured.",
                label=(
                    f"{item['status']}; "
                    f"scope={item.get('scope_kind') or 'observed'}; "
                    f"link={item.get('link_kind') or 'unmapped'}; "
                    f"requirements={linked}; historical data; "
                    f"verification={item['id']}"
                ),
            )
        if len(handoff["verification"]) > SESSION_HANDOFF_RENDERED_VERIFICATION_LIMIT:
            lines.append(
                "- … "
                f"{len(handoff['verification']) - SESSION_HANDOFF_RENDERED_VERIFICATION_LIMIT} "
                "more verification "
                "records remain in the structured handoff."
            )
    else:
        lines.append("- None captured.")

    verification_notes: list[str] = []
    reported_done = [
        requirement["id"]
        for requirement in handoff["requirements"]
        if requirement["status"] == "reported_done"
    ]
    if reported_done:
        verification_notes.append(
            f"{_compact_display_ids(reported_done)} is reported complete but still needs "
            "current repository verification."
        )
    unmapped_verification = [
        item["id"] for item in handoff["verification"] if not item["requirement_ids"]
    ]
    if unmapped_verification:
        verification_notes.append(
            f"{_compact_display_ids(unmapped_verification)} is not mapped to a requirement; "
            "its focused or regression-safety scope is recorded separately."
        )
    lines.extend(["", "### Remaining verification", ""])
    if verification_notes:
        lines.extend(f"- {note}" for note in verification_notes)
    else:
        lines.append("- No additional verification gap was derived.")

    return "\n".join(lines)


def _append_compact_request_quote(
    lines: list[str],
    text: str,
    *,
    label: str,
) -> None:
    lines.append(f"{label}:")
    for line in str(text or "").splitlines() or [""]:
        lines.append(f"> {line}" if line else ">")


def _compact_markdown_code(value: Any, *, fallback: str = "unavailable") -> str:
    """Render repository-controlled text as reversible, injection-safe inline code."""

    raw = str(value if value is not None else "")
    if raw == "":
        if fallback == "":
            return ""
        raw = fallback
    escaped = json.dumps(raw, ensure_ascii=False)[1:-1].replace("`", r"\u0060")
    return f"`{escaped}`"


def _compact_session_task_type_label(handoff: dict[str, Any]) -> str:
    task_mode = str(handoff.get("task_mode") or "report")
    return {
        "change": "code change",
        "diagnose": "diagnosis",
        "plan": "implementation plan",
        "report": "report",
        "review": "review",
        "test_only": "test-only task",
    }.get(task_mode, task_mode.replace("_", " "))


def _compact_session_capture_permission_label(handoff: dict[str, Any]) -> str:
    policy = handoff.get("execution_policy") or {}
    value = str(
        policy.get("permission_observed_at_capture")
        or policy.get("permission_mode")
        or "unavailable"
    )
    return (
        "workspace write access was available"
        if value == "workspace_write"
        else "read-only access was available"
        if value == "read_only"
        else "no runtime permission observation was captured"
    )


def _compact_session_required_capability_label(handoff: dict[str, Any]) -> str:
    policy = handoff.get("execution_policy") or {}
    value = str(
        policy.get("required_capability")
        or ("repository_write" if policy.get("may_edit") else "repository_read")
    )
    return (
        "repository write access" if value == "repository_write" else "read-only repository access"
    )


def _compact_session_start_steps(handoff: dict[str, Any]) -> list[str]:
    """Turn the next action into a deterministic, evidence-aware sequence."""

    action = _compact_session_start_action(handoff)
    policy = handoff.get("execution_policy") or {}
    may_edit = bool(policy.get("may_edit"))
    intent = handoff.get("intent") or {}
    target = intent.get("target_resolution") or {}
    required_attachments = [
        item
        for item in handoff.get("attachment_dependencies") or []
        if item.get("required") is True
    ]
    terminal_prerequisite = action.startswith(
        (
            "Recapture a complete current repository snapshot",
            "Wait for the artifact infrastructure to materialize",
            "Refresh the Session Context",
            "Resolve the Session Context quality warnings or blockers",
        )
    )
    if terminal_prerequisite:
        return [
            action,
            "Regenerate Session Context after this prerequisite is satisfied; do not edit "
            "from this stale brief.",
        ]
    if may_edit and required_attachments and target.get("status") != "resolved":
        candidate_paths = [
            str(candidate.get("path") or "")
            for item in intent.get("targets") or []
            for candidate in item.get("candidates") or []
            if str(candidate.get("path") or "")
        ]
        ui_paths = _compact_session_current_ui_paths(handoff)
        inspect_paths = list(dict.fromkeys([*candidate_paths, *ui_paths]))[:3]
        inspect_step = (
            "Inspect the ranked or recently changed UI files: "
            + ", ".join(_compact_markdown_code(path) for path in inspect_paths)
            + ". Treat them as candidates until the visual evidence matches."
            if inspect_paths
            else (
                "Review UI files changed immediately before the request, if any, "
                "and search route/component names visible in the attachment."
            )
        )
        return [
            action,
            (
                "Run `git status --short` as a read-only check and compare it "
                "with the embedded protected-baseline manifest, including each "
                "file's staged and unstaged status."
            ),
            inspect_step,
            (
                "Search likely UI components and styles for transparent or alpha "
                "backgrounds, `opacity`, `rgba`/`hsla`, transparent gradients, "
                "ancestor opacity, and `backdrop-blur`."
            ),
            (
                "Match the candidates against the required visual evidence and "
                "identify the exact route, component, and style rule."
            ),
            (
                "Edit only after the target is grounded, then execute every item "
                "under Verification required."
            ),
        ]
    steps = [action]
    if may_edit and "git status --short" not in action:
        steps.append(
            "Run `git status --short` as a read-only check and compare it with "
            "the embedded protected-baseline manifest, including each file's "
            "staged and unstaged status, before editing."
        )
    elif not may_edit and "do not edit" not in action.casefold():
        steps.append("Inspect the live repository state; do not edit files.")
    return steps


def render_compact_session_handoff(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    contract: dict[str, Any] | None = None,
    checkpoint_data: dict[str, Any] | None = None,
) -> str:
    """Render the compact Session Context candidate for the A/B experiment."""

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    sections = data["sections"]
    goals = sections["goal"]
    goal = goals[0] if goals else {}
    goal_payload = goal.get("payload") if isinstance(goal.get("payload"), dict) else {}
    resolved_request = request_verbatim
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = goal_payload.get("request_verbatim")
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = str(goal.get("statement") or "").strip()
    if not resolved_request:
        raise ValueError("The checkpoint has no substantive session goal.")
    handoff = contract or build_session_handoff_contract(
        checkpoint,
        request_verbatim=resolved_request,
        supporting_context=supporting_context,
        checkpoint_data=data,
    )
    repository = handoff["repository"]
    protected = handoff["files"].get("pre_existing_at_handoff") or []
    continuation_lead = handoff.get("continuation_lead") or {}
    intent = handoff.get("intent") or {}
    readiness = handoff.get("readiness") or {}
    normalized_goal = _compact_requirement_text(
        intent.get("normalized_requirement")
        or continuation_lead.get("text")
        or handoff["current_goal"]["text"]
    )
    readiness_label = str(readiness.get("label") or "Readiness not evaluated")
    may_edit = bool(handoff.get("execution_policy", {}).get("may_edit"))
    lines = [
        "# Continuation Brief v2",
        "",
        (
            "> Continue from **Start here**. The latest user-authored lead and "
            "explicit constraints carry authority; prior-agent statements and "
            "prior session permissions are historical evidence."
        ),
        "",
        f"Status: **{readiness_label}**",
        "",
    ]
    if continuation_lead.get("text"):
        lines.extend(["## Goal", "", normalized_goal, ""])
        _append_compact_request_quote(
            lines,
            continuation_lead["text"],
            label="Current user instruction (authoritative)",
        )
        if _sha256(continuation_lead["text"]) != _sha256(handoff["current_goal"]["text"]):
            lines.append("")
            _append_compact_request_quote(
                lines,
                handoff["current_goal"]["text"],
                label="Prior carried request (historical reference)",
            )
    else:
        lines.extend(["## Goal", "", normalized_goal, ""])
        _append_compact_request_quote(
            lines,
            handoff["current_goal"]["text"],
            label="Original user request (authoritative)",
        )

    required_capability_label = _compact_session_required_capability_label(handoff)
    captured_permission_label = _compact_session_capture_permission_label(handoff)
    repository_state = str(repository.get("freshness", {}).get("status") or "unavailable")
    repository_state_label = {
        "changed": "it differed from the saved checkpoint",
        "unchanged": "it matched the saved checkpoint",
        "matched": "it matched the saved checkpoint",
        "unavailable": "comparison with the saved checkpoint was unavailable",
    }.get(repository_state, f"comparison state: {repository_state}")
    baseline_manifest = repository.get("protected_baseline_manifest") or {}
    lines.extend(
        [
            "",
            "## State now",
            "",
            f"- Task type: {_compact_session_task_type_label(handoff)}.",
            f"- Required capability: {required_capability_label}.",
            (
                f"- Permission observed at capture: {captured_permission_label}. "
                + (
                    "Revalidate live write permission before editing."
                    if may_edit
                    else "This handoff does not authorize edits."
                )
            ),
            (
                "- Repository at capture: "
                f"{_compact_markdown_code(repository.get('root'))}; "
                f"{repository_state_label}."
            ),
            f"- Captured branch: {_compact_markdown_code(repository.get('branch'))}.",
            f"- Captured HEAD: {_compact_markdown_code(repository.get('head_commit'))}.",
            f"- Captured at: {_compact_markdown_code(repository.get('captured_at'))}.",
            (
                "- Working-tree snapshot: "
                f"{_compact_markdown_code(baseline_manifest.get('portable_reference'))}; "
                "manifest SHA-256 "
                f"{_compact_markdown_code(baseline_manifest.get('manifest_sha256'))}; "
                "repository fingerprint "
                f"{_compact_markdown_code(repository.get('status_fingerprint'))}."
            ),
        ]
    )
    if baseline_manifest.get("receiver_availability") == "available":
        lines.append(
            "- Receiver-local protected-baseline manifest: "
            f"{_compact_markdown_code(baseline_manifest.get('receiver_local_reference'))}; "
            "manifest SHA-256 "
            f"{_compact_markdown_code(baseline_manifest.get('receiver_manifest_sha256'))}; "
            "infrastructure verified."
        )
    if protected:
        if baseline_manifest.get("complete") is True:
            lines.append(
                f"- Protected baseline manifest: {len(protected)} pre-existing change"
                f"{'' if len(protected) == 1 else 's'} with exact index objects, "
                "worktree hashes, and staged/unstaged status. Preserve every "
                "pre-existing change."
            )
        else:
            lines.append(
                f"- Protected baseline is incomplete: {len(protected)} path"
                f"{'' if len(protected) == 1 else 's'} "
                f"{'was' if len(protected) == 1 else 'were'} observed, but an exact "
                "index/worktree manifest was not captured. Preserve every pre-existing "
                "change observed here and recapture before execution."
            )
        manifest_entries = [
            item
            for item in baseline_manifest.get("working_tree") or []
            if isinstance(item, dict) and str(item.get("path") or "") != ""
        ]
        rendered_entries = [
            f"{str(item.get('xy') or '??')} {str(item.get('path') or '')}"
            for item in manifest_entries
        ]
        if (
            baseline_manifest.get("complete") is True
            and len(rendered_entries) <= 12
            and sum(len(item) for item in rendered_entries) <= 1_200
        ):
            lines.append("- Protected manifest entries (`XY path`):")
            lines.extend(f"  - {_compact_markdown_code(item)}" for item in rendered_entries)
        elif baseline_manifest.get("complete") is True and manifest_entries:
            staged_only = sum(
                str(item.get("index_status") or " ") not in {" ", "?"}
                and str(item.get("worktree_status") or " ") == " "
                for item in manifest_entries
            )
            worktree_only = sum(
                str(item.get("index_status") or " ") == " "
                and str(item.get("worktree_status") or " ") not in {" ", "?"}
                for item in manifest_entries
            )
            staged_and_unstaged = sum(
                str(item.get("index_status") or " ") not in {" ", "?"}
                and str(item.get("worktree_status") or " ") not in {" ", "?"}
                for item in manifest_entries
            )
            untracked = sum(str(item.get("xy") or "") == "??" for item in manifest_entries)
            lines.append(
                "- Protected status summary: "
                f"{staged_only} staged-only, {worktree_only} worktree-only, "
                f"{staged_and_unstaged} staged+unstaged, {untracked} untracked. "
                "The exact entries are bound by the manifest reference above."
            )
        lines.append(
            "- Do not stage, unstage, revert, overwrite, or reformat unrelated "
            "files. Preserve their captured index and working-tree states."
        )
    else:
        lines.append("- No pre-existing working-tree change was captured at the handoff boundary.")
    target_resolution = intent.get("target_resolution") or {}
    target_items = intent.get("targets") or []
    if target_resolution.get("required"):
        phrases = (
            ", ".join(
                _compact_markdown_code(item.get("phrase"))
                for item in target_items
                if item.get("phrase")
            )
            or "the referenced target"
        )
        target_status = str(target_resolution.get("status") or "unresolved")
        if target_status == "resolved":
            resolved_paths = [
                str(item.get("resolved_entity") or "")
                for item in target_items
                if str(item.get("resolved_entity") or "")
            ]
            resolution_suffix = (
                " → " + ", ".join(_compact_markdown_code(path) for path in resolved_paths)
                if resolved_paths
                else ""
            )
            lines.append(f"- Target resolved for {phrases}{resolution_suffix}.")
        else:
            lines.append(
                f"- Target resolution: {target_status} for {phrases}. "
                "No affected component or file has been identified yet."
            )
            candidates = [
                candidate
                for item in target_items
                for candidate in item.get("candidates") or []
                if str(candidate.get("path") or "")
            ]
            if candidates:
                lines.append("- Ranked candidates requiring inspection:")
                for candidate in candidates[:3]:
                    lines.append(
                        "  - "
                        + _compact_markdown_code(candidate.get("path"))
                        + " — "
                        + _single_line(str(candidate.get("evidence") or "Candidate only."), 300)
                    )
            else:
                lines.append("- No component has sufficient evidence to be treated as the target.")
                current_ui_paths = _compact_session_current_ui_paths(handoff)
                if current_ui_paths:
                    lines.append("- Circumstantial candidates (all unconfirmed):")
                    for path in current_ui_paths[:3]:
                        lines.append(
                            f"  - `{path}` — captured as a pre-existing runtime UI "
                            "change near the handoff; match its route, visible text, and "
                            "card structure to the required visual evidence before relying on it."
                        )
            lines.append(
                "- Unknowns: exact route, owning component, and whether transparency "
                "comes from the card background or an ancestor style."
            )
    relevant_paths = _compact_session_relevant_paths(handoff)
    protected_paths = {str(item.get("path") or "").strip() for item in protected}
    overlap = [path for path in relevant_paths if path in protected_paths]
    if overlap:
        lines.append(
            "- Target/protected-baseline overlap: "
            + ", ".join(f"`{path}`" for path in overlap[:3])
            + ". Preserve the pre-existing edits in each overlapping file and apply "
            "only the minimum requirement-specific delta without staging or unstaging "
            "the whole file."
        )
    if not handoff.get("implementation_summary") and not handoff.get("verification"):
        lines.append("- No implementation change or current verification has been confirmed.")
    _append_compact_session_progress(lines, handoff)
    _append_compact_session_supporting_context(lines, handoff)
    _append_compact_session_attachments(lines, handoff)

    lines.extend(["", "## Start here", ""])
    for index, step in enumerate(_compact_session_start_steps(handoff), start=1):
        lines.append(f"{index}. {step}")

    trap_lines: list[str] = []
    _append_compact_session_traps(trap_lines, handoff)
    lines.extend(["", "## Do not repeat", ""])
    lines.extend(trap_lines or ["- None."])

    lines.extend(["", "## Done when", ""])
    requirements = handoff.get("requirements") or []
    if requirements:
        for requirement in requirements:
            status = str(requirement.get("status") or "remaining").replace(
                "reported_done",
                "reported done; verify",
            )
            checks = _compact_display_ids(requirement.get("verification_ids") or [])
            suffix = f"; checks={checks}" if checks else ""
            requirement_text = _compact_requirement_text(
                requirement.get("normalized_text") or requirement.get("text")
            )
            lines.append(f"- {requirement['id']} [{status}{suffix}]: {requirement_text}")
    else:
        lines.append("- Complete and verify the carried goal.")
    for criterion in intent.get("acceptance_criteria") or []:
        criterion_text = _single_line(str(criterion.get("text") or ""), 500)
        if not criterion_text:
            continue
        linked = _compact_display_ids(criterion.get("requirement_ids") or [])
        authority = str(criterion.get("authority") or "inferred_acceptance")
        authority_label = (
            "User acceptance" if authority == "user_authored" else "Inferred acceptance"
        )
        lines.append(
            f"- {authority_label}" + (f" for {linked}" if linked else "") + f": {criterion_text}"
        )
    definition = handoff.get("definition_of_done") or {}
    for item in definition.get("operational") or []:
        text = _single_line(str(item.get("text") or ""), 500)
        if text.startswith("Every accepted requirement is observed") or text.startswith(
            "Do not stage, unstage, revert, overwrite, or reformat unrelated pre-existing changes"
        ):
            continue
        if text and not any(_presentation_duplicate(text, line) for line in lines[-12:]):
            lines.append(f"- {text}")
    verification = handoff.get("verification") or []
    for item in verification[-SESSION_HANDOFF_RENDERED_VERIFICATION_LIMIT:]:
        command = _historical_single_line(
            item.get("command"),
            SESSION_HANDOFF_RENDERED_COMMAND_CHARS,
        )
        statement = _historical_single_line(
            item.get("statement"),
            SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
        )
        proof = command or statement
        if proof:
            linked = _compact_display_ids(item.get("requirement_ids") or []) or "unmapped"
            lines.append(
                f"> [prior {item.get('status') or 'observed'} check; requirements={linked}] {proof}"
            )
    verification_plan = handoff.get("verification_plan") or []
    if verification_plan:
        lines.append("- Verification required:")
        for index, item in enumerate(verification_plan, start=1):
            lines.append(f"  {index}. {_single_line(str(item.get('text') or ''), 700)}")
    return "\n".join(lines).rstrip() + "\n"


def _append_compact_session_progress(
    lines: list[str],
    handoff: dict[str, Any],
) -> None:
    implementation = handoff.get("implementation_summary") or []
    for item in implementation[-2:]:
        _append_session_context_quote(
            lines,
            _historical_single_line(
                item.get("statement"),
                SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
            ),
            label=f"historical current-state claim; {item.get('truth_state') or 'reported'}",
        )


def _append_compact_session_supporting_context(
    lines: list[str],
    handoff: dict[str, Any],
) -> None:
    supporting = handoff.get("supporting_context") or []
    if not supporting:
        return
    lines.append("- Referenced historical context required by the goal:")
    for item in supporting:
        _append_session_context_quote(
            lines,
            _self_contained_goal(item["text"]),
            label=f"historical {item['role']}",
        )


def _revalidated_rendered_attachment_inspection(
    attachment: dict[str, Any],
) -> dict[str, Any] | None:
    """Revalidate the canonical inspection record; ignore flattened copies."""

    raw = attachment.get("visual_inspection")
    expected_sha256 = str(
        attachment.get("content_hash") or attachment.get("sha256") or ""
    ).casefold()
    mime_type = str(attachment.get("media_type") or attachment.get("mime_type") or "").casefold()
    if (
        attachment.get("inspection_status") != "inspected"
        or not isinstance(raw, dict)
        or raw.get("trust") != "infrastructure_attested_hash_bound_observation"
    ):
        return None
    return validated_trusted_image_inspection(
        TrustedRequestImageDescriptor(
            path="receiver-render-validation",
            sha256=expected_sha256,
            mime_type=mime_type,
            visual_inspection=raw,
            visual_inspection_attested=True,
        )
    )


def _append_compact_session_attachments(
    lines: list[str],
    handoff: dict[str, Any],
) -> None:
    attachments = [
        item
        for item in handoff.get("attachment_dependencies") or []
        if item.get("required") is True
    ]
    if not attachments:
        return
    lines.append("- Required visual evidence:")
    for attachment in attachments:
        linked = _compact_display_ids(attachment.get("requirement_ids") or []) or "unmapped"
        portable_reference = str(
            attachment.get("portable_reference") or f"attachment:{attachment['id']}"
        )
        inspection_status = str(attachment.get("inspection_status") or "not_inspected")
        lines.append(
            f"  - {attachment['id']} supports {linked}; inspection status: `{inspection_status}`."
        )
        lines.append(f"    - Portable reference: {_compact_markdown_code(portable_reference)}.")
        lines.append(
            "    - Media: "
            f"{_compact_markdown_code(attachment.get('media_type') or attachment.get('mime_type'), fallback='unknown')}; "
            "SHA-256: "
            f"{_compact_markdown_code(attachment.get('content_hash') or attachment.get('sha256'))}."
        )
        if attachment.get("available_at_capture") is True:
            lines.append(
                "    - Integrity: `available_and_verified` at capture. Artifact "
                "infrastructure owns materialization and hash verification; automatic "
                "continuations reverify the bytes during runtime-bundle delivery."
            )
        else:
            lines.append(
                "    - Integrity: `missing_or_corrupted`. Artifact infrastructure "
                "must recover and verify it before an agent may rely on it."
            )
        receiver_reference = str(attachment.get("receiver_local_reference") or "").strip()
        receiver_available = bool(
            attachment.get("receiver_availability") == "available"
            and receiver_reference
            and Path(receiver_reference).is_absolute()
            and attachment.get("receiver_integrity_status") == "available_and_verified"
            and str(attachment.get("receiver_content_hash") or "").casefold()
            == str(attachment.get("content_hash") or attachment.get("sha256") or "").casefold()
        )
        receiver_availability = "available" if receiver_available else "unknown"
        lines.append(
            f"    - Receiver availability: `{receiver_availability}`"
            + (
                "; infrastructure must materialize and reverify it before inspection."
                if receiver_availability != "available"
                else "."
            )
        )
        if receiver_available:
            lines.append(
                f"    - Receiver-local reference: {_compact_markdown_code(receiver_reference)}."
            )
        inspection = _revalidated_rendered_attachment_inspection(attachment)
        visual_anchors = [
            _single_line(str(anchor.get("text") or ""), 240)
            for anchor in (inspection or {}).get("anchors") or []
            if str(anchor.get("text") or "").strip()
        ]
        if visual_anchors:
            lines.append(f"    - Source-time visual anchors (confirm against {attachment['id']}):")
            lines.extend(f"      - {anchor}" for anchor in visual_anchors[:8])
        suspected_surface = _single_line(
            str((inspection or {}).get("suspected_surface") or ""),
            160,
        )
        candidate_route = _single_line(
            str((inspection or {}).get("candidate_route") or ""),
            160,
        )
        if suspected_surface:
            lines.append(
                "    - Suspected surface: "
                f"{_compact_markdown_code(suspected_surface)} (unconfirmed)."
            )
        if candidate_route:
            lines.append(
                f"    - Candidate route: {_compact_markdown_code(candidate_route)} (unconfirmed)."
            )


def _compact_session_relevant_paths(handoff: dict[str, Any]) -> list[str]:
    result: list[str] = []
    files = handoff.get("files") or {}
    for category in ("modified", "relevant"):
        for item in files.get(category) or []:
            path = str(item.get("path") or "")
            if path != "" and path not in result:
                result.append(path)
    for item in (handoff.get("intent") or {}).get("targets") or []:
        path = str(item.get("resolved_entity") or "")
        if path != "" and path not in result:
            result.append(path)
    return result


def _compact_session_current_ui_paths(handoff: dict[str, Any]) -> list[str]:
    result: list[str] = []
    files = handoff.get("files") or {}
    for category in ("modified", "pre_existing_at_handoff"):
        for item in files.get(category) or []:
            path = str(item.get("path") or "")
            if path != "" and path not in result and _path_has_ui_implementation_evidence(path):
                result.append(path)
    return result


def _compact_session_start_action(handoff: dict[str, Any]) -> str:
    requirements = handoff.get("requirements") or []
    readiness_action = _historical_single_line(
        (handoff.get("readiness") or {}).get("next_action"),
        1_200,
    )
    if readiness_action:
        return _expand_compact_requirement_ids(
            readiness_action,
            requirements,
        )
    exact = _historical_single_line(
        (handoff.get("exact_next_action") or {}).get("text"),
        1_200,
    )
    if exact:
        return _expand_compact_requirement_ids(exact, requirements)
    conflicted = next(
        (item for item in requirements if item.get("status") == "conflicted"),
        None,
    )
    reported = next(
        (item for item in requirements if item.get("status") == "reported_done"),
        None,
    )
    remaining = next(
        (item for item in requirements if item.get("status") not in {"done", "reported_done"}),
        None,
    )
    selected = conflicted or remaining or reported
    if selected is not None:
        verb = (
            "Reconcile and then complete"
            if selected is conflicted
            else "Verify before relying on the reported completion of"
            if selected is reported
            else "Complete"
        )
        requirement_id = str(selected.get("id") or "requirement").strip()
        requirement_text = _compact_requirement_text(selected.get("text"))
        return f"{verb} {requirement_id}: {requirement_text}"
    return "Verify the current repository state, then complete the carried goal."


def _expand_compact_requirement_ids(
    action: str,
    requirements: Iterable[dict[str, Any]],
) -> str:
    """Make reconciliation IDs actionable without discarding their identity."""

    expanded = action
    requirement_map = sorted(
        (
            (
                str(item.get("id") or "").strip(),
                _compact_requirement_text(item.get("normalized_text") or item.get("text")),
            )
            for item in requirements
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for requirement_id, requirement_text in requirement_map:
        if not requirement_id or not requirement_text:
            continue
        expanded = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(requirement_id)}(?![A-Za-z0-9])",
            lambda match: f"{match.group(0)} ({requirement_text})",
            expanded,
        )
    return expanded


def _compact_requirement_text(value: Any) -> str:
    """Return the lossless single-line requirement form used by v2."""

    return re.sub(r"\s+", " ", str(value or "")).strip()


def _append_compact_session_traps(
    lines: list[str],
    handoff: dict[str, Any],
) -> None:
    if handoff.get("constraints"):
        lines.append("- Keep every explicit constraint in Goal; it remains binding.")
    sections = (
        ("Failed approach", handoff.get("failed_attempts") or []),
        ("Active blocker", handoff.get("reconciliation", {}).get("active_reported_blockers") or []),
        ("Open risk", handoff.get("open_items") or []),
        ("Decision still in force", handoff.get("decisions") or []),
    )
    remaining_slots = 4
    for label, values in sections:
        if remaining_slots <= 0:
            break
        for item in values[-min(2, remaining_slots) :]:
            statement = _historical_single_line(
                item.get("statement"),
                SESSION_HANDOFF_RENDERED_STATEMENT_CHARS,
            )
            if not statement:
                continue
            _append_session_context_quote(
                lines,
                statement,
                label=f"{label}; historical {item.get('truth_state') or 'reported'}",
            )
            remaining_slots -= 1
    target = (handoff.get("intent") or {}).get("target_resolution") or {}
    if target.get("required") and target.get("status") != "resolved":
        evidence_ids = [
            str(item.get("id") or "")
            for item in handoff.get("attachment_dependencies") or []
            if item.get("required") is True and str(item.get("id") or "")
        ]
        evidence_suffix = (
            " without matching it to " + ", ".join(evidence_ids)
            if evidence_ids
            else " without current repository evidence"
        )
        lines.append(
            "- Do not guess the affected component from the target phrase or treat "
            f"a recent file as confirmed{evidence_suffix}."
        )


def session_handoff_render_issues(
    content: str,
    *,
    request_verbatim: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    handoff_contract: dict[str, Any] | None = None,
    variant: ContinuationBriefVariant | str = ContinuationBriefVariant.LEGACY_V1,
) -> list[dict[str, Any]]:
    """Return fail-closed issues for an incomplete Session Context artifact."""

    resolved_variant = resolve_continuation_brief_variant(variant)
    compact = resolved_variant is ContinuationBriefVariant.COMPACT_V2
    required_headings = (
        COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS if compact else SESSION_CONTEXT_REQUIRED_HEADINGS
    )
    max_overhead_chars = (
        COMPACT_SESSION_HANDOFF_MAX_OVERHEAD_CHARS
        if compact
        else SESSION_HANDOFF_MAX_OVERHEAD_CHARS
    )
    lines = set(content.splitlines())
    missing_sections = [heading for heading in required_headings if heading not in lines]
    issues: list[dict[str, Any]] = []
    if missing_sections:
        issues.append(
            {
                "code": "session_context_required_sections_missing",
                "status": "fail",
                "missing_sections": missing_sections,
                "message": (
                    "Session Context omits required task-memory sections: "
                    + ", ".join(missing_sections)
                    + "."
                ),
            }
        )
    if request_verbatim is not None:
        carried_request_chars = len(_self_contained_goal(request_verbatim))
        carried_lead_chars = len(
            str((handoff_contract or {}).get("continuation_lead", {}).get("text") or "")
        )
        carried_supporting_chars = sum(
            len(_self_contained_goal(str(item.get("text") or "")))
            for item in supporting_context
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        )
        overhead_chars = max(
            0,
            len(content) - carried_request_chars - carried_lead_chars - carried_supporting_chars,
        )
        if overhead_chars > max_overhead_chars:
            issues.append(
                {
                    "code": "session_context_overhead_budget_exceeded",
                    "status": "fail",
                    "overhead_chars": overhead_chars,
                    "max_overhead_chars": max_overhead_chars,
                    "message": (
                        "Session Context exceeds its model-facing overhead budget; "
                        "keep detailed evidence in the structured handoff."
                    ),
                }
            )
    if compact and handoff_contract is not None:
        missing_fragments = _compact_session_handoff_missing_fragments(
            content,
            handoff_contract,
        )
        if missing_fragments:
            issues.append(
                {
                    "code": "compact_session_context_critical_state_missing",
                    "status": "fail",
                    "missing_fragments": missing_fragments,
                    "message": (
                        "Compact Session Context omits critical start, safety, or completion state."
                    ),
                }
            )
    return issues


def _compact_session_handoff_missing_fragments(
    content: str,
    handoff: dict[str, Any],
) -> list[str]:
    """Name critical contract fields absent from the compact projection."""

    goal = str((handoff.get("current_goal") or {}).get("text") or "")
    continuation_lead = str((handoff.get("continuation_lead") or {}).get("text") or "")
    intent = handoff.get("intent") or {}
    readiness = handoff.get("readiness") or {}
    expected: list[tuple[str, str]] = [
        *(
            (f"goal_line_{index}", line.strip())
            for index, line in enumerate(goal.splitlines(), start=1)
            if line.strip()
        ),
        ("task_mode", f"Task type: {_compact_session_task_type_label(handoff)}."),
        (
            "required_capability",
            "Required capability: " + _compact_session_required_capability_label(handoff) + ".",
        ),
        (
            "permission_mode",
            "Permission observed at capture: "
            + _compact_session_capture_permission_label(handoff)
            + ".",
        ),
        *(
            (f"start_step_{index}", step)
            for index, step in enumerate(
                _compact_session_start_steps(handoff),
                start=1,
            )
        ),
        (
            "exact_next_action",
            _compact_session_start_action(handoff),
        ),
        (
            "normalized_requirement",
            str(intent.get("normalized_requirement") or ""),
        ),
        ("readiness", str(readiness.get("label") or "")),
        *(
            (f"continuation_lead_line_{index}", line.strip())
            for index, line in enumerate(
                continuation_lead.splitlines(),
                start=1,
            )
            if line.strip()
        ),
    ]
    repository = handoff.get("repository") or {}
    baseline_manifest = repository.get("protected_baseline_manifest") or {}
    expected.extend(
        (
            (
                "repository_root",
                _compact_markdown_code(repository.get("root"), fallback=""),
            ),
            (
                "repository_branch",
                _compact_markdown_code(repository.get("branch"), fallback=""),
            ),
            (
                "repository_head",
                _compact_markdown_code(repository.get("head_commit"), fallback=""),
            ),
            (
                "repository_captured_at",
                _compact_markdown_code(repository.get("captured_at"), fallback=""),
            ),
            (
                "repository_baseline_reference",
                _compact_markdown_code(
                    baseline_manifest.get("portable_reference"),
                    fallback="",
                ),
            ),
            (
                "repository_baseline_manifest_sha256",
                _compact_markdown_code(
                    baseline_manifest.get("manifest_sha256"),
                    fallback="",
                ),
            ),
            (
                "repository_baseline_receiver_local_reference",
                (
                    _compact_markdown_code(
                        baseline_manifest.get("receiver_local_reference"),
                        fallback="",
                    )
                    if baseline_manifest.get("receiver_availability") == "available"
                    else ""
                ),
            ),
            (
                "repository_status_fingerprint",
                _compact_markdown_code(
                    repository.get("status_fingerprint"),
                    fallback="",
                ),
            ),
        )
    )
    for item in handoff.get("supporting_context") or []:
        role = item.get("role") or "unknown"
        materialized = _self_contained_goal(str(item.get("text") or ""))
        expected.extend(
            (f"supporting_context_{role}_line_{index}", line.strip())
            for index, line in enumerate(materialized.splitlines(), start=1)
            if line.strip()
        )
    for item in handoff.get("attachment_dependencies") or []:
        if item.get("required") is not True:
            continue
        attachment_id = str(item.get("id") or "attachment")
        linked_requirements = _compact_display_ids(item.get("requirement_ids") or []) or "unmapped"
        expected.extend(
            (
                (f"attachment_{attachment_id}_id", attachment_id),
                (
                    f"attachment_{attachment_id}_requirement_linkage",
                    f"{attachment_id} supports {linked_requirements};",
                ),
                (
                    f"attachment_{attachment_id}_portable_reference",
                    _compact_markdown_code(
                        item.get("portable_reference") or f"attachment:{attachment_id}"
                    ),
                ),
                (
                    f"attachment_{attachment_id}_sha256",
                    _compact_markdown_code(
                        item.get("content_hash") or item.get("sha256"),
                        fallback="",
                    ),
                ),
                (
                    f"attachment_{attachment_id}_media_type",
                    _compact_markdown_code(
                        item.get("media_type") or item.get("mime_type"),
                        fallback="",
                    ),
                ),
                (
                    f"attachment_{attachment_id}_inspection_status",
                    str(item.get("inspection_status") or "not_inspected"),
                ),
                (
                    f"attachment_{attachment_id}_integrity_status",
                    str(item.get("integrity_status") or ""),
                ),
                (
                    f"attachment_{attachment_id}_integrity_owner",
                    str(item.get("integrity_verification_owner") or ""),
                ),
                (
                    f"attachment_{attachment_id}_receiver_availability",
                    str(item.get("receiver_availability") or "unknown"),
                ),
                (
                    f"attachment_{attachment_id}_receiver_local_reference",
                    (
                        _compact_markdown_code(
                            item.get("receiver_local_reference"),
                            fallback="",
                        )
                        if item.get("receiver_availability") == "available"
                        else ""
                    ),
                ),
                *(
                    (
                        f"attachment_{attachment_id}_visual_anchor_{index}",
                        _single_line(str(anchor), 240),
                    )
                    for index, anchor in enumerate(item.get("visual_anchors") or [], start=1)
                    if str(anchor).strip()
                ),
                *(
                    (
                        f"attachment_{attachment_id}_requirement_{requirement_id}",
                        str(requirement_id),
                    )
                    for requirement_id in item.get("requirement_ids") or []
                ),
            )
        )
    for item in handoff.get("verification_plan") or []:
        verification_id = str(item.get("id") or "planned_verification")
        expected.append(
            (
                f"verification_plan_{verification_id}",
                _single_line(str(item.get("text") or ""), 700),
            )
        )
    missing = [label for label, value in expected if value.strip() and value.strip() not in content]
    start_section = _compact_generated_section(content, "## Start here")
    start_steps = _compact_session_start_steps(handoff)
    start_positions = [start_section.find(step) for step in start_steps]
    if any(position < 0 for position in start_positions) or start_positions != sorted(
        start_positions
    ):
        missing.append("start_step_order")
    done_section = _compact_generated_section(content, "## Done when")
    done_bullets = [
        _compact_requirement_text(line[2:])
        for line in done_section.splitlines()
        if line.startswith("- ")
    ]
    for item in handoff.get("requirements") or []:
        requirement_id = str(item.get("id") or "").strip()
        requirement_text = _compact_requirement_text(
            item.get("normalized_text") or item.get("text")
        )
        requirement_pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(requirement_id)}(?![A-Za-z0-9])"
        )
        mapped = any(
            requirement_pattern.search(bullet) is not None
            and requirement_text.casefold() in bullet.casefold()
            for bullet in done_bullets
        )
        if requirement_id and requirement_text and not mapped:
            missing.append(f"requirement_{requirement_id}")
    for index, criterion in enumerate(
        intent.get("acceptance_criteria") or [],
        start=1,
    ):
        criterion_text = _compact_requirement_text(criterion.get("text"))
        if criterion_text and criterion_text not in done_section:
            missing.append(f"acceptance_criterion_{index}")
    if (handoff.get("files") or {}).get("pre_existing_at_handoff") and (
        "Do not stage, unstage, revert, overwrite, or reformat unrelated files." not in content
    ):
        missing.append("protected_baseline_policy")
    return missing


def _compact_generated_section(content: str, heading: str) -> str:
    """Return one exact, unquoted generated v2 section bounded by its peers."""

    lines = content.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return ""
    section_headings = frozenset(
        item for item in COMPACT_SESSION_CONTEXT_REQUIRED_HEADINGS if item.startswith("## ")
    )
    end = next(
        (index for index in range(start, len(lines)) if lines[index] in section_headings),
        len(lines),
    )
    return "\n".join(lines[start:end])


def build_session_handoff_artifact(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    continuation_lead: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    trusted_attachment_descriptors: Iterable[TrustedRequestImageDescriptor] = (),
    allow_local_artifacts: bool = False,
    checkpoint_data: dict[str, Any] | None = None,
    repository_comparison: dict[str, Any] | None = None,
    receiver_attachment_deliveries: dict[str, dict[str, str]] | None = None,
    receiver_baseline_delivery: dict[str, str] | None = None,
    render_variant: ContinuationBriefVariant | str | None = None,
) -> dict[str, Any]:
    """Build the one canonical Session Context artifact used by every surface."""

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    contract = build_session_handoff_contract(
        checkpoint,
        request_verbatim=request_verbatim,
        continuation_lead=continuation_lead,
        supporting_context=supporting_context,
        trusted_attachment_descriptors=trusted_attachment_descriptors,
        allow_local_artifacts=allow_local_artifacts,
        checkpoint_data=data,
        repository_comparison=repository_comparison,
        receiver_attachment_deliveries=receiver_attachment_deliveries,
        receiver_baseline_delivery=receiver_baseline_delivery,
    )
    resolved_variant = resolve_continuation_brief_variant(
        render_variant or settings.session_handoff_brief_variant
    )
    content = render_session_handoff(
        checkpoint,
        request_verbatim=request_verbatim,
        supporting_context=supporting_context,
        contract=contract,
        checkpoint_data=data,
        variant=resolved_variant,
    )
    render_issues = session_handoff_render_issues(
        content,
        request_verbatim=request_verbatim,
        supporting_context=contract["supporting_context"],
        handoff_contract=contract,
        variant=resolved_variant,
    )
    if render_issues:
        quality = contract["quality_report"]
        quality["status"] = "blocked"
        quality["copy_ready"] = False
        quality["automatic_execution_ready"] = False
        quality["checks"] = [*quality["checks"], *render_issues]
        quality["blocking_issues"] = [
            *quality["blocking_issues"],
            *render_issues,
        ]
    return {
        "schema_version": SESSION_HANDOFF_SCHEMA_VERSION,
        "scope": "session",
        "provider": data["provider"],
        "session_id": data["session_id"],
        "checkpoint_id": data["id"],
        "source_document_id": data["source_document_id"],
        "boundary": data["boundary"],
        "snapshot_phase": data["boundary"].get("snapshot_phase"),
        "captured_at": data["boundary"].get("occurred_at"),
        "currentness": data.get("currentness"),
        "render_variant": resolved_variant.value,
        **contract,
        "content": content,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "estimated_tokens": max(1, (len(content) + 3) // 4),
    }


def _append_session_context_quote(
    lines: list[str],
    statement: str,
    *,
    label: str,
) -> None:
    statement_lines = statement.splitlines() or [""]
    lines.append(f"> [{label}] {statement_lines[0]}")
    lines.extend(f"> {line}" if line else ">" for line in statement_lines[1:])


async def _resolve_boundary(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    boundary_event_id: UUID | None,
) -> SessionEvent:
    conditions = (
        SessionEvent.workspace_id == workspace_id,
        SessionEvent.provider == provider,
        SessionEvent.session_id == session_id,
    )
    if boundary_event_id is not None:
        boundary = await session.scalar(
            select(SessionEvent).where(SessionEvent.id == boundary_event_id, *conditions)
        )
    else:
        boundary = await session.scalar(
            select(SessionEvent)
            .where(*conditions)
            .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
            .limit(1)
        )
    if boundary is None:
        raise ValueError("Session boundary not found")
    return boundary


def _bind_checkpoint_goal_artifacts(
    sections: dict[str, list[DraftItem]],
    *,
    source_document: SourceDocument,
    provider: str,
) -> None:
    """Freeze exact-turn image descriptors into the immutable checkpoint."""

    goals = sections.get("goal") or []
    if not goals or not goals[0].events:
        return
    goal = goals[0]
    request_verbatim = str(goal.payload.get("request_verbatim") or "").strip()
    if not request_verbatim:
        return

    raw_fragments = goal.payload.get("request_fragments")
    fragments = raw_fragments if isinstance(raw_fragments, list) else []
    fragment_by_event = {
        (
            str(item.get("provider_event_id") or ""),
            item.get("sequence_number"),
        ): str(item.get("request_verbatim") or "").strip()
        for item in fragments
        if isinstance(item, dict)
    }
    metadata = _json_object(source_document.metadata_json)
    source_path = str(metadata.get("source_path") or "").strip()
    configured_root = (
        Path(settings.codex_home).expanduser() if settings.codex_home else Path.home() / ".codex"
    )
    collected: list[TrustedRequestImageDescriptor] = []
    for index, goal_event in enumerate(goal.events):
        fragment_request = fragment_by_event.get(
            (str(goal_event.provider_event_id or ""), goal_event.sequence_number),
            request_verbatim if index == 0 else "",
        )
        if not fragment_request:
            continue
        descriptors = trusted_request_image_descriptors_from_payload(event_payload(goal_event))
        needs_durable_resolution = not descriptors or any(
            not descriptor.resolved_path for descriptor in descriptors if descriptor.binding_valid
        )
        recovered: tuple[TrustedRequestImageDescriptor, ...] = ()
        if provider == "codex" and needs_durable_resolution and source_path:
            recovered = recover_codex_request_image_descriptors(
                source_path=source_path,
                source_sequence_number=goal_event.sequence_number,
                request_verbatim=fragment_request,
                codex_sessions_root=configured_root / "sessions",
                artifact_data_dir=settings.data_dir,
            )
        if recovered:
            if not descriptors:
                descriptors = recovered
            elif _same_descriptor_binding(descriptors, recovered):
                descriptors = tuple(
                    replace(
                        recovered_descriptor,
                        visual_inspection=source_descriptor.visual_inspection,
                        visual_inspection_attested=(source_descriptor.visual_inspection_attested),
                    )
                    for source_descriptor, recovered_descriptor in zip(
                        descriptors,
                        recovered,
                        strict=True,
                    )
                )
            else:
                descriptors = tuple(
                    TrustedRequestImageDescriptor(
                        path=descriptor.path,
                        sha256=descriptor.sha256,
                        mime_type=descriptor.mime_type,
                        resolved_path=None,
                        ordinal=descriptor.ordinal,
                        size_bytes=descriptor.size_bytes,
                        binding_valid=False,
                        binding_error=(
                            "The normalized provider metadata conflicts with "
                            "the immutable raw turn."
                        ),
                        visual_inspection=descriptor.visual_inspection,
                        visual_inspection_attested=descriptor.visual_inspection_attested,
                    )
                    for descriptor in descriptors
                )
        collected.extend(
            materialize_trusted_request_image_descriptor(
                descriptor,
                data_dir=settings.data_dir,
            )
            for descriptor in descriptors
        )

    seen_descriptors: set[tuple[str, str | None]] = set()
    unique_descriptors: list[TrustedRequestImageDescriptor] = []
    for descriptor in collected:
        key = (descriptor.path, descriptor.sha256)
        if key in seen_descriptors:
            continue
        seen_descriptors.add(key)
        unique_descriptors.append(descriptor)
    descriptors = tuple(unique_descriptors)
    serialized = [_trusted_image_descriptor_to_dict(descriptor) for descriptor in descriptors]
    goal.payload.update(
        {
            "trusted_image_descriptors": serialized,
            "trusted_image_descriptors_sha256": _sha256(_canonical_json(serialized)),
        }
    )


def _same_descriptor_binding(
    left: Iterable[TrustedRequestImageDescriptor],
    right: Iterable[TrustedRequestImageDescriptor],
) -> bool:
    left_values = tuple(left)
    right_values = tuple(right)
    if len(left_values) != len(right_values):
        return False
    return all(
        left_item.path == right_item.path
        and left_item.ordinal == right_item.ordinal
        and (
            left_item.sha256 is None
            or right_item.sha256 is None
            or left_item.sha256.casefold() == right_item.sha256.casefold()
        )
        for left_item, right_item in zip(
            left_values,
            right_values,
            strict=True,
        )
    )


def _trusted_image_descriptor_to_dict(
    descriptor: TrustedRequestImageDescriptor,
) -> dict[str, Any]:
    return {
        "path": descriptor.path,
        "sha256": descriptor.sha256,
        "mime_type": descriptor.mime_type,
        "resolved_path": descriptor.resolved_path,
        "stored_path": descriptor.resolved_path,
        "ordinal": descriptor.ordinal,
        "size_bytes": descriptor.size_bytes,
        "binding_valid": descriptor.binding_valid,
        "binding_error": descriptor.binding_error,
        "visual_inspection": descriptor.visual_inspection,
        "visual_inspection_attested": descriptor.visual_inspection_attested,
    }


def _open_item_kind(statement: str) -> str:
    normalized = statement.casefold()
    if "open question" in normalized or "unclear" in normalized:
        return "open_question"
    if "risk" in normalized or "caveat" in normalized:
        return "risk"
    if "assum" in normalized:
        return "assumption"
    if "constraint" in normalized:
        return "constraint"
    return "unknown"


def _is_useful_discovery_command(command: str) -> bool:
    normalized = re.sub(r"\s+", " ", command).strip()
    if not normalized or _LOW_VALUE_DISCOVERY_COMMAND.fullmatch(normalized):
        return False
    segments = _shell_command_segments(command)
    return bool(
        segments is not None
        and all(_is_read_only_discovery_segment(segment) for segment in segments)
    )


def _meaningful_command_result(
    event: SessionEvent,
    payload: dict[str, Any],
) -> str | None:
    raw: Any = next(
        (
            payload.get(key)
            for key in ("stdout", "output", "result", "summary")
            if payload.get(key) not in (None, "")
        ),
        None,
    )
    if not str(raw or "").strip():
        raw = event.content
    if isinstance(raw, (dict, list, tuple)):
        raw = _canonical_json(raw)
    return _compact_command_result_text(raw)


def _compact_command_result_text(value: Any) -> str | None:
    raw_text = _redacted_historical_text(value)
    wrapped_output = re.search(
        r"(?ms)(?:^|\n)Output:\s*\n(?P<output>.*)\Z",
        raw_text,
    )
    if wrapped_output is not None:
        raw_text = wrapped_output.group("output")
    else:
        inline_output = re.search(
            r"(?is)\bOutput:\s*(?P<output>.*)\Z",
            raw_text,
        )
        if inline_output is not None and re.search(
            r"\b(?:Chunk ID|Original token count|Process exited|"
            r"Script (?:completed|failed)|Wall time)\b",
            raw_text[: inline_output.start()],
            re.IGNORECASE,
        ):
            raw_text = inline_output.group("output")
    summary = re.sub(
        r"\s+",
        " ",
        raw_text,
    ).strip()
    if not summary:
        return None
    if re.fullmatch(
        r"(?:process\s+)?(?:completed|finished|exited)"
        r"(?:\s+with)?(?:\s+(?:exit\s+)?code)?\s*0?\.?",
        summary,
        re.IGNORECASE,
    ):
        return None
    return _single_line(summary, SESSION_HANDOFF_RENDERED_RESULT_CHARS)


def _session_task_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", value.casefold()):
        token = raw[:-1] if len(raw) > 4 and raw.endswith("s") else raw
        if len(token) < 3 or token in _SESSION_TASK_TOKEN_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _request_extends_active_session_task(
    request: str,
    *,
    active_requests: Iterable[str],
) -> bool:
    if _SESSION_TASK_RESET_RE.search(request):
        return False
    if _SESSION_TASK_FOLLOWUP_RE.search(request):
        return True

    request_words = re.findall(r"[a-z0-9]+", request.casefold())
    if len(request_words) <= 40 and _SESSION_TASK_DELIVERY_FOLLOWUP_RE.search(request):
        return True

    active_text = "\n".join(active_requests)
    shared = _session_task_tokens(request) & _session_task_tokens(active_text)
    if len(shared) >= 2:
        return True
    return bool(len(request_words) <= 30 and any(len(token) >= 6 for token in shared))


def _active_session_request_chain(
    events: Iterable[SessionEvent],
) -> list[tuple[SessionEvent, str, str]]:
    """Return the latest standalone request plus its dependent follow-ups."""

    chain: list[tuple[SessionEvent, str, str]] = []
    for event in events:
        normalized = _checkpoint_user_request(event)
        if normalized is None:
            continue
        request_verbatim = _validated_session_request(_checkpoint_request_verbatim(event))
        if request_verbatim is None:
            request_verbatim = normalized
        if chain and not _request_extends_active_session_task(
            normalized,
            active_requests=(item[1] for item in chain),
        ):
            chain = []
        chain.append((event, normalized, request_verbatim))
    return chain


def _compose_session_goal_request(
    chain: Iterable[tuple[SessionEvent, str, str]],
) -> str:
    values = list(chain)
    if not values:
        return ""
    if len(values) == 1:
        # A one-turn task can preserve the source request byte-for-byte. The
        # rendered goal trims presentation whitespace separately, while hashes
        # and downstream continuation contracts retain the exact payload.
        return values[0][2]

    primary = values[0][2].strip()
    lines = [primary, "", "## Additional user-authored requirements"]
    for index, (_, _, request_verbatim) in enumerate(values[1:], start=1):
        lines.extend(
            [
                "",
                f"### Follow-up {index}",
                request_verbatim.strip(),
            ]
        )
    return "\n".join(lines).strip()


def _build_sections(
    events: list[SessionEvent],
    snapshot: RepositorySnapshot | None,
) -> dict[str, list[DraftItem]]:
    sections: dict[str, list[DraftItem]] = {category: [] for category in CHECKPOINT_CATEGORIES}
    request_chain = _active_session_request_chain(events)
    goal_events = [item[0] for item in request_chain]
    goal_event = goal_events[0] if goal_events else None
    goal_statement = _compose_session_goal_request(request_chain)
    final_goal_event = goal_events[-1] if goal_events else None
    continuation_events = [
        event
        for event in events
        if event.event_type == "user_request"
        and is_continuation_control(event.content)
        and (final_goal_event is None or event.sequence_number > final_goal_event.sequence_number)
    ]
    # Every derived section belongs to the active task chain. Dependent user
    # follow-ups amend the root task instead of replacing it; a genuinely
    # standalone later request starts a new segment and still excludes older
    # unrelated work.
    events = (
        [event for event in events if event.sequence_number >= goal_event.sequence_number]
        if goal_event is not None
        else []
    )
    if goal_event is not None:
        request_verbatim = goal_statement
        supporting_context: list[dict[str, str]] = []
        seen_supporting_context: set[str] = set()
        for request_event, _, fragment in request_chain:
            for item in _materialized_referenced_context(
                request_event.content,
                request_verbatim=fragment,
            ):
                key = _canonical_json(item)
                if key in seen_supporting_context:
                    continue
                seen_supporting_context.add(key)
                supporting_context.append(item)
        stored_requirements = _derive_session_requirements_from_fragments(
            request_verbatim or str(goal_statement or ""),
            request_fragments=[fragment for _, _, fragment in request_chain],
            supporting_context=supporting_context,
        )
        goal_payload: dict[str, Any] = {
            "request_fragments": [
                {
                    "provider_event_id": event.provider_event_id,
                    "sequence_number": event.sequence_number,
                    "request_verbatim": fragment,
                    "request_sha256": _sha256(fragment),
                }
                for event, _, fragment in request_chain
            ],
        }
        if request_verbatim:
            goal_payload.update(
                {
                    "request_verbatim": request_verbatim,
                    "request_sha256": _sha256(request_verbatim),
                    "task_mode": _infer_session_task_mode(request_verbatim),
                }
            )
        if supporting_context:
            goal_payload.update(
                {
                    "supporting_context": supporting_context,
                    "supporting_context_sha256": _sha256(_canonical_json(supporting_context)),
                }
            )
        if stored_requirements:
            goal_payload["requirements"] = stored_requirements
        sections["goal"] = [
            DraftItem(
                category="goal",
                statement=str(goal_statement or "").strip(),
                truth_state="reported",
                events=goal_events,
                payload=goal_payload,
            )
        ]

    progress: list[DraftItem] = []
    for event in events:
        if (
            event.event_type != "assistant_update"
            or not event.content
            or is_session_instruction_noise(event.content)
        ):
            continue
        for sentence in _sentences(event.content):
            if _PROGRESS_SIGNAL.search(sentence):
                progress.append(
                    DraftItem(
                        category="progress",
                        statement=_statement(sentence),
                        truth_state="reported",
                        events=[event],
                        payload=(
                            {"reason": reason} if (reason := _statement_reason(sentence)) else {}
                        ),
                    )
                )
    sections["progress"] = _dedupe_drafts(progress)[-MAX_ITEMS_PER_CATEGORY:]

    decisions: list[DraftItem] = []
    for event in events:
        if event.event_type not in {"user_request", "assistant_update"}:
            continue
        decision_content = (
            extract_user_authored_request(event.content)
            if event.event_type == "user_request"
            else event.content
        )
        if (
            not decision_content
            or is_session_instruction_noise(decision_content)
            or (event.event_type == "user_request" and is_continuation_control(decision_content))
        ):
            continue
        for sentence in _sentences(decision_content):
            if _DECISION_SIGNAL.search(sentence):
                decisions.append(
                    DraftItem(
                        category="decisions",
                        statement=_statement(sentence),
                        truth_state="reported",
                        events=[event],
                        payload=(
                            {"reason": reason} if (reason := _statement_reason(sentence)) else {}
                        ),
                    )
                )
    sections["decisions"] = _dedupe_drafts(decisions)[-MAX_ITEMS_PER_CATEGORY:]

    reported_failures: list[DraftItem] = []
    discoveries: list[DraftItem] = []
    open_items: list[DraftItem] = []
    for event in events:
        if event.event_type not in {"user_request", "assistant_update"}:
            continue
        source_text = (
            extract_user_authored_request(event.content)
            if event.event_type == "user_request"
            else event.content
        )
        if (
            not source_text
            or is_session_instruction_noise(source_text)
            or (event.event_type == "user_request" and is_continuation_control(source_text))
        ):
            continue
        for sentence in _sentences(source_text):
            if _FAILED_OR_REJECTED_ATTEMPT_SIGNAL.search(
                sentence
            ) and not _is_tool_selection_statement(sentence):
                reason = _failed_attempt_reason(sentence)
                reported_failures.append(
                    DraftItem(
                        category="failed_attempts",
                        statement=_statement(sentence),
                        truth_state=(
                            "user_asserted" if event.event_type == "user_request" else "reported"
                        ),
                        events=[event],
                        state="historical",
                        payload={
                            "attempt_kind": (
                                "rejected"
                                if re.search(
                                    r"\b(?:rejected|ruled\s+out|abandoned)\b",
                                    sentence,
                                    re.IGNORECASE,
                                )
                                else "failed"
                            ),
                            "reason": reason,
                            "evidence_summary": (
                                f"{event.event_type} at session sequence {event.sequence_number}"
                            ),
                        },
                    )
                )
            if (
                event.event_type == "assistant_update"
                and _DISCOVERY_SIGNAL.search(sentence)
                and not _PROGRESS_SIGNAL.search(sentence)
                and not _BLOCKER_SIGNAL.search(sentence)
                and not _NEXT_SIGNAL.search(sentence)
                and not _is_tool_selection_statement(sentence)
            ):
                paths = _extract_paths(sentence)
                discoveries.append(
                    DraftItem(
                        category="discoveries",
                        statement=_statement(sentence),
                        truth_state="reported",
                        events=[event],
                        payload={"paths": paths},
                    )
                )
            if _OPEN_ITEM_SIGNAL.search(sentence) and not _BLOCKER_SIGNAL.search(sentence):
                open_items.append(
                    DraftItem(
                        category="open_items",
                        statement=_statement(sentence),
                        truth_state=(
                            "user_asserted" if event.event_type == "user_request" else "reported"
                        ),
                        events=[event],
                        payload={"kind": _open_item_kind(sentence)},
                    )
                )
    sections["discoveries"] = _dedupe_drafts(discoveries)[-MAX_ITEMS_PER_CATEGORY:]
    sections["open_items"] = _dedupe_drafts(open_items)[-MAX_ITEMS_PER_CATEGORY:]

    result_events = [
        event for event in events if event.event_type in {"command_result", "tool_result"}
    ]
    command_results = [event for event in result_events if event.event_type == "command_result"]
    failures: list[DraftItem] = list(reported_failures)
    for event in result_events:
        payload = event_payload(event)
        exit_code = payload.get("exit_code")
        passed = payload.get("passed")
        if exit_code not in (None, 0) or passed is False:
            command = str(
                payload.get("command") or payload.get("tool_name") or "unknown tool operation"
            )
            failures.append(
                DraftItem(
                    category="failed_attempts",
                    statement=f"`{_single_line(command, 500)}` failed with exit code {exit_code}.",
                    truth_state="observed",
                    events=[event],
                    state="historical",
                    payload={
                        "command": command,
                        "cwd": payload.get("cwd"),
                        "exit_code": exit_code,
                        "result_summary": _meaningful_command_result(event, payload),
                    },
                )
            )
    sections["failed_attempts"] = failures[-MAX_ITEMS_PER_CATEGORY:]

    useful_commands: dict[tuple[str, str], DraftItem] = {}
    for event in command_results:
        payload = event_payload(event)
        command = str(payload.get("command") or "").strip()
        if not command:
            continue
        purpose = (
            "verification"
            if _is_useful_verification_command(command)
            else "discovery"
            if _is_useful_discovery_command(command)
            else None
        )
        if purpose is None:
            continue
        exit_code = payload.get("exit_code")
        passed = payload.get("passed")
        has_outcome = isinstance(passed, bool) or (
            isinstance(exit_code, int) and not isinstance(exit_code, bool)
        )
        if not has_outcome:
            continue
        succeeded = passed is True or (passed is not False and exit_code == 0)
        if purpose == "discovery" and not succeeded:
            # A no-match or failed inspection is useful only when the session
            # explicitly explains the resulting discovery. It is not promoted
            # merely because a read-only command returned non-zero.
            continue
        result_summary = _meaningful_command_result(event, payload)
        if purpose == "discovery" and not result_summary:
            continue
        state = "passed" if succeeded else "failed"
        normalized_command = re.sub(r"\s+", " ", command).strip()
        cwd = str(payload.get("cwd") or "").strip()
        useful_commands[(cwd, normalized_command)] = DraftItem(
            category="useful_commands",
            statement=(
                f"`{_single_line(normalized_command, 500)}` {state}"
                + (f": {_single_line(result_summary, 500)}" if result_summary else ".")
            ),
            truth_state="observed",
            events=[event],
            state=state,
            payload={
                "command": command,
                "cwd": payload.get("cwd"),
                "exit_code": (
                    exit_code
                    if isinstance(exit_code, int) and not isinstance(exit_code, bool)
                    else None
                ),
                "passed": succeeded,
                "purpose": purpose,
                "result_summary": result_summary,
            },
        )
    sections["useful_commands"] = list(useful_commands.values())[-MAX_ITEMS_PER_CATEGORY:]

    file_evidence: dict[str, list[SessionEvent]] = {}
    for event in events:
        if event.event_type not in {
            "command_call",
            "command_result",
            "tool_call",
            "tool_result",
            "assistant_update",
        }:
            continue
        payload = event_payload(event)
        corpus_values = [payload.get("command")]
        if event.event_type in {"command_call", "tool_call", "assistant_update"}:
            corpus_values.append(event.content)
        if event.event_type in {"command_call", "tool_call"} and payload.get("input"):
            corpus_values.append(_canonical_json(payload["input"]))
        corpus = "\n".join(str(value) for value in corpus_values if value)
        for path in _extract_paths(corpus):
            file_evidence.setdefault(path, []).append(event)
    normalized_files: dict[str, tuple[list[SessionEvent], dict[str, Any]]] = {}
    for path, evidence in file_evidence.items():
        payload: dict[str, Any] = {"path": path}
        display_path = path
        if snapshot is not None:
            candidate = Path(path)
            absolute = candidate if candidate.is_absolute() else Path(snapshot.root) / candidate
            try:
                root = Path(snapshot.root).resolve()
                resolved = absolute.resolve()
                if resolved == root or root not in resolved.parents:
                    continue
                display_path = resolved.relative_to(root).as_posix()
                exists = resolved.is_file()
                tracked = display_path in snapshot.changed_files
                if not exists and not tracked:
                    continue
                payload = {
                    "path": display_path,
                    "exists_at_capture": exists,
                    "changed_at_capture": tracked,
                }
            except OSError:
                continue
        existing = normalized_files.get(display_path)
        if existing is None:
            normalized_files[display_path] = (list(evidence), payload)
        else:
            existing[0].extend(evidence)
    for display_path, (evidence, payload) in list(normalized_files.items())[-30:]:
        truth = (
            "observed"
            if any(
                event.event_type in {"command_call", "command_result", "tool_call", "tool_result"}
                for event in evidence
            )
            else "reported"
        )
        sections["relevant_files"].append(
            DraftItem(
                category="relevant_files",
                statement=display_path,
                truth_state=truth,
                events=evidence[-3:],
                payload=payload,
            )
        )

    blockers: list[DraftItem] = []
    for event in events:
        if (
            event.event_type == "assistant_update"
            and event.content
            and not is_session_instruction_noise(event.content)
        ):
            for sentence in _sentences(event.content):
                if _BLOCKER_SIGNAL.search(sentence):
                    blockers.append(
                        DraftItem(
                            category="blockers",
                            statement=_statement(sentence),
                            truth_state="reported",
                            events=[event],
                        )
                    )
    latest_progress_sequence = max(
        (item.events[-1].sequence_number for item in progress if item.events),
        default=None,
    )
    if latest_progress_sequence is not None:
        for blocker in blockers:
            if blocker.events and blocker.events[-1].sequence_number < latest_progress_sequence:
                blocker.state = "historical"
    sections["blockers"] = _dedupe_drafts(blockers)[-MAX_ITEMS_PER_CATEGORY:]

    latest_verification_by_command: dict[tuple[str, str], DraftItem] = {}
    for event in command_results:
        payload = event_payload(event)
        command = str(payload.get("command") or "").strip()
        safe_for_context = _is_useful_verification_command(command)
        if not command or not (
            safe_for_context or _UNTRUSTED_VERIFICATION_COMMAND_MARKER.search(command)
        ):
            continue
        exit_code = payload.get("exit_code")
        label = "passed" if exit_code == 0 else "failed" if exit_code is not None else "completed"
        draft = DraftItem(
            category="verification",
            statement=f"`{_single_line(command, 500)}` {label}"
            + (f" (exit {exit_code})." if exit_code is not None else "."),
            truth_state="observed",
            events=[event],
            state=label,
            payload={
                "command": command,
                "cwd": payload.get("cwd"),
                "exit_code": exit_code,
                "passed": exit_code == 0 if exit_code is not None else None,
                "context_eligible": safe_for_context,
                "scope": next(
                    (
                        payload.get(key)
                        for key in (
                            "scope",
                            "test_scope",
                            "verification_scope",
                            "target",
                        )
                        if payload.get(key) not in (None, "")
                    ),
                    None,
                ),
            },
        )
        latest_verification_by_command[(str(payload.get("cwd") or ""), command)] = draft
    sections["verification"] = list(latest_verification_by_command.values())[
        -MAX_ITEMS_PER_CATEGORY:
    ]

    next_item = _derive_next_action(
        events,
        goal_event,
        goal_statement,
        sections["blockers"],
        continuation_events[-1] if continuation_events else None,
    )
    if next_item is not None:
        sections["exact_next_action"] = [next_item]
    return sections


def _derive_next_action(
    events: list[SessionEvent],
    goal_event: SessionEvent | None,
    goal_statement: str | None,
    blockers: list[DraftItem],
    continuation_event: SessionEvent | None,
) -> DraftItem | None:
    for event in reversed(events):
        if (
            event.event_type != "assistant_update"
            or not event.content
            or is_session_instruction_noise(event.content)
        ):
            continue
        match = _NEXT_SIGNAL.search(event.content)
        if match:
            candidate = _sentences(match.group(1))
            if candidate:
                return DraftItem(
                    category="exact_next_action",
                    statement=_statement(candidate[0]),
                    truth_state="reported",
                    events=[event],
                )
    active_blockers = [
        blocker
        for blocker in blockers
        if blocker.state.strip().lower() not in _INACTIVE_BLOCKER_STATES
    ]
    if active_blockers:
        blocker = active_blockers[-1]
        command = blocker.payload.get("command")
        statement = (
            f"Fix the failure from `{_single_line(str(command), 500)}` and rerun that command."
            if command
            else f"Resolve this blocker: {blocker.statement}"
        )
        return DraftItem(
            category="exact_next_action",
            statement=statement,
            truth_state=blocker.truth_state,
            events=blocker.events,
        )
    latest_assistant = next(
        (
            event
            for event in reversed(events)
            if event.event_type == "assistant_update"
            and event.content
            and not is_session_instruction_noise(event.content)
        ),
        None,
    )
    if (
        latest_assistant is not None
        and _COMPLETION_SIGNAL.search(latest_assistant.content or "")
        and (
            continuation_event is None
            or continuation_event.sequence_number < latest_assistant.sequence_number
        )
    ):
        return DraftItem(
            category="exact_next_action",
            statement=(
                "Review the completed result and start a new request only if more work is needed."
            ),
            truth_state="reported",
            events=[latest_assistant],
        )
    if goal_event is not None:
        return DraftItem(
            category="exact_next_action",
            statement=f"Continue the current request: {_statement(goal_statement, 900)}",
            truth_state=("reported" if continuation_event is not None else "derived"),
            events=[goal_event, *([continuation_event] if continuation_event else [])],
            payload=(
                {"source": "explicit_continuation_control"}
                if continuation_event is not None
                else {"derived_from_recovered_goal": True}
            ),
        )
    return None


def _checkpoint_user_request(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return normalize_substantive_user_request(event.content)
    if event.event_type == "runtime_instruction" and event.role == "user":
        return extract_delegated_user_request(event.content)
    return None


def _checkpoint_request_verbatim(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return extract_user_authored_request(event.content)
    if event.event_type == "runtime_instruction" and event.role == "user":
        return extract_delegated_user_request(event.content)
    return None


async def _capture_snapshot(
    events: list[SessionEvent],
    source_document: SourceDocument,
) -> RepositorySnapshot | None:
    candidates: list[str] = []
    for event in reversed(events):
        cwd = event_payload(event).get("cwd")
        if cwd:
            candidates.append(str(cwd))
    metadata = _json_object(source_document.metadata_json)
    for key in ("cwd", "workdir", "repo_path"):
        if metadata.get(key):
            candidates.append(str(metadata[key]))
    for raw in candidates:
        try:
            path = Path(raw).expanduser()
            if path.exists():
                return await capture_repository_snapshot(path)
        except (OSError, ValueError):
            continue
    return None


def _checkpoint_payload(
    checkpoint: WorkCheckpoint,
    *,
    boundary: SessionEvent,
    sections: dict[str, list[DraftItem]],
    snapshot: RepositorySnapshot | None,
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "workspace_id": str(checkpoint.workspace_id),
        "provider": checkpoint.provider,
        "session_id": checkpoint.session_id,
        "boundary": {
            "session_event_id": str(boundary.id),
            "provider_event_id": boundary.provider_event_id,
            "sequence_number": boundary.sequence_number,
            "event_type": boundary.event_type,
            "occurred_at": boundary.occurred_at.isoformat() if boundary.occurred_at else None,
            "source_document_id": str(boundary.source_document_id),
        },
        "trigger": checkpoint.trigger,
        "capture_status": checkpoint.capture_status,
        "continuation_status": checkpoint.continuation_status,
        "repo": snapshot.to_dict() if snapshot else None,
        "sections": {
            category: [
                {
                    "item_key": f"{category}:{index + 1}",
                    "statement": item.statement,
                    "state": item.state,
                    "truth_state": item.truth_state,
                    "payload": item.payload,
                    "evidence_event_ids": [str(event.id) for event in _unique_events(item.events)],
                }
                for index, item in enumerate(sections[category])
            ]
            for category in CHECKPOINT_CATEGORIES
        },
    }


def _verification_to_dict(value: CheckpointVerification) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "status": value.status,
        "worktree_fingerprint": value.worktree_fingerprint,
        "policy_version": value.policy_version,
        "results": _json_object(value.results_json),
        "verified_at": value.verified_at,
    }


def _sentences(value: str) -> list[str]:
    cleaned = _self_contained_goal(value)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    return [
        part.strip(" -•\t")
        for part in re.split(r"(?<=[.!?])\s+|\s*[\r\n]+\s*", cleaned)
        if len(part.strip(" -•\t")) >= 4
    ]


def _statement(value: str | None, limit: int = MAX_STATEMENT_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _statement_reason(value: str) -> str | None:
    match = _REASON_CLAUSE.search(value)
    if match is None:
        return None
    reason = _statement(match.group(1), 800).rstrip(".!?")
    return reason or None


def _failed_attempt_reason(value: str) -> str | None:
    reason = _statement_reason(value)
    if reason:
        return reason
    match = _FAILED_ATTEMPT_CONTRAST_REASON.search(value)
    if match is None:
        return None
    reason = _statement(match.group(1), 800).rstrip(".!?")
    return reason or None


def _single_line(value: str, limit: int) -> str:
    return _statement(value, limit).replace("`", "'")


def _historical_single_line(value: Any, limit: int) -> str:
    return _single_line(_redacted_historical_text(value), limit)


def _compact_display_ids(values: list[str]) -> str:
    if not values:
        return ""
    parsed: list[tuple[str, int]] = []
    for value in values:
        match = re.fullmatch(r"([A-Za-z]+)([1-9][0-9]*)", value)
        if match is None:
            return ", ".join(values)
        parsed.append((match.group(1), int(match.group(2))))
    if len({prefix for prefix, _number in parsed}) != 1:
        return ", ".join(values)
    numbers = [number for _prefix, number in parsed]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        return ", ".join(values)
    prefix = parsed[0][0]
    return (
        f"{prefix}{numbers[0]}"
        if len(numbers) == 1
        else f"{prefix}{numbers[0]}–{prefix}{numbers[-1]}"
    )


def _extract_paths(value: str) -> list[str]:
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(value):
        path = match.group(1).rstrip(".,);]}")
        lowered = path.lower()
        if any(part in lowered for part in ("node_modules/", ".git/objects/", "__pycache__/")):
            continue
        if path not in paths:
            paths.append(path)
    return paths[:100]


def _dedupe_drafts(values: Iterable[DraftItem]) -> list[DraftItem]:
    result: list[DraftItem] = []
    by_statement: dict[str, DraftItem] = {}
    for value in values:
        key = re.sub(r"\W+", " ", value.statement.lower()).strip()
        if not key:
            continue
        if key in by_statement:
            by_statement[key].events.extend(value.events)
            continue
        by_statement[key] = value
        result.append(value)
    return result


def _unique_events(values: Iterable[SessionEvent]) -> list[SessionEvent]:
    result: list[SessionEvent] = []
    seen: set[UUID] = set()
    for value in values:
        if value.id not in seen:
            result.append(value)
            seen.add(value.id)
    return result


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
