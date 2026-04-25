"""Service layer for connector management."""

from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from base64 import b64encode
from typing import TYPE_CHECKING
from uuid import UUID
from urllib.parse import urlencode

import httpx
from redis import asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.connector import Connector, ConnectorStatus
from app.models.source import ConnectorType, SourceDocument
from app.services.ingestion_service import IngestionService
from app.models.user import Workspace
from app.utils.crypto import EncryptionError, decrypt_token, encrypt_token

if TYPE_CHECKING:
    from app.models.job import SyncJob


class ConnectorServiceError(Exception):
    """Base connector service error."""


class ConnectorNotFoundError(ConnectorServiceError):
    """Raised when a requested connector is not present."""


class WorkspaceNotFoundError(ConnectorServiceError):
    """Raised when the referenced workspace does not exist."""


class ConfigurationError(ConnectorServiceError):
    """Raised when required configuration (env vars) is missing."""


class OAuthError(ConnectorServiceError):
    """Raised when an OAuth exchange fails."""


class InvalidStateError(ConnectorServiceError):
    """Raised when the OAuth state parameter is invalid or expired."""


class SyncError(ConnectorServiceError):
    """Raised when a sync operation fails."""


class SyncInProgressError(ConnectorServiceError):
    """Raised when a sync is already running for this connector."""

    def __init__(self, job_id: UUID) -> None:
        super().__init__(f"Sync already in progress. Job ID: {job_id}")
        self.job_id = job_id


class WebhookVerificationError(ConnectorServiceError):
    """Raised when a webhook request cannot be verified."""


# Redis key prefix for OAuth state nonces
_STATE_PREFIX = "ce:oauth_state:"


class ConnectorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── List / get / sync / disconnect (unchanged) ─────────────────

    async def list_connectors(self, workspace_id: UUID) -> list[Connector]:
        await self._require_workspace(workspace_id)
        result = await self.session.scalars(
            select(Connector)
            .where(Connector.workspace_id == workspace_id)
            .order_by(Connector.connector_type)
        )
        return list(result)

    async def get_connector(self, connector_id: UUID) -> Connector:
        connector = await self.session.scalar(
            select(Connector).where(Connector.id == connector_id)
        )
        if connector is None:
            raise ConnectorNotFoundError("Connector not found")
        return connector

    async def queue_sync(self, connector_id: UUID) -> "SyncJob":
        """Dispatch a background sync job for the given connector.

        Validates connector state, creates a SyncJob, dispatches to Celery,
        and returns immediately with the pending job.  The pipeline runs
        asynchronously in the worker process.
        """
        from app.models.job import SyncJob, SyncJobStatus

        connector = await self.get_connector(connector_id)

        if connector.status != ConnectorStatus.CONNECTED:
            raise SyncError("Connector is not in a connected state")

        if not connector.oauth_token_encrypted:
            raise SyncError("Connector has no stored auth token")

        try:
            decrypt_token(connector.oauth_token_encrypted)  # validate decryptable now
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        # Guard against double-dispatch
        existing = await self.session.scalar(
            select(SyncJob).where(
                SyncJob.connector_id == connector_id,
                SyncJob.status.in_([SyncJobStatus.PENDING, SyncJobStatus.RUNNING]),
            )
        )
        if existing is not None:
            raise SyncInProgressError(existing.id)

        job = SyncJob(
            connector_id=connector_id,
            job_type="sync",
            status=SyncJobStatus.PENDING,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)

        # Dispatch to Celery.  Store any exception so we can commit the FAILED
        # state OUTSIDE the except block — inside an except block, Python 3.13's
        # asyncio/greenlet interaction prevents a successful session.commit().
        dispatch_exc: Exception | None = None
        try:
            from app.tasks.sync import run_sync
            task_result = run_sync.delay(str(job.id), str(connector_id))
            job.celery_task_id = task_result.id
            connector.config = {
                **connector.config,
                "sync_queued_at": datetime.now(timezone.utc).isoformat(),
                "message": "Sync queued",
            }
        except Exception as exc:
            dispatch_exc = exc

        if dispatch_exc is not None:
            # No dirty session state — dispatch failed before any mutations.
            # Just update the job and commit the FAILED status directly.
            job.status = SyncJobStatus.FAILED
            job.error_type = "DispatchError"
            job.error_message = str(dispatch_exc)
            await self.session.commit()
            raise SyncError(f"Failed to dispatch sync task: {dispatch_exc}") from dispatch_exc

        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_latest_sync_job(self, connector_id: UUID):
        """Return the most recent SyncJob for this connector, or None."""
        from app.models.job import SyncJob
        await self.get_connector(connector_id)  # raises ConnectorNotFoundError if missing
        return await self.session.scalar(
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )

    async def list_sync_jobs(self, connector_id: UUID, limit: int = 20):
        """Return recent SyncJobs for this connector, most recent first."""
        from app.models.job import SyncJob
        await self.get_connector(connector_id)  # raises ConnectorNotFoundError if missing
        result = await self.session.scalars(
            select(SyncJob)
            .where(SyncJob.connector_id == connector_id)
            .order_by(SyncJob.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def disconnect(self, connector_id: UUID) -> None:
        connector = await self.get_connector(connector_id)
        connector.status = ConnectorStatus.DISCONNECTED
        connector.oauth_token_encrypted = None
        connector.refresh_token_encrypted = None
        await self.session.commit()

    # ── Notion manual connect ─────────────────────────────────────

    async def connect_notion(
        self, *, workspace_id: UUID, token: str
    ) -> Connector:
        """Create or update a Notion connector with the given integration token."""
        await self._require_workspace(workspace_id)

        try:
            encrypted = encrypt_token(token)
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        connector = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == ConnectorType.NOTION,
            )
        )

        if connector is None:
            connector = Connector(
                workspace_id=workspace_id,
                connector_type=ConnectorType.NOTION,
                status=ConnectorStatus.CONNECTED,
                oauth_token_encrypted=encrypted,
                config={},
            )
            self.session.add(connector)
        else:
            connector.status = ConnectorStatus.CONNECTED
            connector.oauth_token_encrypted = encrypted

        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def connect_zoom(
        self, *, workspace_id: UUID, token: str
    ) -> Connector:
        """Create or update a Zoom connector with the given access token."""
        await self._require_workspace(workspace_id)

        try:
            encrypted = encrypt_token(token)
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        connector = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == ConnectorType.ZOOM,
            )
        )

        base_config = {
            "ingestion_mode": "transcripts_only",
            "source_focus": "meeting_transcripts",
            "auth_mode": "manual_token",
            "sync_delivery_mode": "polling_only",
            "webhook_auto_sync": False,
            "requires_oauth_for_webhooks": True,
        }

        if connector is None:
            connector = Connector(
                workspace_id=workspace_id,
                connector_type=ConnectorType.ZOOM,
                status=ConnectorStatus.CONNECTED,
                oauth_token_encrypted=encrypted,
                config=base_config,
            )
            self.session.add(connector)
        else:
            connector.status = ConnectorStatus.CONNECTED
            connector.oauth_token_encrypted = encrypted
            connector.refresh_token_encrypted = None
            connector.config = {
                **self._strip_zoom_oauth_config(connector.config),
                **base_config,
            }

        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def connect_github(
        self,
        *,
        workspace_id: UUID,
        token: str,
        repositories: list[str],
    ) -> Connector:
        """Create or update a GitHub connector with a manual access token."""
        await self._require_workspace(workspace_id)

        try:
            encrypted = encrypt_token(token)
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        connector = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == ConnectorType.GITHUB,
            )
        )

        base_config = {
            "ingestion_mode": "issues_pull_requests_reviews_comments",
            "source_focus": "engineering_system_of_record",
            "auth_mode": "manual_token",
            "sync_delivery_mode": "polling_only",
            "webhook_auto_sync": False,
            "repositories": repositories,
        }

        if connector is None:
            connector = Connector(
                workspace_id=workspace_id,
                connector_type=ConnectorType.GITHUB,
                status=ConnectorStatus.CONNECTED,
                oauth_token_encrypted=encrypted,
                config=base_config,
            )
            self.session.add(connector)
        else:
            connector.status = ConnectorStatus.CONNECTED
            connector.oauth_token_encrypted = encrypted
            connector.refresh_token_encrypted = None
            connector.config = {
                **connector.config,
                **base_config,
            }

        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def build_zoom_install_url(self, workspace_id: UUID) -> str:
        self._require_zoom_oauth_config()
        await self._require_workspace(workspace_id)

        nonce = secrets.token_urlsafe(24)
        state = f"{workspace_id}:{nonce}"

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.setex(
                f"{_STATE_PREFIX}{state}",
                settings.oauth_state_ttl_seconds,
                str(workspace_id),
            )
        finally:
            await redis.aclose()

        redirect_uri = settings.zoom_redirect_uri or ""
        params = {
            "response_type": "code",
            "client_id": settings.zoom_client_id,
            "state": state,
        }
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        return f"{settings.zoom_oauth_base_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"

    async def handle_zoom_callback(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> Connector:
        if error:
            raise OAuthError(f"Zoom returned an error: {error}")
        if not state:
            raise InvalidStateError("Missing OAuth state parameter")
        if not code:
            raise OAuthError("Missing authorization code from Zoom")

        workspace_id = await self._validate_and_consume_state(state)
        token_data = await self._exchange_zoom_code(code)
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthError("Zoom token exchange did not return an access token")

        try:
            encrypted = encrypt_token(access_token)
            encrypted_refresh = (
                encrypt_token(token_data["refresh_token"])
                if token_data.get("refresh_token")
                else None
            )
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        connector = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == ConnectorType.ZOOM,
            )
        )

        oauth_meta = {
            "ingestion_mode": "transcripts_only",
            "source_focus": "meeting_transcripts",
            "auth_mode": "oauth",
            "sync_delivery_mode": "webhook_auto_sync",
            "webhook_auto_sync": True,
            "requires_oauth_for_webhooks": True,
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type"),
            "account_id": token_data.get("account_id"),
        }
        oauth_meta.update(
            self._zoom_expiry_metadata(token_data.get("expires_in"))
        )

        if connector is None:
            connector = Connector(
                workspace_id=workspace_id,
                connector_type=ConnectorType.ZOOM,
                status=ConnectorStatus.CONNECTED,
                oauth_token_encrypted=encrypted,
                refresh_token_encrypted=encrypted_refresh,
                config=oauth_meta,
            )
            self.session.add(connector)
        else:
            connector.status = ConnectorStatus.CONNECTED
            connector.oauth_token_encrypted = encrypted
            connector.refresh_token_encrypted = encrypted_refresh
            connector.config = {**connector.config, **oauth_meta}

        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    async def get_access_token_for_connector(self, connector: Connector) -> str:
        if connector.oauth_token_encrypted is None:
            raise ConfigurationError("Connector has no stored auth token")

        token = decrypt_token(connector.oauth_token_encrypted)
        if connector.connector_type != ConnectorType.ZOOM:
            return token

        expires_at = connector.config.get("access_token_expires_at")
        if (
            not connector.refresh_token_encrypted
            or not expires_at
            or not self._is_expired_or_expiring_soon(expires_at)
        ):
            return token

        refresh_token = decrypt_token(connector.refresh_token_encrypted)
        token_data = await self._refresh_zoom_access_token(refresh_token)
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthError("Zoom refresh did not return an access token")

        connector.oauth_token_encrypted = encrypt_token(access_token)
        if token_data.get("refresh_token"):
            connector.refresh_token_encrypted = encrypt_token(token_data["refresh_token"])
        connector.config = {
            **connector.config,
            **self._zoom_expiry_metadata(token_data.get("expires_in")),
            "scope": token_data.get("scope", connector.config.get("scope")),
            "token_type": token_data.get("token_type", connector.config.get("token_type")),
            "auth_mode": connector.config.get("auth_mode", "oauth"),
            "sync_delivery_mode": "webhook_auto_sync",
            "webhook_auto_sync": True,
            "requires_oauth_for_webhooks": True,
        }
        await self.session.flush()
        return access_token

    async def handle_zoom_webhook(
        self,
        *,
        payload: dict,
        raw_body: bytes,
        signature: str | None,
        request_timestamp: str | None,
    ) -> dict[str, object]:
        self.verify_zoom_webhook_signature(
            raw_body=raw_body,
            signature=signature,
            request_timestamp=request_timestamp,
        )
        event = payload.get("event")
        if event == "endpoint.url_validation":
            plain_token = ((payload.get("payload") or {}).get("plainToken"))
            if not plain_token:
                raise OAuthError("Zoom webhook validation payload is missing plainToken")
            if not settings.zoom_webhook_secret:
                raise ConfigurationError(
                    "Zoom webhook validation is not configured. "
                    "Set ZOOM_WEBHOOK_SECRET."
                )
            encrypted = hmac.new(
                settings.zoom_webhook_secret.encode(),
                plain_token.encode(),
                hashlib.sha256,
            ).hexdigest()
            return {"plainToken": plain_token, "encryptedToken": encrypted}

        queued_connector_ids: list[str] = []
        queued_job_ids: list[str] = []
        skipped_connector_ids: list[str] = []
        reconciled_document_ids: list[str] = []
        account_id = self._zoom_payload_account_id(payload)

        if self._should_reconcile_zoom_deletion(str(event or "")) and account_id:
            reconciled_document_ids = await self._reconcile_zoom_deletion_event(
                payload=payload,
                account_id=account_id,
                event=str(event or ""),
            )
        elif self._should_queue_zoom_sync(str(event or "")) and account_id:
            received_at = datetime.now(timezone.utc).isoformat()
            for connector in await self._load_zoom_webhook_connectors(account_id):
                connector.config = {
                    **connector.config,
                    "last_zoom_webhook_event": event,
                    "last_zoom_webhook_received_at": received_at,
                }
                try:
                    job = await self.queue_sync(connector.id)
                except (SyncInProgressError, SyncError, ConfigurationError, OAuthError):
                    skipped_connector_ids.append(str(connector.id))
                    continue

                job.result_metadata = {
                    **(job.result_metadata or {}),
                    "trigger": "zoom_webhook",
                    "webhook_event": event,
                    "webhook_event_ts": payload.get("event_ts"),
                    "zoom_account_id": account_id,
                }
                queued_connector_ids.append(str(connector.id))
                queued_job_ids.append(str(job.id))

            await self.session.commit()

        return {
            "accepted": True,
            "event": event,
            "queued_count": len(queued_job_ids),
            "queued_connector_ids": queued_connector_ids,
            "queued_job_ids": queued_job_ids,
            "skipped_connector_ids": skipped_connector_ids,
            "reconciled_document_ids": reconciled_document_ids,
            "reconciled_count": len(reconciled_document_ids),
        }

    # ── Source document queries ────────────────────────────────────

    async def list_source_documents(
        self,
        workspace_id: UUID,
        *,
        connector_type: ConnectorType | None = None,
        processed: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[SourceDocument], int, bool]:
        """Return source documents for a workspace with optional filters.

        Returns (items, total_count, has_more).
        """
        await self._require_workspace(workspace_id)

        # Base filter: docs scoped to workspace via connector join
        connector_ids_q = (
            select(Connector.id)
            .where(Connector.workspace_id == workspace_id)
        )
        if connector_type is not None:
            connector_ids_q = connector_ids_q.where(
                Connector.connector_type == connector_type
            )

        base = select(SourceDocument).where(
            SourceDocument.connector_id.in_(connector_ids_q),
            SourceDocument.deleted_at.is_(None),
        )
        count_q = select(func.count()).select_from(SourceDocument).where(
            SourceDocument.connector_id.in_(connector_ids_q),
            SourceDocument.deleted_at.is_(None),
        )

        if processed is True:
            base = base.where(SourceDocument.processed_at.is_not(None))
            count_q = count_q.where(SourceDocument.processed_at.is_not(None))
        elif processed is False:
            base = base.where(SourceDocument.processed_at.is_(None))
            count_q = count_q.where(SourceDocument.processed_at.is_(None))

        if cursor:
            try:
                cursor_id = UUID(cursor)
                # Fetch the cursor document's (ingested_at, id) for keyset pagination
                cursor_row = (await self.session.execute(
                    select(SourceDocument.ingested_at, SourceDocument.id).where(
                        SourceDocument.id == cursor_id,
                        SourceDocument.connector_id.in_(connector_ids_q),
                        SourceDocument.deleted_at.is_(None),
                    )
                )).one_or_none()
                if cursor_row is not None:
                    cursor_ts, cursor_uid = cursor_row
                    # Compound keyset: rows that sort strictly after the cursor
                    from sqlalchemy import tuple_
                    base = base.where(
                        tuple_(
                            SourceDocument.ingested_at, SourceDocument.id
                        ) < tuple_(cursor_ts, cursor_uid)
                    )
            except ValueError:
                pass  # Invalid cursor — ignore

        total = await self.session.scalar(count_q) or 0

        rows = list(await self.session.scalars(
            base.order_by(
                SourceDocument.ingested_at.desc(),
                SourceDocument.id.desc(),
            ).limit(limit + 1)
        ))

        has_more = len(rows) > limit
        items = rows[:limit]

        return items, total, has_more

    async def get_source_document(
        self, document_id: UUID, workspace_id: UUID
    ) -> SourceDocument:
        """Return a single source document by ID, scoped to workspace."""
        await self._require_workspace(workspace_id)

        connector_ids_q = (
            select(Connector.id)
            .where(Connector.workspace_id == workspace_id)
        )
        doc = await self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.id == document_id,
                SourceDocument.connector_id.in_(connector_ids_q),
                SourceDocument.deleted_at.is_(None),
            )
        )
        if doc is None:
            raise ConnectorNotFoundError("Source document not found")
        return doc

    async def get_processing_summary(
        self, workspace_id: UUID
    ) -> list[dict]:
        """Return per-connector processing counts for a workspace."""
        await self._require_workspace(workspace_id)

        connectors = await self.list_connectors(workspace_id)
        summaries = []
        for conn in connectors:
            total = await self.session.scalar(
                select(func.count()).select_from(SourceDocument).where(
                    SourceDocument.connector_id == conn.id,
                    SourceDocument.deleted_at.is_(None),
                )
            ) or 0
            processed = await self.session.scalar(
                select(func.count()).select_from(SourceDocument).where(
                    SourceDocument.connector_id == conn.id,
                    SourceDocument.processed_at.is_not(None),
                    SourceDocument.deleted_at.is_(None),
                )
            ) or 0
            summaries.append({
                "connector_id": conn.id,
                "connector_type": conn.connector_type.value,
                "status": conn.status.value,
                "total_documents": total,
                "processed_documents": processed,
                "unprocessed_documents": total - processed,
                "last_sync_at": conn.last_sync_at,
            })
        return summaries

    # ── Slack install URL with Redis-backed state ──────────────────

    async def build_slack_install_url(self, workspace_id: UUID) -> str:
        self._require_slack_config()

        nonce = secrets.token_urlsafe(24)
        state = f"{workspace_id}:{nonce}"

        # Persist state → workspace_id mapping in Redis with TTL
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.setex(
                f"{_STATE_PREFIX}{state}",
                settings.oauth_state_ttl_seconds,
                str(workspace_id),
            )
        finally:
            await redis.aclose()

        scopes = "channels:history,channels:read,groups:history,groups:read,users:read,team:read"
        redirect_uri = settings.slack_redirect_uri or ""

        url = (
            "https://slack.com/oauth/v2/authorize"
            f"?client_id={settings.slack_client_id}"
            f"&scope={scopes}"
            f"&state={state}"
        )
        if redirect_uri:
            url += f"&redirect_uri={redirect_uri}"

        return url

    # ── Slack OAuth callback ───────────────────────────────────────

    async def handle_slack_callback(
        self, *, code: str | None, state: str | None, error: str | None
    ) -> Connector:
        """Process the OAuth callback from Slack.

        Validates state, exchanges the code for a token, and upserts
        the Connector row.
        """
        if error:
            raise OAuthError(f"Slack returned an error: {error}")

        if not state:
            raise InvalidStateError("Missing OAuth state parameter")

        if not code:
            raise OAuthError("Missing authorization code from Slack")

        # Validate + consume state from Redis (one-time use)
        workspace_id = await self._validate_and_consume_state(state)

        # Exchange code for access token
        token_data = await self._exchange_slack_code(code)
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthError("Slack token exchange did not return an access token")

        try:
            encrypted = encrypt_token(access_token)
        except EncryptionError as exc:
            raise ConfigurationError(str(exc)) from exc

        # Upsert: create or update connector for workspace + slack
        connector = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == ConnectorType.SLACK,
            )
        )

        slack_team = token_data.get("team", {})
        oauth_meta = {
            "team_id": slack_team.get("id"),
            "team_name": slack_team.get("name"),
            "authed_user_id": token_data.get("authed_user", {}).get("id"),
            "scope": token_data.get("scope"),
        }

        if connector is None:
            connector = Connector(
                workspace_id=workspace_id,
                connector_type=ConnectorType.SLACK,
                status=ConnectorStatus.CONNECTED,
                oauth_token_encrypted=encrypted,
                config=oauth_meta,
            )
            self.session.add(connector)
        else:
            connector.status = ConnectorStatus.CONNECTED
            connector.oauth_token_encrypted = encrypted
            # Merge: preserve existing operational fields (document_count,
            # sync_queued_at, etc.) while updating OAuth/team metadata.
            connector.config = {**connector.config, **oauth_meta}

        await self.session.commit()
        await self.session.refresh(connector)
        return connector

    # ── Private helpers ────────────────────────────────────────────

    async def _validate_and_consume_state(self, state: str) -> UUID:
        """Look up the state nonce in Redis, delete it, return the workspace_id."""
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            key = f"{_STATE_PREFIX}{state}"
            workspace_id_str = await redis.getdel(key)
        finally:
            await redis.aclose()

        if workspace_id_str is None:
            raise InvalidStateError("Invalid or expired OAuth state")

        try:
            workspace_id = UUID(workspace_id_str)
        except ValueError:
            raise InvalidStateError("Corrupt OAuth state data")

        # Verify workspace still exists
        await self._require_workspace(workspace_id)
        return workspace_id

    async def _exchange_slack_code(self, code: str) -> dict:
        """POST to Slack's oauth.v2.access to exchange code for token."""
        self._require_slack_config()

        async with httpx.AsyncClient(timeout=15) as http:
            try:
                resp = await http.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": settings.slack_client_id,
                        "client_secret": settings.slack_client_secret,
                        "code": code,
                        "redirect_uri": settings.slack_redirect_uri or "",
                    },
                )
            except httpx.HTTPError as exc:
                raise OAuthError(
                    f"Slack token exchange request failed: {exc.__class__.__name__}"
                ) from exc

        if resp.status_code != 200:
            raise OAuthError(f"Slack API returned HTTP {resp.status_code}")

        body = resp.json()
        if not body.get("ok"):
            slack_error = body.get("error", "unknown_error")
            raise OAuthError(f"Slack token exchange failed: {slack_error}")

        return body

    async def _exchange_zoom_code(self, code: str) -> dict:
        self._require_zoom_oauth_config()

        async with httpx.AsyncClient(timeout=15) as http:
            try:
                resp = await http.post(
                    f"{settings.zoom_oauth_base_url.rstrip('/')}/oauth/token",
                    params={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": settings.zoom_redirect_uri or "",
                    },
                    headers=self._zoom_basic_auth_header(),
                )
            except httpx.HTTPError as exc:
                raise OAuthError(
                    f"Zoom token exchange request failed: {exc.__class__.__name__}"
                ) from exc

        if resp.status_code != 200:
            raise OAuthError(f"Zoom API returned HTTP {resp.status_code}")

        body = resp.json()
        if body.get("error"):
            raise OAuthError(f"Zoom token exchange failed: {body['error']}")
        return body

    async def _refresh_zoom_access_token(self, refresh_token: str) -> dict:
        self._require_zoom_oauth_config()

        async with httpx.AsyncClient(timeout=15) as http:
            try:
                resp = await http.post(
                    f"{settings.zoom_oauth_base_url.rstrip('/')}/oauth/token",
                    params={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers=self._zoom_basic_auth_header(),
                )
            except httpx.HTTPError as exc:
                raise OAuthError(
                    f"Zoom refresh request failed: {exc.__class__.__name__}"
                ) from exc

        if resp.status_code != 200:
            raise OAuthError(f"Zoom refresh returned HTTP {resp.status_code}")

        body = resp.json()
        if body.get("error"):
            raise OAuthError(f"Zoom refresh failed: {body['error']}")
        return body

    def _require_slack_config(self) -> None:
        missing = []
        if not settings.slack_client_id:
            missing.append("SLACK_CLIENT_ID")
        if not settings.slack_client_secret:
            missing.append("SLACK_CLIENT_SECRET")
        if not settings.slack_redirect_uri:
            missing.append("SLACK_REDIRECT_URI")
        if missing:
            raise ConfigurationError(
                "Slack OAuth is not configured yet. "
                f"Set {', '.join(missing)} in .env, restart Context Engine, "
                "then connect Slack again. See docs/slack.md for the Slack app manifest."
            )

    def _require_zoom_oauth_config(self) -> None:
        if not settings.zoom_client_id or not settings.zoom_client_secret:
            raise ConfigurationError(
                "Zoom OAuth is not configured. "
                "Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET environment variables."
            )

    def verify_zoom_webhook_signature(
        self,
        *,
        raw_body: bytes,
        signature: str | None,
        request_timestamp: str | None,
    ) -> None:
        if not settings.zoom_webhook_secret:
            raise ConfigurationError(
                "Zoom webhook verification is not configured. "
                "Set ZOOM_WEBHOOK_SECRET."
            )
        if not signature or not request_timestamp:
            raise WebhookVerificationError("Missing Zoom webhook signature headers")

        try:
            timestamp_int = int(request_timestamp)
        except ValueError as exc:
            raise WebhookVerificationError("Invalid Zoom webhook timestamp") from exc

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if abs(now_ts - timestamp_int) > settings.zoom_webhook_tolerance_seconds:
            raise WebhookVerificationError(
                "Zoom webhook timestamp is outside the allowed tolerance window"
            )

        signed_message = b"v0:" + request_timestamp.encode() + b":" + raw_body
        expected_signature = "v0=" + hmac.new(
            settings.zoom_webhook_secret.encode(),
            signed_message,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise WebhookVerificationError("Zoom webhook signature verification failed")

    def _zoom_basic_auth_header(self) -> dict[str, str]:
        raw = f"{settings.zoom_client_id}:{settings.zoom_client_secret}".encode()
        encoded = b64encode(raw).decode()
        return {"Authorization": f"Basic {encoded}"}

    @staticmethod
    def _zoom_expiry_metadata(expires_in: object) -> dict[str, str]:
        try:
            seconds = int(expires_in or 0)
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0:
            return {}
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(seconds - 60, 0))
        return {"access_token_expires_at": expires_at.isoformat()}

    @staticmethod
    def _is_expired_or_expiring_soon(expires_at: str) -> bool:
        try:
            parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed <= datetime.now(timezone.utc) + timedelta(minutes=2)

    @staticmethod
    def _should_queue_zoom_sync(event: str) -> bool:
        return event in {
            "recording.completed",
            "recording.transcript_completed",
            "recording.recovered",
        }

    @staticmethod
    def _should_reconcile_zoom_deletion(event: str) -> bool:
        return event in {
            "recording.deleted",
            "recording.trash",
        }

    @staticmethod
    def _zoom_payload_account_id(payload: dict) -> str | None:
        payload_root = payload.get("payload") or {}
        zoom_object = payload_root.get("object") or {}
        for candidate in (
            payload_root.get("account_id"),
            zoom_object.get("account_id"),
            zoom_object.get("accountId"),
        ):
            if candidate:
                return str(candidate)
        return None

    async def _load_zoom_webhook_connectors(self, account_id: str) -> list[Connector]:
        result = await self.session.scalars(
            select(Connector).where(
                Connector.connector_type == ConnectorType.ZOOM,
                Connector.status == ConnectorStatus.CONNECTED,
            )
        )
        return [
            connector
            for connector in result
            if connector.config.get("auth_mode") == "oauth"
            and connector.config.get("account_id") == account_id
        ]

    async def _reconcile_zoom_deletion_event(
        self,
        *,
        payload: dict,
        account_id: str,
        event: str,
    ) -> list[str]:
        connectors = await self._load_zoom_webhook_connectors(account_id)
        if not connectors:
            return []

        connector_ids = [connector.id for connector in connectors]
        docs = await self._load_zoom_documents_for_deletion(
            connector_ids=connector_ids,
            payload=payload,
        )
        if not docs:
            return []

        object_payload = ((payload.get("payload") or {}).get("object") or {})
        meeting_id = object_payload.get("id") or object_payload.get("meeting_id")
        event_ts = self._zoom_event_datetime(payload)
        reason = (
            f"Zoom webhook {event} removed transcript support for meeting "
            f"{meeting_id or 'unknown'}."
        )
        ingestion = IngestionService(self.session)
        retired_ids: list[str] = []
        for document in docs:
            await ingestion.retire_source_document(
                document,
                reason=reason,
                retired_at=event_ts,
            )
            document.deleted_at = event_ts
            document.metadata_json = {
                **(document.metadata_json or {}),
                "lifecycle_state": "deleted",
                "deleted_by_event": event,
                "deleted_at": event_ts.isoformat(),
            }
            retired_ids.append(str(document.id))

        for connector in connectors:
            active_count = await self._count_active_documents(connector.id)
            connector.config = {
                **connector.config,
                "document_count": active_count,
                "last_zoom_webhook_event": event,
                "last_zoom_webhook_received_at": event_ts.isoformat(),
                "message": (
                    f"Zoom webhook reconciled {len(retired_ids)} deleted transcript "
                    f"documents."
                ),
            }
        await self.session.commit()
        return retired_ids

    async def _load_zoom_documents_for_deletion(
        self,
        *,
        connector_ids: list[UUID],
        payload: dict,
    ) -> list[SourceDocument]:
        object_payload = ((payload.get("payload") or {}).get("object") or {})
        meeting_id = object_payload.get("id") or object_payload.get("meeting_id")
        transcript_file_ids = self._zoom_transcript_file_ids(
            object_payload.get("recording_files") or []
        )

        filters = [SourceDocument.connector_id.in_(connector_ids), SourceDocument.deleted_at.is_(None)]
        if transcript_file_ids:
            filters.append(
                SourceDocument.metadata_json["transcript_file_id"].astext.in_(transcript_file_ids)
            )
        elif meeting_id is not None:
            filters.append(
                SourceDocument.metadata_json["meeting_id"].astext == str(meeting_id)
            )
        else:
            return []

        result = await self.session.scalars(select(SourceDocument).where(*filters))
        return list(result)

    async def _count_active_documents(self, connector_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count()).select_from(SourceDocument).where(
                SourceDocument.connector_id == connector_id,
                SourceDocument.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    @staticmethod
    def _zoom_event_datetime(payload: dict) -> datetime:
        for candidate in (
            payload.get("event_ts"),
            ((payload.get("payload") or {}).get("object") or {}).get("deleted_time"),
            ((payload.get("payload") or {}).get("object") or {}).get("trash_time"),
        ):
            parsed = ConnectorService._parse_zoom_datetime(candidate)
            if parsed is not None:
                return parsed
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_zoom_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str):
            try:
                if value.isdigit():
                    return datetime.fromtimestamp(float(value), tz=timezone.utc)
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _zoom_transcript_file_ids(recording_files: list[dict]) -> list[str]:
        transcript_ids: list[str] = []
        for file_payload in recording_files:
            recording_type = str(file_payload.get("recording_type", "")).lower()
            file_type = str(file_payload.get("file_type", "")).lower()
            extension = str(file_payload.get("file_extension", "")).lower()
            if (
                "transcript" in recording_type
                or file_type == "transcript"
                or extension in {"vtt", "txt"}
            ) and file_payload.get("id"):
                transcript_ids.append(str(file_payload["id"]))
        return transcript_ids

    @staticmethod
    def _strip_zoom_oauth_config(config: dict) -> dict:
        return {
            key: value
            for key, value in (config or {}).items()
            if key
            not in {
                "account_id",
                "access_token_expires_at",
                "access_token_expires_in",
                "scope",
                "token_type",
                "last_zoom_webhook_event",
                "last_zoom_webhook_received_at",
            }
        }

    async def _require_workspace(self, workspace_id: UUID) -> None:
        exists = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).limit(1)
        )
        if exists is None:
            raise WorkspaceNotFoundError("Workspace not found")
