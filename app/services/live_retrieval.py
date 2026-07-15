from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeFile, Connector
from app.services.credentials import load_credentials
from app.services.ingest import IngestionService
from app.services.source_revisions import ingest_source_document_revision


MAX_LIVE_RESULTS = 12
MAX_LOCAL_FILES = 500
MAX_LOCAL_BYTES = 250_000
_SENSITIVE_PATH = re.compile(
    r"(^|/)(?:\.env(?:\.|$)|.*(?:secret|credential|token|private[_-]?key).*)"
    r"|\.(?:pem|key|p12|pfx)$",
    re.IGNORECASE,
)
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "this", "to",
    "what", "when", "where", "which", "with",
}


class LiveRetrievalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LiveRetrievalItem:
    lane: str
    source_identity: str
    title: str
    excerpt: str
    observed_at: str
    source_document_id: str | None = None
    source_url: str | None = None
    provider_updated_at: str | None = None
    path: str | None = None
    line: int | None = None
    sha256: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveRetrievalLane:
    lane: str
    status: str
    observed_at: str
    items: list[LiveRetrievalItem]
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "status": self.status,
            "observed_at": self.observed_at,
            "items": [item.to_dict() for item in self.items],
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


async def retrieve_live_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    question: str,
    sources: list[str],
    repo_path: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    fail_fast: bool = True,
) -> list[LiveRetrievalLane]:
    requested = list(dict.fromkeys(str(item).strip().lower() for item in sources if item))
    if not requested:
        raise LiveRetrievalError(
            "live_source_required",
            "Live retrieval requires at least one explicit source lane.",
        )
    lanes: list[LiveRetrievalLane] = []
    for source in requested:
        try:
            if source not in {"local_repo", "github"}:
                raise LiveRetrievalError(
                    "live_source_unsupported",
                    f"Live retrieval is unsupported for: {source}.",
                )
            if source == "local_repo":
                lane = await _retrieve_local_repo(
                    session,
                    workspace_id=workspace_id,
                    question=question,
                    repo_path=repo_path,
                )
            else:
                lane = await _retrieve_github(
                    session,
                    workspace_id=workspace_id,
                    question=question,
                    http_client=http_client,
                )
            lanes.append(lane)
        except LiveRetrievalError as exc:
            if fail_fast:
                raise
            lanes.append(LiveRetrievalLane(
                lane=source,
                status="error",
                observed_at=_now_iso(),
                items=[],
                error_code=exc.code,
                error_message=str(exc),
            ))
        except Exception as exc:
            wrapped = LiveRetrievalError(
                "live_retrieval_failed",
                f"{source} live retrieval failed before a source result was available.",
            )
            if fail_fast:
                raise wrapped from exc
            lanes.append(LiveRetrievalLane(
                lane=source,
                status="error",
                observed_at=_now_iso(),
                items=[],
                error_code=wrapped.code,
                error_message=str(wrapped),
            ))
    return lanes


