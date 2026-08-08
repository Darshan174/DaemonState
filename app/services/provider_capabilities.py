from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from app.schemas.continuation_execution import TaskMode
from app.services.harness_adapters import ProviderName


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capabilities that affect whether a provider can execute one contract.

    Installation and authentication are deliberately not represented here.
    Those are live readiness facts. This object describes the stable transport
    and permission features that the DaemonState adapter can enforce.
    """

    provider: ProviderName
    supports_command_execution: bool
    supports_filesystem_write: bool
    supports_resume: bool
    supports_structured_events: bool
    supports_native_images: bool
    supports_file_context: bool
    supports_mcp: bool
    supports_permission_modes: bool
    supports_reasoning_effort: bool
    supports_noninteractive_execution: bool
    supports_browser_verification: bool
    max_context_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityCheck:
    capability: str
    supported: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAPABILITIES: dict[ProviderName, ProviderCapabilities] = {
    "codex": ProviderCapabilities(
        provider="codex",
        supports_command_execution=True,
        supports_filesystem_write=True,
        supports_resume=True,
        supports_structured_events=True,
        supports_native_images=True,
        supports_file_context=True,
        supports_mcp=True,
        supports_permission_modes=True,
        supports_reasoning_effort=True,
        supports_noninteractive_execution=True,
        supports_browser_verification=False,
    ),
    "claude": ProviderCapabilities(
        provider="claude",
        supports_command_execution=True,
        supports_filesystem_write=True,
        supports_resume=True,
        supports_structured_events=True,
        supports_native_images=False,
        supports_file_context=True,
        supports_mcp=True,
        # The adapter pins `acceptEdits` for change work and `plan` for the
        # contract's read-only modes instead of inheriting a user's broader
        # default Claude permission mode.
        supports_permission_modes=True,
        supports_reasoning_effort=False,
        supports_noninteractive_execution=True,
        supports_browser_verification=False,
    ),
    "opencode": ProviderCapabilities(
        provider="opencode",
        supports_command_execution=True,
        supports_filesystem_write=True,
        supports_resume=True,
        supports_structured_events=True,
        supports_native_images=False,
        supports_file_context=True,
        supports_mcp=False,
        # OpenCode retains its installed permission policy; the adapter cannot
        # currently prove a task-specific read-only boundary.
        supports_permission_modes=False,
        supports_reasoning_effort=False,
        supports_noninteractive_execution=True,
        supports_browser_verification=False,
    ),
}


def provider_capabilities(provider: ProviderName | str) -> ProviderCapabilities:
    normalized = str(provider or "").strip().lower()
    if normalized == "claude_code":
        normalized = "claude"
    try:
        return _CAPABILITIES[normalized]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"unsupported continuation provider: {normalized or 'empty'}") from exc


def required_capabilities(contract: Any) -> tuple[str, ...]:
    """Return deterministic task capabilities, tolerating v1 schema growth."""

    declared = _field(contract, "required_capabilities", ())
    result = {str(value).strip() for value in _iterable(declared) if str(value).strip()}
    result.add("command_execution")

    mode = _task_mode(contract)
    authority = _field(contract, "authority", {})
    allow_edits = bool(_field(authority, "allow_product_edits", mode == TaskMode.CHANGE))
    if not allow_edits:
        result.add("permission_modes")

    artifacts = _iterable(_field(contract, "artifacts", ()))
    for artifact in artifacts:
        kind = str(_field(artifact, "kind", _field(artifact, "artifact_type", ""))).strip().lower()
        mime_type = str(_field(artifact, "mime_type", "") or "").strip().lower()
        required = bool(_field(artifact, "required", True))
        available = bool(_field(artifact, "available", True))
        if (
            required
            and available
            and (
                kind in {"image", "screenshot", "visual_reference"}
                or mime_type.startswith("image/")
            )
        ):
            # A prose summary is derived evidence, not a substitute for the
            # exact visual bytes when the artifact remains task input.
            result.add("image_input")
        if _field(artifact, "path", _field(artifact, "local_path", None)):
            result.add("file_context")
    return tuple(sorted(result))


def check_provider_capabilities(
    provider: ProviderName | str,
    contract: Any,
) -> tuple[CapabilityCheck, ...]:
    capabilities = provider_capabilities(provider)
    checks: list[CapabilityCheck] = []
    for requirement in required_capabilities(contract):
        attribute = {
            "browser_verification": "supports_browser_verification",
            "command_execution": "supports_command_execution",
            "file_context": "supports_file_context",
            "filesystem_write": "supports_filesystem_write",
            "image_input": "supports_native_images",
            "mcp": "supports_mcp",
            "native_images": "supports_native_images",
            "noninteractive_execution": "supports_noninteractive_execution",
            "permission_modes": "supports_permission_modes",
            "reasoning_effort": "supports_reasoning_effort",
            "resume": "supports_resume",
            "structured_events": "supports_structured_events",
        }.get(requirement)
        supported = bool(attribute and getattr(capabilities, attribute))
        checks.append(
            CapabilityCheck(
                capability=requirement,
                supported=supported,
                message=(
                    f"{capabilities.provider} supports {requirement}."
                    if supported
                    else f"{capabilities.provider} cannot enforce required capability "
                    f"{requirement} for this task."
                ),
            )
        )
    return tuple(checks)


def provider_supports_contract(
    provider: ProviderName | str,
    contract: Any,
) -> bool:
    return all(item.supported for item in check_provider_capabilities(provider, contract))


def _task_mode(contract: Any) -> TaskMode:
    value = _field(contract, "task_mode", TaskMode.CHANGE)
    if isinstance(value, TaskMode):
        return value
    return TaskMode(str(value))


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _iterable(value: Any) -> Iterable[Any]:
    if isinstance(value, (str, bytes, dict)) or value is None:
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()
