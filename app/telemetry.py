from __future__ import annotations

import inspect
import logging
import math
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from enum import Enum
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

from app.config import Settings, settings, telemetry_configuration_errors


TELEMETRY_SCHEMA_VERSION = "daemonstate.telemetry.v1"
INSTRUMENTATION_NAME = "daemonstate.continuation"

_ALLOWED_SPAN_NAMES = frozenset({
    "daemonstate.checkpoint.verify",
    "daemonstate.context.compile",
    "daemonstate.continuation.prepare",
    "daemonstate.continuation.run",
    "daemonstate.continuation.stage",
    "daemonstate.harness.execute",
    "daemonstate.harness.launch",
    "daemonstate.harness.stage",
    "daemonstate.operation",
    "daemonstate.requirements.judge",
})
_ALLOWED_ATTRIBUTES = frozenset({
    "daemonstate.attempt.index",
    "daemonstate.checkpoint.fingerprint",
    "daemonstate.checkpoint.id",
    "daemonstate.context.excluded_count",
    "daemonstate.context.health_score",
    "daemonstate.context.selected_count",
    "daemonstate.context.token_budget",
    "daemonstate.context_pack.id",
    "daemonstate.context_pack.sha256",
    "daemonstate.continuation.execution.id",
    "daemonstate.delivery.context_char_count",
    "daemonstate.delivery.context_estimated_tokens",
    "daemonstate.delivery.context_render_variant",
    "daemonstate.delivery.context_sha256",
    "daemonstate.harness.launched",
    "daemonstate.harness.navigation_requested",
    "daemonstate.harness.navigation_verified",
    "daemonstate.phase",
    "daemonstate.provider",
    "daemonstate.repository.fingerprint",
    "daemonstate.request.sha256",
    "daemonstate.run.id",
    "daemonstate.runtime.bundle_integrity_passed",
    "daemonstate.runtime.changed_file_count",
    "daemonstate.runtime.preservation_passed",
    "daemonstate.runtime.worker_succeeded",
    "daemonstate.session.id",
    "daemonstate.source.provider",
    "daemonstate.staging.awaiting_user",
    "daemonstate.staging.execution_started",
    "daemonstate.staging.observed_turn_count",
    "daemonstate.status",
    "daemonstate.target.provider",
    "daemonstate.task.mode",
    "daemonstate.telemetry.schema_version",
    "daemonstate.verification.enabled",
    "daemonstate.verification.failed",
    "daemonstate.verification.passed",
    "daemonstate.verification.total",
    "daemonstate.verification.unproven",
    "daemonstate.workspace.id",
    "error.type",
})
_HASH_ATTRIBUTES = frozenset({
    "daemonstate.checkpoint.fingerprint",
    "daemonstate.context_pack.sha256",
    "daemonstate.delivery.context_sha256",
    "daemonstate.repository.fingerprint",
    "daemonstate.request.sha256",
})
_COUNT_ATTRIBUTES = frozenset({
    "daemonstate.attempt.index",
    "daemonstate.context.excluded_count",
    "daemonstate.context.selected_count",
    "daemonstate.context.token_budget",
    "daemonstate.delivery.context_char_count",
    "daemonstate.delivery.context_estimated_tokens",
    "daemonstate.runtime.changed_file_count",
    "daemonstate.staging.observed_turn_count",
    "daemonstate.verification.failed",
    "daemonstate.verification.passed",
    "daemonstate.verification.total",
    "daemonstate.verification.unproven",
})
_BOOLEAN_ATTRIBUTES = frozenset({
    "daemonstate.harness.launched",
    "daemonstate.harness.navigation_requested",
    "daemonstate.harness.navigation_verified",
    "daemonstate.runtime.bundle_integrity_passed",
    "daemonstate.runtime.preservation_passed",
    "daemonstate.runtime.worker_succeeded",
    "daemonstate.staging.awaiting_user",
    "daemonstate.staging.execution_started",
    "daemonstate.verification.enabled",
})
_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

logger = logging.getLogger("daemonstate.telemetry")
_state_lock = threading.RLock()
_provider: Any | None = None
_tracer: Any | None = None

