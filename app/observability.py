from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Info

from app.config import settings


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter(
    "daemonstate_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "daemonstate_http_request_duration_seconds",
    "HTTP request latency.",
    ("method", "route"),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "daemonstate_http_requests_in_progress",
    "HTTP requests currently being handled.",
)
HTTP_RATE_LIMITED = Counter(
    "daemonstate_http_rate_limited_total",
    "HTTP requests rejected by a rate limit.",
    ("kind",),
)
READINESS = Gauge(
    "daemonstate_readiness",
    "Whether this API instance passed its most recent readiness check.",
)
SYNC_JOBS = Counter(
    "daemonstate_sync_jobs_total",
    "Connector sync job outcomes observed by this worker process.",
    ("status",),
)
SYNC_WORKER_LAST_RUN = Gauge(
    "daemonstate_sync_worker_last_run_unixtime",
    "Unix time of the most recent sync-worker polling cycle.",
)
BUILD_INFO = Info(
    "daemonstate_build",
    "DaemonState build metadata.",
)
BUILD_INFO.info({
    "release_sha": settings.release_sha,
    "environment": settings.environment,
})
_HTTP_METHOD_LABELS = frozenset({
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
})


def normalized_http_method(method: str) -> str:
    normalized = method.upper()
    return normalized if normalized in _HTTP_METHOD_LABELS else "OTHER"


class JsonFormatter(logging.Formatter):
    _standard_fields = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
        }
        for key, value in record.__dict__.items():
            if key in self._standard_fields or key.startswith("_"):
                continue
            if key not in payload and isinstance(value, (str, int, float, bool, type(None))):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True


def record_sync_worker_result(result: dict[str, Any]) -> None:
    for status in ("completed", "retried", "failed", "dead_lettered"):
        count = int(result.get(status) or 0)
        if count:
            SYNC_JOBS.labels(status=status).inc(count)
    for key, status in (
        ("source_completed", "source_completed"),
        ("source_retried", "source_retried"),
        ("source_dead_lettered", "source_dead_lettered"),
    ):
        count = int(result.get(key) or 0)
        if count:
            SYNC_JOBS.labels(status=status).inc(count)
    SYNC_WORKER_LAST_RUN.set_to_current_time()
