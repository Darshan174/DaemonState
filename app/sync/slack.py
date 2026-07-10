from __future__ import annotations

import logging
import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connector
from app.services.credentials import load_credentials
from app.services.source_revisions import ingest_source_document_revision

logger = logging.getLogger(__name__)

MAX_CHANNELS = 20
MAX_MESSAGES_PER_CHANNEL = 200
MAX_THREAD_REPLIES = 100
MAX_SLACK_PAGES = 10
MAX_SLACK_RETRIES = 2
SLACK_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


async def sync_slack(connector: Connector, session: AsyncSession) -> dict:
    creds = load_credentials(connector.credentials_json)
    token = creds.get("access_token", "")
    if not token:
        raise ValueError("No Slack access token found on connector.")

    docs_fetched = 0
    docs_persisted = 0
    documents_revised = 0
    duplicates_skipped = 0
    empty_skipped = 0
    filtered_skipped = 0
    channels_synced = 0
    threads_synced = 0
    thread_replies_fetched = 0
    permalink_errors = 0
    pages_fetched = 0
    retry_count = 0
    rate_limit_retries = 0
    scope_limited_channels = 0
    partial_failures = 0
    errors: list[str] = []

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as http:
        channels, list_stats = await _slack_paginated_get(
            http,
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={"types": "public_channel", "limit": MAX_CHANNELS, "exclude_archived": "true"},
            item_key="channels",
            context="conversations.list",
        )
        pages_fetched += list_stats["pages_fetched"]
        retry_count += list_stats["retries"]
        rate_limit_retries += list_stats["rate_limit_retries"]
        if list_stats["scope_limited"]:
            scope_limited_channels += 1
            errors.append("Slack channel list skipped due to missing scope or unavailable channels")
        if list_stats["partial_failure"]:
            partial_failures += 1

        logger.info("Slack sync: found %d channels", len(channels))

        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel.get("name", channel_id)

            # Try to join the channel (requires channels:join scope).
            # If we already have access (is_member) or join succeeds, proceed.
            is_member = channel.get("is_member", False)
            if not is_member:
                join_resp, join_stats = await _slack_request_with_retries(
                    http,
                    "POST",
                    "https://slack.com/api/conversations.join",
                    headers=headers,
                    json={"channel": channel_id},
                )
                retry_count += join_stats["retries"]
                rate_limit_retries += join_stats["rate_limit_retries"]
                join_data = join_resp.json()
                if join_data.get("ok"):
                    is_member = True
                elif join_data.get("error") in ("method_not_supported_for_channel_type",):
                    # Private channel — skip silently
                    scope_limited_channels += 1
                    continue
                else:
                    partial_failures += 1
                    errors.append(f"#{channel_name}: join failed ({join_data.get('error', 'unknown')})")
                    continue

            try:
                messages, history_stats = await _slack_paginated_get(
                    http,
                    "https://slack.com/api/conversations.history",
                    headers=headers,
                    params={"channel": channel_id, "limit": MAX_MESSAGES_PER_CHANNEL},
                    item_key="messages",
                    context=f"#{channel_name}: history",
                )
            except Exception as exc:
                partial_failures += 1
                errors.append(f"#{channel_name}: {exc}")
                continue

            pages_fetched += history_stats["pages_fetched"]
            retry_count += history_stats["retries"]
            rate_limit_retries += history_stats["rate_limit_retries"]
            if history_stats["scope_limited"]:
                scope_limited_channels += 1
                errors.append(f"#{channel_name}: history skipped due to Slack scope limits")
                continue
            if history_stats["partial_failure"]:
                partial_failures += 1
                errors.append(f"#{channel_name}: history partially synced before a Slack API error")
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
                elif result == "revised":
                    docs_persisted += 1
                    documents_revised += 1
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
                reply_messages, reply_stats = replies
                pages_fetched += reply_stats["pages_fetched"]
                retry_count += reply_stats["retries"]
                rate_limit_retries += reply_stats["rate_limit_retries"]
                if reply_stats["partial_failure"]:
                    partial_failures += 1
                if reply_stats["scope_limited"]:
                    scope_limited_channels += 1
                if reply_messages:
                    threads_synced += 1
                    thread_replies_fetched += len(reply_messages)
                    docs_fetched += len(reply_messages)
                for reply in reply_messages:
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
                    elif result == "revised":
                        docs_persisted += 1
                        documents_revised += 1
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
        "documents_revised": documents_revised,
        "empty_skipped": empty_skipped,
        "filtered_skipped": filtered_skipped,
        "channels_synced": channels_synced,
        "threads_synced": threads_synced,
        "thread_replies_fetched": thread_replies_fetched,
        "permalink_errors": permalink_errors,
        "pages_fetched": pages_fetched,
        "retry_count": retry_count,
        "rate_limit_retries": rate_limit_retries,
        "scope_limited_channels": scope_limited_channels,
        "partial_failures": partial_failures,
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
    result = await ingest_source_document_revision(
        session,
        workspace_id=connector.workspace_id,
        source_type="slack",
        external_id=external_id,
        content=text,
        author=author_name or msg.get("user", ""),
        source_url=permalink,
        metadata_json={k: v for k, v in metadata.items() if v is not None},
    )
    if result.unchanged:
        return "duplicate"
    if result.revised:
        return "revised"
    return "persisted_without_permalink" if permalink_failed else "persisted"


