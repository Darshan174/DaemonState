from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
    from yaml.constructor import ConstructorError
    from yaml.resolver import BaseResolver
    from yaml.tokens import AliasToken, AnchorToken
except ImportError:  # pragma: no cover - exercised only in minimal installations
    yaml = None
    ConstructorError = BaseResolver = None  # type: ignore[assignment,misc]
    AliasToken = AnchorToken = None  # type: ignore[assignment,misc]

from app.services.repo_indexer import IndexedFile, RepoFrame


ADAPTER_VERSION = "workspace_foundation_adapters.v4"
MAX_DOCUMENT_BYTES = 96_000
MAX_DOCUMENT_LINES = 1_200
MAX_ENGINEERING_KNOWLEDGE_FACTS = 16
MAX_GITHUB_WORKFLOW_FILES = 32
MAX_GITHUB_WORKFLOW_BYTES = 128_000
MAX_GITHUB_WORKFLOW_LINES = 2_000
MAX_REQUIRED_CHECKS = 128

_PROMPT_RISK_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "system prompt",
    "developer message",
    "reveal secrets",
    "print secrets",
    "send credentials",
    "disable safety",
)
_PRODUCT_SECTION_MARKERS = (
    "why ",
    "about",
    "overview",
    "introduction",
    "what is",
)
_AUDIENCE_SECTION_MARKERS = (
    "who it is for",
    "who is it for",
    "audience",
    "users",
)
_CONCEPT_SECTION_MARKERS = (
    "concept",
    "context type",
    "domain",
    "glossary",
    "terminology",
)
_WORKFLOW_SECTION_MARKERS = (
    "how ",
    "workflow",
    "user flow",
    "lifecycle",
)
_SYSTEM_FLOW_SECTION_MARKERS = (
    "data flow",
    "ingestion flow",
    "processing flow",
    "request flow",
    "runtime flow",
    "system flow",
    "pipeline",
)
_ENGINEERING_KNOWLEDGE_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "decision",
        re.compile(
            r"^(?:[a-z0-9][a-z0-9 -]*\s+)?"
            r"(?:decisions?|decision records?|adrs?)$",
            re.IGNORECASE,
        ),
    ),
    (
        "invariant",
        re.compile(
            r"^(?:(?:architectural|architecture|system|engineering)\s+)?"
            r"invariants?$",
            re.IGNORECASE,
        ),
    ),
    (
        "convention",
        re.compile(
            r"^(?:(?:engineering|coding|code|repository|development|testing)\s+)?"
            r"conventions?$|^(?:code\s+style|product\s+rules?|engineering\s+rules?|"
            r"repository\s+rules?)$",
            re.IGNORECASE,
        ),
    ),
    (
        "current_limitation",
        re.compile(
            r"^(?:(?:current|known|product|system|technical)\s+)?"
            r"(?:limits?|limitations?|non[- ]goals?)$",
            re.IGNORECASE,
        ),
    ),
    (
        "known_failure",
        re.compile(
            r"^(?:known\s+)?(?:failures?|failure modes?|issues?|pitfalls?)$",
            re.IGNORECASE,
        ),
    ),
    (
        "lesson",
        re.compile(
            r"^(?:(?:engineering|architecture|implementation)\s+)?"
            r"lessons?(?:\s+learned)?$",
            re.IGNORECASE,
        ),
    ),
)
_FEATURE_HEADERS = frozenset(
    {
        "capability",
        "feature",
        "flow",
        "use case",
        "workflow",
    }
)
_CONCEPT_HEADERS = frozenset(
    {
        "concept",
        "context",
        "entity",
        "term",
    }
)
_DEFINITION_HEADERS = frozenset(
    {
        "definition",
        "description",
        "meaning",
        "purpose",
        "what belongs in it",
        "what it does",
        "what it helps you do",
    }
)


@dataclass(frozen=True)
class SourceLocation:
    path: str
    sha256: str | None
    heading: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    rule_id: str = "markdown_structure.v1"


@dataclass(frozen=True)
class DocumentedConcept:
    term: str
    definition: str
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedWorkflowStep:
    description: str
    position: int
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedStatement:
    text: str
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedFlow:
    name: str
    summary: str
    steps: tuple[DocumentedWorkflowStep, ...]
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedEngineeringKnowledge:
    kind: str
    title: str
    statement: str
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedCapability:
    name: str
    summary: str
    steps: tuple[DocumentedWorkflowStep, ...]
    source: SourceLocation


@dataclass(frozen=True)
class DocumentedProject:
    name: str | None
    summary: str | None
    audiences: tuple[DocumentedStatement, ...]
    boundaries: tuple[DocumentedStatement, ...]
    concepts: tuple[DocumentedConcept, ...]
    capabilities: tuple[DocumentedCapability, ...]
    system_flows: tuple[DocumentedFlow, ...]
    engineering_knowledge: tuple[DocumentedEngineeringKnowledge, ...]
    source: SourceLocation | None
    truncated: bool = False


@dataclass(frozen=True)
class ArchitectureObservation:
    path: str
    role: str
    summary: str
    source: SourceLocation


@dataclass(frozen=True)
class StackObservation:
    name: str
    category: str
    declaration: str
    source: SourceLocation


@dataclass(frozen=True)
class DeclaredCommand:
    command: str
    purpose: str
    category: str
    source: SourceLocation
    declaration_kind: str
    working_directory: str = "."
    required: bool = False


@dataclass(frozen=True)
class DeclaredVerificationPolicy:
    """Fail-closed adapter result for one repository required-check policy."""

    source: str
    discovery_complete: bool
    required_commands: tuple[DeclaredCommand, ...]
    sources: tuple[SourceLocation, ...]
    incomplete_reasons: tuple[str, ...]


if yaml is not None:

    class _UniqueKeySafeLoader(yaml.SafeLoader):
        pass

    def _construct_unique_yaml_mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _UniqueKeySafeLoader.add_constructor(
        BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_yaml_mapping,
    )
else:  # pragma: no cover - guarded before use
    _UniqueKeySafeLoader = None


@dataclass(frozen=True)
class _MarkdownSection:
    heading: str
    level: int
    start_line: int
    end_line: int
    lines: tuple[tuple[int, str], ...]


