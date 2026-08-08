from dataclasses import replace

from app.services.repo_indexer import (
    IndexedCall,
    IndexedFile,
    IndexedHttpReference,
    IndexedImport,
    IndexedRouteOwner,
    IndexedSymbol,
    IndexedTestReference,
    RepoFrame,
)
from app.services.workspace_foundation_edges import (
    MAX_WORKSPACE_FOUNDATION_EDGE_CANDIDATES,
    MAX_WORKSPACE_FOUNDATION_EDGES,
    observe_workspace_edges,
    observe_workspace_edges_result,
    observe_workspace_flow_edges_result,
)


def _indexed_file(
    path: str,
    *,
    language: str = "python",
    symbols: tuple[IndexedSymbol, ...] = (),
    import_hints: tuple[IndexedImport, ...] = (),
    route_hints: tuple[str, ...] = (),
    route_owners: tuple[IndexedRouteOwner, ...] = (),
    call_hints: tuple[IndexedCall, ...] = (),
    http_references: tuple[IndexedHttpReference, ...] = (),
    test_references: tuple[IndexedTestReference, ...] = (),
    is_test: bool = False,
) -> IndexedFile:
    return IndexedFile(
        path=path,
        language=language,
        sha256=f"sha256:{path}",
        size=1,
        symbols=list(symbols),
        import_hints=list(import_hints),
        route_hints=list(route_hints),
        route_owners=list(route_owners),
        call_hints=list(call_hints),
        http_references=list(http_references),
        test_references=list(test_references),
        is_test=is_test,
    )


def _frame(*files: IndexedFile) -> RepoFrame:
    return RepoFrame(
        repo_path="/workspace/project",
        branch="main",
        base_commit="base",
        head_commit="head",
        dirty=False,
        changed_files=[],
        untracked_files=[],
        indexed_files=list(files),
        package_manifests={},
        recent_commits=[],
        test_files=sorted(item.path for item in files if item.is_test),
        manifest_files=[],
        env_files=[],
        last_indexed_at="2026-08-05T00:00:00Z",
        snapshot_fingerprint="snapshot-123",
    )


def _exact_edge_frame() -> RepoFrame:
    service = _indexed_file(
        "app/service.py",
        symbols=(
            IndexedSymbol(
                symbol_type="module",
                name="app/service.py",
                qualified_name="app/service.py",
            ),
            IndexedSymbol(
                symbol_type="function",
                name="run_service",
                qualified_name="app.service.run_service",
                start_line=1,
                end_line=2,
            ),
        ),
    )
    service_import = IndexedImport(
        specifier=".service",
        start_line=1,
        end_line=1,
        python_level=1,
        python_module="service",
    )
    api = _indexed_file(
        "app/api.py",
        symbols=(
            IndexedSymbol(
                symbol_type="module",
                name="app/api.py",
                qualified_name="app/api.py",
            ),
            IndexedSymbol(
                symbol_type="route",
                name="/health",
                qualified_name="app.api.health:/health",
                start_line=4,
                end_line=6,
            ),
            IndexedSymbol(
                symbol_type="function",
                name="health",
                qualified_name="app.api.health",
                start_line=5,
                end_line=6,
            ),
        ),
        # Repeated parser evidence must collapse to one stable structural edge.
        import_hints=(service_import, service_import),
        route_owners=(
            IndexedRouteOwner(
                route="/health",
                handler_name="health",
                start_line=4,
                end_line=6,
            ),
        ),
    )
    test_service = _indexed_file(
        "tests/test_service.py",
        symbols=(
            IndexedSymbol(
                symbol_type="module",
                name="tests/test_service.py",
                qualified_name="tests/test_service.py",
            ),
            IndexedSymbol(
                symbol_type="function",
                name="test_run_service",
                qualified_name="tests.test_service.test_run_service",
                start_line=3,
                end_line=4,
            ),
        ),
        import_hints=(
            IndexedImport(
                specifier="app.service",
                start_line=1,
                end_line=1,
                python_module="app.service",
            ),
        ),
        test_references=(
            IndexedTestReference(
                test_symbol_name="test_run_service",
                test_symbol_start_line=3,
                target_name="run_service",
                target_specifier="app.service",
                binding_line=1,
                reference_line=4,
            ),
        ),
        is_test=True,
    )
    typescript_target = _indexed_file(
        "frontend/math.ts",
        language="typescript",
    )
    typescript_source = _indexed_file(
        "frontend/view.tsx",
        language="typescript-react",
        import_hints=(IndexedImport(specifier="./math", start_line=2, end_line=2),),
    )
    javascript_target = _indexed_file(
        "scripts/helper.js",
        language="javascript",
    )
    javascript_source = _indexed_file(
        "scripts/run.js",
        language="javascript",
        import_hints=(IndexedImport(specifier="./helper", start_line=1, end_line=1),),
    )
    return _frame(
        javascript_source,
        test_service,
        typescript_target,
        api,
        javascript_target,
        service,
        typescript_source,
    )


