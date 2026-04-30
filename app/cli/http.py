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
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                resp = client.get(url)
            elif method == "POST":
                resp = client.post(url, json=payload)
            elif method == "PATCH":
                resp = client.patch(url, json=payload)
            elif method == "DELETE":
                resp = client.delete(url)
            else:
                raise APIError(f"Unsupported method: {method}")
    except httpx.RequestError as exc:
        raise APIError(f"Request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise APIError(f"API error {resp.status_code}: {resp.text}", status_code=resp.status_code)
    return resp.json()
