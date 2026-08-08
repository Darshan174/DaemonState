"""Pure, bounded structural-edge observations from an indexed repository frame.

This module deliberately consumes only data already present in ``RepoFrame``.
It does not inspect the filesystem, persist rows, or turn structural matches into
prose claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.repo_indexer import (
    IndexedFile,
    IndexedImport,
    IndexedSymbol,
    RepoFrame,
    _canonical_hash,
    _python_module_for_path,
    _resolve_javascript_import_path,
    _resolve_python_import_module,
    _test_reference_resolves_to_target,
    _test_target_candidates,
)


MAX_WORKSPACE_FOUNDATION_EDGES = 256
MAX_WORKSPACE_FOUNDATION_FLOW_EDGES = 128
MAX_WORKSPACE_FOUNDATION_EDGE_CANDIDATES = 1_536
MAX_WORKSPACE_FOUNDATION_FLOW_CANDIDATES = 768
MAX_EDGE_EVIDENCE_FIELDS = 16
MAX_EDGE_EVIDENCE_STRING_LENGTH = 512

_HTTP_EDGE_CANDIDATES = 256
_ROUTE_OWNER_EDGE_CANDIDATES = 256
_CALL_EDGE_CANDIDATES = 384
_IMPORT_EDGE_CANDIDATES = 384
_TEST_EDGE_CANDIDATES = 256
_FLOW_HTTP_EDGE_CANDIDATES = 128
_FLOW_ROUTE_OWNER_EDGE_CANDIDATES = 128
_FLOW_CALL_EDGE_CANDIDATES = 512

_EDGE_RULE_VERSION = "1"
_JAVASCRIPT_LANGUAGES = frozenset({
    "javascript",
    "javascript-react",
    "typescript",
    "typescript-react",
})


@dataclass(frozen=True, slots=True)
class WorkspaceEdgeObservation:
    """Bounded edge output plus explicit truncation metadata."""

    edges: tuple[dict[str, Any], ...]
    observed_count: int
    truncated: bool
    limit: int


@dataclass(frozen=True, slots=True)
class _EdgeCandidates:
    edges: tuple[dict[str, Any], ...]
    truncated: bool


def observe_workspace_edges(frame: RepoFrame) -> tuple[dict[str, Any], ...]:
    """Return exact structural edges derivable from an existing ``RepoFrame``.

    Resolution is intentionally conservative: duplicate indexed paths, ambiguous
    Python module identities, ambiguous JavaScript targets, duplicate route or
    handler symbols, and non-unique test pairings produce no edge.
    """

    return observe_workspace_edges_result(frame).edges


def observe_workspace_edges_result(
    frame: RepoFrame,
    *,
    limit: int = MAX_WORKSPACE_FOUNDATION_EDGES,
) -> WorkspaceEdgeObservation:
    """Return structural edges with a separate, deterministic truncation signal."""

    if limit < 0:
        raise ValueError("workspace edge limit must be non-negative")

    indexed_by_path = _unique_indexed_files(frame.indexed_files)
    candidate_groups = (
        _observe_http_route_edges(
            frame,
            indexed_by_path,
            limit=_HTTP_EDGE_CANDIDATES,
        ),
        _observe_route_owner_edges(
            frame,
            indexed_by_path,
            limit=_ROUTE_OWNER_EDGE_CANDIDATES,
        ),
        _observe_call_edges(
            frame,
            indexed_by_path,
            limit=_CALL_EDGE_CANDIDATES,
        ),
        _observe_import_edges(
            frame,
            indexed_by_path,
            limit=_IMPORT_EDGE_CANDIDATES,
        ),
        _observe_test_edges(
            frame,
            indexed_by_path,
            limit=_TEST_EDGE_CANDIDATES,
        ),
    )
    candidates = [
        edge
        for group in candidate_groups
        for edge in group.edges
    ]
    unique = {str(edge["edge_key"]): edge for edge in candidates}
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda edge: _semantic_edge_sort_key(edge, indexed_by_path),
        )
    )
    return WorkspaceEdgeObservation(
        edges=ordered[:limit],
        observed_count=len(ordered),
        truncated=(
            any(group.truncated for group in candidate_groups)
            or len(ordered) > limit
        ),
        limit=limit,
    )


def _semantic_edge_sort_key(
    edge: dict[str, Any],
    indexed_by_path: dict[str, IndexedFile],
) -> tuple[int, int, int, str, int, str, str]:
    """Keep useful production structure ahead of bounded scanner/test noise."""

    source_path = str(edge.get("source_path") or "")
    target_path = str(edge.get("target_path") or "")
    rule_id = str(edge.get("rule_id") or "")
    source = indexed_by_path.get(source_path)
    target = indexed_by_path.get(target_path)
    is_test_edge = (
        rule_id in {"test_path_match.v1", "test_symbol_match.v1"}
        or bool(source and source.is_test)
        or bool(target and target.is_test)
    )
    is_scanner_noise = _edge_noise_path(source_path) or _edge_noise_path(target_path)
    lane = 2 if is_test_edge else 1 if is_scanner_noise else 0
    rule_priority = {
        "static_http_route_reference.v1": 0,
        "route_handler_owner.v1": 1,
        "local_symbol_call.v1": 2,
        "local_module_import.v1": 3,
        "test_path_match.v1": 4,
        "test_symbol_match.v1": 5,
    }.get(rule_id, 6)
    cross_file_priority = 0 if source_path != target_path else 1
    line = edge.get("evidence_start_line")
    return (
        lane,
        rule_priority,
        cross_file_priority,
        source_path.casefold(),
        int(line) if isinstance(line, int) else 0,
        target_path.casefold(),
        str(edge.get("edge_key") or ""),
    )


def _edge_noise_path(path: str) -> bool:
    normalized = path.casefold().replace("\\", "/").strip("/")
    parts = set(normalized.split("/"))
    name = normalized.rsplit("/", 1)[-1]
    return bool(
        parts
        & {
            ".agent-runs",
            "build",
            "coverage",
            "dist",
            "evals",
            "fixture",
            "fixtures",
            "generated",
            "node_modules",
            "target",
            "vendor",
        }
    ) or name in {"__init__.py", "conftest.py"}


def observe_workspace_flow_edges_result(
    frame: RepoFrame,
    *,
    anchor_paths: tuple[str, ...],
    preferred_terms: frozenset[str] = frozenset(),
    limit: int = MAX_WORKSPACE_FOUNDATION_FLOW_EDGES,
    max_depth: int = 6,
) -> WorkspaceEdgeObservation:
    """Return bounded exact route-owner and local-symbol-call edges near anchors.

    This view is deliberately capability-anchored. Traversal follows exact
    qualified-symbol identities, so an unrelated call in the same module cannot
    complete a production flow.
    """

    if limit < 0:
        raise ValueError("workspace flow edge limit must be non-negative")
    if max_depth < 1:
        raise ValueError("workspace flow edge depth must be positive")

    indexed_by_path = _unique_indexed_files(frame.indexed_files)
    anchors = tuple(sorted({path for path in anchor_paths if path in indexed_by_path}))
    if not anchors:
        return WorkspaceEdgeObservation(
            edges=(),
            observed_count=0,
            truncated=False,
            limit=limit,
        )
    http_candidates = _observe_http_route_edges(
        frame,
        indexed_by_path,
        limit=_FLOW_HTTP_EDGE_CANDIDATES,
        source_paths=frozenset(anchors),
    )
    http_edges = list(http_candidates.edges)
    routed_target_paths = {str(edge["target_path"]) for edge in http_edges}
    route_source_paths = frozenset({*anchors, *routed_target_paths})
    route_candidates = _observe_route_owner_edges(
        frame,
        indexed_by_path,
        limit=_FLOW_ROUTE_OWNER_EDGE_CANDIDATES,
        source_paths=route_source_paths,
    )
    route_edges = [
        edge
        for edge in route_candidates.edges
        if not indexed_by_path[edge["source_path"]].is_test
    ]
    selected: dict[str, dict[str, Any]] = {}
    for edge in sorted(
        http_edges,
        key=lambda item: _flow_edge_sort_key(item, preferred_terms),
    ):
        selected[str(edge["edge_key"])] = edge

    routed_signatures = {
        (
            str(edge["target_path"]),
            str((edge.get("evidence") or {}).get("declared_route") or ""),
        )
        for edge in http_edges
    }
    route_handler_symbols: set[str] = set()
    for edge in sorted(
        route_edges,
        key=lambda item: _flow_edge_sort_key(item, preferred_terms),
    ):
        route_signature = (
            str(edge["source_path"]),
            str((edge.get("evidence") or {}).get("route") or ""),
        )
        if edge["source_path"] not in anchors and route_signature not in routed_signatures:
            continue
        selected[str(edge["edge_key"])] = edge
        handler = str((edge.get("evidence") or {}).get("handler_symbol") or "")
        if handler:
            route_handler_symbols.add(handler)

    # Resolve calls from exact route handlers before considering generic calls in
    # anchor modules. Previously this was one repository-wide, lexically ordered
    # scan with a fixed candidate budget. Enough unrelated files named earlier in
    # the tree could therefore erase a valid capability flow. Each query below
    # is restricted to an exact qualified caller identity (or an anchor path),
    # while the aggregate call budget remains unchanged.
    call_edges: dict[str, dict[str, Any]] = {}
    call_truncated = False
    seen_callers: set[str] = set()

    def add_call_candidates(candidates: _EdgeCandidates) -> tuple[str, ...]:
        nonlocal call_truncated
        call_truncated = call_truncated or candidates.truncated
        added_callees: list[str] = []
        for edge in candidates.edges:
            key = str(edge["edge_key"])
            if key in call_edges:
                continue
            if len(call_edges) >= _FLOW_CALL_EDGE_CANDIDATES:
                call_truncated = True
                break
            call_edges[key] = edge
            callee = str((edge.get("evidence") or {}).get("callee") or "")
            if callee:
                added_callees.append(callee)
        return tuple(added_callees)

    def traverse_exact_callers(
        initial_callers: set[str],
        *,
        starting_depth: int,
    ) -> None:
        nonlocal call_truncated
        frontier = set(initial_callers)
        for _depth in range(starting_depth, max_depth):
            callers = frozenset(sorted(frontier - seen_callers))
            if not callers:
                return
            if len(call_edges) >= _FLOW_CALL_EDGE_CANDIDATES:
                call_truncated = True
                return
            seen_callers.update(callers)
            candidates = _observe_call_edges(
                frame,
                indexed_by_path,
                limit=_FLOW_CALL_EDGE_CANDIDATES - len(call_edges),
                caller_identities=callers,
                preferred_terms=preferred_terms,
                rank_before_limit=True,
                production_only=True,
            )
            frontier = set(add_call_candidates(candidates))

    traverse_exact_callers(route_handler_symbols, starting_depth=0)

    # Keep call-only capability traces available when no route is present, and
    # retain exact calls from frontend/API anchor modules that may seed a deeper
    # chain. Ranking occurs before this cap, so path order cannot decide which
    # anchor calls survive.
    anchor_call_candidates = _observe_call_edges(
        frame,
        indexed_by_path,
        limit=_FLOW_CALL_EDGE_CANDIDATES,
        source_paths=route_source_paths,
        preferred_terms=preferred_terms,
        rank_before_limit=True,
        production_only=True,
    )
    anchor_callees = set(add_call_candidates(anchor_call_candidates))
    traverse_exact_callers(anchor_callees, starting_depth=1)

    for key, edge in call_edges.items():
        selected[key] = edge

    ordered = tuple(
        sorted(
            selected.values(),
            key=lambda item: _flow_edge_sort_key(item, preferred_terms),
        )
    )
    return WorkspaceEdgeObservation(
        edges=ordered[:limit],
        observed_count=len(ordered),
        truncated=(
            http_candidates.truncated
            or route_candidates.truncated
            or call_truncated
            or len(ordered) > limit
        ),
        limit=limit,
    )


def _flow_edge_sort_key(
    edge: dict[str, Any],
    preferred_terms: frozenset[str],
) -> tuple[int, int, str, str, str]:
    evidence = edge.get("evidence") or {}
    searchable = " ".join(
        str(value or "")
        for value in (
            edge.get("source_path"),
            edge.get("target_path"),
            evidence.get("caller"),
            evidence.get("callee"),
            evidence.get("route"),
            evidence.get("handler_symbol"),
            evidence.get("declared_route"),
        )
    )
    relevance = _flow_term_relevance(searchable, preferred_terms)
    return (
        {
            "static_http_route_reference.v1": 0,
            "route_handler_owner.v1": 1,
            "local_symbol_call.v1": 2,
        }.get(str(edge.get("rule_id") or ""), 3),
        -relevance,
        str(edge.get("source_path") or ""),
        str(edge.get("target_path") or ""),
        str(edge.get("edge_key") or ""),
    )


def _flow_term_relevance(searchable: str, preferred_terms: frozenset[str]) -> int:
    """Score capability roots against snake-, kebab-, and camel-cased evidence."""

    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", searchable)
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9]*", expanded.casefold()))
    return sum(
        any(term.startswith(preferred) or preferred.startswith(term) for term in terms)
        for preferred in preferred_terms
        if len(preferred) >= 3
    )


def _observe_http_route_edges(
    frame: RepoFrame,
    indexed_by_path: dict[str, IndexedFile],
    *,
    limit: int,
    source_paths: frozenset[str] | None = None,
) -> _EdgeCandidates:
    """Link static client method/path references to one unique route declaration."""

    route_targets: dict[tuple[str, str], list[tuple[str, IndexedSymbol]]] = {}
    for target_path in sorted(indexed_by_path):
        target_file = indexed_by_path[target_path]
        if target_file.is_test:
            continue
        for route in target_file.route_hints:
            signature = _http_route_signature(route)
            if signature is None:
                continue
            symbols = [
                symbol
                for symbol in target_file.symbols
                if symbol.symbol_type == "route" and symbol.name == route
            ]
            if len(symbols) == 1:
                route_targets.setdefault(signature, []).append((target_path, symbols[0]))

    edges: list[dict[str, Any]] = []
    for source_path in sorted(indexed_by_path):
        if source_paths is not None and source_path not in source_paths:
            continue
        source_file = indexed_by_path[source_path]
        if source_file.is_test:
            continue
        for reference in source_file.http_references:
            signature = (reference.method, _normalized_http_path(reference.path))
            matches = set(route_targets.get(signature, ()))
            if len(matches) != 1:
                continue
            target_path, target_symbol = next(iter(matches))
            if len(edges) >= limit:
                return _EdgeCandidates(edges=tuple(edges), truncated=True)
            edges.append(_edge(
                frame=frame,
                source_path=source_path,
                target_path=target_path,
                edge_type="routes_to",
                rule_id="static_http_route_reference.v1",
                evidence_path=source_path,
                evidence_start_line=reference.start_line,
                evidence_end_line=reference.end_line,
                source_identity={
                    "kind": "module",
                    "path": source_path,
                    "line": reference.start_line,
                },
                target_identity=_symbol_identity(target_path, target_symbol),
                evidence={
                    "method": reference.method,
                    "client_path": reference.path,
                    "declared_route": target_symbol.name,
                },
            ))
    return _EdgeCandidates(edges=tuple(edges), truncated=False)


def _http_route_signature(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"([A-Z]+)\s+(.+)", str(value or "").strip())
    if match is None:
        return None
    return match.group(1), _normalized_http_path(match.group(2))


def _normalized_http_path(value: str) -> str:
    path = str(value or "").split("?", 1)[0]
    path = re.sub(r"\$\{[^{}]+\}", "{}", path)
    path = re.sub(r"\{[^{}]+\}", "{}", path)
    path = re.sub(r"(?<=/):[A-Za-z_][A-Za-z0-9_]*", "{}", path)
    return re.sub(r"/{2,}", "/", path) or "/"


def _observe_import_edges(
    frame: RepoFrame,
    indexed_by_path: dict[str, IndexedFile],
    *,
    limit: int,
) -> _EdgeCandidates:
    python_modules: dict[str, list[str]] = {}
    for path in sorted(indexed_by_path):
        module_name = _python_module_for_path(path)
        if module_name is not None:
            python_modules.setdefault(module_name, []).append(path)

    edges: list[dict[str, Any]] = []
    for path in sorted(indexed_by_path):
        indexed = indexed_by_path[path]
        for hint in sorted(
            indexed.import_hints,
            key=lambda item: (
                item.start_line,
                item.end_line,
                item.specifier,
                item.python_level,
                item.python_module or "",
            ),
        ):
            target_path: str | None = None
            if indexed.language == "python":
                module_name = _resolve_python_import_module(path, hint)
                if module_name is not None:
                    candidates = python_modules.get(module_name, [])
                    if len(candidates) == 1:
                        target_path = candidates[0]
            elif indexed.language in _JAVASCRIPT_LANGUAGES:
                target_path = _resolve_javascript_import_path(
                    path,
                    hint.specifier,
                    indexed_by_path,
                )

            if not target_path or target_path == path:
                continue
            if len(edges) >= limit:
                return _EdgeCandidates(edges=tuple(edges), truncated=True)
            edges.append(_edge(
                frame=frame,
                source_path=path,
                target_path=target_path,
                edge_type="imports",
                rule_id="local_module_import.v1",
                evidence_path=path,
                evidence_start_line=hint.start_line,
                evidence_end_line=hint.end_line,
                source_identity={"kind": "module", "path": path},
                target_identity={"kind": "module", "path": target_path},
                evidence={
                    "importer": path,
                    "specifier": hint.specifier,
                    "target": target_path,
                },
            ))
    return _EdgeCandidates(edges=tuple(edges), truncated=False)


def _observe_route_owner_edges(
    frame: RepoFrame,
    indexed_by_path: dict[str, IndexedFile],
    *,
    limit: int,
    source_paths: frozenset[str] | None = None,
) -> _EdgeCandidates:
    edges: list[dict[str, Any]] = []
    for path in sorted(indexed_by_path):
        if source_paths is not None and path not in source_paths:
            continue
        indexed = indexed_by_path[path]
        for owner in sorted(
            indexed.route_owners,
            key=lambda item: (
                item.start_line,
                item.end_line,
                item.route,
                item.handler_name,
            ),
        ):
            routes = [
                symbol
                for symbol in indexed.symbols
                if symbol.symbol_type == "route" and symbol.name == owner.route
            ]
            handlers = [
                symbol
                for symbol in indexed.symbols
                if symbol.symbol_type in {"function", "async_function"}
                and symbol.name == owner.handler_name
            ]
            if len(routes) != 1 or len(handlers) != 1:
                continue

            route = routes[0]
            handler = handlers[0]
            if len(edges) >= limit:
                return _EdgeCandidates(edges=tuple(edges), truncated=True)
            edges.append(_edge(
                frame=frame,
                source_path=path,
                target_path=path,
                edge_type="owned_by",
                rule_id="route_handler_owner.v1",
                evidence_path=path,
                evidence_start_line=owner.start_line,
                evidence_end_line=owner.end_line,
                source_identity=_symbol_identity(path, route),
                target_identity=_symbol_identity(path, handler),
                evidence={
                    "file": path,
                    "route": owner.route,
                    "handler": owner.handler_name,
                    "route_symbol": route.qualified_name or route.name,
                    "handler_symbol": handler.qualified_name or handler.name,
                },
            ))
    return _EdgeCandidates(edges=tuple(edges), truncated=False)


def _observe_call_edges(
    frame: RepoFrame,
    indexed_by_path: dict[str, IndexedFile],
    *,
    limit: int,
    source_paths: frozenset[str] | None = None,
    caller_identities: frozenset[str] | None = None,
    preferred_terms: frozenset[str] = frozenset(),
    rank_before_limit: bool = False,
    production_only: bool = False,
) -> _EdgeCandidates:
    """Resolve conservative Python call hints to unique local symbols."""

    python_modules: dict[str, list[str]] = {}
    for path in sorted(indexed_by_path):
        module_name = _python_module_for_path(path)
        if module_name is not None:
            python_modules.setdefault(module_name, []).append(path)

    edges: list[dict[str, Any]] = []
    for source_path in sorted(indexed_by_path):
        if source_paths is not None and source_path not in source_paths:
            continue
        source_file = indexed_by_path[source_path]
        if source_file.language != "python" or (
            production_only and source_file.is_test
        ):
            continue
        for hint in sorted(
            source_file.call_hints,
            key=lambda item: (
                item.start_line,
                item.end_line,
                item.caller_start_line,
                item.caller_name,
                item.target_specifier or "",
                item.target_name,
            ),
        ):
            source_symbols = [
                symbol
                for symbol in source_file.symbols
                if symbol.symbol_type in {"function", "async_function"}
                and symbol.name == hint.caller_name
                and symbol.start_line == hint.caller_start_line
            ]
            if len(source_symbols) != 1:
                continue
            source_symbol = source_symbols[0]
            caller_identity = source_symbol.qualified_name or source_symbol.name
            if (
                caller_identities is not None
                and caller_identity not in caller_identities
            ):
                continue
            if hint.binding_kind == "local_symbol":
                target_path = source_path
            else:
                specifier = str(hint.target_specifier or "")
                level = len(specifier) - len(specifier.lstrip("."))
                module_name = _resolve_python_import_module(
                    source_path,
                    IndexedImport(
                        specifier=specifier,
                        start_line=hint.start_line,
                        end_line=hint.end_line,
                        python_level=level,
                        python_module=specifier[level:] or None,
                    ),
                )
                candidates = python_modules.get(module_name or "", [])
                if len(candidates) != 1:
                    continue
                target_path = candidates[0]
            target_file = indexed_by_path.get(target_path)
            if target_file is None or (production_only and target_file.is_test):
                continue
            target_symbols = [
                symbol
                for symbol in target_file.symbols
                if symbol.symbol_type
                in {"function", "async_function", "class", "component"}
                and symbol.name == hint.target_name
            ]
            if len(target_symbols) != 1:
                continue
            target_symbol = target_symbols[0]
            if (
                source_path == target_path
                and source_symbol.start_line == target_symbol.start_line
                and source_symbol.name == target_symbol.name
            ):
                continue
            if not rank_before_limit and len(edges) >= limit:
                return _EdgeCandidates(edges=tuple(edges), truncated=True)
            edges.append(_edge(
                frame=frame,
                source_path=source_path,
                target_path=target_path,
                edge_type="calls",
                rule_id="local_symbol_call.v1",
                evidence_path=source_path,
                evidence_start_line=hint.start_line,
                evidence_end_line=hint.end_line,
                source_identity=_symbol_identity(source_path, source_symbol),
                target_identity=_symbol_identity(target_path, target_symbol),
                evidence={
                    "caller": source_symbol.qualified_name or source_symbol.name,
                    "callee": target_symbol.qualified_name or target_symbol.name,
                    "binding_kind": hint.binding_kind,
                    "specifier": hint.target_specifier,
                    "call_line": hint.start_line,
                },
            ))
    if not rank_before_limit:
        return _EdgeCandidates(edges=tuple(edges), truncated=False)

    unique = {str(edge["edge_key"]): edge for edge in edges}
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda item: _flow_edge_sort_key(item, preferred_terms),
        )
    )
    return _EdgeCandidates(
        edges=ordered[:limit],
        truncated=len(ordered) > limit,
    )


def _observe_test_edges(
    frame: RepoFrame,
    indexed_by_path: dict[str, IndexedFile],
    *,
    limit: int,
) -> _EdgeCandidates:
    edges: list[dict[str, Any]] = []
    for test_path in sorted(indexed_by_path):
        test_file = indexed_by_path[test_path]
        if not test_file.is_test:
            continue

        candidates = _test_target_candidates(test_path, indexed_by_path)
        if len(candidates) != 1:
            continue
        target_path = candidates[0]
        target_file = indexed_by_path[target_path]
        if len(edges) >= limit:
            return _EdgeCandidates(edges=tuple(edges), truncated=True)
        pair_edge = _edge(
            frame=frame,
            source_path=test_path,
            target_path=target_path,
            edge_type="tests",
            rule_id="test_path_match.v1",
            evidence_path=test_path,
            evidence_start_line=None,
            evidence_end_line=None,
            source_identity={"kind": "module", "path": test_path},
            target_identity={"kind": "module", "path": target_path},
            evidence={
                "test_path": test_path,
                "target_path": target_path,
                "test_sha256": test_file.sha256,
                "target_sha256": target_file.sha256,
                "transformation": "exact_test_path",
            },
        )
        edges.append(pair_edge)

        for reference in sorted(
            test_file.test_references,
            key=lambda item: (
                item.reference_line,
                item.binding_line,
                item.test_symbol_start_line,
                item.test_symbol_name,
                item.target_specifier,
                item.target_name,
            ),
        ):
            if not _test_reference_resolves_to_target(
                test_path,
                target_path,
                test_file,
                reference,
                indexed_by_path,
            ):
                continue
            source_matches = [
                symbol
                for symbol in test_file.symbols
                if symbol.name == reference.test_symbol_name
                and symbol.start_line == reference.test_symbol_start_line
                and symbol.symbol_type in {"function", "async_function", "test"}
            ]
            target_matches = [
                symbol
                for symbol in target_file.symbols
                if symbol.name == reference.target_name
                and symbol.symbol_type not in {"module", "import", "route", "test"}
            ]
            if len(source_matches) != 1 or len(target_matches) != 1:
                continue

            source_symbol = source_matches[0]
            target_symbol = target_matches[0]
            if len(edges) >= limit:
                return _EdgeCandidates(edges=tuple(edges), truncated=True)
            edges.append(_edge(
                frame=frame,
                source_path=test_path,
                target_path=target_path,
                edge_type="tests",
                rule_id="test_symbol_match.v1",
                evidence_path=test_path,
                evidence_start_line=reference.reference_line,
                evidence_end_line=reference.reference_line,
                source_identity=_symbol_identity(test_path, source_symbol),
                target_identity=_symbol_identity(target_path, target_symbol),
                evidence={
                    "pairing_edge_key": pair_edge["edge_key"],
                    "test_path": test_path,
                    "target_path": target_path,
                    "test_symbol": source_symbol.qualified_name or source_symbol.name,
                    "target_symbol": target_symbol.qualified_name or target_symbol.name,
                    "binding_specifier": reference.target_specifier,
                    "binding_line": reference.binding_line,
                    "reference_line": reference.reference_line,
                    "test_sha256": test_file.sha256,
                    "target_sha256": target_file.sha256,
                },
            ))
    return _EdgeCandidates(edges=tuple(edges), truncated=False)


def _edge(
    *,
    frame: RepoFrame,
    source_path: str,
    target_path: str,
    edge_type: str,
    rule_id: str,
    evidence_path: str,
    evidence_start_line: int | None,
    evidence_end_line: int | None,
    source_identity: dict[str, Any],
    target_identity: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    bounded_evidence = _bounded_evidence(evidence)
    edge_key = _canonical_hash([
        rule_id,
        _EDGE_RULE_VERSION,
        source_identity,
        target_identity,
        evidence_path,
        evidence_start_line,
        evidence_end_line,
    ])
    return {
        "source_path": source_path,
        "target_path": target_path,
        "relationship": edge_type,
        "edge_type": edge_type,
        "rule_id": rule_id,
        "rule_version": _EDGE_RULE_VERSION,
        "evidence_path": evidence_path,
        "evidence_start_line": evidence_start_line,
        "evidence_end_line": evidence_end_line,
        "evidence": bounded_evidence,
        "edge_key": edge_key,
        "snapshot_fingerprint": frame.snapshot_fingerprint,
    }


def _symbol_identity(path: str, symbol: IndexedSymbol) -> dict[str, Any]:
    return {
        "path": path,
        "symbol_type": symbol.symbol_type,
        "qualified_name": symbol.qualified_name or symbol.name,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
    }


def _bounded_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in sorted(evidence)[:MAX_EDGE_EVIDENCE_FIELDS]:
        value = evidence[key]
        if isinstance(value, str):
            bounded[key] = value[:MAX_EDGE_EVIDENCE_STRING_LENGTH]
        elif value is None or isinstance(value, (bool, int, float)):
            bounded[key] = value
        else:
            bounded[key] = str(value)[:MAX_EDGE_EVIDENCE_STRING_LENGTH]
    return bounded


def _unique_indexed_files(indexed_files: list[IndexedFile]) -> dict[str, IndexedFile]:
    by_path: dict[str, list[IndexedFile]] = {}
    for indexed in indexed_files:
        by_path.setdefault(indexed.path, []).append(indexed)
    return {
        path: matches[0]
        for path, matches in sorted(by_path.items())
        if len(matches) == 1
    }