def collect_documented_project(
    frame: RepoFrame,
    inventory: dict[str, Any],
) -> DocumentedProject:
    """Read one bounded root README and return located repository statements.

    Documentation remains a separately labelled assertion lane. This adapter
    does not promote a README sentence to a code or runtime observation.
    """

    readme_inventory = inventory.get("readme") or {}
    readme_path = str(readme_inventory.get("path") or "").strip()
    if not readme_path or not frame.repo_path:
        # Inventory-only metadata has no hash-bound source location. Preserve a
        # bounded identity hint, but do not turn source-less audience strings
        # into documentation statements (or expose raw strings where callers
        # require ``DocumentedStatement`` records).
        return DocumentedProject(
            name=_text(readme_inventory.get("title"), 160) or None,
            summary=_safe_text(readme_inventory.get("summary"), 520) or None,
            audiences=(),
            boundaries=(),
            concepts=(),
            capabilities=(),
            system_flows=(),
            engineering_knowledge=(),
            source=None,
        )
    indexed = next(
        (item for item in frame.indexed_files if item.path == readme_path),
        None,
    )
    if indexed is None or not indexed.sha256:
        return DocumentedProject(
            name=_text(readme_inventory.get("title"), 160) or None,
            summary=None,
            audiences=(),
            boundaries=(),
            concepts=(),
            capabilities=(),
            system_flows=(),
            engineering_knowledge=(),
            source=None,
        )
    try:
        root = Path(frame.repo_path).resolve(strict=True)
        candidate = (root / readme_path).resolve(strict=True)
        candidate.relative_to(root)
        raw = candidate.read_bytes()
    except (OSError, ValueError):
        raw = b""
    current_sha256 = hashlib.sha256(raw).hexdigest() if raw else None
    if current_sha256 != indexed.sha256:
        # The compiler is bound to the indexed snapshot.  Never parse newer
        # bytes while attaching the older scan digest.
        return DocumentedProject(
            name=_text(readme_inventory.get("title"), 160) or None,
            summary=None,
            audiences=(),
            boundaries=(),
            concepts=(),
            capabilities=(),
            system_flows=(),
            engineering_knowledge=(),
            source=None,
        )
    truncated = len(raw) > MAX_DOCUMENT_BYTES
    text = raw[:MAX_DOCUMENT_BYTES].decode("utf-8", errors="replace")
    lines = text.splitlines()[:MAX_DOCUMENT_LINES]
    sections = _markdown_sections(lines)
    document_source = SourceLocation(
        path=readme_path,
        sha256=current_sha256,
        heading=None,
        start_line=1 if lines else None,
        end_line=len(lines) if lines else None,
    )

    product_section = next(
        (
            section
            for section in sections
            if any(marker in section.heading.casefold() for marker in _PRODUCT_SECTION_MARKERS)
        ),
        None,
    )
    source = (
        SourceLocation(
            path=readme_path,
            sha256=current_sha256,
            heading=product_section.heading,
            start_line=product_section.start_line,
            end_line=product_section.end_line,
        )
        if product_section is not None
        else document_source
    )
    summary = _section_summary(product_section, limit=520)
    if not summary:
        summary = _safe_text(readme_inventory.get("summary"), 520)

    audiences = _audiences(sections, readme_path, current_sha256)
    if not audiences:
        audiences = tuple(
            DocumentedStatement(
                text=value,
                source=SourceLocation(
                    path=readme_path,
                    sha256=current_sha256,
                    start_line=1 if lines else None,
                    end_line=len(lines) if lines else None,
                    rule_id="readme_inventory_fallback.v1",
                ),
            )
            for raw_audience in readme_inventory.get("audiences") or []
            if (value := _safe_text(raw_audience, 120))
        )[:4]

    boundaries = _documented_boundaries(
        lines,
        sections,
        readme_path,
        current_sha256,
    )
    concepts = _documented_concepts(sections, readme_path, source.sha256)
    capabilities = _documented_capabilities(
        sections,
        readme_path,
        source.sha256,
    )
    if not capabilities:
        capabilities = tuple(
            DocumentedCapability(
                name=name,
                summary=summary_text,
                steps=(),
                source=document_source,
            )
            for raw_capability in (readme_inventory.get("capabilities") or [])[:8]
            if (name := _safe_text(raw_capability.get("name"), 80))
            and (
                summary_text := _safe_text(
                    raw_capability.get("summary"),
                    260,
                )
            )
        )
    system_flows = _collect_documented_system_flows(
        frame,
        root=root,
        readme_path=readme_path,
        readme_lines=lines,
        readme_sections=sections,
        readme_sha256=current_sha256,
    )
    engineering_knowledge = _collect_repository_engineering_knowledge(
        frame,
        root=root,
        readme_path=readme_path,
        readme_lines=lines,
        readme_sections=sections,
        readme_sha256=current_sha256,
    )

    return DocumentedProject(
        name=_text(readme_inventory.get("title"), 160) or None,
        summary=summary or None,
        audiences=audiences,
        boundaries=boundaries,
        concepts=concepts,
        capabilities=capabilities,
        system_flows=system_flows,
        engineering_knowledge=engineering_knowledge,
        source=source,
        truncated=truncated or len(text.splitlines()) > MAX_DOCUMENT_LINES,
    )


def collect_architecture_observations(
    frame: RepoFrame,
) -> tuple[ArchitectureObservation, ...]:
    """Describe concrete repository surfaces without inventing data flow."""

    grouped: dict[tuple[str, str], list[IndexedFile]] = {}
    for item in frame.indexed_files:
        path = item.path.replace("\\", "/").strip("/")
        if not path:
            continue
        role, prefix = _repository_role(path, item)
        if role is None or prefix is None:
            continue
        grouped.setdefault((role, prefix), []).append(item)

    role_order = (
        "interface",
        "api",
        "implementation",
        "data",
        "verification",
        "operations",
        "documentation",
    )
    candidates: dict[str, list[ArchitectureObservation]] = {}
    for (role, prefix), items in sorted(
        grouped.items(),
        key=lambda value: (
            role_order.index(value[0][0]) if value[0][0] in role_order else 99,
            value[0][1].casefold(),
        ),
    ):
        if _architecture_noise_path(prefix):
            continue
        representative = sorted(
            items,
            key=lambda item: (
                item.is_test,
                not bool(item.route_hints or item.route_owners),
                not bool(item.symbols[1:]),
                len(Path(item.path).parts),
                item.path.casefold(),
            ),
        )[0]
        candidates.setdefault(role, []).append(
            ArchitectureObservation(
                path=prefix,
                role=role,
                summary=_role_summary(role),
                source=SourceLocation(
                    path=representative.path,
                    sha256=representative.sha256,
                    rule_id="repository_role.v1",
                ),
            )
        )
    # Select one component from every observed role before appending the
    # remaining candidates. A global path sort otherwise lets a large frontend
    # crowd out the service, data, verification, and operations lanes. The
    # compiler owns the explicit artifact bound so it can report omissions.
    observations: list[ArchitectureObservation] = []
    for role in role_order:
        candidates[role] = sorted(
            candidates.get(role, []),
            key=lambda item: _architecture_candidate_priority(role, item.path),
        )
        if candidates.get(role):
            observations.append(candidates[role].pop(0))
    for role in ("interface", "implementation", "api", *role_order[3:]):
        while candidates.get(role):
            observations.append(candidates[role].pop(0))
    return tuple(observations)


def collect_stack_observations(
    frame: RepoFrame,
    inventory: dict[str, Any],
) -> tuple[StackObservation, ...]:
    observations: list[StackObservation] = []
    for manifest in inventory.get("manifest_signals") or []:
        path = str(manifest.get("path") or "").strip()
        if not path:
            continue
        source = SourceLocation(
            path=path,
            sha256=str(manifest.get("sha256") or "") or None,
            rule_id="manifest_declaration.v1",
        )
        role = _safe_text(manifest.get("role") or manifest.get("type"), 120)
        if role:
            observations.append(
                StackObservation(
                    name=Path(path).name,
                    category="manifest",
                    declaration=role,
                    source=source,
                )
            )
        for dependency in manifest.get("dependencies") or []:
            name = _dependency_name(str(dependency))
            if not name:
                continue
            observations.append(
                StackObservation(
                    name=name,
                    category="dependency",
                    declaration=_safe_text(dependency, 160),
                    source=source,
                )
            )
            if len(observations) >= 16:
                break
        if len(observations) >= 16:
            break
    return tuple(observations[:16])


