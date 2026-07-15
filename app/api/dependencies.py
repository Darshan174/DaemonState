from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.access import AccessScope
from app.services.auth import request_access_scope


async def get_access_scope(request: Request) -> AccessScope:
    scope = getattr(request.state, "access_scope", None) or request_access_scope(request)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
    return scope
