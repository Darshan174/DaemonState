from __future__ import annotations

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


def test_cli_eval_extraction_runs_local_corpus(capsys):
    assert cli_main.main(["eval", "extraction"]) == 0

    output = capsys.readouterr().out
    assert "extraction:" in output
    assert "local-decision-postgres" in output


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
