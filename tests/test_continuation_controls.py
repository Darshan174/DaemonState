from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.continuation_runtime import provider_readiness
from app.services.harness_adapters import ProviderReadiness
from app.services.harness_launcher import HarnessComposerReadiness


async def test_run_continuation_forwards_codex_model_and_effort(
    client,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run(_service, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            to_dict=lambda: {
                "schema_version": "continuation.run.v1",
                "status": "verified",
            },
        )

    monkeypatch.setattr(
        "app.api.continuations.ContinuationRunService.run",
        fake_run,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(uuid4()),
            "objective": "Continue in the visible Codex harness.",
            "target_provider": "codex",
            "provider_model": "gpt-5.6-sol",
            "provider_effort": "xhigh",
        },
    )

    assert response.status_code == 200, response.text
    assert captured["target_provider"] == "codex"
    assert captured["provider_model"] == "gpt-5.6-sol"
    assert captured["provider_effort"] == "xhigh"


async def test_stage_continuation_forwards_requested_codex_model_and_effort(
    client,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_stage(_service, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            to_dict=lambda: {
                "schema_version": "continuation.stage.v1",
                "status": "awaiting_user",
            },
        )

    monkeypatch.setattr(
        "app.api.continuations.ContinuationStageService.stage",
        fake_stage,
    )

    response = await client.post(
        "/api/continuations/stage",
        json={
            "workspace_id": str(uuid4()),
            "objective": "Open a reviewable Codex desktop draft.",
            "target_provider": "codex",
            "provider_model": "gpt-5.6-sol",
            "provider_effort": "xhigh",
            "idempotency_key": f"continue-{uuid4()}",
        },
    )

    assert response.status_code == 200, response.text
    assert captured["target_provider"] == "codex"
    assert captured["provider_model"] == "gpt-5.6-sol"
    assert captured["provider_effort"] == "xhigh"


async def test_run_continuation_rejects_unknown_codex_effort(
    client,
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_run(_service, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(to_dict=lambda: {})

    monkeypatch.setattr(
        "app.api.continuations.ContinuationRunService.run",
        fake_run,
    )

    response = await client.post(
        "/api/continuations/run",
        json={
            "workspace_id": str(uuid4()),
            "objective": "Do not accept an invented effort.",
            "target_provider": "codex",
            "provider_model": "gpt-5.6-sol",
            "provider_effort": "turbo",
        },
    )

    assert response.status_code == 422, response.text
    assert "provider_effort" in response.text
    assert calls == []


async def test_provider_readiness_uses_desktop_apps_not_cli_or_exact_sessions(
    monkeypatch,
) -> None:
    def fail_cli_probe(*_args, **_kwargs):
        pytest.fail("desktop readiness must not invoke a provider CLI")

    composer_readiness = {
        "codex": HarnessComposerReadiness(
            provider="codex",
            ready=False,
            desktop_available=False,
            url_scheme_registered=False,
            required_url_scheme="codex",
            code="desktop_app_missing",
            message="Codex desktop is missing.",
            action="Install Codex desktop.",
        ),
        "claude": HarnessComposerReadiness(
            provider="claude",
            ready=False,
            desktop_available=True,
            url_scheme_registered=False,
            required_url_scheme="claude",
            code="desktop_url_scheme_missing",
            message="Claude does not register its composer URL scheme.",
            action="Update Claude desktop.",
        ),
        "opencode": HarnessComposerReadiness(
            provider="opencode",
            ready=True,
            desktop_available=True,
            url_scheme_registered=True,
            required_url_scheme="opencode",
            code="desktop_dispatch_ready",
            message=(
                "OpenCode is ready to receive a desktop draft."
            ),
            action="Open OpenCode.",
            account_access_state="unverified",
            account_access_verified=False,
        ),
    }
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        fail_cli_probe,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_harness_composer_readiness",
        lambda provider: composer_readiness[provider],
        raising=False,
    )

    statuses = {
        item.provider: item
        for item in await provider_readiness()
    }

    assert statuses["codex"].ready is False
    assert statuses["codex"].code == "desktop_app_missing"
    assert statuses["claude"].ready is False
    assert statuses["claude"].desktop_available is True
    assert statuses["claude"].code == "desktop_url_scheme_missing"
    assert statuses["claude"].desktop_handoff_supported is False
    assert statuses["opencode"].ready is True
    assert statuses["opencode"].status == "ready"
    assert statuses["opencode"].code == "desktop_dispatch_ready"
    assert statuses["opencode"].desktop_available is True
    assert statuses["opencode"].desktop_handoff_supported is True


async def test_provider_readiness_reuses_recent_local_probes(monkeypatch) -> None:
    cli_calls: list[str] = []
    composer_calls: list[str] = []

    def fail_cli_probe(provider: str, **_kwargs) -> ProviderReadiness:
        cli_calls.append(provider)
        pytest.fail("desktop readiness must not invoke a provider CLI")

    def composer_dispatch_ready(provider: str) -> HarnessComposerReadiness:
        composer_calls.append(provider)
        return HarnessComposerReadiness(
            provider=provider,
            ready=True,
            desktop_available=True,
            url_scheme_registered=True,
            required_url_scheme=provider,
            code="desktop_dispatch_ready",
            message=f"{provider} is ready to receive a desktop draft.",
            action=f"Open {provider}.",
            account_access_state="unverified",
            account_access_verified=False,
        )

    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        fail_cli_probe,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_harness_composer_readiness",
        composer_dispatch_ready,
    )

    first = await provider_readiness()
    second = await provider_readiness()
    refreshed = await provider_readiness(force_refresh=True)

    assert second == first
    assert refreshed == first
    assert cli_calls == []
    assert sorted(composer_calls) == [
        "claude", "claude", "codex", "codex", "opencode", "opencode",
    ]


async def test_provider_readiness_times_out_stalled_desktop_probes(
    monkeypatch,
) -> None:
    def stalled_probe(provider: str) -> HarnessComposerReadiness:
        time.sleep(0.05)
        return HarnessComposerReadiness(
            provider=provider,
            ready=True,
            desktop_available=True,
            url_scheme_registered=True,
            required_url_scheme=provider,
            code="late_result_must_not_be_used",
            message="Late probe result.",
            action="Ignore this result.",
        )

    monkeypatch.setattr(
        "app.services.continuation_runtime.COMPOSER_READINESS_TIMEOUT_SECONDS",
        0.005,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_harness_composer_readiness",
        stalled_probe,
    )

    statuses = await provider_readiness(force_refresh=True)

    assert len(statuses) == 3
    assert all(item.ready is False for item in statuses)
    assert all(item.code == "desktop_readiness_timeout" for item in statuses)
    assert all(
        item.readiness_scope == "desktop_dispatch_with_account_evidence"
        for item in statuses
    )