def test_observes_exact_import_route_test_path_and_test_symbol_edges():
    edges = observe_workspace_edges(_exact_edge_frame())

    assert len(edges) == 7
    assert {
        (edge["rule_id"], edge["source_path"], edge["target_path"])
        for edge in edges
    } == {
        ("local_module_import.v1", "app/api.py", "app/service.py"),
        ("local_module_import.v1", "frontend/view.tsx", "frontend/math.ts"),
        ("local_module_import.v1", "scripts/run.js", "scripts/helper.js"),
        ("local_module_import.v1", "tests/test_service.py", "app/service.py"),
        ("route_handler_owner.v1", "app/api.py", "app/api.py"),
        ("test_path_match.v1", "tests/test_service.py", "app/service.py"),
        ("test_symbol_match.v1", "tests/test_service.py", "app/service.py"),
    }
    required = {
        "source_path",
        "target_path",
        "relationship",
        "edge_type",
        "rule_id",
        "rule_version",
        "evidence_path",
        "evidence_start_line",
        "evidence_end_line",
        "evidence",
        "edge_key",
        "snapshot_fingerprint",
    }
    assert all(required <= edge.keys() for edge in edges)
    assert all(edge["relationship"] == edge["edge_type"] for edge in edges)
    assert all(edge["rule_version"] == "1" for edge in edges)
    assert all(edge["snapshot_fingerprint"] == "snapshot-123" for edge in edges)

    path_edge = next(edge for edge in edges if edge["rule_id"] == "test_path_match.v1")
    symbol_edge = next(
        edge for edge in edges if edge["rule_id"] == "test_symbol_match.v1"
    )
    assert symbol_edge["evidence"]["pairing_edge_key"] == path_edge["edge_key"]
    assert symbol_edge["evidence_start_line"] == 4
    assert symbol_edge["evidence_end_line"] == 4


def test_observes_unique_local_symbol_calls_and_rejects_ambiguous_targets():
    service = _indexed_file(
        "app/service.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="run_service",
                qualified_name="app.service.run_service",
                start_line=2,
                end_line=4,
            ),
        ),
    )
    api = _indexed_file(
        "app/api.py",
        symbols=(
            IndexedSymbol(
                symbol_type="async_function",
                name="create_item",
                qualified_name="app.api.create_item",
                start_line=5,
                end_line=7,
            ),
        ),
        call_hints=(
            IndexedCall(
                caller_name="create_item",
                caller_start_line=5,
                target_name="run_service",
                target_specifier=".service",
                binding_kind="imported_symbol",
                start_line=7,
                end_line=7,
            ),
        ),
    )

    edges = observe_workspace_edges(_frame(api, service))
    call_edge = next(edge for edge in edges if edge["rule_id"] == "local_symbol_call.v1")

    assert call_edge["source_path"] == "app/api.py"
    assert call_edge["target_path"] == "app/service.py"
    assert call_edge["edge_type"] == "calls"
    assert call_edge["evidence"] == {
        "binding_kind": "imported_symbol",
        "call_line": 7,
        "callee": "app.service.run_service",
        "caller": "app.api.create_item",
        "specifier": ".service",
    }

    ambiguous_service = replace(
        service,
        symbols=[
            *service.symbols,
            IndexedSymbol(
                symbol_type="async_function",
                name="run_service",
                qualified_name="app.service.run_service_async",
                start_line=8,
                end_line=9,
            ),
        ],
    )
    assert not any(
        edge["rule_id"] == "local_symbol_call.v1"
        for edge in observe_workspace_edges(_frame(api, ambiguous_service))
    )


