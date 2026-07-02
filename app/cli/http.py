from __future__ import annotations

from typing import Any
import httpx


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


def api_request(
    base_url: str,
    method: str,
    path: str,
    payload: Any = None,
    timeout: int = 30,
    api_key: str | None = None,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"X-Context-Engine-API-Key": api_key} if api_key else None
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                resp = client.get(url, headers=headers)
            elif method == "POST":
                resp = client.post(url, json=payload, headers=headers)
            elif method == "PATCH":
                resp = client.patch(url, json=payload, headers=headers)
            elif method == "DELETE":
                resp = client.delete(url, headers=headers)
            else:
                raise APIError(f"Unsupported method: {method}")
    except httpx.RequestError as exc:
        raise APIError(f"Request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise APIError(f"API error {resp.status_code}: {resp.text}", status_code=resp.status_code)
    return resp.json()
