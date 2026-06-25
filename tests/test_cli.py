from __future__ import annotations

from app.cli import main as cli_main


def test_cli_ingest_single_file_passes_sync_query(monkeypatch, tmp_path):
    source = tmp_path / "decision.md"
    source.write_text("# Launch\nDecision: ship source-backed CLI ingest.", encoding="utf-8")
    calls = []

    def fake_api_request(base_url, method, path, payload=None, timeout=30):
        calls.append(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": payload,
                "timeout": timeout,
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
        }
    ]


def test_cli_ingest_directory_passes_sync_to_bulk_endpoint(monkeypatch, tmp_path):
    (tmp_path / "one.md").write_text("Decision: keep CLI sync honest.", encoding="utf-8")
    (tmp_path / "two.md").write_text("Task: document the CLI sync path.", encoding="utf-8")
    calls = []

    def fake_api_request(base_url, method, path, payload=None, timeout=30):
        calls.append((base_url, method, path, payload, timeout))
        return {"created": len(payload["documents"])}

    monkeypatch.setattr(cli_main, "api_request", fake_api_request)

    assert cli_main.main(["ingest", str(tmp_path), "--sync", "--base-url", "http://ce.test"]) == 0

    assert len(calls) == 1
    base_url, method, path, payload, timeout = calls[0]
    assert base_url == "http://ce.test"
    assert method == "POST"
    assert path == "/api/sources/bulk?sync=true"
    assert timeout == 30
    assert [doc["content"] for doc in payload["documents"]] == [
        "Decision: keep CLI sync honest.",
        "Task: document the CLI sync path.",
    ]