def collect_declared_commands(
    frame: RepoFrame,
    inventory: dict[str, Any],
) -> tuple[DeclaredCommand, ...]:
    """Return repository-declared commands; none are represented as passing."""

    commands: list[DeclaredCommand] = []
    indexed = {item.path: item for item in frame.indexed_files}
    script_purposes = {
        "doctor.sh": ("Check local prerequisites", "diagnostic"),
        "setup.sh": ("Set up the local workspace", "setup"),
        "bootstrap.sh": ("Bootstrap local dependencies", "setup"),
        "start.sh": ("Start the application", "run"),
        "dev.sh": ("Start the development runtime", "run"),
        "self-host.sh": ("Start the self-hosted runtime", "run"),
        "smoke.sh": ("Run the repository smoke check", "test"),
        "self-host-smoke.sh": ("Run the self-hosting smoke check", "test"),
    }
    for path in inventory.get("workflow_paths") or []:
        normalized = str(path).replace("\\", "/").strip("/")
        name = Path(normalized).name.casefold()
        purpose, category = script_purposes.get(
            name,
            (f"Run {Path(normalized).stem.replace('-', ' ')}", "other"),
        )
        commands.append(
            DeclaredCommand(
                command=f"bash {normalized}",
                purpose=purpose,
                category=category,
                source=SourceLocation(
                    path=normalized,
                    sha256=getattr(indexed.get(normalized), "sha256", None),
                    rule_id="executable_script.v1",
                ),
                declaration_kind="repository_script",
            )
        )

    priority = {
        "test": 0,
        "check": 1,
        "lint": 2,
        "typecheck": 3,
        "build": 4,
        "dev": 5,
        "start": 6,
        "preview": 7,
        "deploy": 8,
    }
    for path, raw_manifest in sorted(frame.package_manifests.items()):
        # ``scripts`` means different things across ecosystems.  Only npm's
        # package.json contract can be rendered as ``npm run <name>``.  A
        # Python ``project.scripts`` entry, for example, declares a console
        # entry point rather than a repository workflow command.
        if Path(path).name.casefold() != "package.json":
            continue
        scripts = raw_manifest.get("scripts")
        if not isinstance(scripts, dict):
            continue
        directory = str(Path(path).parent).replace("\\", "/")
        for name in sorted(
            (str(value) for value in scripts),
            key=lambda value: (priority.get(value.casefold(), 30), value.casefold()),
        ):
            if len(commands) >= 10:
                break
            command = (
                f"npm run {name}"
                if directory in {"", "."}
                else f"npm --prefix {directory} run {name}"
            )
            commands.append(
                DeclaredCommand(
                    command=command,
                    purpose=_script_purpose(name),
                    category=_script_category(name),
                    source=SourceLocation(
                        path=path,
                        sha256=getattr(indexed.get(path), "sha256", None),
                        rule_id="package_script.v1",
                    ),
                    declaration_kind="manifest_script",
                )
            )

    if len(commands) < 10 and _declares_pytest(frame):
        pyproject_path = next(
            (
                path
                for path in sorted(frame.package_manifests)
                if Path(path).name.casefold() == "pyproject.toml"
            ),
            None,
        )
        if pyproject_path:
            commands.append(
                DeclaredCommand(
                    command="pytest",
                    purpose="Run the Python test suite",
                    category="test",
                    source=SourceLocation(
                        path=pyproject_path,
                        sha256=getattr(indexed.get(pyproject_path), "sha256", None),
                        rule_id="pyproject_test_declaration.v1",
                    ),
                    declaration_kind="manifest_tool",
                )
            )

    deduped: list[DeclaredCommand] = []
    seen: set[tuple[str, str]] = set()
    for command in commands:
        key = (command.command, command.working_directory)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return tuple(deduped[:10])