def test_links_static_frontend_http_reference_to_one_exact_backend_route():
    frontend = _indexed_file(
        "frontend/hooks.js",
        language="javascript",
        http_references=(
            IndexedHttpReference(
                method="POST",
                path="/continuations/{}/open",
                start_line=12,
                end_line=12,
            ),
        ),
    )
    backend = _indexed_file(
        "app/api/continuations.py",
        route_hints=("POST /continuations/{run_id}/open",),
        symbols=(
            IndexedSymbol(
                symbol_type="route",
                name="POST /continuations/{run_id}/open",
                qualified_name="app.api.continuations.open_run:POST",
                start_line=40,
                end_line=42,
            ),
        ),
    )

    edges = observe_workspace_edges(_frame(frontend, backend))
    route_edge = next(
        edge for edge in edges if edge["rule_id"] == "static_http_route_reference.v1"
    )

    assert route_edge["source_path"] == "frontend/hooks.js"
    assert route_edge["target_path"] == "app/api/continuations.py"
    assert route_edge["edge_type"] == "routes_to"
    assert route_edge["evidence"] == {
        "client_path": "/continuations/{}/open",
        "declared_route": "POST /continuations/{run_id}/open",
        "method": "POST",
    }

    duplicate_backend = replace(backend, path="app/api/duplicate.py")
    assert not any(
        edge["rule_id"] == "static_http_route_reference.v1"
        for edge in observe_workspace_edges(_frame(frontend, backend, duplicate_backend))
    )


def test_http_route_edges_do_not_invent_an_unobserved_api_mount():
    frontend = _indexed_file(
        "frontend/hooks.js",
        language="javascript",
        http_references=(
            IndexedHttpReference(
                method="POST",
                path="/api/continuations/{}/open",
                start_line=12,
                end_line=12,
            ),
        ),
    )
    backend = _indexed_file(
        "app/api/continuations.py",
        route_hints=("POST /continuations/{run_id}/open",),
        symbols=(
            IndexedSymbol(
                symbol_type="route",
                name="POST /continuations/{run_id}/open",
                qualified_name="app.api.continuations.open_run:POST",
                start_line=40,
                end_line=42,
            ),
        ),
    )

    assert not any(
        edge["rule_id"] == "static_http_route_reference.v1"
        for edge in observe_workspace_edges(_frame(frontend, backend))
    )

    exact_backend = replace(
        backend,
        route_hints=["POST /api/continuations/{run_id}/open"],
        symbols=[
            replace(
                backend.symbols[0],
                name="POST /api/continuations/{run_id}/open",
            )
        ],
    )
    assert any(
        edge["rule_id"] == "static_http_route_reference.v1"
        for edge in observe_workspace_edges(_frame(frontend, exact_backend))
    )


def test_observation_is_deterministic_deduplicated_and_stably_sorted():
    frame = _exact_edge_frame()
    original_file_order = tuple(item.path for item in frame.indexed_files)

    first = observe_workspace_edges(frame)
    reversed_frame = replace(frame, indexed_files=list(reversed(frame.indexed_files)))
    second = observe_workspace_edges(reversed_frame)

    assert first == second
    assert [edge["rule_id"] for edge in first[:3]] == [
        "route_handler_owner.v1",
        "local_module_import.v1",
        "local_module_import.v1",
    ]
    assert len({edge["edge_key"] for edge in first}) == len(first)
    assert tuple(item.path for item in frame.indexed_files) == original_file_order


