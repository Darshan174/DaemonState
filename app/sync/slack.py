from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connector, SourceDocument

logger = logging.getLogger(__name__)

MAX_CHANNELS = 20
MAX_MESSAGES_PER_CHANNEL = 200
MAX_THREAD_REPLIES = 100


async def sync_slack(connector: Connector, session: AsyncSession) -> dict:
    creds = json.loads(connector.credentials_json or "{}")
    token = creds.get("access_token", "")
    if not token:
        raise ValueError("No Slack access token found on connector.")

    docs_fetched = 0
    docs_persisted = 0
    duplicates_skipped = 0
    empty_skipped = 0
    filtered_skipped = 0
    channels_synced = 0
    threads_synced = 0
    thread_replies_fetched = 0
    permalink_errors = 0
    errors: list[str] = []

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as http:
        # ── List channels ──────────────────────────────────────────
        resp = await http.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={
                "types": "public_channel",
                "limit": MAX_CHANNELS,
                "exclude_archived": "true",
            },
        )
        channels_data = resp.json()
        if not channels_data.get("ok"):
            raise ValueError(f"Slack conversations.list error: {channels_data.get('error', 'unknown')}")

        channels = channels_data.get("channels", [])
        logger.info("Slack sync: found %d channels", len(channels))

        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel.get("name", channel_id)

            # Try to join the channel (requires channels:join scope).
            # If we already have access (is_member) or join succeeds, proceed.
            is_member = channel.get("is_member", False)
            if not is_member:
                join_resp = await http.post(
                    "https://slack.com/api/conversations.join",
                    headers=headers,
                    json={"channel": channel_id},
                )
                join_data = join_resp.json()
                if join_data.get("ok"):
                    is_member = True
                elif join_data.get("error") in ("method_not_supported_for_channel_type",):
                    # Private channel — skip silently
                    continue
                else:
                    errors.append(f"#{channel_name}: join failed ({join_data.get('error', 'unknown')})")
                    continue

            # ── Fetch message history ──────────────────────────────
            try:
                resp = await http.get(
                    "https://slack.com/api/conversations.history",
                    headers=headers,
                    params={"channel": channel_id, "limit": MAX_MESSAGES_PER_CHANNEL},
                )
                history = resp.json()
            except Exception as exc:
                errors.append(f"#{channel_name}: {exc}")
                continue

            if not history.get("ok"):
                errors.append(f"#{channel_name}: {history.get('error', 'unknown')}")
                continue

            messages = history.get("messages", [])
            docs_fetched += len(messages)
            channels_synced += 1

            for msg in messages:
                result = await _persist_slack_message(
                    msg,
                    connector,
                    session,
                    http,
                    headers,
                    channel_id,
                    channel_name,
                )
                if result == "persisted":
                    docs_persisted += 1
                elif result == "persisted_without_permalink":
                    docs_persisted += 1
                    permalink_errors += 1
                elif result == "duplicate":
                    duplicates_skipped += 1
                elif result == "empty":
                    empty_skipped += 1
                elif result == "filtered":
                    filtered_skipped += 1

                reply_count = int(msg.get("reply_count") or 0)
                if reply_count <= 0:
                    continue

                replies = await _fetch_thread_replies(
                    http,
                    headers,
                    channel_id,
                    channel_name,
                    msg["ts"],
                    errors,
                )
                if replies:
                    threads_synced += 1
                    thread_replies_fetched += len(replies)
                    docs_fetched += len(replies)
                for reply in replies:
                    result = await _persist_slack_message(
                        reply,
                        connector,
                        session,
                        http,
                        headers,
                        channel_id,
                        channel_name,
                        parent_ts=msg["ts"],
                    )
                    if result == "persisted":
                        docs_persisted += 1
                    elif result == "persisted_without_permalink":
                        docs_persisted += 1
                        permalink_errors += 1
                    elif result == "duplicate":
                        duplicates_skipped += 1
                    elif result == "empty":
                        empty_skipped += 1
                    elif result == "filtered":
                        filtered_skipped += 1

            await session.commit()

    logger.info(
        "Slack sync complete: %d fetched, %d persisted across %d channels",
        docs_fetched, docs_persisted, channels_synced,
    )
    return {
        "documents_fetched": docs_fetched,
        "documents_persisted": docs_persisted,
        "documents_skipped": duplicates_skipped + empty_skipped + filtered_skipped,
        "duplicates_skipped": duplicates_skipped,
        "empty_skipped": empty_skipped,
        "filtered_skipped": filtered_skipped,
        "channels_synced": channels_synced,
        "threads_synced": threads_synced,
        "thread_replies_fetched": thread_replies_fetched,
        "permalink_errors": permalink_errors,
        "errors": errors,
    }


