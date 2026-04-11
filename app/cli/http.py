from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request


class APIError(RuntimeError):
    """Raised when an API request fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def api_request(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        query = parse.urlencode(
            {key: value for key, value in params.items() if value is not None},
            doseq=True,
        )
        if query:
            url = f"{url}?{query}"

    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        detail = _extract_detail(body) or exc.reason
        raise APIError(
            f"{method} {path} failed with {exc.code}: {detail}",
            status_code=exc.code,
        ) from exc
    except error.URLError as exc:
        raise APIError(f"Unable to reach {url}: {exc.reason}") from exc

    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _extract_detail(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or None

    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if detail is not None:
        return json.dumps(detail, sort_keys=True)
    return json.dumps(payload, sort_keys=True)
