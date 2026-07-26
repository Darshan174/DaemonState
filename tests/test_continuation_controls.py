from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.continuation_runtime import provider_readiness
from app.services.harness_adapters import ProviderReadiness
from app.services.harness_launcher import HarnessVisibility


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


async def test_provider_readiness_fails_closed_when_execution_cannot_be_shown(
    monkeypatch,
) -> None:
    def cli_ready(provider: str, **_kwargs) -> ProviderReadiness:
        return ProviderReadiness(
            provider=provider,
            ready=True,
            status="ready",
            code="provider_ready",
            message=f"{provider} CLI is ready.",
            action=f"Continue in {provider}.",
        )

    visibility = {
        "codex": HarnessVisibility(
            provider="codex",
            ready=False,
            desktop_available=False,
            exact_session_supported=True,
            code="desktop_app_missing",
            message="Codex desktop is missing.",
            action="Install Codex desktop.",
        ),
        "claude": HarnessVisibility(
            provider="claude",
            ready=False,
            desktop_available=True,
            exact_session_supported=False,
            code="visible_session_unsupported",
            message="Claude cannot open the exact automation session.",
            action="Choose a visible harness.",
        ),
        "opencode": HarnessVisibility(
            provider="opencode",
            ready=False,
            desktop_available=True,
            exact_session_supported=False,
            code="visible_session_unsupported",
            message="OpenCode cannot open the exact automation session.",
            action="Choose a visible harness.",
        ),
    }
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_provider_readiness",
        cli_ready,
    )
    monkeypatch.setattr(
        "app.services.continuation_runtime.probe_harness_visibility",
        lambda provider: visibility[provider],
        raising=False,
    )

    statuses = {
        item.provider: item
        for item in await provider_readiness()
    }

    assert statuses["codex"].ready is False
    assert statuses["codex"].code == "desktop_app_missing"
    assert statuses["claude"].ready is False
    assert statuses["claude"].code == "visible_session_unsupported"
    assert statuses["opencode"].ready is False
    assert statuses["opencode"].code == "visible_session_unsupported"
