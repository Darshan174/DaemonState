"""Tests for the zero-auth importers.

Covers:
- NotionDirectoryImporter
- SlackExportImporter
- GenericFileScanner
- ImportService orchestration
- Import API endpoints

Tests use real filesystem (temp directories) but the DB savepoint pattern
from conftest.py so nothing persists.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.connectors.base import NormalizedDocument
from app.importers.generic import GenericFileScanner
from app.importers.notion import NotionDirectoryImporter
from app.importers.slack import SlackExportImporter
from app.services.import_service import ImportService, ImportStatus, ImportType


# ── NotionDirectoryImporter tests ─────────────────────────────────────


class TestNotionDirectoryImporter:
    def test_validates_directory_with_md_files(self, tmp_path):
        (tmp_path / "page1.md").write_text("# Page 1\n\nContent here")
        ok, err = NotionDirectoryImporter.validate_source(tmp_path)
        assert ok is True
        assert err is None

    def test_validates_nonexistent_path(self, tmp_path):
        bad = tmp_path / "nonexistent"
        ok, err = NotionDirectoryImporter.validate_source(bad)
        assert ok is False
        assert "does not exist" in err

    def test_validates_file_not_directory(self, tmp_path):
        f = tmp_path / "page.md"
        f.write_text("# Page")
        ok, err = NotionDirectoryImporter.validate_source(f)
        assert ok is False
        assert "must be a directory" in err

    def test_validates_no_md_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("just text")
        ok, err = NotionDirectoryImporter.validate_source(tmp_path)
        assert ok is False
        assert "No .md files" in err

    def test_ingests_single_page(self, tmp_path):
        content = "# Engineering Roadmap\n\nWe are targeting Q3 for the SSO launch.\n\n- Adopt SAML over OIDC"
        (tmp_path / "roadmap.md").write_text(content)

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))

        assert len(docs) == 1
        doc = docs[0]
        assert isinstance(doc, NormalizedDocument)
        # Title heading is stripped from content but present in metadata
        assert "SSO launch" in doc.content
        assert doc.metadata["page_title"] == "Engineering Roadmap"
        assert doc.metadata["source_type"] == "notion_import"
        assert doc.metadata["authority_weight"] == 0.95
        assert doc.external_id.startswith("notion-import:ws-1:")

    def test_ingests_nested_directories(self, tmp_path):
        sub = tmp_path / "Engineering" / "Decisions"
        sub.mkdir(parents=True)
        (sub / "decision-1.md").write_text("# Decision: Use Postgres\n\nAgreed in meeting")
        (tmp_path / "index.md").write_text("# Home\n\nWelcome")

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 2
        external_ids = {d.external_id for d in docs}
        assert len(external_ids) == 2

    def test_skips_empty_files(self, tmp_path):
        (tmp_path / "empty.md").write_text("")
        (tmp_path / "whitespace.md").write_text("   \n\n   ")
        (tmp_path / "real.md").write_text("# Real\n\nContent")

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        # Title is stripped from content but in metadata
        assert docs[0].metadata["page_title"] == "Real"

    def test_strips_title_heading_from_content(self, tmp_path):
        content = "# My Title\n\nThe body starts here."
        (tmp_path / "page.md").write_text(content)

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))

        assert len(docs) == 1
        assert "My Title" not in docs[0].content
        assert "body starts here" in docs[0].content

    def test_fallback_title_from_filename(self, tmp_path):
        content = "No heading here, just text."
        (tmp_path / "my-awesome-page.md").write_text(content)

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))

        assert len(docs) == 1
        assert docs[0].metadata["page_title"] == "My Awesome Page"

    def test_handles_encoding_errors(self, tmp_path):
        # Write with invalid UTF-8 bytes
        (tmp_path / "bad.md").write_bytes(b"# Title\n\nHello \xff\xfe world")

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert "Hello" in docs[0].content

    def test_csv_files_are_skipped(self, tmp_path):
        (tmp_path / "database.csv").write_text("id,name\n1,Alice\n2,Bob")
        (tmp_path / "page.md").write_text("# Page\n\nContent")

        importer = NotionDirectoryImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1


# ── SlackExportImporter tests ─────────────────────────────────────────


class TestSlackExportImporter:
    def _create_slack_export_dir(self, tmp_path, channels=None):
        """Create a realistic Slack export directory structure."""
        if channels is None:
            channels = {
                "general": [
                    {
                        "user": "U123",
                        "text": "Welcome to the channel!",
                        "ts": "1704067200.000100",
                        "thread_ts": None,
                    },
                    {
                        "user": "U456",
                        "text": "Thanks for having me!",
                        "ts": "1704067300.000200",
                        "thread_ts": None,
                    },
                ],
                "engineering": [
                    {
                        "user": "U789",
                        "text": "decision: migrate to Postgres 16",
                        "ts": "1704070800.000300",
                        "thread_ts": "1704070800.000300",
                        "reply_count": 2,
                    },
                    {
                        "user": "U123",
                        "text": "I agree with the migration plan",
                        "ts": "1704070900.000400",
                        "thread_ts": "1704070800.000300",
                    },
                    {
                        "user": "U456",
                        "text": "DBA approved",
                        "ts": "1704071000.000500",
                        "thread_ts": "1704070800.000300",
                    },
                ],
            }

        for channel_name, messages in channels.items():
            channel_dir = tmp_path / channel_name
            channel_dir.mkdir()
            # Group by date
            by_date = {}
            for msg in messages:
                ts = msg.get("ts", "")
                if ts:
                    date_str = "2024-01-01"  # All same date for simplicity
                    by_date.setdefault(date_str, []).append(msg)

            for date_str, msgs in by_date.items():
                json_file = channel_dir / f"{date_str}.json"
                json_file.write_text(json.dumps(msgs, indent=2))

        return tmp_path

    def test_validates_directory_with_json_files(self, tmp_path):
        self._create_slack_export_dir(tmp_path)
        ok, err = SlackExportImporter.validate_source(tmp_path)
        assert ok is True
        assert err is None

    def test_validates_zip_file(self, tmp_path):
        zip_path = tmp_path / "export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("general/2024-01-01.json", json.dumps([
                {"user": "U1", "text": "Hello", "ts": "1704067200.000100"}
            ]))
        ok, err = SlackExportImporter.validate_source(zip_path)
        assert ok is True

    def test_validates_nonexistent_path(self, tmp_path):
        ok, err = SlackExportImporter.validate_source(tmp_path / "nonexistent")
        assert ok is False

    def test_ingests_messages_from_directory(self, tmp_path):
        self._create_slack_export_dir(tmp_path)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))

        assert len(docs) >= 2  # At least the two parent messages
        # Thread messages should be embedded, not separate docs
        for doc in docs:
            assert isinstance(doc, NormalizedDocument)
            assert doc.metadata["source_type"] == "slack_import"
            assert doc.metadata["workspace_id"] == "ws-1"

    def test_embeds_thread_replies(self, tmp_path):
        self._create_slack_export_dir(tmp_path)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))

        # Find the engineering thread document
        eng_doc = next(
            (d for d in docs if d.metadata.get("channel_name") == "engineering"),
            None,
        )
        assert eng_doc is not None
        assert "Thread replies:" in eng_doc.content
        assert "I agree" in eng_doc.content
        assert "DBA approved" in eng_doc.content
        assert eng_doc.metadata.get("reply_count") == 2

    def test_skips_empty_messages(self, tmp_path):
        channels = {
            "general": [
                {"user": "U1", "text": "", "ts": "1704067200.000100"},
                {"user": "U1", "text": "   ", "ts": "1704067201.000100"},
                {"user": "U1", "text": "Real message", "ts": "1704067202.000100"},
            ],
        }
        self._create_slack_export_dir(tmp_path, channels=channels)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].content == "Real message"

    def test_skips_system_messages(self, tmp_path):
        channels = {
            "general": [
                {"type": "message", "subtype": "channel_join", "text": "User joined", "ts": "1704067200.000100"},
                {"type": "message", "user": "U1", "text": "Hello!", "ts": "1704067201.000100"},
            ],
        }
        self._create_slack_export_dir(tmp_path, channels=channels)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].content == "Hello!"

    def test_channel_filter(self, tmp_path):
        self._create_slack_export_dir(tmp_path)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1", channels=["general"]))
        for doc in docs:
            assert doc.metadata["channel_name"] == "general"

    def test_ingests_from_zip(self, tmp_path):
        zip_path = tmp_path / "slack-export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("general/2024-01-01.json", json.dumps([
                {
                    "user": "U123",
                    "text": "Hello from ZIP",
                    "ts": "1704067200.000100",
                }
            ]))

        importer = SlackExportImporter()
        docs = list(importer.ingest(zip_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].content == "Hello from ZIP"
        assert docs[0].metadata["channel_name"] == "general"

    def test_handles_malformed_json(self, tmp_path):
        channel_dir = tmp_path / "general"
        channel_dir.mkdir()
        (channel_dir / "2024-01-01.json").write_text("not valid json {{{")
        (channel_dir / "2024-01-02.json").write_text(json.dumps([
            {"user": "U1", "text": "Valid message", "ts": "1704067200.000100"}
        ]))

        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].content == "Valid message"

    def test_handles_bot_messages(self, tmp_path):
        channels = {
            "general": [
                {
                    "bot_id": "B123",
                    "bot_profile": {"name": "GitHub Bot"},
                    "text": "PR #42 merged",
                    "ts": "1704067200.000100",
                },
            ],
        }
        self._create_slack_export_dir(tmp_path, channels=channels)
        importer = SlackExportImporter()
        docs = list(importer.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].author == "GitHub Bot"

    def test_handles_invalid_zip(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip")

        importer = SlackExportImporter()
        with pytest.raises(Exception):  # ImporterError
            list(importer.ingest(bad_zip, workspace_id="ws-1"))


# ── GenericFileScanner tests ──────────────────────────────────────────


class TestGenericFileScanner:
    def test_validates_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Test")
        ok, err = GenericFileScanner.validate_source(f)
        assert ok is True

    def test_validates_directory(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello")
        ok, err = GenericFileScanner.validate_source(tmp_path)
        assert ok is True

    def test_validates_nonexistent(self, tmp_path):
        ok, err = GenericFileScanner.validate_source(tmp_path / "nope")
        assert ok is False

    def test_rejects_binary_extensions(self, tmp_path):
        for ext in (".pdf", ".png", ".docx", ".xlsx", ".zip"):
            f = tmp_path / f"file{ext}"
            f.write_bytes(b"binary")
            ok, err = GenericFileScanner.validate_source(f)
            assert ok is False, f"Should reject {ext}"

    def test_scans_text_file(self, tmp_path):
        content = "# Project Notes\n\nSome important info here."
        f = tmp_path / "notes.md"
        f.write_text(content)

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 1
        assert "Project Notes" in docs[0].content
        assert docs[0].metadata["source_type"] == "file_import"

    def test_scans_directory_with_multiple_files(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "a.txt").write_text("File A")
        (tmp_path / "b.md").write_text("# File B")
        (sub / "c.txt").write_text("File C")
        (tmp_path / "d.pdf").write_bytes(b"binary")  # should be skipped

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 3

    def test_csv_creates_per_row_documents(self, tmp_path):
        csv_content = "name,role,team\nAlice,Engineer,Backend\nBob,Designer,Frontend\n"
        f = tmp_path / "team.csv"
        f.write_text(csv_content)

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 2

        assert "name: Alice" in docs[0].content
        assert "role: Engineer" in docs[0].content
        assert "name: Bob" in docs[1].content

    def test_empty_csv_produces_no_documents(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("")

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 0

    def test_json_array_creates_per_item_documents(self, tmp_path):
        data = [
            {"title": "Item 1", "body": "Content 1"},
            {"title": "Item 2", "body": "Content 2"},
        ]
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 2
        assert "title: Item 1" in docs[0].content
        assert "body: Content 1" in docs[0].content

    def test_jsonl_parsing(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"title": "A", "body": "Body A"}\n{"title": "B", "body": "Body B"}\n')

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 2

    def test_single_json_object(self, tmp_path):
        data = {"title": "Single", "body": "Just one"}
        f = tmp_path / "single.json"
        f.write_text(json.dumps(data))

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 1
        assert "title: Single" in docs[0].content

    def test_html_strips_tags(self, tmp_path):
        html = "<html><head><title>Test Page</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        f = tmp_path / "page.html"
        f.write_text(html)

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 1
        assert "<html>" not in docs[0].content
        assert "Hello" in docs[0].content
        assert "World" in docs[0].content

    def test_hidden_files_are_skipped(self, tmp_path):
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "visible.txt").write_text("visible")

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(tmp_path, workspace_id="ws-1"))
        assert len(docs) == 1
        assert docs[0].content == "visible"

    def test_empty_file_produces_no_document(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")

        scanner = GenericFileScanner()
        docs = list(scanner.ingest(f, workspace_id="ws-1"))
        assert len(docs) == 0

    def test_connector_type_hint_affects_authority_weight(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Content")

        scanner = GenericFileScanner()
        docs_notion = list(scanner.ingest(f, workspace_id="ws-1", connector_type_hint="notion"))
        docs_slack = list(scanner.ingest(f, workspace_id="ws-1", connector_type_hint="slack"))
        docs_generic = list(scanner.ingest(f, workspace_id="ws-1", connector_type_hint="generic"))

        assert docs_notion[0].metadata["authority_weight"] == 0.95
        assert docs_slack[0].metadata["authority_weight"] == 0.75
        assert docs_generic[0].metadata["authority_weight"] == 0.50


# ── ImportService integration tests ───────────────────────────────────


class TestImportService:
    async def test_import_notion_directory(
        self, db_session, workspace
    ):
        """Notion directory import creates connector and SourceDocuments."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page1.md").write_text(
                "# Engineering Roadmap\n\nWe are targeting Q3 for the SSO launch."
            )
            (tmp_path / "page2.md").write_text(
                "# Pricing\n\ndecision: Enterprise starts at $500/seat"
            )

            svc = ImportService(db_session)
            result = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
                run_ingestion=True,
            )

        assert result.status == ImportStatus.COMPLETED
        assert result.documents_imported == 2
        assert result.documents_ingested == 2
        assert result.connector_id is not None
        assert not result.errors

    async def test_import_slack_export(
        self, db_session, workspace
    ):
        """Slack export import creates connector and SourceDocuments."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            general_dir = tmp_path / "general"
            general_dir.mkdir()
            (general_dir / "2024-01-01.json").write_text(json.dumps([
                {
                    "user": "U123",
                    "text": "decision: use FastAPI for the API",
                    "ts": "1704067200.000100",
                },
                {
                    "user": "U456",
                    "text": "blocker: need to migrate DB first",
                    "ts": "1704067300.000200",
                },
            ]))

            svc = ImportService(db_session)
            result = await svc.run_import(
                import_type=ImportType.SLACK_EXPORT,
                source_path=tmp_path,
                workspace_id=workspace.id,
                run_ingestion=True,
            )

        assert result.status == ImportStatus.COMPLETED
        assert result.documents_imported == 2
        assert result.documents_ingested == 2

    async def test_import_generic_file(
        self, db_session, workspace
    ):
        """Generic file import creates SourceDocuments."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "notes.md").write_text(
                "# Meeting Notes\n\ndecision: ship v2 next week\naction item: update docs"
            )

            svc = ImportService(db_session)
            result = await svc.run_import(
                import_type=ImportType.GENERIC_FILE,
                source_path=tmp_path / "notes.md",
                workspace_id=workspace.id,
                run_ingestion=True,
            )

        assert result.status == ImportStatus.COMPLETED
        assert result.documents_imported == 1
        assert result.documents_ingested >= 1  # depends on pattern matching

    async def test_import_without_ingestion(
        self, db_session, workspace
    ):
        """Import can skip ingestion if run_ingestion=False."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page.md").write_text("# Test\n\nContent")

            svc = ImportService(db_session)
            result = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
                run_ingestion=False,
            )

        assert result.status == ImportStatus.COMPLETED
        assert result.documents_imported == 1
        assert result.documents_ingested == 0

    async def test_import_fails_on_nonexistent_path(
        self, db_session, workspace
    ):
        svc = ImportService(db_session)
        result = await svc.run_import(
            import_type=ImportType.NOTION_DIRECTORY,
            source_path=Path("/nonexistent/path"),
            workspace_id=workspace.id,
        )
        assert result.status == ImportStatus.FAILED
        assert "does not exist" in result.error_detail

    async def test_import_reuses_existing_connector(
        self, db_session, workspace
    ):
        """Second import reuses the same manual import connector."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page1.md").write_text("# Page 1\n\nContent 1")

            svc = ImportService(db_session)
            result1 = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
            )
            connector_id_1 = result1.connector_id

            (tmp_path / "page2.md").write_text("# Page 2\n\nContent 2")
            result2 = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
            )
            connector_id_2 = result2.connector_id

        assert connector_id_1 == connector_id_2

    async def test_get_import_connectors(
        self, db_session, workspace
    ):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page.md").write_text("# Test\n\nContent")

            svc = ImportService(db_session)
            await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
            )

        connectors = await svc.get_import_connectors(workspace.id)
        assert len(connectors) == 1
        assert connectors[0].connector_type.value == "notion"
        assert connectors[0].config["import_source"] == "manual"

    async def test_reimport_changed_file_re_runs_ingestion(
        self, db_session, workspace
    ):
        """Re-importing a file whose content changed should re-run ingestion.

        This is a regression test for the bug where _persist_documents
        only counted freshly inserted rows (xmax = 0) and skipped
        ingestion for update-only reimports even though processed_at
        had been reset to None.
        """
        import tempfile
        from app.models.knowledge import Component

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page.md").write_text(
                "# Decision\n\ndecision: use Postgres for storage"
            )

            svc = ImportService(db_session)
            result1 = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
                run_ingestion=True,
            )
            assert result1.documents_ingested >= 1

            # Modify the file content — same title, different decision
            (tmp_path / "page.md").write_text(
                "# Decision\n\ndecision: use MySQL for storage"
            )

            result2 = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
                run_ingestion=True,
            )
            # The key assertion: ingestion must have re-run
            assert result2.documents_ingested >= 1

            # Verify both fact versions exist in the knowledge graph
            components = list(await db_session.scalars(
                select(Component).where(
                    Component.name.like("Decision%"),
                ).order_by(Component.valid_from)
            ))
            # Should have at least 2 component versions (old + new)
            values = {c.value for c in components}
            assert any("Postgres" in v for v in values)
            assert any("MySQL" in v for v in values)

    async def test_get_source_documents_for_connector(
        self, db_session, workspace
    ):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "page.md").write_text("# Test\n\nContent")

            svc = ImportService(db_session)
            result = await svc.run_import(
                import_type=ImportType.NOTION_DIRECTORY,
                source_path=tmp_path,
                workspace_id=workspace.id,
            )

        docs = await svc.get_source_documents_for_connector(result.connector_id)
        assert len(docs) == 1
        assert docs[0].connector_type.value == "notion"