def test_ambiguous_import_route_and_test_links_are_rejected():
    ambiguous_typescript = _indexed_file(
        "src/ambiguous.ts",
        language="typescript",
        import_hints=(IndexedImport(specifier="./util", start_line=1, end_line=1),),
    )
    util_ts = _indexed_file("src/util.ts", language="typescript")
    util_js = _indexed_file("src/util.js", language="javascript")
    ambiguous_python = _indexed_file(
        "consumer.py",
        import_hints=(
            IndexedImport(
                specifier="pkg",
                start_line=1,
                end_line=1,
                python_module="pkg",
            ),
        ),
    )
    package_module = _indexed_file("pkg.py")
    package_init = _indexed_file("pkg/__init__.py")
    ambiguous_route = _indexed_file(
        "app/routes.py",
        symbols=(
            IndexedSymbol(symbol_type="route", name="/items", start_line=2, end_line=4),
            IndexedSymbol(symbol_type="route", name="/items", start_line=6, end_line=8),
            IndexedSymbol(symbol_type="function", name="items", start_line=3, end_line=4),
        ),
        route_owners=(
            IndexedRouteOwner(
                route="/items",
                handler_name="items",
                start_line=2,
                end_line=4,
            ),
        ),
    )
    ambiguous_test = _indexed_file(
        "tests/test_service.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="test_run",
                start_line=2,
                end_line=3,
            ),
        ),
        test_references=(
            IndexedTestReference(
                test_symbol_name="test_run",
                test_symbol_start_line=2,
                target_name="run",
                target_specifier="app.service",
                binding_line=1,
                reference_line=3,
            ),
        ),
        is_test=True,
    )
    app_service = _indexed_file(
        "app/service.py",
        symbols=(IndexedSymbol(symbol_type="function", name="run", start_line=1),),
    )
    src_service = _indexed_file(
        "src/service.py",
        symbols=(IndexedSymbol(symbol_type="function", name="run", start_line=1),),
    )

    assert observe_workspace_edges(_frame(
        ambiguous_typescript,
        util_ts,
        util_js,
        ambiguous_python,
        package_module,
        package_init,
        ambiguous_route,
        ambiguous_test,
        app_service,
        src_service,
    )) == ()


def test_default_cap_exposes_deterministic_truncation_metadata():
    target = _indexed_file("pkg/target.py")
    importers = [
        _indexed_file(
            f"pkg/source_{index:03d}.py",
            import_hints=(
                IndexedImport(
                    specifier="pkg.target",
                    start_line=1,
                    end_line=1,
                    python_module="pkg.target",
                ),
            ),
        )
        for index in range(MAX_WORKSPACE_FOUNDATION_EDGES + 4)
    ]
    frame = _frame(target, *importers)

    result = observe_workspace_edges_result(frame)

    assert result.observed_count == MAX_WORKSPACE_FOUNDATION_EDGES + 4
    assert len(result.edges) == MAX_WORKSPACE_FOUNDATION_EDGES
    assert result.limit == MAX_WORKSPACE_FOUNDATION_EDGES
    assert result.truncated is True
    assert observe_workspace_edges(frame) == result.edges


def test_candidate_work_is_strictly_capped_and_reports_truncation():
    target = _indexed_file("pkg/target.py")
    requested_candidates = MAX_WORKSPACE_FOUNDATION_EDGE_CANDIDATES + 10
    importers = [
        _indexed_file(
            f"pkg/source_{index:04d}.py",
            import_hints=(
                IndexedImport(
                    specifier="pkg.target",
                    start_line=1,
                    end_line=1,
                    python_module="pkg.target",
                ),
            ),
        )
        for index in range(requested_candidates)
    ]

    result = observe_workspace_edges_result(
        _frame(target, *importers),
        limit=MAX_WORKSPACE_FOUNDATION_EDGE_CANDIDATES + 1,
    )

    assert result.observed_count <= MAX_WORKSPACE_FOUNDATION_EDGE_CANDIDATES
    assert result.observed_count < requested_candidates
    assert len(result.edges) == result.observed_count
    assert result.truncated is True


def test_bounded_order_keeps_production_calls_routes_and_imports_before_noise_and_tests():
    service = _indexed_file(
        "app/services/deploy.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="deploy",
                qualified_name="app.services.deploy.deploy",
                start_line=1,
                end_line=2,
            ),
        ),
    )
    api = _indexed_file(
        "app/api/deploy.py",
        symbols=(
            IndexedSymbol(
                symbol_type="route",
                name="/deploy",
                qualified_name="app.api.deploy.submit:/deploy",
                start_line=3,
                end_line=5,
            ),
            IndexedSymbol(
                symbol_type="function",
                name="submit",
                qualified_name="app.api.deploy.submit",
                start_line=4,
                end_line=5,
            ),
        ),
        call_hints=(
            IndexedCall(
                caller_name="submit",
                caller_start_line=4,
                target_name="deploy",
                target_specifier="app.services.deploy",
                binding_kind="imported_symbol",
                start_line=5,
                end_line=5,
            ),
        ),
        import_hints=(
            IndexedImport(
                specifier="app.services.deploy",
                start_line=1,
                end_line=1,
                python_module="app.services.deploy",
            ),
        ),
        route_owners=(
            IndexedRouteOwner(
                route="/deploy",
                handler_name="submit",
                start_line=3,
                end_line=5,
            ),
        ),
    )
    generated_target = _indexed_file("generated/helper.py")
    generated_source = _indexed_file(
        "generated/client.py",
        import_hints=(
            IndexedImport(
                specifier="generated.helper",
                start_line=1,
                end_line=1,
                python_module="generated.helper",
            ),
        ),
    )
    test_service = _indexed_file("tests/test_deploy.py", is_test=True)
    frame = _frame(
        generated_source,
        test_service,
        service,
        api,
        generated_target,
    )

    result = observe_workspace_edges_result(frame, limit=3)

    assert [edge["rule_id"] for edge in result.edges] == [
        "route_handler_owner.v1",
        "local_symbol_call.v1",
        "local_module_import.v1",
    ]
    assert all("generated/" not in edge["source_path"] for edge in result.edges)