def collect_required_check_policy(frame: RepoFrame) -> DeclaredVerificationPolicy:
    """Read unconditional GitHub Actions checks from the exact indexed snapshot.

    This adapter discovers command identities only. It never executes a command
    and never derives repository health. If any workflow cannot be read and
    interpreted completely, discovery remains incomplete while checks proved
    by other exact, supported workflow sources remain available.
    """

    source_kind = "github_actions"
    if not frame.repo_path:
        return _incomplete_verification_policy(
            source_kind,
            ("repository_path_unavailable",),
        )
    try:
        root = Path(frame.repo_path).resolve(strict=True)
    except OSError:
        return _incomplete_verification_policy(
            source_kind,
            ("repository_path_unavailable",),
        )

    indexed = {item.path: item for item in frame.indexed_files}
    indexed_workflows = {path for path in indexed if _is_github_workflow_path(path)}
    workflow_directory = root / ".github" / "workflows"
    if not workflow_directory.exists():
        if indexed_workflows:
            return _incomplete_verification_policy(
                source_kind,
                tuple(
                    f"workflow_snapshot_mismatch:{path}" for path in sorted(indexed_workflows)[:32]
                ),
            )
        return DeclaredVerificationPolicy(
            source=source_kind,
            discovery_complete=True,
            required_commands=(),
            sources=(),
            incomplete_reasons=(),
        )
    if not workflow_directory.is_dir() or workflow_directory.is_symlink():
        return _incomplete_verification_policy(
            source_kind,
            ("workflow_directory_unsupported",),
        )

    try:
        candidates = sorted(
            item
            for item in workflow_directory.iterdir()
            if item.is_file() and item.suffix.casefold() in {".yml", ".yaml"}
        )
    except OSError:
        return _incomplete_verification_policy(
            source_kind,
            ("workflow_directory_unreadable",),
        )
    if len(candidates) > MAX_GITHUB_WORKFLOW_FILES:
        return _incomplete_verification_policy(
            source_kind,
            ("workflow_file_limit_exceeded",),
        )

    actual_paths: set[str] = set()
    sources: list[SourceLocation] = []
    required_commands: list[DeclaredCommand] = []
    reasons: list[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            if candidate.is_symlink():
                raise ValueError
            path = resolved.relative_to(root).as_posix()
        except (OSError, ValueError):
            reasons.append(f"workflow_path_unsupported:{candidate.name}")
            continue
        actual_paths.add(path)
        indexed_file = indexed.get(path)
        if indexed_file is None or not indexed_file.sha256:
            reasons.append(f"workflow_not_indexed:{path}")
            continue
        try:
            raw = resolved.read_bytes()
        except OSError:
            reasons.append(f"workflow_unreadable:{path}")
            continue
        if len(raw) > MAX_GITHUB_WORKFLOW_BYTES or raw.count(b"\n") + 1 > MAX_GITHUB_WORKFLOW_LINES:
            reasons.append(f"workflow_truncated:{path}")
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest != indexed_file.sha256 or len(raw) != indexed_file.size:
            reasons.append(f"workflow_snapshot_mismatch:{path}")
            continue
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            reasons.append(f"workflow_encoding_unsupported:{path}")
            continue
        source = SourceLocation(
            path=path,
            sha256=digest,
            start_line=1 if text else None,
            end_line=len(text.splitlines()) if text else None,
            rule_id="github_actions_required_checks.v1",
        )
        sources.append(source)
        commands, workflow_reasons = _required_commands_from_workflow(
            text,
            source=source,
        )
        required_commands.extend(commands)
        reasons.extend(f"{reason}:{path}" for reason in workflow_reasons)

    missing_from_worktree = sorted(indexed_workflows - actual_paths)
    reasons.extend(f"workflow_snapshot_mismatch:{path}" for path in missing_from_worktree)
    deduped: list[DeclaredCommand] = []
    seen: set[tuple[str, str]] = set()
    for command in required_commands:
        key = (command.command, command.working_directory)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    if reasons:
        return _incomplete_verification_policy(
            source_kind,
            tuple(dict.fromkeys(reasons))[:32],
            sources=tuple(sources),
            required_commands=tuple(deduped[:MAX_REQUIRED_CHECKS]),
        )
    if len(deduped) > MAX_REQUIRED_CHECKS:
        return _incomplete_verification_policy(
            source_kind,
            ("required_check_limit_exceeded",),
            sources=tuple(sources),
            required_commands=tuple(deduped[:MAX_REQUIRED_CHECKS]),
        )
    return DeclaredVerificationPolicy(
        source=source_kind,
        discovery_complete=True,
        required_commands=tuple(deduped),
        sources=tuple(sources),
        incomplete_reasons=(),
    )


def _incomplete_verification_policy(
    source: str,
    reasons: tuple[str, ...],
    *,
    sources: tuple[SourceLocation, ...] = (),
    required_commands: tuple[DeclaredCommand, ...] = (),
) -> DeclaredVerificationPolicy:
    return DeclaredVerificationPolicy(
        source=source,
        discovery_complete=False,
        required_commands=required_commands,
        sources=sources,
        incomplete_reasons=reasons or ("required_check_discovery_incomplete",),
    )


def _is_github_workflow_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(".github/workflows/") and Path(normalized).suffix.casefold() in {
        ".yml",
        ".yaml",
    }


def _required_commands_from_workflow(
    text: str,
    *,
    source: SourceLocation,
) -> tuple[tuple[DeclaredCommand, ...], tuple[str, ...]]:
    if yaml is None:
        return (), ("yaml_parser_unavailable",)
    try:
        tokens = tuple(yaml.scan(text, Loader=yaml.SafeLoader))
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in tokens):
            return (), ("yaml_alias_or_anchor_unsupported",)
        parsed = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError:
        return (), ("yaml_parse_unsupported",)
    if not isinstance(parsed, dict):
        return (), ("workflow_root_unsupported",)
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return (), ("workflow_jobs_unsupported",)

    workflow_cwd, reason = _workflow_default_directory(parsed.get("defaults"), ".")
    if reason:
        return (), (reason,)
    commands: list[DeclaredCommand] = []
    reasons: list[str] = []
    for raw_job_id, raw_job in jobs.items():
        job_id = str(raw_job_id).strip()
        if not job_id or not isinstance(raw_job, dict):
            reasons.append("workflow_job_unsupported")
            continue
        job_name = str(raw_job.get("name") or job_id).strip()
        job_text = f"{job_name} {raw_job.get('uses') or ''}"
        if _is_install_or_deploy_step(job_text):
            continue
        if "uses" in raw_job:
            reasons.append(f"reusable_workflow_job_unsupported:{job_id}")
            continue
        if _is_non_required(raw_job.get("continue-on-error")):
            continue
        if _invalid_continue_on_error(raw_job.get("continue-on-error")):
            reasons.append(f"continue_on_error_unsupported:{job_id}")
            continue
        if raw_job.get("if") is not None:
            # Conditional jobs are not unconditional required commands.
            continue
        job_cwd, reason = _workflow_default_directory(
            raw_job.get("defaults"),
            workflow_cwd,
        )
        if reason:
            reasons.append(f"{reason}:{job_id}")
            continue
        steps = raw_job.get("steps")
        if not isinstance(steps, list):
            reasons.append(f"workflow_steps_unsupported:{job_id}")
            continue
        for step_index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                reasons.append(f"workflow_step_unsupported:{job_id}:{step_index}")
                continue
            step_name = str(raw_step.get("name") or f"Step {step_index}").strip()
            run = raw_step.get("run")
            uses = raw_step.get("uses")
            classification_text = f"{step_name}\n{run or uses or ''}"
            verification_like = _is_verification_step(classification_text)
            excluded = _is_install_or_deploy_step(classification_text)
            if verification_like and excluded:
                reasons.append(f"mixed_setup_or_deploy_check:{job_id}:{step_index}")
                continue
            if excluded:
                continue
            if run is None:
                if uses is not None and verification_like:
                    reasons.append(f"action_check_unsupported:{job_id}:{step_index}")
                continue
            if not isinstance(run, str):
                reasons.append(f"workflow_run_unsupported:{job_id}:{step_index}")
                continue
            if not verification_like:
                continue
            if raw_step.get("if") is not None or _is_non_required(
                raw_step.get("continue-on-error")
            ):
                continue
            if _invalid_continue_on_error(raw_step.get("continue-on-error")):
                reasons.append(f"continue_on_error_unsupported:{job_id}:{step_index}")
                continue
            command = _normalized_workflow_command(run)
            if not command or len(command) > 4_000:
                reasons.append(f"workflow_command_unsupported:{job_id}:{step_index}")
                continue
            if "${{" in command:
                reasons.append(f"dynamic_check_command_unsupported:{job_id}:{step_index}")
                continue
            working_directory, reason = _step_working_directory(
                raw_step.get("working-directory"),
                job_cwd,
            )
            if reason:
                reasons.append(f"{reason}:{job_id}:{step_index}")
                continue
            category = _verification_step_category(classification_text)
            commands.append(
                DeclaredCommand(
                    command=command,
                    purpose=f"Run required GitHub Actions step: {step_name}",
                    category=category,
                    source=source,
                    declaration_kind="github_actions_required_step",
                    working_directory=working_directory,
                    required=True,
                )
            )
    return tuple(commands), tuple(reasons)


def _workflow_default_directory(
    raw_defaults: object,
    inherited: str,
) -> tuple[str, str | None]:
    if raw_defaults is None:
        return inherited, None
    if not isinstance(raw_defaults, dict):
        return inherited, "workflow_defaults_unsupported"
    raw_run = raw_defaults.get("run")
    if raw_run is None:
        return inherited, None
    if not isinstance(raw_run, dict):
        return inherited, "workflow_run_defaults_unsupported"
    return _step_working_directory(raw_run.get("working-directory"), inherited)


def _step_working_directory(
    raw_value: object,
    inherited: str,
) -> tuple[str, str | None]:
    if raw_value is None:
        return inherited, None
    if not isinstance(raw_value, str):
        return inherited, "working_directory_unsupported"
    stripped = raw_value.strip()
    if not stripped or stripped.startswith("/") or "\\" in stripped or "${{" in stripped:
        return inherited, "working_directory_unsupported"
    parts = stripped.rstrip("/").split("/")
    if any(part in {"", ".."} for part in parts):
        return inherited, "working_directory_unsupported"
    normalized_parts = [part for part in parts if part != "."]
    return "/".join(normalized_parts) or ".", None


