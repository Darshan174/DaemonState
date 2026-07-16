from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.cli import main as cli_main


def test_cli_ingest_single_file_passes_sync_query(monkeypatch, tmp_path):
    source = tmp_path / "decision.md"
    source.write_text("# Launch\nDecision: ship source-backed CLI ingest.", encoding="utf-8")
    calls = []

    def fake_api_request(base_url, method, path, payload=None, timeout=30, api_key=None):
        calls.append(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": payload,
                "timeout": timeout,
                "api_key": api_key,
            }
        )
        return {"id": "source-1", "external_id": payload["external_id"]}

    monkeypatch.setattr(cli_main, "api_request", fake_api_request)

    assert cli_main.main(["ingest", str(source), "--sync"]) == 0

    assert calls == [
        {
            "base_url": "http://localhost:8000",
            "method": "POST",
            "path": "/api/sources?sync=true",
            "payload": {
                "source_type": "local",
                "external_id": calls[0]["payload"]["external_id"],
                "content": "# Launch\nDecision: ship source-backed CLI ingest.",
                "author": None,
                "url": source.resolve().as_uri(),
                "metadata": {"title": "Launch", "file_name": "decision.md"},
            },
            "timeout": 30,
            "api_key": None,
        }
    ]


def test_cli_ingest_directory_passes_sync_to_bulk_endpoint(monkeypatch, tmp_path):
    (tmp_path / "one.md").write_text("Decision: keep CLI sync honest.", encoding="utf-8")
    (tmp_path / "two.md").write_text("Task: document the CLI sync path.", encoding="utf-8")
    calls = []

    def fake_api_request(base_url, method, path, payload=None, timeout=30, api_key=None):
        calls.append((base_url, method, path, payload, timeout, api_key))
        return {"created": len(payload["documents"])}

    monkeypatch.setattr(cli_main, "api_request", fake_api_request)

    assert cli_main.main(["ingest", str(tmp_path), "--sync", "--base-url", "http://ce.test"]) == 0

    assert len(calls) == 1
    base_url, method, path, payload, timeout, api_key = calls[0]
    assert base_url == "http://ce.test"
    assert method == "POST"
    assert path == "/api/sources/bulk?sync=true"
    assert timeout == 30
    assert api_key is None
    assert [doc["content"] for doc in payload["documents"]] == [
        "Decision: keep CLI sync honest.",
        "Task: document the CLI sync path.",
    ]


def test_cli_query_uses_context_engine_api_key_env(monkeypatch):
    calls = []

    def fake_api_request(base_url, method, path, payload=None, timeout=30, api_key=None):
        calls.append((base_url, method, path, payload, timeout, api_key))
        return {"answer": "source-backed answer", "confidence": 0.9, "sources": []}

    monkeypatch.setenv("CONTEXT_ENGINE_API_KEY", "server-secret")
    monkeypatch.setattr(cli_main, "api_request", fake_api_request)

    assert cli_main.main(["query", "What changed?"]) == 0

    assert calls == [
        (
            "http://localhost:8000",
            "POST",
            "/api/query",
            {"question": "What changed?"},
            30,
            "server-secret",
        )
    ]


def test_cli_prepare_file_output_only_writes_markdown_and_manifest(tmp_path, capsys):
    (tmp_path / "app.py").write_text("def handler():\n    return True\n", encoding="utf-8")
    out = tmp_path / "AGENT_CONTEXT.md"
    manifest_out = tmp_path / "manifest.json"

    assert cli_main.main([
        "prepare",
        "fix app.py and add tests",
        "--repo",
        str(tmp_path),
        "--target-model",
        "qwen2.5-coder-7b",
        "--budget",
        "2500",
        "--out",
        str(out),
        "--manifest-out",
        str(manifest_out),
        "--file-output-only",
        "--json",
    ]) == 0

    assert out.read_text(encoding="utf-8").startswith("# Objective\n")
    manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "context_pack.v2"
    assert manifest["context_pack_id"] is None
    assert manifest["persistence"]["available"] is False
    assert manifest["persistence"]["mode"] == "file_output_only"
    data = json.loads(capsys.readouterr().out)
    assert data["context_pack_id"] is None
    assert data["markdown_path"] == str(out)


