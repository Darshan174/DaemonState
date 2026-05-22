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


async def sync_slack(connector: Connector, session: AsyncSession) -> dict:
    creds = json.loads(connector.credentials_json or "{}")
    token = creds.get("access_token", "")
    if not token:
        raise ValueError("No Slack access token found on connector.")

    docs_fetched = 0
    docs_persisted = 0
    channels_synced = 0
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
                text = (msg.get("text") or "").strip()
                # Skip empty messages, system subtypes (joins, leaves, etc.), and bot messages
                if not text or msg.get("subtype") or msg.get("bot_id"):
                    continue

                external_id = f"slack:{channel_id}:{msg['ts']}"

                # Skip if already ingested
                existing = await session.scalar(
                    select(SourceDocument).where(SourceDocument.external_id == external_id)
                )
                if existing:
                    continue

                doc = SourceDocument(
                    id=uuid4(),
                    source_type="slack",
                    external_id=external_id,
                    content=text,
                    author=msg.get("user", ""),
                    source_url=None,
                    metadata_json=json.dumps({
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "ts": msg["ts"],
                        "thread_ts": msg.get("thread_ts"),
                        "reply_count": msg.get("reply_count", 0),
                    }),
                )
                session.add(doc)
                docs_persisted += 1

            await session.commit()

    logger.info(
        "Slack sync complete: %d fetched, %d persisted across %d channels",
        docs_fetched, docs_persisted, channels_synced,
    )
    return {
        "documents_fetched": docs_fetched,
        "documents_persisted": docs_persisted,
        "channels_synced": channels_synced,
        "errors": errors,
    }