def _normalized_workflow_command(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_non_required(value: object) -> bool:
    return value is True


def _invalid_continue_on_error(value: object) -> bool:
    return value is not None and not isinstance(value, bool)


_VERIFICATION_STEP_RE = re.compile(
    r"(?:^|[^a-z0-9_])(?:tests?|testing|pytest|lint|ruff|eslint|typecheck|type[- ]check|"
    r"mypy|pyright|build|smoke|checks?|verify|verification|validate|validation|audit|"
    r"docker\s+compose\b[^\n]*\bconfig|cmp|analy[sz]e|scan)(?:[^a-z0-9_]|$)",
    re.IGNORECASE,
)
_INSTALL_OR_DEPLOY_STEP_RE = re.compile(
    r"(?:^|[^a-z0-9_])(?:install(?:ing|ation)?|dependencies|dependency|bootstrap|setup|"
    r"checkout|deploy(?:ment|ing)?|publish(?:ing)?|release|upload|npm\s+ci|pip\s+install|"
    r"apt(?:-get)?\s+install)(?:[^a-z0-9_]|$)",
    re.IGNORECASE,
)


def _is_verification_step(value: str) -> bool:
    return bool(_VERIFICATION_STEP_RE.search(value))


def _is_install_or_deploy_step(value: str) -> bool:
    return bool(_INSTALL_OR_DEPLOY_STEP_RE.search(value))


def _verification_step_category(value: str) -> str:
    lowered = value.casefold()
    if (
        "typecheck" in lowered
        or "type-check" in lowered
        or "mypy" in lowered
        or "pyright" in lowered
    ):
        return "check"
    if "lint" in lowered or "ruff" in lowered or "eslint" in lowered or "check" in lowered:
        return "check"
    if "smoke" in lowered or "test" in lowered or "pytest" in lowered:
        return "test"
    if "build" in lowered:
        return "build"
    return "test"


def _markdown_sections(lines: list[str]) -> tuple[_MarkdownSection, ...]:
    headings: list[tuple[int, int, str]] = []
    for index, raw_line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", raw_line.strip())
        if not match:
            continue
        heading = _safe_text(match.group(2), 160)
        if heading:
            headings.append((index, len(match.group(1)), heading))
    sections: list[_MarkdownSection] = []
    for offset, (start, level, heading) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_heading in headings[offset + 1 :]:
            if next_level <= level:
                end = next_start - 1
                break
        content = tuple(
            (line_number, lines[line_number - 1]) for line_number in range(start + 1, end + 1)
        )
        sections.append(
            _MarkdownSection(
                heading=heading,
                level=level,
                start_line=start,
                end_line=end,
                lines=content,
            )
        )
    return tuple(sections)


def _section_summary(
    section: _MarkdownSection | None,
    *,
    limit: int,
) -> str:
    if section is None:
        return ""
    paragraphs = _paragraphs(section.lines)
    return _safe_text(" ".join(paragraphs[:2]), limit)


def _paragraphs(lines: Iterable[tuple[int, str]]) -> tuple[str, ...]:
    result: list[str] = []
    current: list[str] = []
    in_code = False
    for _line_number, raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            if current:
                value = _safe_text(" ".join(current), 800)
                if value:
                    result.append(value)
                current = []
            continue
        if (
            stripped.startswith(("#", "|", "![", "<"))
            or re.match(r"^[-*+]\s+", stripped)
            or re.match(r"^\d+[.)]\s+", stripped)
        ):
            continue
        current.append(stripped.lstrip("> "))
    if current:
        value = _safe_text(" ".join(current), 800)
        if value:
            result.append(value)
    return tuple(result)


def _audiences(
    sections: tuple[_MarkdownSection, ...],
    path: str,
    sha256: str | None,
) -> tuple[DocumentedStatement, ...]:
    section = next(
        (
            value
            for value in sections
            if any(marker in value.heading.casefold() for marker in _AUDIENCE_SECTION_MARKERS)
        ),
        None,
    )
    if section is None:
        return ()
    audiences: list[DocumentedStatement] = []
    for line_number, line in section.lines:
        match = re.match(r"^\s*[-*+]\s+(?:\*\*)?([^:*]+)", line)
        if not match:
            continue
        audience = _safe_text(match.group(1).strip("* "), 120)
        if audience:
            audiences.append(
                DocumentedStatement(
                    text=audience,
                    source=SourceLocation(
                        path=path,
                        sha256=sha256,
                        heading=section.heading,
                        start_line=line_number,
                        end_line=line_number,
                    ),
                )
            )
        if len(audiences) >= 4:
            break
    return tuple(audiences)


def _documented_boundaries(
    lines: list[str],
    sections: tuple[_MarkdownSection, ...],
    path: str,
    sha256: str | None,
) -> tuple[DocumentedStatement, ...]:
    candidate_lines = list(enumerate(lines[:80], start=1))
    for section in sections:
        if any(
            marker in section.heading.casefold()
            for marker in ("limitation", "non-goal", "status", "scope")
        ):
            candidate_lines.extend(section.lines)
    boundaries: list[DocumentedStatement] = []
    seen: set[str] = set()
    for paragraph, start_line, end_line in _located_paragraphs(candidate_lines):
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            normalized = _safe_text(sentence.strip("* "), 240)
            lowered = normalized.casefold()
            if not normalized or not re.search(
                r"\b(?:active alpha|self-hosted|runs? locally|containerized|docker|"
                r"does not|do not|is not|isn't|not a|currently requires|"
                r"only supports|unsupported)\b",
                lowered,
            ):
                continue
            identity = normalized.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            boundaries.append(
                DocumentedStatement(
                    text=normalized,
                    source=SourceLocation(
                        path=path,
                        sha256=sha256,
                        start_line=start_line,
                        end_line=end_line,
                        rule_id="markdown_boundary_statement.v2",
                    ),
                )
            )
            if len(boundaries) >= 8:
                return tuple(boundaries)
    return tuple(boundaries)


def _located_paragraphs(
    numbered_lines: Iterable[tuple[int, str]],
) -> tuple[tuple[str, int, int], ...]:
    unique_lines = sorted(dict(numbered_lines).items())
    result: list[tuple[str, int, int]] = []
    current: list[str] = []
    start_line: int | None = None
    end_line: int | None = None

    def flush() -> None:
        nonlocal current, start_line, end_line
        if current and start_line is not None and end_line is not None:
            value = _safe_text(" ".join(current), 1_200)
            if value:
                result.append((value, start_line, end_line))
        current = []
        start_line = None
        end_line = None

    for line_number, raw_line in unique_lines:
        stripped = raw_line.strip()
        is_boundary = not stripped or stripped.startswith(("#", "|", "![", "<", "```"))
        new_list_item = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", stripped))
        if is_boundary or (end_line is not None and line_number != end_line + 1):
            flush()
        if is_boundary:
            continue
        if new_list_item and current:
            flush()
        cleaned = re.sub(r"^(?:>\s*)+", "", stripped)
        cleaned = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", cleaned)
        if start_line is None:
            start_line = line_number
        end_line = line_number
        current.append(cleaned)
    flush()
    return tuple(result)


def _documented_concepts(
    sections: tuple[_MarkdownSection, ...],
    path: str,
    sha256: str | None,
) -> tuple[DocumentedConcept, ...]:
    result: list[DocumentedConcept] = []
    seen: set[str] = set()
    for section in sections:
        if not any(marker in section.heading.casefold() for marker in _CONCEPT_SECTION_MARKERS):
            continue
        for headers, cells, line_number in _tables(section):
            if len(headers) < 2 or len(cells) < 2:
                continue
            if headers[0] not in _CONCEPT_HEADERS:
                continue
            if headers[1] not in _DEFINITION_HEADERS:
                continue
            term = _safe_text(cells[0], 100)
            definition = _safe_text(cells[1], 280)
            key = term.casefold()
            if not term or not definition or key in seen:
                continue
            seen.add(key)
            result.append(
                DocumentedConcept(
                    term=term,
                    definition=definition,
                    source=SourceLocation(
                        path=path,
                        sha256=sha256,
                        heading=section.heading,
                        start_line=line_number,
                        end_line=line_number,
                    ),
                )
            )
            if len(result) >= 8:
                return tuple(result)
    return tuple(result)


def _documented_capabilities(
    sections: tuple[_MarkdownSection, ...],
    path: str,
    sha256: str | None,
) -> tuple[DocumentedCapability, ...]:
    raw_capabilities: list[tuple[str, str, SourceLocation]] = []
    seen: set[str] = set()
    for section in sections:
        for headers, cells, line_number in _tables(section):
            if len(headers) < 2 or len(cells) < 2:
                continue
            if headers[0] not in _FEATURE_HEADERS:
                continue
            if headers[1] not in _DEFINITION_HEADERS:
                continue
            name = _safe_text(cells[0], 100)
            summary = _safe_text(cells[1], 280)
            key = name.casefold()
            if not name or not summary or key in seen:
                continue
            seen.add(key)
            raw_capabilities.append(
                (
                    name,
                    summary,
                    SourceLocation(
                        path=path,
                        sha256=sha256,
                        heading=section.heading,
                        start_line=line_number,
                        end_line=line_number,
                    ),
                )
            )
            if len(raw_capabilities) >= 8:
                break
        if len(raw_capabilities) >= 8:
            break

    workflow_sections = [
        section
        for section in sections
        if any(marker in section.heading.casefold() for marker in _WORKFLOW_SECTION_MARKERS)
    ]
    result: list[DocumentedCapability] = []
    for name, summary, source in raw_capabilities:
        steps: tuple[DocumentedWorkflowStep, ...] = ()
        name_roots = _word_roots(name)
        matching_section = next(
            (section for section in workflow_sections if name_roots & _word_roots(section.heading)),
            None,
        )
        if matching_section is not None:
            steps = _documented_ordered_steps(
                matching_section,
                path=path,
                sha256=sha256,
                max_steps=6,
                description_limit=500,
            )
        result.append(
            DocumentedCapability(
                name=name,
                summary=summary,
                steps=steps,
                source=source,
            )
        )
    return tuple(result)


def _collect_documented_system_flows(
    frame: RepoFrame,
    *,
    root: Path,
    readme_path: str,
    readme_lines: list[str],
    readme_sections: tuple[_MarkdownSection, ...],
    readme_sha256: str,
) -> tuple[DocumentedFlow, ...]:
    """Collect a few explicit ordered flows from hash-matched repository docs."""

    documents: list[tuple[str, str, list[str], tuple[_MarkdownSection, ...]]] = [
        (readme_path, readme_sha256, readme_lines, readme_sections)
    ]
    candidates = sorted(
        (
            item
            for item in frame.indexed_files
            if item.path != readme_path
            and item.language == "markdown"
            and item.sha256
            and _system_flow_document_priority(item.path) is not None
        ),
        key=lambda item: (
            _system_flow_document_priority(item.path),
            item.path.casefold(),
        ),
    )[:6]
    for indexed in candidates:
        try:
            candidate = (root / indexed.path).resolve(strict=True)
            candidate.relative_to(root)
            raw = candidate.read_bytes()
        except (OSError, ValueError):
            continue
        if not raw:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest != indexed.sha256:
            continue
        lines = (
            raw[:MAX_DOCUMENT_BYTES]
            .decode("utf-8", errors="replace")
            .splitlines()[:MAX_DOCUMENT_LINES]
        )
        documents.append((indexed.path, digest, lines, _markdown_sections(lines)))

    flows: list[DocumentedFlow] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for path, digest, _lines, sections in documents:
        for section in sections:
            normalized_heading = section.heading.casefold()
            if not any(marker in normalized_heading for marker in _SYSTEM_FLOW_SECTION_MARKERS):
                continue
            steps = list(
                _documented_ordered_steps(
                    section,
                    path=path,
                    sha256=digest,
                    max_steps=12,
                    description_limit=700,
                )
            )
            if len(steps) < 2:
                continue
            key = (
                normalized_heading,
                tuple(step.description.casefold() for step in steps),
            )
            if key in seen:
                continue
            seen.add(key)
            flows.append(
                DocumentedFlow(
                    name=section.heading,
                    summary=(
                        f"Repository-stated ordered {section.heading.casefold()} with "
                        f"{len(steps)} steps."
                    ),
                    steps=tuple(steps),
                    source=SourceLocation(
                        path=path,
                        sha256=digest,
                        heading=section.heading,
                        start_line=section.start_line,
                        end_line=section.end_line,
                    ),
                )
            )
            if len(flows) >= 4:
                return tuple(flows)
    return tuple(flows)


def _collect_repository_engineering_knowledge(
    frame: RepoFrame,
    *,
    root: Path,
    readme_path: str,
    readme_lines: list[str],
    readme_sections: tuple[_MarkdownSection, ...],
    readme_sha256: str,
) -> tuple[DocumentedEngineeringKnowledge, ...]:
    """Collect bounded engineering statements from exact, hash-matched headings."""

    documents: list[tuple[str, str, list[str], tuple[_MarkdownSection, ...]]] = [
        (readme_path, readme_sha256, readme_lines, readme_sections)
    ]
    candidates = sorted(
        (
            item
            for item in frame.indexed_files
            if item.path != readme_path
            and item.language == "markdown"
            and item.sha256
            and _engineering_knowledge_document_priority(item.path) is not None
        ),
        key=lambda item: (
            _engineering_knowledge_document_priority(item.path),
            item.path.casefold(),
        ),
    )[:16]
    for indexed in candidates:
        try:
            candidate = (root / indexed.path).resolve(strict=True)
            candidate.relative_to(root)
            raw = candidate.read_bytes()
        except (OSError, ValueError):
            continue
        if not raw:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest != indexed.sha256:
            continue
        lines = (
            raw[:MAX_DOCUMENT_BYTES]
            .decode("utf-8", errors="replace")
            .splitlines()[:MAX_DOCUMENT_LINES]
        )
        documents.append((indexed.path, digest, lines, _markdown_sections(lines)))

    result: list[DocumentedEngineeringKnowledge] = []
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for path, digest, _lines, sections in documents:
        for section in sections:
            kind = _engineering_knowledge_kind(section.heading)
            if kind is None or counts.get(kind, 0) >= 4:
                continue
            remaining = min(
                4 - counts.get(kind, 0),
                MAX_ENGINEERING_KNOWLEDGE_FACTS - len(result),
            )
            for statement, start_line, end_line in _engineering_knowledge_statements(
                section,
                limit=remaining,
            ):
                key = (kind, " ".join(statement.casefold().split()))
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    DocumentedEngineeringKnowledge(
                        kind=kind,
                        title=_engineering_knowledge_title(
                            statement,
                            heading=section.heading,
                        ),
                        statement=statement,
                        source=SourceLocation(
                            path=path,
                            sha256=digest,
                            heading=section.heading,
                            start_line=start_line,
                            end_line=end_line,
                            rule_id="repository_engineering_knowledge.v1",
                        ),
                    )
                )
                counts[kind] = counts.get(kind, 0) + 1
                if len(result) >= MAX_ENGINEERING_KNOWLEDGE_FACTS:
                    return tuple(result)
    return tuple(result)


