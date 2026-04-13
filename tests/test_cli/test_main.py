from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import app.cli.main as cli_main
import pytest


class TestCtxeCLI:
    def test_verify_targets_include_trust_review_api_suite(self):
        assert "tests/test_api/test_trust.py" in cli_main.VERIFY_TEST_TARGETS

    def test_verify_runs_release_gate_steps(self, monkeypatch, tmp_path, capsys):
        project_root = tmp_path / "context-engine"
        frontend_dir = project_root / "frontend"
        frontend_dir.mkdir(parents=True)
        calls: list[tuple[tuple[str, ...], Path, bool, dict[str, str] | None]] = []

        def fake_boot_stack(base_url, *, wait_timeout, quiet=False):
            assert base_url == "http://example.test"
            assert wait_timeout == 90
            assert quiet is True
            return project_root

        def fake_run_subprocess(command, *, cwd, capture_output=False, env=None):
            calls.append((tuple(command), cwd, capture_output, env))
            return SimpleNamespace(stdout="ok\n", stderr="")

        monkeypatch.setattr(cli_main, "boot_stack", fake_boot_stack)
        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda base_url: (
                {"status": "ok"},
                {"status": "ready", "checks": {"database": "ok", "redis": "ok"}},
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "seed_demo_workspace",
            lambda base_url, *, workspace_id=None: {
                "workspaceId": str(uuid4()),
                "workspaceName": cli_main.DEFAULT_DEMO_WORKSPACE_NAME,
                "status": "existing",
                "seededCaseCount": 5,
            },
        )
        monkeypatch.setattr(cli_main, "run_subprocess", fake_run_subprocess)

        exit_code = cli_main.main(["verify", "--base-url", "http://example.test"])

        assert exit_code == 0
        assert calls[0] == (
            ("bash", "scripts/smoke.sh"),
            project_root,
            True,
            {
                "BASE_URL": "http://example.test",
                "SMOKE_QUESTION": cli_main.DEFAULT_VERIFY_QUESTION,
                "SMOKE_EXPECT": cli_main.DEFAULT_VERIFY_EXPECT,
            },
        )
        assert calls[1] == (
            (sys.executable, "-m", "pytest", *cli_main.VERIFY_TEST_TARGETS, "-q"),
            project_root,
            True,
            {"TEST_DATABASE_URL": cli_main.DEFAULT_VERIFY_TEST_DATABASE_URL},
        )
        assert calls[2] == (("npm", "test"), frontend_dir, True, None)
        assert calls[3] == (("npm", "run", "build"), frontend_dir, True, None)
        output = capsys.readouterr().out
        assert "boot: docker services, migrations, and API boot completed" in output
        assert "readiness: /health=ok | /health/ready=ready" in output
        assert "seed: Acme Accuracy Demo" in output
        assert "OSS v1 verification passed." in output

    def test_verify_can_skip_frontend_checks(self, monkeypatch, tmp_path):
        project_root = tmp_path / "context-engine"
        project_root.mkdir()
        calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: project_root,
        )
        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda base_url: (
                {"status": "ok"},
                {"status": "ready", "checks": {"database": "ok", "redis": "ok"}},
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "seed_demo_workspace",
            lambda base_url, *, workspace_id=None: {
                "workspaceId": str(uuid4()),
                "workspaceName": cli_main.DEFAULT_DEMO_WORKSPACE_NAME,
                "status": "existing",
                "seededCaseCount": 5,
            },
        )

        def fake_run_subprocess(command, *, cwd, capture_output=False, env=None):
            calls.append((tuple(command), env))
            return SimpleNamespace(stdout="ok\n", stderr="")

        monkeypatch.setattr(cli_main, "run_subprocess", fake_run_subprocess)

        exit_code = cli_main.main(["verify", "--skip-frontend"])

        assert exit_code == 0
        assert calls == [
            (
                ("bash", "scripts/smoke.sh"),
                {
                    "BASE_URL": cli_main.DEFAULT_BASE_URL,
                    "SMOKE_QUESTION": cli_main.DEFAULT_VERIFY_QUESTION,
                    "SMOKE_EXPECT": cli_main.DEFAULT_VERIFY_EXPECT,
                },
            ),
            (
                (sys.executable, "-m", "pytest", *cli_main.VERIFY_TEST_TARGETS, "-q"),
                {"TEST_DATABASE_URL": cli_main.DEFAULT_VERIFY_TEST_DATABASE_URL},
            ),
        ]

    def test_verify_supports_phase_selection_and_contract_test_database(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        project_root = tmp_path / "context-engine"
        frontend_dir = project_root / "frontend"
        frontend_dir.mkdir(parents=True)
        calls: list[tuple[tuple[str, ...], Path, dict[str, str] | None]] = []

        monkeypatch.setattr(
            cli_main,
            "find_project_root",
            lambda: project_root,
        )
        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("boot should not run")),
        )
        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("readiness should not run")
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "seed_demo_workspace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("seed should not run")),
        )

        def fake_run_subprocess(command, *, cwd, capture_output=False, env=None):
            calls.append((tuple(command), cwd, env))
            return SimpleNamespace(stdout="ok\n", stderr="")

        monkeypatch.setattr(cli_main, "run_subprocess", fake_run_subprocess)

        exit_code = cli_main.main(
            [
                "verify",
                "--phase",
                "contract-tests",
                "--phase",
                "frontend-build",
                "--test-database-url",
                "postgresql+asyncpg://postgres:postgres@localhost:5432/release_gate_db",
            ]
        )

        assert exit_code == 0
        assert calls == [
            (
                (sys.executable, "-m", "pytest", *cli_main.VERIFY_TEST_TARGETS, "-q"),
                project_root,
                {
                    "TEST_DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/release_gate_db",
                },
            ),
            (("npm", "run", "build"), frontend_dir, None),
        ]
        output = capsys.readouterr().out
        assert "verify phases: contract-tests, frontend-build" in output
        assert "skipped phases: boot, readiness, seed, smoke, frontend-tests" in output

    def test_verify_rejects_skip_frontend_with_explicit_frontend_phase(self, capsys):
        exit_code = cli_main.main(["verify", "--skip-frontend", "--phase", "frontend-tests"])

        assert exit_code == 1
        assert (
            "--skip-frontend cannot be combined with --phase frontend-tests/frontend-build."
            in capsys.readouterr().err
        )

    def test_verify_reports_phase_specific_failures(self, monkeypatch, tmp_path, capsys):
        project_root = tmp_path / "context-engine"
        project_root.mkdir()

        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: project_root,
        )
        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda base_url: (
                {"status": "ok"},
                {"status": "ready", "checks": {"database": "ok", "redis": "ok"}},
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "seed_demo_workspace",
            lambda base_url, *, workspace_id=None: {
                "workspaceId": str(uuid4()),
                "workspaceName": cli_main.DEFAULT_DEMO_WORKSPACE_NAME,
                "status": "existing",
                "seededCaseCount": 5,
            },
        )

        def fake_run_subprocess(command, *, cwd, capture_output=False, env=None):
            if command[:2] == ["bash", "scripts/smoke.sh"]:
                raise cli_main.CLIError("smoke command failed")
            return SimpleNamespace(stdout="ok\n", stderr="")

        monkeypatch.setattr(cli_main, "run_subprocess", fake_run_subprocess)

        exit_code = cli_main.main(["verify"])

        assert exit_code == 1
        err = capsys.readouterr().err
        assert f"verify phases: {', '.join(cli_main.VERIFY_PHASES)}" in err
        assert "completed phases: boot, readiness, seed" in err
        assert "verify failed during smoke: smoke command failed" in err
        assert "next step: rerun 'bash scripts/smoke.sh'" in err

    def test_verify_reports_json_errors_when_requested(self, monkeypatch, tmp_path, capsys):
        project_root = tmp_path / "context-engine"
        project_root.mkdir()
        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: project_root,
        )
        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda base_url: (_ for _ in ()).throw(cli_main.CLIError("readiness check failed")),
        )

        exit_code = cli_main.main(["verify", "--json"])

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "status": "error",
            "detail": (
                "verify failed during readiness: readiness check failed. Next step: "
                "probe 'http://localhost:8000/health' and 'http://localhost:8000/health/ready', "
                "then inspect 'docker compose logs --tail 40 api postgres redis'"
            ),
            "phase": "readiness",
            "next_step": (
                "probe 'http://localhost:8000/health' and 'http://localhost:8000/health/ready', "
                "then inspect 'docker compose logs --tail 40 api postgres redis'"
            ),
            "selected_phases": list(cli_main.VERIFY_PHASES),
            "skipped_phases": [],
            "completed_steps": [
                {
                    "step": "boot",
                    "status": "ok",
                    "detail": "docker services, migrations, and API boot completed at http://localhost:8000",
                }
            ],
        }

    @pytest.mark.parametrize(
        ("failing_phase", "expected_fragment"),
        [
            ("boot", "boot failed"),
            ("seed", "seed failed"),
            ("contract-tests", "contract-tests failed"),
            ("frontend-tests", "frontend-tests failed"),
            ("frontend-build", "frontend-build failed"),
        ],
    )
    def test_verify_labels_each_phase_failure(
        self,
        monkeypatch,
        tmp_path,
        capsys,
        failing_phase,
        expected_fragment,
    ):
        project_root = tmp_path / "context-engine"
        frontend_dir = project_root / "frontend"
        frontend_dir.mkdir(parents=True)

        if failing_phase == "boot":
            monkeypatch.setattr(
                cli_main,
                "boot_stack",
                lambda base_url, *, wait_timeout, quiet=False: (_ for _ in ()).throw(
                    cli_main.CLIError("boot failed")
                ),
            )
        else:
            monkeypatch.setattr(
                cli_main,
                "boot_stack",
                lambda base_url, *, wait_timeout, quiet=False: project_root,
            )

        monkeypatch.setattr(
            cli_main,
            "check_verify_readiness",
            lambda base_url: (
                {"status": "ok"},
                {"status": "ready", "checks": {"database": "ok", "redis": "ok"}},
            ),
        )

        if failing_phase == "seed":
            monkeypatch.setattr(
                cli_main,
                "seed_demo_workspace",
                lambda base_url, *, workspace_id=None: (_ for _ in ()).throw(
                    cli_main.CLIError("seed failed")
                ),
            )
        else:
            monkeypatch.setattr(
                cli_main,
                "seed_demo_workspace",
                lambda base_url, *, workspace_id=None: {
                    "workspaceId": str(uuid4()),
                    "workspaceName": cli_main.DEFAULT_DEMO_WORKSPACE_NAME,
                    "status": "existing",
                    "seededCaseCount": 5,
                },
            )

        def fake_run_subprocess(command, *, cwd, capture_output=False, env=None):
            phase_by_command = {
                ("bash", "scripts/smoke.sh"): "smoke",
                (sys.executable, "-m", "pytest", *cli_main.VERIFY_TEST_TARGETS, "-q"): "contract-tests",
                ("npm", "test"): "frontend-tests",
                ("npm", "run", "build"): "frontend-build",
            }
            phase = phase_by_command.get(tuple(command))
            if phase == failing_phase:
                raise cli_main.CLIError(f"{phase} failed")
            return SimpleNamespace(stdout="ok\n", stderr="")

        monkeypatch.setattr(cli_main, "run_subprocess", fake_run_subprocess)

        exit_code = cli_main.main(["verify"])

        assert exit_code == 1
        err = capsys.readouterr().err
        assert f"verify failed during {failing_phase}: {expected_fragment}" in err
        assert "next step:" in err

    def test_ensure_local_env_creates_env_and_encryption_key(self, tmp_path):
        project_root = tmp_path / "context-engine"
        project_root.mkdir()
        (project_root / ".env.example").write_text(
            "ENVIRONMENT=development\nENCRYPTION_KEY=\n",
            encoding="utf-8",
        )

        cli_main.ensure_local_env(project_root)

        env_contents = (project_root / ".env").read_text(encoding="utf-8")
        assert "ENVIRONMENT=development" in env_contents
        key_line = next(
            line for line in env_contents.splitlines() if line.startswith("ENCRYPTION_KEY=")
        )
        assert key_line != "ENCRYPTION_KEY="

    def test_demo_seeds_canonical_workspace_via_http_api(self, monkeypatch, capsys):
        calls: list[tuple[str, str, dict | None]] = []

        def fake_boot_stack(base_url, *, wait_timeout, quiet=False):
            assert base_url == "http://example.test"
            assert wait_timeout == 90
            assert quiet is False
            return Path("/tmp/context-engine")

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            calls.append((method, path, payload))
            if method == "POST" and path == cli_main.SEED_DEMO_PATH:
                assert payload == {}
                return {
                    "workspaceId": str(uuid4()),
                    "workspaceName": cli_main.DEFAULT_DEMO_WORKSPACE_NAME,
                    "status": "created",
                    "seededCaseCount": 5,
                }
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "boot_stack", fake_boot_stack)
        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["demo", "--base-url", "http://example.test"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Demo workspace ready: Acme Accuracy Demo" in captured.out
        assert calls == [("POST", cli_main.SEED_DEMO_PATH, {})]

    def test_demo_targets_existing_workspace_when_selected(self, monkeypatch, capsys):
        workspace_id = str(uuid4())
        calls: list[tuple[str, str, dict | None]] = []

        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: Path("/tmp/context-engine"),
        )

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            calls.append((method, path, payload))
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return [{"id": workspace_id, "name": "Selected Workspace"}]
            if method == "POST" and path == cli_main.SEED_DEMO_PATH:
                assert payload == {"workspace_id": workspace_id}
                return {
                    "workspaceId": workspace_id,
                    "workspaceName": "Selected Workspace",
                    "status": "created",
                    "seededCaseCount": 5,
                }
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(
            ["demo", "--workspace", "Selected Workspace", "--base-url", "http://example.test"],
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Demo workspace ready: Selected Workspace" in captured.out
        assert calls[0][:2] == ("GET", cli_main.WORKSPACES_PATH)
        assert calls[1][:2] == ("POST", cli_main.SEED_DEMO_PATH)

    def test_demo_rejects_malformed_seed_response(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: Path("/tmp/context-engine"),
        )
        monkeypatch.setattr(
            cli_main,
            "api_request",
            lambda base_url, method, path, **kwargs: {"workspaceName": "Acme Accuracy Demo"},
        )

        exit_code = cli_main.main(["demo", "--base-url", "http://example.test"])

        assert exit_code == 1
        assert "POST /api/seed-demo response missing 'workspaceId'." in capsys.readouterr().err

    def test_ingest_creates_default_workspace_and_posts_documents(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        source = tmp_path / "notes.txt"
        source.write_text("decision: ship Friday", encoding="utf-8")
        workspace_id = str(uuid4())
        calls: list[tuple[str, str, dict | None]] = []

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            calls.append((method, path, payload))
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return []
            if method == "POST" and path == cli_main.WORKSPACES_PATH:
                return {"id": workspace_id, "name": "Local Workspace"}
            if method == "POST" and path == cli_main.IMPORTS_PATH:
                assert payload["workspace_id"] == workspace_id
                assert len(payload["documents"]) == 1
                assert payload["documents"][0]["content"] == "decision: ship Friday"
                return {
                    "workspace_id": workspace_id,
                    "connector_id": str(uuid4()),
                    "connector_type": "local",
                    "model_name": "Imported Files",
                    "total_documents": 1,
                    "created_documents": 1,
                    "updated_documents": 0,
                    "unchanged_documents": 0,
                    "processed_documents": 1,
                    "failed_documents": 0,
                    "documents": [],
                    "imported_at": "2026-04-11T00:00:00+00:00",
                }
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["ingest", str(source), "--base-url", "http://example.test"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Imported 1 documents into Local Workspace" in captured.out
        assert calls[0][:2] == ("GET", cli_main.WORKSPACES_PATH)
        assert calls[1][:2] == ("POST", cli_main.WORKSPACES_PATH)
        assert calls[2][:2] == ("POST", cli_main.IMPORTS_PATH)

    def test_ingest_fails_when_multiple_workspaces_exist_without_selector(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        source = tmp_path / "notes.txt"
        source.write_text("decision: ship Friday", encoding="utf-8")
        workspaces = [
            {"id": str(uuid4()), "name": "Alpha"},
            {"id": str(uuid4()), "name": "Beta"},
        ]

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return workspaces
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["ingest", str(source), "--base-url", "http://example.test"])

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "Multiple workspaces found; pass --workspace NAME_OR_UUID." in err
        assert "Alpha" in err and "Beta" in err

    def test_ingest_creates_named_workspace_when_selector_is_missing_and_none_exist(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        source = tmp_path / "notes.txt"
        source.write_text("decision: ship Friday", encoding="utf-8")
        workspace_id = str(uuid4())
        calls: list[tuple[str, str, dict | None]] = []

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            calls.append((method, path, payload))
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return []
            if method == "POST" and path == cli_main.WORKSPACES_PATH:
                assert payload["name"] == "Research"
                return {"id": workspace_id, "name": "Research"}
            if method == "POST" and path == cli_main.IMPORTS_PATH:
                return {
                    "total_documents": 1,
                    "created_documents": 1,
                    "updated_documents": 0,
                    "unchanged_documents": 0,
                    "processed_documents": 1,
                    "failed_documents": 0,
                    "documents": [],
                }
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(
            ["ingest", str(source), "--workspace", "Research", "--base-url", "http://example.test"],
        )

        assert exit_code == 0
        assert "Imported 1 documents into Research" in capsys.readouterr().out
        assert calls[1][:2] == ("POST", cli_main.WORKSPACES_PATH)

    def test_query_uses_single_workspace_when_unambiguous(self, monkeypatch, capsys):
        workspace_id = str(uuid4())

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return [{"id": workspace_id, "name": "Acme Demo"}]
            if method == "POST" and path == cli_main.QUERY_PATH:
                assert payload["workspace_id"] == workspace_id
                assert payload["question"] == "What changed?"
                return {
                    "question": "What changed?",
                    "answer": "Pricing changed on Wednesday.",
                    "confidence": 0.92,
                    "freshness": "current",
                    "components": [],
                    "sources": [{"type": "local", "url": "file:///tmp/change.md"}],
                    "answeredAt": "2026-04-11T00:00:00+00:00",
                }
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Pricing changed on Wednesday." in captured.out
        assert "workspace: Acme Demo" in captured.out

    def test_query_fails_when_no_workspaces_exist(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli_main,
            "api_request",
            lambda base_url, method, path, **kwargs: [] if path == cli_main.WORKSPACES_PATH else None,
        )

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 1
        assert (
            "No workspaces found. Run 'ctxe demo' for sample data or 'ctxe ingest <path>' to create a workspace."
            in capsys.readouterr().err
        )

    def test_query_fails_when_workspace_selection_is_ambiguous(self, monkeypatch, capsys):
        workspaces = [
            {"id": str(uuid4()), "name": "Alpha"},
            {"id": str(uuid4()), "name": "Beta"},
        ]
        monkeypatch.setattr(
            cli_main,
            "api_request",
            lambda base_url, method, path, **kwargs: workspaces if path == cli_main.WORKSPACES_PATH else None,
        )

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "Multiple workspaces found; pass --workspace NAME_OR_UUID." in err
        assert "Alpha" in err and "Beta" in err

    def test_query_fails_with_available_workspaces_when_named_workspace_is_missing(self, monkeypatch, capsys):
        workspaces = [{"id": str(uuid4()), "name": "Alpha"}]

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return workspaces
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(
            ["query", "What changed?", "--workspace", "Missing", "--base-url", "http://example.test"],
        )

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "Workspace not found: Missing." in err
        assert "Alpha" in err

    def test_query_fails_with_missing_uuid_selector_when_no_workspaces_exist(self, monkeypatch, capsys):
        missing_workspace_id = str(uuid4())

        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return []
            if method == "GET" and path == f"{cli_main.WORKSPACES_PATH}/{missing_workspace_id}":
                raise cli_main.APIError(
                    "GET /api/workspaces/uuid failed with 404: Workspace not found",
                    status_code=404,
                )
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(
            [
                "query",
                "What changed?",
                "--workspace",
                missing_workspace_id,
                "--base-url",
                "http://example.test",
            ],
        )

        assert exit_code == 1
        assert (
            f"Workspace not found: {missing_workspace_id}. No workspaces exist yet."
            in capsys.readouterr().err
        )

    def test_query_rejects_blank_workspace_selector_without_listing_workspaces(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli_main,
            "list_workspaces",
            lambda base_url: (_ for _ in ()).throw(AssertionError("should not list workspaces")),
        )

        exit_code = cli_main.main(
            ["query", "What changed?", "--workspace", "   ", "--base-url", "http://example.test"],
        )

        assert exit_code == 1
        assert "Workspace selector cannot be blank." in capsys.readouterr().err

    def test_query_rejects_malformed_workspace_list(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli_main,
            "api_request",
            lambda base_url, method, path, **kwargs: {"items": []} if path == cli_main.WORKSPACES_PATH else None,
        )

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 1
        assert "GET /api/workspaces returned an unexpected response shape." in capsys.readouterr().err

    def test_query_rejects_malformed_success_response(self, monkeypatch, capsys):
        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return [{"id": str(uuid4()), "name": "Acme Demo"}]
            if method == "POST" and path == cli_main.QUERY_PATH:
                return {"confidence": 0.92, "freshness": "current"}
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 1
        assert "POST /api/query response missing 'answer'." in capsys.readouterr().err

    def test_query_surfaces_api_errors(self, monkeypatch, capsys):
        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return [{"id": str(uuid4()), "name": "Acme Demo"}]
            if method == "POST" and path == cli_main.QUERY_PATH:
                raise cli_main.APIError(
                    "POST /api/query failed with 502: upstream unavailable",
                    status_code=502,
                )
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test"])

        assert exit_code == 1
        assert "POST /api/query failed with 502: upstream unavailable" in capsys.readouterr().err

    def test_query_json_errors_are_machine_readable(self, monkeypatch, capsys):
        def fake_api_request(base_url, method, path, *, payload=None, params=None, timeout=30):
            if method == "GET" and path == cli_main.WORKSPACES_PATH:
                return [{"id": str(uuid4()), "name": "Acme Demo"}]
            if method == "POST" and path == cli_main.QUERY_PATH:
                raise cli_main.APIError(
                    "POST /api/query failed with 502: upstream unavailable",
                    status_code=502,
                )
            raise AssertionError(f"Unexpected API call: {method} {path}")

        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["query", "What changed?", "--base-url", "http://example.test", "--json"])

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "status": "error",
            "detail": "POST /api/query failed with 502: upstream unavailable",
        }
