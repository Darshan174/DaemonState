from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import app.cli.main as cli_main


class TestCtxeCLI:
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
            None,
        )
        assert calls[2] == (("npm", "test"), frontend_dir, True, None)
        assert calls[3] == (("npm", "run", "build"), frontend_dir, True, None)
        assert "OSS v1 verification passed." in capsys.readouterr().out

    def test_verify_can_skip_frontend_checks(self, monkeypatch, tmp_path):
        project_root = tmp_path / "context-engine"
        project_root.mkdir()
        calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

        monkeypatch.setattr(
            cli_main,
            "boot_stack",
            lambda base_url, *, wait_timeout, quiet=False: project_root,
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
            ((sys.executable, "-m", "pytest", *cli_main.VERIFY_TEST_TARGETS, "-q"), None),
        ]

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