P = ParamSpec("P")
R = TypeVar("R")
AttributeFactory = Callable[
    [tuple[Any, ...], dict[str, Any]],
    Mapping[str, Any] | None,
]
ResultAttributeFactory = Callable[[Any], Mapping[str, Any] | None]


class _NoopSpan:
    def set_attribute(self, _key: str, _value: Any) -> None:
        return None

    def set_status(self, _status: Any) -> None:
        return None


_NOOP_SPAN = _NoopSpan()


def configure_telemetry(
    config: Settings = settings,
    *,
    span_exporter: Any | None = None,
    use_batch_processor: bool = True,
) -> bool:
    """Configure optional OTLP tracing without making it an app dependency."""

    shutdown_telemetry()
    if not config.otel_enabled:
        return False

    errors = telemetry_configuration_errors(
        config,
        require_https=config.environment.strip().lower() == "production",
    )
    if errors:
        logger.warning(
            "otel_disabled_invalid_configuration",
            extra={"error_count": len(errors)},
        )
        return False

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )

        if span_exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            span_exporter = OTLPSpanExporter(
                endpoint=config.otel_exporter_otlp_traces_endpoint,
                timeout=config.otel_export_timeout_seconds,
            )

        provider = TracerProvider(
            resource=Resource.create({
                "service.name": config.otel_service_name,
                "service.version": _resource_token(config.release_sha, "unknown"),
                "deployment.environment.name": _resource_token(
                    config.environment,
                    "unknown",
                ),
                "daemonstate.telemetry.schema_version": TELEMETRY_SCHEMA_VERSION,
            }),
            sampler=ParentBased(TraceIdRatioBased(config.otel_sample_ratio)),
        )
        if use_batch_processor:
            processor = BatchSpanProcessor(
                span_exporter,
                max_queue_size=config.otel_batch_max_queue_size,
                schedule_delay_millis=config.otel_batch_schedule_delay_ms,
                max_export_batch_size=(
                    config.otel_batch_max_export_batch_size
                ),
                export_timeout_millis=int(
                    config.otel_export_timeout_seconds * 1000
                ),
            )
        else:
            processor = SimpleSpanProcessor(span_exporter)
        provider.add_span_processor(processor)
        tracer = provider.get_tracer(
            INSTRUMENTATION_NAME,
            TELEMETRY_SCHEMA_VERSION,
        )
    except Exception as exc:
        logger.warning(
            "otel_disabled_configuration_failed",
            extra={"error_type": type(exc).__name__},
        )
        return False

    with _state_lock:
        global _provider, _tracer
        _provider = provider
        _tracer = tracer
    logger.info(
        "otel_enabled",
        extra={
            "service_name": config.otel_service_name,
            "sample_ratio": config.otel_sample_ratio,
        },
    )
    return True


def shutdown_telemetry() -> None:
    """Flush and detach the active provider; exporter errors are non-fatal."""

    with _state_lock:
        global _provider, _tracer
        provider = _provider
        _provider = None
        _tracer = None
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception as exc:
        logger.warning(
            "otel_shutdown_failed",
            extra={"error_type": type(exc).__name__},
        )


def telemetry_enabled() -> bool:
    with _state_lock:
        return _tracer is not None


def safe_span_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, str | bool | int | float]:
    """Reduce attributes to the explicit metadata-only telemetry contract."""

    sanitized: dict[str, str | bool | int | float] = {
        "daemonstate.telemetry.schema_version": TELEMETRY_SCHEMA_VERSION,
    }
    for key, raw_value in (attributes or {}).items():
        if key not in _ALLOWED_ATTRIBUTES:
            continue
        value = _safe_attribute_value(key, raw_value)
        if value is not None:
            sanitized[key] = value
    return sanitized


def set_span_attributes(
    span: Any,
    attributes: Mapping[str, Any] | None,
) -> None:
    for key, value in safe_span_attributes(attributes).items():
        try:
            span.set_attribute(key, value)
        except Exception as exc:
            logger.warning(
                "otel_attribute_write_failed",
                extra={"error_type": type(exc).__name__},
            )
            return