def _engineering_knowledge_kind(heading: str) -> str | None:
    normalized = re.sub(
        r"^\s*\d+(?:\.\d+)*[.) -]+",
        "",
        heading.casefold(),
    )
    normalized = re.sub(r"[`*_:#]+", "", normalized)
    normalized = " ".join(normalized.split()).strip(" .:-")
    for kind, pattern in _ENGINEERING_KNOWLEDGE_HEADING_PATTERNS:
        if pattern.fullmatch(normalized):
            return kind
    return None


def _engineering_knowledge_statements(
    section: _MarkdownSection,
    *,
    limit: int,
) -> tuple[tuple[str, int, int], ...]:
    if limit <= 0:
        return ()
    listed: list[tuple[str, int, int]] = []
    parts: list[str] = []
    start_line: int | None = None
    end_line: int | None = None
    in_code = False

    def finish_list_item() -> None:
        nonlocal parts, start_line, end_line
        if start_line is not None:
            statement = _safe_text(" ".join(parts), 1_200)
            if statement:
                listed.append((statement, start_line, end_line or start_line))
        parts = []
        start_line = None
        end_line = None

    for line_number, raw_line in section.lines:
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)", raw_line)
        if match is not None:
            finish_list_item()
            value = _safe_text(match.group(1), 1_200)
            if value:
                parts = [value]
                start_line = line_number
                end_line = line_number
            if len(listed) >= limit:
                break
            continue
        if start_line is not None and raw_line[:1].isspace() and stripped:
            continuation = _safe_text(stripped, 1_200)
            if continuation:
                parts.append(continuation)
                end_line = line_number
            continue
        if start_line is not None:
            finish_list_item()
            if len(listed) >= limit:
                break
    if len(listed) < limit:
        finish_list_item()
    if listed:
        return tuple(listed[:limit])

    paragraphs: list[tuple[str, int, int]] = []
    paragraph_parts: list[str] = []
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    in_code = False

    def finish_paragraph() -> None:
        nonlocal paragraph_parts, paragraph_start, paragraph_end
        if paragraph_start is not None:
            statement = _safe_text(" ".join(paragraph_parts), 1_200)
            if statement:
                paragraphs.append(
                    (
                        statement,
                        paragraph_start,
                        paragraph_end or paragraph_start,
                    )
                )
        paragraph_parts = []
        paragraph_start = None
        paragraph_end = None

    for line_number, raw_line in section.lines:
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            finish_paragraph()
            continue
        if in_code:
            continue
        if not stripped:
            finish_paragraph()
            if len(paragraphs) >= limit:
                break
            continue
        if stripped.startswith(("#", "|", "![", "<")):
            finish_paragraph()
            continue
        value = _safe_text(stripped.lstrip("> "), 1_200)
        if not value:
            continue
        if paragraph_start is None:
            paragraph_start = line_number
        paragraph_end = line_number
        paragraph_parts.append(value)
    if len(paragraphs) < limit:
        finish_paragraph()
    return tuple(paragraphs[:limit])


