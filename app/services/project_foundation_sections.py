from __future__ import annotations

import re
from typing import Any

from app.schemas.continuation_execution import (
    ProjectContextKind,
    ProjectFoundationSection,
)


PROJECT_FOUNDATION_SECTIONS: tuple[
    tuple[ProjectFoundationSection, str], ...
] = (
    (
        ProjectFoundationSection.IDENTITY,
        "What the project is, who it serves, what problem it solves, and why it exists",
    ),
    (
        ProjectFoundationSection.WORKFLOWS,
        "Primary workflows and expected behaviour",
    ),
    (
        ProjectFoundationSection.ARCHITECTURE,
        "Architecture, boundaries, data flow, storage, APIs, integrations, and authentication",
    ),
    (ProjectFoundationSection.DOMAIN, "Domain model and terminology"),
    (
        ProjectFoundationSection.REPOSITORY,
        "Repository map, modules, entry points, and responsibilities",
    ),
    (
        ProjectFoundationSection.STACK,
        "Technology stack, services, runtime, deployment, and infrastructure",
    ),
    (
        ProjectFoundationSection.DECISIONS,
        "Persistent decisions and invariants",
    ),
    (
        ProjectFoundationSection.CONVENTIONS,
        "Engineering conventions",
    ),
    (ProjectFoundationSection.COMMANDS, "Canonical commands"),
    (
        ProjectFoundationSection.CAPABILITIES,
        "Supported capabilities and deliberate non-capabilities",
    ),
    (
        ProjectFoundationSection.CONSTRAINTS,
        "Long-term constraints, technical debt, security boundaries, and persistent risks",
    ),
    (
        ProjectFoundationSection.DIRECTION,
        "Current product direction and quality requirements",
    ),
)

PROJECT_FOUNDATION_CORE_SECTIONS = frozenset({
    ProjectFoundationSection.IDENTITY,
    ProjectFoundationSection.WORKFLOWS,
    ProjectFoundationSection.ARCHITECTURE,
    ProjectFoundationSection.REPOSITORY,
})

PROJECT_FOUNDATION_REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Project foundation",
    *(
        f"### {title}"
        for section, title in PROJECT_FOUNDATION_SECTIONS
        if section in PROJECT_FOUNDATION_CORE_SECTIONS
    ),
    "## Session Context — task-specific child",
)

_PATTERNS: dict[ProjectFoundationSection, re.Pattern[str]] = {
    ProjectFoundationSection.IDENTITY: re.compile(
        r"\b(?:project identity|product identity|project purpose|"
        r"product purpose|mission|target users?|customers?|audience|"
        r"problem (?:it|the (?:project|product)) solves?|"
        r"who (?:the )?(?:project|product) serves|why\s+it\s+exists)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.WORKFLOWS: re.compile(
        r"\b(?:workflow|user flow|journey|expected behaviou?r|use case|"
        r"happy path|interaction|end[- ]to[- ]end flow)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.ARCHITECTURE: re.compile(
        r"\b(?:architecture|component|boundary|data flow|storage|database|"
        r"\bapi\b|endpoint|integration|authentication|authorization|"
        r"service|pipeline)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.DOMAIN: re.compile(
        r"\b(?:domain model|entity|entities|terminology|relationship|"
        r"aggregate|value object|schema term)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.REPOSITORY: re.compile(
        r"\b(?:repository|repo map|director(?:y|ies)|module|entry point|"
        r"package|responsibilit(?:y|ies)|source tree)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.STACK: re.compile(
        r"\b(?:technology|tech stack|framework|runtime|deployment|"
        r"infrastructure|dependency|language|container|cloud|hosting)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.CONVENTIONS: re.compile(
        r"\b(?:convention|coding pattern|testing strategy|error handling|"
        r"naming|style guide|schema convention)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.COMMANDS: re.compile(
        r"\b(?:canonical command|setup command|development command|"
        r"build command|test command|lint command|migration command|"
        r"deploy command|run with|use `?(?:pytest|npm|pnpm|yarn|make|"
        r"docker|uv|ruff|alembic))\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.CAPABILITIES: re.compile(
        r"\b(?:capabilit(?:y|ies)|supports?|unsupported|non-capabilit|"
        r"does not support|deliberately does not)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.CONSTRAINTS: re.compile(
        r"\b(?:long-term constraint|technical debt|security boundary|"
        r"persistent risk|security|debt|constraint|invariant)\b",
        re.IGNORECASE,
    ),
    ProjectFoundationSection.DIRECTION: re.compile(
        r"\b(?:product direction|roadmap|quality requirement|quality bar|"
        r"current direction|north star|current priority)\b",
        re.IGNORECASE,
    ),
}

