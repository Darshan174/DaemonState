"""Compatibility shim for the stable workspace and demo-seed routes.

Founder-facing callers should import and reason about ``app.api.workspaces``.
This module remains so older imports do not break while the OSS v1 contract
centers workspace lifecycle on a dedicated module instead of a generic
``admin`` namespace.
"""

from app.api.workspaces import (
    DEFAULT_WORKSPACE_NAME,
    SeedDemoRequest,
    SeedDemoResponse,
    SeedWorkspaceNotFoundError,
    create_workspace,
    get_workspace,
    list_workspaces,
    router,
    seed_demo,
    seed_demo_into_workspace,
    seed_demo_workspace,
)

__all__ = [
    "DEFAULT_WORKSPACE_NAME",
    "SeedDemoRequest",
    "SeedDemoResponse",
    "SeedWorkspaceNotFoundError",
    "create_workspace",
    "get_workspace",
    "list_workspaces",
    "router",
    "seed_demo",
    "seed_demo_into_workspace",
    "seed_demo_workspace",
]