def test_cli_repo_index_no_persist_reports_counts(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "server.js").write_text(
        "import express from 'express';\n"
        "app.get('/health', () => true);\n",
        encoding="utf-8",
    )

    assert cli_main.main(["repo", "index", str(tmp_path), "--no-persist"]) == 0

    output = capsys.readouterr().out
    assert "repo index:" in output
    assert "files=1" in output
    assert "persistence=False" in output


def test_cli_repo_watch_forwards_bounded_options(monkeypatch, tmp_path, capsys):
    workspace_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    captured = {}

    async def fake_watch_repo(args):
        captured.update(vars(args))
        return SimpleNamespace(
            cycles=3,
            changes_detected=2,
            events_created=2,
            last_snapshot_fingerprint="f" * 64,
            stopped_reason="max_cycles",
            to_dict=lambda: {
                "workspace_id": workspace_id,
                "cycles": 3,
                "changes_detected": 2,
                "events_created": 2,
                "last_snapshot_fingerprint": "f" * 64,
                "stopped_reason": "max_cycles",
            },
        )

    monkeypatch.setattr(cli_main, "_watch_repo", fake_watch_repo)

    assert cli_main.main([
        "repo",
        "watch",
        str(tmp_path),
        "--workspace-id",
        workspace_id,
        "--poll-interval",
        "0.25",
        "--debounce",
        "0.1",
        "--max-cycles",
        "3",
    ]) == 0

    assert captured["repo_command"] == "watch"
    assert captured["path"] == str(tmp_path)
    assert captured["workspace_id"] == workspace_id
    assert captured["poll_interval"] == 0.25
    assert captured["debounce"] == 0.1
    assert captured["once"] is False
    assert captured["max_cycles"] == 3
    assert "repo watch complete: cycles=3 changes=2 events_created=2" in (
        capsys.readouterr().out
    )


def test_cli_repo_watch_requires_workspace_id():
    with pytest.raises(SystemExit) as exc:
        cli_main.main(["repo", "watch", ".", "--once"])
    assert exc.value.code == 2


def test_cli_eval_extraction_runs_local_corpus(capsys):
    assert cli_main.main(["eval", "extraction"]) == 0

    output = capsys.readouterr().out
    assert "extraction:" in output
    assert "local-decision-postgres" in output


def test_cli_eval_harness_reports_only_directional_evidence(tmp_path, capsys):
    rows = []
    for label, solved in (
        ("old_alone", False),
        ("old_with_context_engine", True),
        ("new_alone", True),
    ):
        rows.append({
            "task_id": "task-1",
            "label": label,
            "outcome_evidence": {
                "completed": solved,
                "verification_passed": solved,
                "unresolved_blockers": 0,
                "evidence_ids": [f"evidence-{label}"],
            },
        })
    input_path = tmp_path / "harness-eval.json"
    input_path.write_text(json.dumps(rows), encoding="utf-8")

    assert cli_main.main(["eval", "harness", "--input", str(input_path)]) == 0

    output = capsys.readouterr().out
    assert "paired_tasks=1" in output
    assert "claim_status=insufficient_evidence" in output
    assert "old_with_context_engine: solved=1/1" in output


def test_cli_harness_run_forwards_explicit_argv(monkeypatch, capsys):
    captured = {}

    async def fake_run(args, worker_command):
        captured.update(vars(args))
        captured["worker_command"] = worker_command
        return {
            "context_pack_id": "pack-1",
            "run_id": "run-1",
            "status": "completed",
            "changed_files": ["app.py"],
            "verification_results": [],
        }

    monkeypatch.setattr(cli_main, "_run_local_harness", fake_run)

    assert cli_main.main([
        "harness",
        "run",
        "fix app.py",
        "--repo",
        ".",
        "--workspace-id",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "--target-model",
        "qwen2.5-coder-7b",
        "--",
        "worker-bin",
        "--context",
        "{context_file}",
    ]) == 0

    assert captured["worker_command"] == [
        "worker-bin",
        "--context",
        "{context_file}",
    ]
    assert captured["target_model"] == "qwen2.5-coder-7b"
    assert "verification: not executed" in capsys.readouterr().out


