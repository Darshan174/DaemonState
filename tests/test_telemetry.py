from __future__ import annotations

from uuid import uuid4

import pytest
from opentelemetry.sdk.trace.export import (
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from app.config import (
    Settings,
    production_configuration_errors,
    telemetry_configuration_errors,
)
from app.telemetry import (
    TELEMETRY_SCHEMA_VERSION,
    configure_telemetry,
    safe_span_attributes,
    shutdown_telemetry,
    telemetry_enabled,
    traced,
)


@pytest.fixture(autouse=True)
def _reset_telemetry():
    shutdown_telemetry()
    yield
    shutdown_telemetry()


def _enabled_settings(**overrides) -> Settings:
    values = {
        "otel_enabled": True,
        "otel_content_capture": False,
        "otel_exporter_otlp_traces_endpoint": (
            "http://localhost:4318/v1/traces"
        ),
        "otel_sample_ratio": 1.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_telemetry_is_disabled_and_noop_by_default():
    configured = Settings(_env_file=None)

    @traced("daemonstate.context.compile")
    def operation() -> str:
        return "unchanged"

    assert configure_telemetry(configured) is False
    assert telemetry_enabled() is False
    assert operation() == "unchanged"


def test_nested_spans_export_only_allowlisted_metadata():
    exporter = InMemorySpanExporter()
    workspace_id = uuid4()
    context_pack_id = uuid4()
    digest = "a" * 64
    secret = "prompt contains sk-secret-value"

    assert configure_telemetry(
        _enabled_settings(),
        span_exporter=exporter,
        use_batch_processor=False,
    )

    @traced(
        "daemonstate.context.compile",
        attributes=lambda _args, _kwargs: {
            "daemonstate.workspace.id": workspace_id,
            "daemonstate.context.token_budget": 4096,
            "prompt": secret,
        },
        result_attributes=lambda _result: {
            "daemonstate.context_pack.id": context_pack_id,
            "daemonstate.context_pack.sha256": digest,
            "daemonstate.status": "compiled",
        },
    )
    def compile_context() -> str:
        return "compiled"

    @traced(
        "daemonstate.continuation.prepare",
        attributes=lambda _args, _kwargs: {
            "daemonstate.workspace.id": workspace_id,
            "daemonstate.phase": "continuation_prepare",
        },
    )
    def prepare() -> str:
        return compile_context()

    assert prepare() == "compiled"

    spans = {
        span.name: span
        for span in exporter.get_finished_spans()
    }
    root = spans["daemonstate.continuation.prepare"]
    child = spans["daemonstate.context.compile"]
    assert child.context.trace_id == root.context.trace_id
    assert child.parent is not None
    assert child.parent.span_id == root.context.span_id
    assert child.attributes["daemonstate.context_pack.id"] == str(context_pack_id)
    assert child.attributes["daemonstate.context_pack.sha256"] == digest
    assert child.attributes["daemonstate.context.token_budget"] == 4096
    assert (
        child.attributes["daemonstate.telemetry.schema_version"]
        == TELEMETRY_SCHEMA_VERSION
    )
    serialized = repr([span.attributes for span in spans.values()])
    assert secret not in serialized
    assert "prompt" not in serialized
    assert child.resource.attributes["service.name"] == "daemonstate-api"


def test_sensitive_or_unbounded_attribute_values_are_dropped():
    attributes = safe_span_attributes({
        "daemonstate.status": "contains secret words",
        "daemonstate.session.id": "/Users/person/private/session",
        "daemonstate.context_pack.sha256": "not-a-digest",
        "tool.arguments": "--token secret",
        "daemonstate.verification.total": 3,
    })

    assert attributes == {
        "daemonstate.telemetry.schema_version": TELEMETRY_SCHEMA_VERSION,
        "daemonstate.verification.total": 3,
    }


def test_exception_span_omits_message_stack_and_events():
    exporter = InMemorySpanExporter()
    assert configure_telemetry(
        _enabled_settings(),
        span_exporter=exporter,
        use_batch_processor=False,
    )

    @traced("daemonstate.harness.execute")
    def operation() -> None:
        raise RuntimeError(
            "prompt, path, and credential must never reach telemetry"
        )

    with pytest.raises(RuntimeError, match="must never reach telemetry"):
        operation()

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.events == ()
    serialized = repr(span.attributes)
    assert "credential" not in serialized
    assert "prompt" not in serialized
    assert "path" not in serialized


class _ExplodingExporter(SpanExporter):
    def export(self, spans) -> SpanExportResult:
        raise RuntimeError("collector unavailable")

    def shutdown(self) -> None:
        return None


def test_exporter_failure_does_not_change_application_result():
    assert configure_telemetry(
        _enabled_settings(),
        span_exporter=_ExplodingExporter(),
        use_batch_processor=False,
    )

    @traced("daemonstate.requirements.judge")
    def operation() -> str:
        return "verified-by-application"

    assert operation() == "verified-by-application"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"otel_content_capture": True},
            "OTEL_CONTENT_CAPTURE",
        ),
        (
            {"otel_sample_ratio": 1.1},
            "OTEL_SAMPLE_RATIO",
        ),
        (
            {
                "otel_batch_max_queue_size": 10,
                "otel_batch_max_export_batch_size": 11,
            },
            "OTEL_BATCH_MAX_EXPORT_BATCH_SIZE",
        ),
        (
            {
                "otel_exporter_otlp_traces_endpoint": (
                    "https://user:secret@collector.example/v1/traces"
                ),
            },
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        ),
    ],
)
def test_invalid_telemetry_configuration_disables_export(
    overrides,
    expected,
):
    configured = _enabled_settings(**overrides)

    errors = telemetry_configuration_errors(configured)

    assert any(expected in error for error in errors)
    assert configure_telemetry(configured) is False
    assert telemetry_enabled() is False


def test_production_export_requires_https():
    configured = _enabled_settings(environment="production")

    errors = telemetry_configuration_errors(
        configured,
        require_https=True,
    )

    assert any("absolute https URL" in error for error in errors)
    assert any(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" in error
        for error in production_configuration_errors(configured)
    )