def _engineering_knowledge_title(statement: str, *, heading: str) -> str:
    bold = re.match(r"^\*\*([^*]{3,120})\*\*[:. -]*(.*)$", statement)
    if bold is not None:
        return _safe_text(bold.group(1), 160)
    prefix = statement.split(":", 1)[0]
    if 3 <= len(prefix) <= 100 and len(prefix.split()) <= 12:
        return _safe_text(prefix, 160)
    sentence = re.split(r"(?<=[.!?])\s+", statement, maxsplit=1)[0]
    title = _safe_text(sentence, 120)
    if title:
        return title
    return _safe_text(heading, 120) or "Repository engineering statement"


def _documented_ordered_steps(
    section: _MarkdownSection,
    *,
    path: str,
    sha256: str | None,
    max_steps: int,
    description_limit: int,
) -> tuple[DocumentedWorkflowStep, ...]:
    """Parse ordered Markdown items including their indented continuation lines."""

    result: list[DocumentedWorkflowStep] = []
    parts: list[str] = []
    start_line: int | None = None
    end_line: int | None = None

    def finish() -> None:
        nonlocal parts, start_line, end_line
        if start_line is None:
            return
        description = _safe_text(" ".join(parts), description_limit)
        if description:
            result.append(
                DocumentedWorkflowStep(
                    description=description,
                    position=len(result) + 1,
                    source=SourceLocation(
                        path=path,
                        sha256=sha256,
                        heading=section.heading,
                        start_line=start_line,
                        end_line=end_line or start_line,
                    ),
                )
            )
        parts = []
        start_line = None
        end_line = None

    for line_number, line in section.lines:
        match = re.match(r"^\s*\d+[.)]\s+(.+)", line)
        if match is not None:
            finish()
            value = _safe_text(match.group(1), description_limit)
            if value:
                parts = [value]
                start_line = line_number
                end_line = line_number
            if len(result) >= max_steps:
                break
            continue
        if start_line is None:
            continue
        if not line.strip():
            continue
        if line[:1].isspace():
            continuation = _safe_text(line, description_limit)
            if continuation:
                parts.append(continuation)
                end_line = line_number
            continue
        finish()
        break
    if len(result) < max_steps:
        finish()
    return tuple(result[:max_steps])


def _system_flow_document_priority(path: str) -> int | None:
    normalized = path.casefold().replace("\\", "/")
    name = Path(normalized).name
    if name in {"architecture.md", "architecture.rst"}:
        return 0
    if any(marker in name for marker in ("architecture", "system-design", "data-flow")):
        return 1
    if any(marker in name for marker in ("design", "technical", "ingestion", "pipeline")):
        return 2
    return None


def _engineering_knowledge_document_priority(path: str) -> int | None:
    normalized = path.casefold().replace("\\", "/").strip("/")
    parts = set(normalized.split("/"))
    name = Path(normalized).name
    if parts & {
        ".agent-runs",
        "archive",
        "archives",
        "fixtures",
        "generated",
        "node_modules",
        "vendor",
    }:
        return None
    if name in {
        "contributing.md",
        "contributing.rst",
        "developer-guide.md",
        "development.md",
    }:
        return 1
    if any(marker in name for marker in ("architecture", "decision", "design", "adr")) or parts & {
        "adr",
        "adrs",
        "decisions",
    }:
        return 0
    if any(marker in name for marker in ("convention", "lesson", "failure", "limitation")):
        return 1
    if "contract" in name:
        return 2
    if "docs" in parts:
        return 3
    return None