# ── Import API tests ──────────────────────────────────────────────────


class TestImportAPI:
    async def test_validate_import_source(self, client, tmp_path):
        (tmp_path / "page.md").write_text("# Test\n\nContent")
        resp = await client.post("/api/imports/validate", json={
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["error"] is None

    async def test_validate_import_source_invalid(self, client, tmp_path):
        resp = await client.post("/api/imports/validate", json={
            "import_type": "notion_directory",
            "source_path": str(tmp_path / "nonexistent"),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert "does not exist" in body["error"]

    async def test_trigger_notion_import(self, client, workspace, tmp_path):
        (tmp_path / "page.md").write_text(
            "# Engineering Roadmap\n\nWe are targeting Q3 for the SSO launch."
        )
        resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
            "run_ingestion": True,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["documents_imported"] == 1
        assert body["documents_ingested"] == 1

    async def test_trigger_import_requires_absolute_path(self, client, workspace):
        resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "notion_directory",
            "source_path": "relative/path",
        })
        assert resp.status_code == 400
        assert "absolute path" in resp.json()["detail"]

    async def test_trigger_import_missing_workspace_returns_404(self, client, tmp_path):
        """POST /api/imports/trigger with a non-existent workspace_id must return 404.

        Regression test: run_import() previously created the import connector
        before verifying the workspace existed, causing a generic 500 instead
        of a clean 404.
        """
        from uuid import uuid4

        (tmp_path / "page.md").write_text("# Test\n\nContent")
        resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(uuid4()),
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
        })
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_trigger_import_invalid_type(self, client, workspace, tmp_path):
        resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "invalid_type",
            "source_path": str(tmp_path),
        })
        assert resp.status_code == 422  # Pydantic validation error

    async def test_list_import_connectors(self, client, workspace, tmp_path):
        # First create an import
        (tmp_path / "page.md").write_text("# Test\n\nContent")
        await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
        })

        resp = await client.get(
            "/api/imports/connectors",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["connector_type"] == "notion"

    async def test_list_import_documents(self, client, workspace, tmp_path):
        (tmp_path / "page.md").write_text("# Test\n\nContent")
        trigger_resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
        })
        connector_id = trigger_resp.json()["connector_id"]

        resp = await client.get(
            f"/api/imports/connectors/{connector_id}/documents"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["connector_type"] == "notion"

    async def test_list_import_documents_filtered_total(self, client, workspace, tmp_path):
        """Filtered document lists must return correct total counts.

        Regression test: the total count query ignored the processed filter,
        causing pagination metadata to be wrong in filtered views.
        """
        (tmp_path / "page.md").write_text("# Test\n\nContent")
        trigger_resp = await client.post("/api/imports/trigger", json={
            "workspace_id": str(workspace.id),
            "import_type": "notion_directory",
            "source_path": str(tmp_path),
            "run_ingestion": True,
        })
        connector_id = trigger_resp.json()["connector_id"]

        # All documents should be processed after import
        resp = await client.get(
            f"/api/imports/connectors/{connector_id}/documents",
            params={"processed": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1

        # No unprocessed documents after successful ingestion
        resp_unprocessed = await client.get(
            f"/api/imports/connectors/{connector_id}/documents",
            params={"processed": False},
        )
        assert resp_unprocessed.status_code == 200
        body_unprocessed = resp_unprocessed.json()
        assert body_unprocessed["total"] == 0
        assert len(body_unprocessed["items"]) == 0
