from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connector, SourceDocument

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_REPO = 100


async def sync_github(connector: Connector, session: AsyncSession) -> dict:
    creds = json.loads(connector.credentials_json or "{}")
    token = creds.get("access_token", "")
    if not token:
        raise ValueError("No GitHub access token found on connector.")

    config = json.loads(connector.config_json or "{}")
    repositories: list[str] = config.get("repositories", [])
    if not repositories:
        logger.warning("GitHub connector has no repositories configured.")
        return {"documents_fetched": 0, "documents_persisted": 0, "errors": []}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    docs_fetched = 0
    docs_persisted = 0
    duplicates_skipped = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30) as http:
        for repo in repositories:
            for item_type, endpoint in [("issue", "issues"), ("pull_request", "pulls")]:
                try:
                    resp = await http.get(
                        f"https://api.github.com/repos/{repo}/{endpoint}",
                        headers=headers,
                        params={
                            "state": "all",
                            "per_page": MAX_ITEMS_PER_REPO,
                            "sort": "updated",
                            "direction": "desc",
                        },
                    )
                    if resp.status_code == 401:
                        raise ValueError("GitHub token is invalid or expired.")
                    if resp.status_code == 403:
                        raise ValueError("GitHub token lacks required permissions.")
                    if resp.status_code == 404:
                        errors.append(f"{repo}: repository not found (404). Check the name and token permissions.")
                        continue
                    resp.raise_for_status()
                    items = resp.json()
                except Exception as exc:
                    errors.append(f"{repo}/{endpoint}: {exc}")
                    continue

                docs_fetched += len(items)
                for item in items:
                    number = item.get("number")
                    external_id = f"github:{repo}:{item_type}:{number}"

                    existing = await session.scalar(
                        select(SourceDocument).where(SourceDocument.external_id == external_id)
                    )
                    if existing:
                        duplicates_skipped += 1
                        continue

                    title = item.get("title", "")
                    body = (item.get("body") or "").strip()
                    state = item.get("state", "open")
                    labels = [label.get("name", "") for label in item.get("labels", [])]
                    merged = item.get("merged_at") is not None
                    author = (item.get("user") or {}).get("login", "")
                    url = item.get("html_url", "")
                    created_at = item.get("created_at")
                    assignees = [a.get("login", "") for a in item.get("assignees", [])]

                    label_str = ", ".join(labels) if labels else "none"
                    status_note = "merged" if merged else state
                    assignee_note = f"\nAssignees: {', '.join(assignees)}" if assignees else ""
                    display_type = "Pull Request" if item_type == "pull_request" else "Issue"

                    content = (
                        f"[{display_type}] #{number}: {title}\n\n"
                        f"State: {status_note}\n"
                        f"Labels: {label_str}"
                        f"{assignee_note}\n\n"
                        f"{body[:4000]}"
                    )

                    doc = SourceDocument(
                        id=uuid4(),
                        source_type="github",
                        external_id=external_id,
                        content=content,
                        author=author,
                        source_url=url,
                        metadata_json=json.dumps({
                            "workspace_id": str(connector.workspace_id),
                            "item_type": item_type,
                            "repo_full_name": repo,
                            "number": number,
                            "title": title,
                            "state": state,
                            "merged": merged,
                            "labels": labels,
                            "assignees": assignees,
                            "created_at": created_at,
                            "source_type": f"github_{item_type}",
                        }),
                    )
                    session.add(doc)
                    docs_persisted += 1

                await session.commit()

    logger.info(
        "GitHub sync complete: %d fetched, %d persisted across %d repos",
        docs_fetched,
        docs_persisted,
        len(repositories),
    )
    return {
        "documents_fetched": docs_fetched,
        "documents_persisted": docs_persisted,
        "documents_skipped": duplicates_skipped,
        "duplicates_skipped": duplicates_skipped,
        "repos_synced": len(repositories),
        "errors": errors,
    }