def _tables(
    section: _MarkdownSection,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...], int], ...]:
    table_rows: list[tuple[int, list[str]]] = []
    result: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []
    for line_number, raw_line in section.lines:
        stripped = raw_line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows.append(
                (
                    line_number,
                    [cell.strip() for cell in stripped.strip("|").split("|")],
                )
            )
            continue
        if table_rows:
            result.extend(_table_records(table_rows))
            table_rows = []
    if table_rows:
        result.extend(_table_records(table_rows))
    return tuple(result)


def _table_records(
    rows: list[tuple[int, list[str]]],
) -> list[tuple[tuple[str, ...], tuple[str, ...], int]]:
    if len(rows) < 3:
        return []
    headers = tuple(_normalized_header(value) for value in rows[0][1])
    separator = rows[1][1]
    if not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator):
        return []
    return [
        (
            headers,
            tuple(_safe_text(cell, 500) for cell in cells),
            line_number,
        )
        for line_number, cells in rows[2:]
        if len(cells) >= len(headers) and any(cells)
    ]


def _repository_role(
    path: str,
    item: IndexedFile,
) -> tuple[str | None, str | None]:
    parts = path.casefold().split("/")
    directories = parts[:-1]
    name = parts[-1]
    path_value = "/".join(parts)
    if item.is_test or {"test", "tests", "spec", "specs"} & set(directories):
        return "verification", _matched_prefix(parts, {"test", "tests", "spec", "specs"})
    interface_markers = {"frontend", "web", "ui", "client", "desktop", "mobile"}
    if interface_markers & set(directories):
        return "interface", _matched_prefix(parts, interface_markers, depth=2)
    if "api" in directories or item.route_hints or item.route_owners:
        return "api", _matched_prefix(parts, {"api"}, depth=2) or str(Path(path).parent)
    if {"model", "models", "schema", "schemas", "db", "database", "migrations"} & set(directories):
        return "data", _matched_prefix(
            parts,
            {"model", "models", "schema", "schemas", "db", "database", "migrations"},
            depth=2,
        )
    if {"service", "services", "core", "domain", "src", "app", "lib"} & set(directories):
        return "implementation", _matched_prefix(
            parts,
            {"service", "services", "core", "domain", "src", "app", "lib"},
            depth=2,
        )
    if {"script", "scripts", "deploy", "deployment", "infra", "ops"} & set(directories) or (
        name.startswith("dockerfile") or "compose" in name
    ):
        return "operations", _matched_prefix(
            parts,
            {"script", "scripts", "deploy", "deployment", "infra", "ops"},
            depth=2,
        ) or path
    if "docs" in directories or item.language == "markdown":
        if "/" not in path_value and name.startswith("readme"):
            return "documentation", path
        return "documentation", _matched_prefix(parts, {"docs"}, depth=2) or path
    if len(parts) == 1 and name in {
        "main.py",
        "app.py",
        "server.py",
        "main.js",
        "main.ts",
        "main.go",
    }:
        return "implementation", path
    return None, None


def _architecture_noise_path(path: str) -> bool:
    parts = set(path.casefold().replace("\\", "/").split("/"))
    return bool(
        parts
        & {
            "build",
            "coverage",
            "dist",
            ".agent-runs",
            ".git",
            "evals",
            "fixture",
            "fixtures",
            "generated",
            "node_modules",
            "target",
            "vendor",
        }
    ) or any(part.startswith("dummy") for part in parts)


def _architecture_candidate_priority(role: str, path: str) -> tuple[int, int, str]:
    normalized = path.casefold().replace("\\", "/").strip("/")
    parts = set(normalized.split("/"))
    preferred = {
        "interface": ("frontend", "web", "desktop", "mobile"),
        "api": ("api",),
        "implementation": ("services", "service", "core", "domain", "src", "lib"),
        "data": ("models", "schemas", "migrations", "database", "db"),
        "verification": ("tests", "test", "specs", "spec"),
        "operations": ("scripts", "deploy", "deployment", "infra", "ops"),
        "documentation": ("docs", "readme.md"),
    }.get(role, ())
    marker_index = next(
        (index for index, marker in enumerate(preferred) if marker in parts),
        len(preferred) + 1,
    )
    return marker_index, len(normalized.split("/")), normalized


def _matched_prefix(
    parts: list[str],
    markers: set[str],
    *,
    depth: int = 1,
) -> str | None:
    for index, part in enumerate(parts[:-1]):
        if part not in markers:
            continue
        return "/".join(parts[: min(len(parts) - 1, index + depth)])
    return None


def _role_summary(role: str) -> str:
    return {
        "interface": "User-facing interface code.",
        "api": "API routes and request-facing handlers.",
        "implementation": "Core application or service implementation.",
        "data": "Persistence, schema, or migration definitions.",
        "verification": "Automated verification surfaces.",
        "operations": "Setup, runtime, or deployment automation.",
        "documentation": "Repository documentation.",
    }.get(role, "Repository implementation surface.")


def _declares_pytest(frame: RepoFrame) -> bool:
    if not frame.test_files:
        return False
    for path, manifest in frame.package_manifests.items():
        if Path(path).name.casefold() not in {"pyproject.toml", "requirements.txt"}:
            continue
        if "pytest" in str(manifest).casefold():
            return True
    return False


def _script_category(name: str) -> str:
    lowered = name.casefold()
    if "test" in lowered or "smoke" in lowered:
        return "test"
    if "lint" in lowered or "check" in lowered or "type" in lowered:
        return "check"
    if "build" in lowered:
        return "build"
    if "dev" in lowered or "start" in lowered or "preview" in lowered:
        return "run"
    if "deploy" in lowered or "publish" in lowered:
        return "deploy"
    return "other"


def _script_purpose(name: str) -> str:
    category = _script_category(name)
    return {
        "test": f"Run the {name} verification script",
        "check": f"Run the {name} static check",
        "build": f"Build with the {name} script",
        "run": f"Start the {name} runtime",
        "deploy": f"Run the {name} deployment script",
        "other": f"Run the declared {name} script",
    }[category]


def _dependency_name(value: str) -> str:
    cleaned = value.strip().strip("'\"")
    match = re.match(r"(?:[a-z]+://)?([@a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)?)", cleaned)
    return match.group(1) if match else ""


def _normalized_header(value: str) -> str:
    return " ".join(_safe_text(value, 100).casefold().split())


def _word_roots(value: str) -> set[str]:
    result: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.casefold()):
        if len(token) < 4:
            continue
        for prefix in (
            "continu",
            "execut",
            "eviden",
            "integrat",
            "librar",
            "memor",
            "sourc",
        ):
            if token.startswith(prefix):
                result.add(prefix)
                break
        else:
            result.add(token)
    return result


def _safe_text(value: Any, limit: int) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^]]*]\([^)]*\)", "", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = " ".join(text.strip(" |>*_-").split())
    if not text:
        return ""
    lowered = text.casefold()
    if any(pattern in lowered for pattern in _PROMPT_RISK_PATTERNS):
        return ""
    if len(text) <= limit:
        return text
    prefix = text[: max(1, limit - 1)].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(".,;:") + "…"


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]