def test_flow_call_cap_is_applied_after_exact_anchor_traversal():
    noise_target = _indexed_file(
        "aaa/noise_target.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="run_noise",
                qualified_name="aaa.noise_target.run_noise",
                start_line=1,
                end_line=2,
            ),
        ),
    )
    # More than the former repository-wide flow-call cap, all lexically before
    # the capability anchor. These exact but irrelevant edges must not consume
    # the capability traversal budget.
    noise_sources = [
        _indexed_file(
            f"aaa/noise_{index:04d}.py",
            symbols=(
                IndexedSymbol(
                    symbol_type="function",
                    name="run",
                    qualified_name=f"aaa.noise_{index:04d}.run",
                    start_line=2,
                    end_line=3,
                ),
            ),
            call_hints=(
                IndexedCall(
                    caller_name="run",
                    caller_start_line=2,
                    target_name="run_noise",
                    target_specifier="aaa.noise_target",
                    binding_kind="imported_symbol",
                    start_line=3,
                    end_line=3,
                ),
            ),
        )
        for index in range(800)
    ]
    final_service = _indexed_file(
        "zzz/final.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="finish_launch",
                qualified_name="zzz.final.finish_launch",
                start_line=1,
                end_line=2,
            ),
        ),
    )
    service = _indexed_file(
        "zzz/service.py",
        symbols=(
            IndexedSymbol(
                symbol_type="function",
                name="launch_service",
                qualified_name="zzz.service.launch_service",
                start_line=2,
                end_line=3,
            ),
        ),
        call_hints=(
            IndexedCall(
                caller_name="launch_service",
                caller_start_line=2,
                target_name="finish_launch",
                target_specifier="zzz.final",
                binding_kind="imported_symbol",
                start_line=3,
                end_line=3,
            ),
        ),
    )
    api = _indexed_file(
        "zzz/api.py",
        symbols=(
            IndexedSymbol(
                symbol_type="route",
                name="POST /launch",
                qualified_name="zzz.api.launch:POST /launch",
                start_line=4,
                end_line=6,
            ),
            IndexedSymbol(
                symbol_type="function",
                name="launch",
                qualified_name="zzz.api.launch",
                start_line=5,
                end_line=6,
            ),
        ),
        route_owners=(
            IndexedRouteOwner(
                route="POST /launch",
                handler_name="launch",
                start_line=4,
                end_line=6,
            ),
        ),
        call_hints=(
            IndexedCall(
                caller_name="launch",
                caller_start_line=5,
                target_name="launch_service",
                target_specifier="zzz.service",
                binding_kind="imported_symbol",
                start_line=6,
                end_line=6,
            ),
        ),
    )

    result = observe_workspace_flow_edges_result(
        _frame(noise_target, *noise_sources, final_service, service, api),
        anchor_paths=("zzz/api.py",),
        preferred_terms=frozenset({"launch"}),
    )

    assert [edge["rule_id"] for edge in result.edges] == [
        "route_handler_owner.v1",
        "local_symbol_call.v1",
        "local_symbol_call.v1",
    ]
    assert [
        edge["evidence"].get("caller")
        for edge in result.edges
        if edge["rule_id"] == "local_symbol_call.v1"
    ] == ["zzz.api.launch", "zzz.service.launch_service"]
    assert all(not edge["source_path"].startswith("aaa/") for edge in result.edges)
