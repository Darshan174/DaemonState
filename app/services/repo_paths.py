from __future__ import annotations

from pathlib import Path

from app.config import comma_separated, settings


class RepositoryPathNotAllowed(ValueError):
    pass


def validated_repository_path(value: str | Path) -> Path:
    requested = Path(value).expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RepositoryPathNotAllowed(
            f"repo_path must be an existing directory: {requested}"
        ) from exc
    if not resolved.is_dir():
        raise RepositoryPathNotAllowed(f"repo_path is not a directory: {resolved}")

    configured_roots = comma_separated(settings.allowed_repo_roots)
    if not configured_roots:
        if settings.environment.strip().lower() == "production":
            raise RepositoryPathNotAllowed("No repository roots are configured")
        return resolved

    allowed_roots: list[Path] = []
    for root in configured_roots:
        try:
            allowed = Path(root).expanduser().resolve(strict=True)
        except FileNotFoundError:
            continue
        if allowed.is_dir():
            allowed_roots.append(allowed)

    if not any(resolved == allowed or resolved.is_relative_to(allowed) for allowed in allowed_roots):
        raise RepositoryPathNotAllowed(
            "repo_path is outside the configured repository roots"
        )
    return resolved
