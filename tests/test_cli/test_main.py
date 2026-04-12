from __future__ import annotations

from uuid import uuid4

import app.cli.main as cli_main


class TestCtxeCLI:
    def test_demo_seeds_canonical_workspace_via_http_api(self, monkeypatch, capsys):
        calls: list[tuple[str, str, dict | None]] = []

        def fake_run_up(args):
            return 0

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

        monkeypatch.setattr(cli_main, "run_up", fake_run_up)
        monkeypatch.setattr(cli_main, "api_request", fake_api_request)

        exit_code = cli_main.main(["demo", "--base-url", "http://example.test"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Demo workspace ready: Acme Accuracy Demo" in captured.out
        assert calls == [("POST", cli_main.SEED_DEMO_PATH, {})]

    def test_demo_targets_existing_workspace_when_selected(self, monkeypatch, capsys):
        workspace_id = str(uuid4())
        calls: list[tuple[str, str, dict | None]] = []

        def fake_run_up(args):
            return 0

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

        monkeypatch.setattr(cli_main, "run_up", fake_run_up)
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