_PATTERN_PRIORITY = (
    ProjectFoundationSection.COMMANDS,
    ProjectFoundationSection.CONVENTIONS,
    ProjectFoundationSection.WORKFLOWS,
    ProjectFoundationSection.DOMAIN,
    ProjectFoundationSection.ARCHITECTURE,
    ProjectFoundationSection.REPOSITORY,
    ProjectFoundationSection.STACK,
    ProjectFoundationSection.CAPABILITIES,
    ProjectFoundationSection.CONSTRAINTS,
    ProjectFoundationSection.DIRECTION,
    ProjectFoundationSection.IDENTITY,
)


def classify_project_foundation_section(
    *,
    kind: ProjectContextKind | str,
    title: str,
    statement: str,
) -> ProjectFoundationSection | None:
    kind_value = str(getattr(kind, "value", kind)).strip().casefold()
    if kind_value in {
        ProjectContextKind.DECISION.value,
        ProjectContextKind.INVARIANT.value,
    }:
        return ProjectFoundationSection.DECISIONS
    if kind_value in {
        ProjectContextKind.RISK.value,
        ProjectContextKind.BLOCKER.value,
    }:
        return ProjectFoundationSection.CONSTRAINTS
    text = f"{title} {statement}"
    if kind_value == ProjectContextKind.LEARNING.value:
        for section in (
            ProjectFoundationSection.CONVENTIONS,
            ProjectFoundationSection.ARCHITECTURE,
            ProjectFoundationSection.CONSTRAINTS,
            ProjectFoundationSection.REPOSITORY,
            ProjectFoundationSection.STACK,
        ):
            if _PATTERNS[section].search(text):
                return section
        if re.match(r"\s*(?:failed|known failure|failure)", title, re.IGNORECASE):
            return ProjectFoundationSection.CONSTRAINTS
        return ProjectFoundationSection.CONVENTIONS
    for section in _PATTERN_PRIORITY:
        if _PATTERNS[section].search(text):
            return section
    return None


def project_foundation_section_from_item(
    item: Any,
) -> ProjectFoundationSection | None:
    section = _field(item, "section", None)
    if section is not None:
        try:
            return (
                section
                if isinstance(section, ProjectFoundationSection)
                else ProjectFoundationSection(str(section))
            )
        except ValueError:
            return None
    return classify_project_foundation_section(
        kind=_field(item, "kind", ProjectContextKind.CONTEXT),
        title=str(_field(item, "title", "") or ""),
        statement=str(_field(item, "statement", "") or ""),
    )


def looks_like_generic_inventory(title: str, statement: str) -> bool:
    normalized_title = " ".join(title.casefold().split())
    normalized_statement = " ".join(statement.casefold().split())
    if re.match(r"^(?:area|file|folder|repository|symbol)\s*:", normalized_title):
        return True
    return bool(
        re.fullmatch(
            r"(?:contains?|includes?|lists?|has)\s+(?:files?|folders?|"
            r"modules?|symbols?|directories)(?:\s+and\s+\w+)*[.!]?",
            normalized_statement,
        )
    )


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