def test_cli_harness_run_requires_explicit_worker_command(capsys):
    assert cli_main.main([
        "harness",
        "run",
        "fix app.py",
        "--workspace-id",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    ]) == 1
    assert "provide an explicit worker command" in capsys.readouterr().err


def test_cli_worker_sync_runs_pending_jobs(monkeypatch, capsys):
    class FakeResult:
        def to_dict(self):
            return {
                "scanned": 1,
                "started": 1,
                "completed": 1,
                "failed": 0,
                "retried": 0,
                "dead_lettered": 0,
                "skipped": 0,
                "job_ids": ["job-1"],
            }

    async def fake_run_pending_sync_jobs(
        limit,
        worker_id=None,
        lease_seconds=None,
        retry_base_seconds=None,
        retry_max_seconds=None,
    ):
        assert limit == 3
        assert worker_id == "worker-a"
        assert lease_seconds == 120
        assert retry_base_seconds == 5
        assert retry_max_seconds == 60
        return FakeResult()

    monkeypatch.setattr(
        "app.services.sync_worker.run_pending_sync_jobs",
        fake_run_pending_sync_jobs,
    )

    assert cli_main.main([
        "worker",
        "sync",
        "--limit",
        "3",
        "--worker-id",
        "worker-a",
        "--lease-seconds",
        "120",
        "--retry-base-seconds",
        "5",
        "--retry-max-seconds",
        "60",
    ]) == 0

    output = capsys.readouterr().out
    assert "sync worker:" in output
    assert "completed=1" in output
    assert "dead_lettered=0" in output


def test_cli_db_upgrade_invokes_alembic(monkeypatch, capsys):
    calls = []

    def fake_run_alembic_command(name, config, revision=None):
        calls.append((name, config.get_main_option("sqlalchemy.url"), revision))

    monkeypatch.setattr(cli_main, "_run_alembic_command", fake_run_alembic_command)

    assert cli_main.main([
        "db",
        "upgrade",
        "head",
        "--database-url",
        "sqlite+aiosqlite:////tmp/context-engine-test.db",
    ]) == 0

    assert calls == [
        ("upgrade", "sqlite+aiosqlite:////tmp/context-engine-test.db", "head")
    ]
    assert "database upgraded to head" in capsys.readouterr().out


def test_cli_db_stamp_head_invokes_alembic(monkeypatch, capsys):
    calls = []

    def fake_run_alembic_command(name, config, revision=None):
        calls.append((name, config.get_main_option("sqlalchemy.url"), revision))

    monkeypatch.setattr(cli_main, "_run_alembic_command", fake_run_alembic_command)

    assert cli_main.main(["db", "stamp-head"]) == 0

    assert calls == [("stamp", "sqlite+aiosqlite:///data/context.db", "head")]
    assert "database stamped at head" in capsys.readouterr().out


def test_cli_credentials_rotate_invokes_database_rotation(monkeypatch, capsys):
    calls = []

    async def fake_rotate_stored_credentials(database_url=None):
        calls.append(database_url)
        return {"scanned": 2, "updated": 1, "encrypted": 2}

    monkeypatch.setattr(
        cli_main,
        "_rotate_stored_credentials",
        fake_rotate_stored_credentials,
    )

    assert cli_main.main([
        "credentials",
        "rotate",
        "--database-url",
        "sqlite+aiosqlite:////tmp/context-engine-test.db",
    ]) == 0

    assert calls == ["sqlite+aiosqlite:////tmp/context-engine-test.db"]
    output = capsys.readouterr().out
    assert "credentials rotated:" in output
    assert "updated=1" in output
