"""Public adapter interfaces without private engine or authentication logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .cli import load_bundle


@dataclass(frozen=True)
class BundleRequest:
    """Minimal public request identifier for a context bundle."""

    workspace_ref: str


class ContextBundleAdapter(Protocol):
    """Boundary implemented by local fixtures or a future reviewed API client."""

    name: str

    def fetch_bundle(self, request: BundleRequest) -> Mapping[str, Any]:
        """Return a versioned bundle without mutating the workspace."""


@dataclass(frozen=True)
class LocalFileAdapter:
    """Safe example adapter that reads one already-created JSON file."""

    path: Path
    name: str = "local-file-demo"

    def fetch_bundle(self, request: BundleRequest) -> Mapping[str, Any]:
        bundle = load_bundle(self.path)
        if bundle["workspace"]["id"] != request.workspace_ref:
            raise LookupError(f"workspace not present in fixture: {request.workspace_ref}")
        return bundle


class AdapterUnavailable(RuntimeError):
    """Raised when a capability is intentionally absent from the public export."""


@dataclass(frozen=True)
class HostedAdapterStub:
    """Placeholder that prevents accidental claims of a bundled hosted client."""

    name: str = "hosted-api-not-configured"

    def fetch_bundle(self, request: BundleRequest) -> Mapping[str, Any]:
        del request
        raise AdapterUnavailable(
            "No hosted endpoint or credential flow is bundled. "
            "Use a reviewed private-service client when that contract is published."
        )