async def _fetch_thread_replies(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    channel_id: str,
    channel_name: str,
    parent_ts: str,
    errors: list[str],
) -> tuple[list[dict], dict[str, int | bool]]:
    empty_stats = {
        "pages_fetched": 0,
        "retries": 0,
        "rate_limit_retries": 0,
        "partial_failure": False,
        "scope_limited": False,
    }
    try:
        messages, stats = await _slack_paginated_get(
            http,
            "https://slack.com/api/conversations.replies",
            headers=headers,
            params={"channel": channel_id, "ts": parent_ts, "limit": MAX_THREAD_REPLIES},
            item_key="messages",
            context=f"#{channel_name}: thread {parent_ts}",
        )
    except Exception as exc:
        empty_stats["partial_failure"] = True
        errors.append(f"#{channel_name}: thread {parent_ts} replies failed ({exc})")
        return [], empty_stats

    scope_limited = stats.pop("scope_limited", False)
    partial_failure = stats.pop("partial_failure", False)
    stats["partial_failure"] = partial_failure
    stats["scope_limited"] = scope_limited
    if scope_limited:
        errors.append(f"#{channel_name}: thread {parent_ts} replies skipped due to Slack scope limits")
    elif partial_failure:
        errors.append(f"#{channel_name}: thread {parent_ts} replies failed")

    return [reply for reply in messages if reply.get("ts") != parent_ts], stats


async def _slack_permalink(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    channel_id: str,
    ts: str,
) -> str | None:
    try:
        resp, _stats = await _slack_request_with_retries(
            http,
            "GET",
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


async def _slack_paginated_get(
    http: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    params: dict,
    item_key: str,
    context: str,
) -> tuple[list[dict], dict[str, int | bool]]:
    items: list[dict] = []
    cursor = ""
    stats: dict[str, int | bool] = {
        "pages_fetched": 0,
        "retries": 0,
        "rate_limit_retries": 0,
        "partial_failure": False,
        "scope_limited": False,
    }

    for _page in range(MAX_SLACK_PAGES):
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        resp, request_stats = await _slack_request_with_retries(
            http,
            "GET",
            url,
            headers=headers,
            params=page_params,
        )
        stats["retries"] += request_stats["retries"]
        stats["rate_limit_retries"] += request_stats["rate_limit_retries"]
        if resp.status_code != 200:
            stats["partial_failure"] = True
            if not items:
                raise ValueError(f"Slack {context} HTTP {resp.status_code}")
            return items, stats
        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown")
            if error in {"missing_scope", "not_in_channel", "channel_not_found", "is_archived"}:
                stats["scope_limited"] = True
                return items, stats
            stats["partial_failure"] = True
            if not items:
                raise ValueError(f"Slack {context} error: {error}")
            return items, stats

        stats["pages_fetched"] += 1
        items.extend(data.get(item_key, []))
        cursor = str(data.get("response_metadata", {}).get("next_cursor") or "")
        if not cursor:
            return items, stats

    stats["partial_failure"] = bool(cursor)
    return items, stats


async def _slack_request_with_retries(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> tuple[httpx.Response, dict[str, int]]:
    retries = 0
    rate_limit_retries = 0
    response: httpx.Response | None = None
    for attempt in range(MAX_SLACK_RETRIES + 1):
        response = await _perform_http_request(http, method, url, **kwargs)
        if response.status_code not in SLACK_RETRYABLE_STATUS_CODES:
            return response, {"retries": retries, "rate_limit_retries": rate_limit_retries}
        if attempt >= MAX_SLACK_RETRIES:
            return response, {"retries": retries, "rate_limit_retries": rate_limit_retries}
        retries += 1
        if response.status_code == 429:
            rate_limit_retries += 1
        retry_after = _retry_after_seconds(response)
        if retry_after > 0:
            await asyncio.sleep(retry_after)
    assert response is not None
    return response, {"retries": retries, "rate_limit_retries": rate_limit_retries}


async def _perform_http_request(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    request = getattr(http, "request", None)
    if callable(request):
        return await request(method, url, **kwargs)
    if method.upper() == "POST":
        return await http.post(url, **kwargs)
    return await http.get(url, **kwargs)


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    try:
        return min(max(float(raw or 0), 0.0), 2.0)
    except (TypeError, ValueError):
        return 0.0


def _slack_author_name(msg: dict) -> str:
    profile = msg.get("user_profile") if isinstance(msg.get("user_profile"), dict) else {}
    author = (
        profile.get("real_name")
        or profile.get("display_name")
        or msg.get("username")
    )
    return str(author or "").strip()