async def _retrieve_local_repo(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    question: str,
    repo_path: str | None,
) -> LiveRetrievalLane:
    observed_at = _now_iso()
    rows = list(await session.scalars(
        select(CodeFile)
        .where(CodeFile.workspace_id == workspace_id)
        .order_by(CodeFile.path)
    ))
    roots = sorted({str(item.repo_root) for item in rows if item.repo_root})
    if not roots:
        raise LiveRetrievalError(
            "live_repo_not_indexed",
            "This workspace has no indexed local repository.",
        )
    if len(roots) != 1:
        raise LiveRetrievalError(
            "live_repo_ambiguous",
            "This workspace does not have one active local repository root.",
        )
    root = Path(roots[0]).resolve()
    if repo_path is not None and Path(repo_path).expanduser().resolve() != root:
        raise LiveRetrievalError(
            "live_repo_scope_mismatch",
            "The requested repository is not the workspace's active indexed root.",
        )
    if not root.is_dir():
        raise LiveRetrievalError(
            "live_repo_unavailable",
            "The workspace's indexed local repository is unavailable.",
        )

    query_terms = _query_terms(question)
    if not query_terms:
        raise LiveRetrievalError("live_query_empty", "Live retrieval query has no searchable terms.")
    scored: list[LiveRetrievalItem] = []
    for code_file in rows[:MAX_LOCAL_FILES]:
        relative_path = str(code_file.path or "").replace("\\", "/")
        if _SENSITIVE_PATH.search(relative_path):
            continue
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > MAX_LOCAL_BYTES:
            continue
        current_sha = _sha256(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        match = _best_line_match(text, query_terms)
        path_matches = query_terms & set(_tokens(relative_path))
        if match is None and not path_matches:
            continue
        line_number, excerpt, line_matches = match or (1, relative_path, set())
        matched = path_matches | line_matches
        score = len(path_matches) * 1.5 + len(line_matches)
        scored.append(LiveRetrievalItem(
            lane="local_repo",
            source_identity=f"local_repo:{root}:{relative_path}:{current_sha}",
            title=relative_path,
            excerpt=excerpt,
            observed_at=observed_at,
            path=relative_path,
            line=line_number,
            sha256=current_sha,
            score=round(score + len(matched) * 0.1, 4),
        ))
    scored.sort(key=lambda item: (-item.score, item.path or ""))
    return LiveRetrievalLane(
        lane="local_repo",
        status="checked_live",
        observed_at=observed_at,
        items=scored[:MAX_LIVE_RESULTS],
    )


async def _retrieve_github(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    question: str,
    http_client: httpx.AsyncClient | None,
) -> LiveRetrievalLane:
    observed_at = _now_iso()
    connector = await session.scalar(
        select(Connector)
        .where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type == "github",
        )
        .order_by(Connector.updated_at.desc(), Connector.id.desc())
        .limit(1)
    )
    if connector is None or connector.status != "connected":
        raise LiveRetrievalError(
            "github_connector_disconnected",
            "Live GitHub retrieval requires a connected GitHub connector.",
        )
    config = _json_object(connector.config_json)
    if config.get("auth_mode") != "manual_token":
        raise LiveRetrievalError(
            "github_auth_mode_unsupported",
            "Live GitHub retrieval currently supports manual-token connectors only.",
        )
    repositories = [
        str(item).strip() for item in (config.get("repositories") or []) if str(item).strip()
    ]
    if not repositories:
        raise LiveRetrievalError(
            "github_repository_scope_missing",
            "The GitHub connector has no configured repository scope.",
        )
    token = str(load_credentials(connector.credentials_json).get("access_token") or "")
    if not token:
        raise LiveRetrievalError(
            "github_credentials_missing",
            "The GitHub connector has no usable access token.",
        )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    results: list[LiveRetrievalItem] = []
    try:
        for repository in repositories:
            response = await client.get(
                "https://api.github.com/search/issues",
                headers=headers,
                params={"q": f"{question} repo:{repository}", "per_page": 10},
            )
            if response.status_code == 401:
                raise LiveRetrievalError("github_credentials_expired", "GitHub rejected the access token.")
            if response.status_code == 403:
                raise LiveRetrievalError("github_forbidden", "GitHub denied live search for the configured repository.")
            if response.status_code == 404:
                raise LiveRetrievalError("github_repository_not_found", f"GitHub repository {repository} was not found.")
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise LiveRetrievalError("live_retrieval_failed", f"GitHub live search failed: {exc}") from exc
            payload = response.json()
            for item in payload.get("items", [])[:10]:
                result = await _persist_github_live_item(
                    session,
                    workspace_id=workspace_id,
                    repository=repository,
                    item=item,
                )
                results.append(result)
        await session.flush()
    finally:
        if owns_client:
            await client.aclose()
    results.sort(key=lambda item: (item.provider_updated_at or "", item.title), reverse=True)
    return LiveRetrievalLane(
        lane="github",
        status="checked_live",
        observed_at=observed_at,
        items=results[:MAX_LIVE_RESULTS],
    )


async def _persist_github_live_item(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    repository: str,
    item: dict[str, Any],
) -> LiveRetrievalItem:
    number = item.get("number")
    is_pull_request = bool(item.get("pull_request"))
    item_type = "pull_request" if is_pull_request else "issue"
    title = str(item.get("title") or "")
    body = str(item.get("body") or "").strip()
    state = str(item.get("state") or "unknown")
    updated_at = str(item.get("updated_at") or "") or None
    url = str(item.get("html_url") or "") or None
    content = (
        f"[{'Pull Request' if is_pull_request else 'Issue'}] #{number}: {title}\n\n"
        f"State: {state}\n\n{body[:4000]}"
    )
    if updated_at:
        content += f"\n\nProvider updated at: {updated_at}"
    revision = await ingest_source_document_revision(
        session,
        workspace_id=workspace_id,
        source_type="github",
        external_id=f"github:{repository}:{item_type}:{number}",
        content=content,
        author=str((item.get("user") or {}).get("login") or "") or None,
        source_url=url,
        metadata_json={
            "workspace_id": str(workspace_id),
            "item_type": item_type,
            "repo_full_name": repository,
            "number": number,
            "title": title,
            "state": state,
            "updated_at": updated_at,
            "live_retrieval": True,
        },
        source_created_at=_parse_datetime(updated_at),
        permission_source="github_connector_scope",
    )
    if revision.document.processed_at is None:
        await IngestionService(session).process_document(revision.document.id)
    return LiveRetrievalItem(
        lane="github",
        source_identity=f"github:{repository}:{item_type}:{number}",
        source_document_id=str(revision.document.id),
        title=f"{repository} #{number} · {title}",
        excerpt=body[:500] or f"State: {state}",
        source_url=url,
        observed_at=_now_iso(),
        provider_updated_at=updated_at,
        score=1.0,
    )


def _best_line_match(
    text: str,
    query_terms: set[str],
) -> tuple[int, str, set[str]] | None:
    best: tuple[int, int, str, set[str]] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        matches = query_terms & set(_tokens(line))
        if not matches:
            continue
        candidate = (len(matches), -number, line.strip()[:500], matches)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    return -best[1], best[2], best[3]


def _query_terms(value: str) -> set[str]:
    return {token for token in _tokens(value) if token not in _QUERY_STOPWORDS}


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", str(value or "").lower()) if len(token) > 1]


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)
