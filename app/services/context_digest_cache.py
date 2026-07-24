from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import settings
from app.services.access import AccessScope


_CACHE_SCHEMA_VERSION = 1


def context_digest_cache_key(
    *,
    access_scope: AccessScope,
    workspace_id: UUID,
    limit: int,
) -> tuple:
    """Build a permission-aware key for a workspace digest."""
    return (
        _CACHE_SCHEMA_VERSION,
        str(workspace_id),
        limit,
        access_scope.principal_id,
        access_scope.unrestricted,
        tuple(sorted(str(item) for item in access_scope.workspace_ids)),
    )


class ContextDigestCache:
    """Small process-local LRU cache with a hard staleness bound."""

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def get(self, key: tuple) -> Any | None:
        if self.ttl_seconds <= 0:
            return None
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return _copy_value(value)

    def set(
        self,
        key: tuple,
        value: Any,
        *,
        expected_generation: int | None = None,
    ) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            if (
                expected_generation is not None
                and expected_generation != self._generation
            ):
                return
            self._entries[key] = (
                monotonic() + self.ttl_seconds,
                _copy_value(value),
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._generation += 1


def _copy_value(value: Any) -> Any:
    model_copy = getattr(value, "model_copy", None)
    return model_copy(deep=True) if callable(model_copy) else deepcopy(value)


context_digest_cache = ContextDigestCache(
    ttl_seconds=settings.context_digest_cache_ttl_seconds,
    max_entries=settings.context_digest_cache_max_entries,
)


@event.listens_for(Session, "after_flush")
def _invalidate_digest_cache_after_flush(_session: Session, _flush_context: object) -> None:
    # Digest inputs span several tables. Clearing this small cache on a write
    # keeps every mutation path correct without requiring scattered callbacks.
    context_digest_cache.clear()


@event.listens_for(Session, "do_orm_execute")
def _invalidate_digest_cache_after_direct_write(execute_state: object) -> None:
    if not getattr(execute_state, "is_select", False):
        context_digest_cache.clear()
