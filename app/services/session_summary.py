from __future__ import annotations

import re


_GENERIC_TITLE_RE = re.compile(
    r"^(?:ai|codex|claude(?: code)?|opencode)?\s*session(?:\s*[·:#-]\s*[\w-]+)?$",
    re.IGNORECASE,
)
_NOISE_MARKERS = (
    "request_user_input availability",
    "<apps_instructions>",
    "<collaboration_mode>",
    "<environment_context>",
    "<permissions instructions>",
    "<plugins_instructions>",
    "<skills_instructions>",
    "available skills",
    "filesystem sandboxing",
    "you are codex",
)
_LEADING_REQUEST_RE = re.compile(
    r"^(?:/goal\s+|now\s+|please\s+|can you\s+|could you\s+|would you\s+|"
    r"i (?:now )?want you to\s+|i need you to\s+|help me(?: to)?\s+|go ahead and\s+|"
    r"work on\s+)",
    re.IGNORECASE,
)


def derive_session_topic(
    content: str | None,
    *,
    explicit_title: str | None = None,
    tool: str | None = None,
    session_id: str | None = None,
) -> str | None:
    """Return a short human topic, never a provider name or raw session ID."""

    title = _clean_candidate(explicit_title or "")
    if title and not _is_generic_title(title, tool=tool, session_id=session_id):
        return _shorten(title)

    text = content or ""
    user_blocks = re.findall(
        r"(?ms)^\[USER\]\s*(.*?)(?=^\[[A-Z_]+\]\s*|\Z)",
        text,
    )
    for candidate in user_blocks or [text]:
        if _looks_like_bootstrap_noise(candidate):
            continue
        cleaned = _clean_candidate(candidate)
        if cleaned:
            return _shorten(cleaned)
    return None


def _is_generic_title(title: str, *, tool: str | None, session_id: str | None) -> bool:
    if not title or _GENERIC_TITLE_RE.fullmatch(title):
        return True
    lowered = title.lower()
    if session_id and session_id.lower() in lowered:
        return True
    short_id = (session_id or "")[-12:].lower()
    if short_id and short_id in lowered:
        return True
    return bool(tool and lowered in {tool.lower(), f"{tool.lower()} session"})


def _looks_like_bootstrap_noise(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _NOISE_MARKERS)


def _clean_candidate(value: str) -> str:
    text = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"(?:/[\w. -]+){2,}", " ", text)
    text = re.sub(
        r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"^[#>*\-\d.)\s]+", "", raw_line).strip()
        if not line or line.startswith("["):
            continue
        if line.lower().startswith(("files mentioned", "image #")):
            continue
        if any(marker in line.lower() for marker in _NOISE_MARKERS):
            continue
        lines.append(line)
    if not lines:
        return ""
    sentence = re.split(r"[.!?,;]", " ".join(lines), maxsplit=1)[0].strip()
    previous = None
    while sentence and sentence != previous:
        previous = sentence
        sentence = _LEADING_REQUEST_RE.sub("", sentence).strip()
    sentence = re.sub(r"\ba\s+oss\b", "an OSS", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\boss\s+sucess\b", "OSS success", sentence, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", sentence).strip(" :;,-")


def _shorten(value: str, max_words: int = 7, max_chars: int = 56) -> str:
    shortened = " ".join(value.split()[:max_words]).strip()
    if len(shortened) > max_chars:
        shortened = shortened[:max_chars].rsplit(" ", 1)[0]
    return shortened[:1].upper() + shortened[1:] if shortened else ""
