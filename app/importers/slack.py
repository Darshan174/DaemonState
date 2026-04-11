"""Slack export importer.

Parses Slack export data in either format:

1. **ZIP export** — Slack's native export produces a ZIP containing a
   directory per channel, with one ``YYYY-MM-DD.json`` file per day.
   Each JSON file is a list of message objects.

2. **Unzipped directory** — the same structure but already extracted.

Thread replies are embedded into the parent message document (same
strategy as the live Slack connector).
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.connectors.base import NormalizedDocument
from app.importers.base import BaseImporter, ImporterError

# Slack message timestamp format: "1704067200.000100"
_TS_RE = re.compile(r"^\d+\.\d+$")


class SlackExportImporter(BaseImporter):
    """Import Slack export ZIP or directory."""

    @classmethod
    def validate_source(cls, source_path: Path) -> tuple[bool, str | None]:
        if not source_path.exists():
            return False, f"Path does not exist: {source_path}"

        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            return True, None

        if source_path.is_dir():
            # Check for at least one JSON file in subdirectories
            json_files = list(source_path.rglob("*.json"))
            if not json_files:
                return False, f"No .json files found in {source_path}"
            return True, None

        return False, f"Slack export must be a .zip file or directory: {source_path}"

    def ingest(
        self,
        source_path: Path,
        *,
        workspace_id: str = "unknown",
        channels: list[str] | None = None,
    ) -> Iterator[NormalizedDocument]:
        """Parse Slack export and yield one document per message.

        Parameters
        ----------
        source_path : Path
            Path to a .zip file or extracted directory.
        workspace_id : str
            Workspace identifier for provenance.
        channels : list[str] | None
            If provided, only import these channel names.
        """
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            yield from self._ingest_zip(source_path, workspace_id, channels=channels)
        elif source_path.is_dir():
            yield from self._ingest_directory(source_path, workspace_id, channels=channels)
        else:
            raise ImporterError(f"Invalid Slack export path: {source_path}")

    # ── ZIP ingestion ──────────────────────────────────────────────────

    def _ingest_zip(
        self,
        zip_path: Path,
        workspace_id: str,
        *,
        channels: list[str] | None,
    ) -> Iterator[NormalizedDocument]:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                channel_dirs = self._list_channel_dirs(zf)
                for channel_name in channel_dirs:
                    if channels and channel_name not in channels:
                        continue
                    messages = self._read_channel_from_zip(zf, channel_name)
                    yield from self._build_documents(
                        messages, channel_name, workspace_id
                    )
        except zipfile.BadZipFile as exc:
            raise ImporterError(f"Invalid ZIP file: {zip_path}: {exc}") from exc
        except OSError as exc:
            raise ImporterError(f"Cannot read ZIP file {zip_path}: {exc}") from exc

    @staticmethod
    def _list_channel_dirs(zf: zipfile.ZipFile) -> list[str]:
        """Extract unique channel directory names from a ZIP."""
        dirs: set[str] = set()
        for name in zf.namelist():
            parts = name.rstrip("/").split("/")
            if len(parts) >= 1 and not name.endswith("/"):
                # Channel dirs are top-level directories containing .json
                pass
        # Better approach: look for directories that contain .json files
        dir_contents: dict[str, list[str]] = {}
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            parts = name.split("/")
            if len(parts) >= 2:
                channel = parts[0]
                dir_contents.setdefault(channel, []).append(parts[-1])

        for channel, files in dir_contents.items():
            if any(f.endswith(".json") for f in files):
                dirs.add(channel)
        return sorted(dirs)

    @staticmethod
    def _read_channel_from_zip(
        zf: zipfile.ZipFile, channel_name: str
    ) -> list[dict[str, Any]]:
        """Read all JSON message files for a channel from a ZIP."""
        messages: list[dict[str, Any]] = []
        prefix = f"{channel_name}/"
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            if not info.filename.endswith(".json"):
                continue
            with zf.open(info.filename) as f:
                raw = f.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw)
                    if isinstance(data, list):
                        messages.extend(data)
                except json.JSONDecodeError:
                    continue
        return messages

    # ── Directory ingestion ────────────────────────────────────────────

    def _ingest_directory(
        self,
        dir_path: Path,
        workspace_id: str,
        *,
        channels: list[str] | None,
    ) -> Iterator[NormalizedDocument]:
        """Walk an extracted Slack export directory."""
        # Top-level entries are channel directories
        for entry in sorted(dir_path.iterdir()):
            if not entry.is_dir():
                continue
            channel_name = entry.name
            if channels and channel_name not in channels:
                continue
            messages = self._read_channel_from_dir(entry)
            yield from self._build_documents(messages, channel_name, workspace_id)

    @staticmethod
    def _read_channel_from_dir(channel_dir: Path) -> list[dict[str, Any]]:
        """Read all JSON message files from a channel directory."""
        messages: list[dict[str, Any]] = []
        for json_file in sorted(channel_dir.glob("*.json")):
            try:
                raw = json_file.read_text(encoding="utf-8", errors="replace")
                data = json.loads(raw)
                if isinstance(data, list):
                    messages.extend(data)
            except (json.JSONDecodeError, OSError):
                continue
        return messages

    # ── Document building ──────────────────────────────────────────────

    def _build_documents(
        self,
        messages: list[dict[str, Any]],
        channel_name: str,
        workspace_id: str,
    ) -> Iterator[NormalizedDocument]:
        """Convert raw Slack messages into NormalizedDocuments.

        Thread replies are embedded into the parent message.
        """
        # Group messages by thread
        parent_map: dict[str, dict[str, Any]] = {}  # ts -> parent msg
        thread_replies: dict[str, list[dict[str, Any]]] = {}  # thread_ts -> replies

        for msg in messages:
            ts = msg.get("ts", "")
            thread_ts = msg.get("thread_ts")
            if thread_ts and thread_ts != ts:
                thread_replies.setdefault(thread_ts, []).append(msg)
            else:
                parent_map[ts] = msg

        # Process each parent message
        for ts, msg in sorted(parent_map.items()):
            doc = self._make_document(msg, channel_name, workspace_id, thread_replies.get(ts, []))
            if doc is not None:
                yield doc

    @staticmethod
    def _make_document(
        msg: dict[str, Any],
        channel_name: str,
        workspace_id: str,
        replies: list[dict[str, Any]],
    ) -> NormalizedDocument | None:
        """Build a NormalizedDocument from a Slack message and its replies."""
        text = (msg.get("text") or "").strip()
        if not text:
            return None

        # Skip system messages
        if msg.get("subtype") in ("channel_join", "channel_leave", "bot_add", "bot_remove"):
            return None

        ts = msg.get("ts", "")
        created_at = _parse_ts(ts)

        # Resolve author
        author = (
            msg.get("username")
            or msg.get("bot_profile", {}).get("name")
            or msg.get("user")
        )

        # Build source URL
        source_url = None
        if ts:
            source_url = f"https://slack.com/archives/{channel_name}/p{ts.replace('.', '')}"

        # Build content with thread replies
        content = text
        metadata: dict[str, Any] = {
            "channel_name": channel_name,
            "source_type": "slack_import",
            "workspace_id": workspace_id,
            "ts": ts,
        }

        if replies:
            reply_lines: list[str] = []
            for reply in replies:
                reply_text = (reply.get("text") or "").strip()
                if not reply_text:
                    continue
                reply_author = (
                    reply.get("username")
                    or reply.get("bot_profile", {}).get("name")
                    or reply.get("user")
                    or "unknown"
                )
                reply_lines.append(f"{reply_author}: {reply_text}")

            if reply_lines:
                content = f"{text}\n\nThread replies:\n" + "\n".join(reply_lines)
                metadata["reply_count"] = len(reply_lines)

        external_id = f"slack-import:{workspace_id}:{channel_name}:{ts}"

        return NormalizedDocument(
            external_id=external_id,
            content=content,
            author=author,
            source_url=source_url,
            created_at=created_at,
            metadata=metadata,
        )


def _parse_ts(ts: str) -> datetime | None:
    """Parse a Slack timestamp string like '1704067200.000100'."""
    if not ts or not _TS_RE.match(ts):
        return None
    try:
        epoch = float(ts)
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, OSError):
        return None
