# OpenTelemetry Tracing

DaemonState can export optional OTLP/HTTP traces for the continuation
pipeline. Tracing is disabled by default and is operational telemetry only. It
does not replace the canonical `continuation_execution.v1` contract,
checkpoint and context-pack hashes, persisted run evidence, or the requirement
verification matrix.

## Enable tracing

Install the project dependencies, run an OpenTelemetry Collector or compatible
OTLP/HTTP backend, and set:

```dotenv
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
```

Production configuration requires an HTTPS endpoint. The exporter uses a
bounded batch queue, a finite timeout, parent-aware ratio sampling, and the
service resource configured by:

```dotenv
OTEL_SERVICE_NAME=daemonstate-api
OTEL_SAMPLE_RATIO=1.0
OTEL_EXPORT_TIMEOUT_SECONDS=5
OTEL_BATCH_MAX_QUEUE_SIZE=2048
OTEL_BATCH_MAX_EXPORT_BATCH_SIZE=512
OTEL_BATCH_SCHEDULE_DELAY_MS=5000
```

Collector unavailability, export failures, and SDK failures do not change a
continuation result. They are logged and tracing degrades to a no-op.

## Span boundaries

Phase 1 emits nested spans at these boundaries:

- continuation preparation and context compilation;
- checkpoint verification;
- waiting-thread staging and desktop launch;
- local harness execution and verification;
- requirement-matrix evaluation and the complete run boundary.

Span attributes are restricted to an explicit metadata allowlist: opaque IDs,
SHA-256 hashes, bounded status/provider/mode values, booleans, and counts.

## Privacy and truth

`OTEL_CONTENT_CAPTURE=false` is mandatory. The Phase 1 implementation rejects
content capture instead of exporting prompts, source text, repository paths,
file names, commands, tool arguments, environment values, credentials,
exception messages, or stack traces. Exception spans contain only the bounded
exception type and an error status.

Trace data cannot promote a claim from reported to observed, prove a decision,
confirm a blocker, or mark work complete. Only controller observations and the
persisted requirement-linked evidence contract can do that.