@contextmanager
def trace_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """Create one bounded span and preserve the application outcome."""

    span_name = name if name in _ALLOWED_SPAN_NAMES else "daemonstate.operation"
    with _state_lock:
        tracer = _tracer

    manager = None
    span: Any = _NOOP_SPAN
    if tracer is not None:
        try:
            manager = tracer.start_as_current_span(
                span_name,
                record_exception=False,
                set_status_on_exception=False,
            )
            span = manager.__enter__()
        except Exception as exc:
            manager = None
            span = _NOOP_SPAN
            logger.warning(
                "otel_span_start_failed",
                extra={"error_type": type(exc).__name__},
            )

    set_span_attributes(span, attributes)
    try:
        yield span
    except BaseException as exc:
        set_span_attributes(span, {"error.type": type(exc).__name__})
        _set_error_status(span)
        _close_span_manager(manager, type(exc), exc, exc.__traceback__)
        raise
    else:
        _close_span_manager(manager, None, None, None)


def traced(
    name: str,
    *,
    attributes: AttributeFactory | None = None,
    result_attributes: ResultAttributeFactory | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Trace a sync or async boundary using only explicit metadata factories."""

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs):
                initial = _call_attribute_factory(attributes, args, kwargs)
                with trace_span(name, initial) as span:
                    result = await function(*args, **kwargs)
                    set_span_attributes(
                        span,
                        _call_result_attribute_factory(
                            result_attributes,
                            result,
                        ),
                    )
                    return result

            return async_wrapper  # type: ignore[return-value]

        @wraps(function)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs):
            initial = _call_attribute_factory(attributes, args, kwargs)
            with trace_span(name, initial) as span:
                result = function(*args, **kwargs)
                set_span_attributes(
                    span,
                    _call_result_attribute_factory(
                        result_attributes,
                        result,
                    ),
                )
                return result

        return sync_wrapper

    return decorator


def _call_attribute_factory(
    factory: AttributeFactory | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Mapping[str, Any] | None:
    if factory is None:
        return None
    try:
        return factory(args, kwargs)
    except Exception as exc:
        logger.warning(
            "otel_attribute_factory_failed",
            extra={"error_type": type(exc).__name__},
        )
        return None


def _call_result_attribute_factory(
    factory: ResultAttributeFactory | None,
    result: Any,
) -> Mapping[str, Any] | None:
    if factory is None:
        return None
    try:
        return factory(result)
    except Exception as exc:
        logger.warning(
            "otel_result_attribute_factory_failed",
            extra={"error_type": type(exc).__name__},
        )
        return None


def _safe_attribute_value(
    key: str,
    raw_value: Any,
) -> str | bool | int | float | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, Enum):
        raw_value = raw_value.value
    if isinstance(raw_value, UUID):
        raw_value = str(raw_value)

    if key in _BOOLEAN_ATTRIBUTES:
        return raw_value if isinstance(raw_value, bool) else None
    if key in _COUNT_ATTRIBUTES:
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            return None
        return raw_value if raw_value >= 0 else None
    if key == "daemonstate.context.health_score":
        if isinstance(raw_value, bool) or not isinstance(
            raw_value,
            (int, float),
        ):
            return None
        value = float(raw_value)
        return value if math.isfinite(value) else None

    value = str(raw_value).strip()
    if key in _HASH_ATTRIBUTES:
        normalized_hash = value.lower()
        return normalized_hash if _HASH_PATTERN.fullmatch(normalized_hash) else None
    return value if _IDENTIFIER_PATTERN.fullmatch(value) else None


def _set_error_status(span: Any) -> None:
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR))
    except Exception as exc:
        logger.warning(
            "otel_status_write_failed",
            extra={"error_type": type(exc).__name__},
        )


def _close_span_manager(
    manager: Any | None,
    exc_type: type[BaseException] | None,
    exc: BaseException | None,
    traceback: Any | None,
) -> None:
    if manager is None:
        return
    try:
        manager.__exit__(exc_type, exc, traceback)
    except Exception as telemetry_exc:
        logger.warning(
            "otel_span_finish_failed",
            extra={"error_type": type(telemetry_exc).__name__},
        )


def _resource_token(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", candidate):
        return candidate
    return fallback