async def _persist_slack_message(
    msg: dict,
    connector: Connector,
    session: AsyncSession,
    http: httpx.AsyncClient,
    headers: dict[str, str],
    channel_id: str,
    channel_name: str,
    parent_ts: str | None = None,
) -> str:
    text = (msg.get("text") or "").strip()
    # Skip empty messages, system subtypes (joins, leaves, etc.), and bot messages.
    if not text:
        return "empty"
    if msg.get("subtype") or msg.get("bot_id"):
        return "filtered"

    ts = msg["ts"]
    external_id = f"slack:{channel_id}:{ts}"

    existing = await session.scalar(
        select(SourceDocument).where(SourceDocument.external_id == external_id)
    )
    if existing:
        return "duplicate"

    permalink = await _slack_permalink(http, headers, channel_id, ts)
    permalink_failed = permalink is None
    author_name = _slack_author_name(msg)
    thread_ts = msg.get("thread_ts") or parent_ts or ts
    is_thread_reply = parent_ts is not None or (thread_ts != ts)
    metadata = {
        "workspace_id": str(connector.workspace_id),
        "channel_id": channel_id,
        "channel_name": channel_name,
        "user_id": msg.get("user"),
        "author_name": author_name,
        "ts": ts,
        "thread_ts": thread_ts,
        "parent_ts": parent_ts,
        "is_thread_reply": is_thread_reply,
        "reply_count": msg.get("reply_count", 0),
        "permalink": permalink,
    }
    doc = SourceDocument(
        id=uuid4(),
        source_type="slack",
        external_id=external_id,
        content=text,
        author=author_name or msg.get("user", ""),
        source_url=permalink,
        metadata_json=json.dumps({k: v for k, v in metadata.items() if v is not None}),
    )
    session.add(doc)
    return "persisted_without_permalink" if permalink_failed else "persisted"


async def _fetch_thread_replies(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    channel_id: str,
    channel_name: str,
    parent_ts: str,
    errors: list[str],
) -> list[dict]:
    try:
        resp = await http.get(
            "https://slack.com/api/conversations.replies",
            headers=headers,
            params={"channel": channel_id, "ts": parent_ts, "limit": MAX_THREAD_REPLIES},
        )
        data = resp.json()
    except Exception as exc:
        errors.append(f"#{channel_name}: thread {parent_ts} replies failed ({exc})")
        return []

    if not data.get("ok"):
        errors.append(f"#{channel_name}: thread {parent_ts} replies failed ({data.get('error', 'unknown')})")
        return []

    return [reply for reply in data.get("messages", []) if reply.get("ts") != parent_ts]


async def _slack_permalink(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    channel_id: str,
    ts: str,
) -> str | None:
    try:
        resp = await http.get(
            "https://slack.com/api/chat.getPermalink",
            headers=headers,
            params={"channel": channel_id, "message_ts": ts},
        )
        data = resp.json()
    except Exception:
        return None

    if not data.get("ok"):
        return None
    permalink = data.get("permalink")
    return str(permalink) if permalink else None


def _slack_author_name(msg: dict) -> str:
    profile = msg.get("user_profile") if isinstance(msg.get("user_profile"), dict) else {}
    author = (
        profile.get("real_name")
        or profile.get("display_name")
        or msg.get("username")
    )
    return str(author or "").strip()
