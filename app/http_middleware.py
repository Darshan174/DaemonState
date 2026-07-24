from __future__ import annotations

from typing import Awaitable, Callable


class RequestBodyLimitMiddleware:
    """Enforce a byte limit even when a client omits Content-Length."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers") or []
        }
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = -1
            if content_length < 0:
                await _send_json_error(
                    send, 400, "invalid_content_length", "Invalid Content-Length header."
                )
                return
            if content_length > self.max_bytes:
                await _send_json_error(
                    send, 413, "request_too_large", "Request body exceeds the configured limit."
                )
                return

        consumed = 0
        limit_exceeded = False
        pending_response_start: dict | None = None
        response_committed = False

        async def limited_receive():
            nonlocal consumed, limit_exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body") or b"")
                if consumed > self.max_bytes:
                    limit_exceeded = True
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal pending_response_start, response_committed
            if message["type"] == "http.response.start":
                # Delay the start until the first body frame. If an inner
                # framework error handler starts a 500 after the receive
                # wrapper rejects a chunk, we can still replace it with the
                # intended 413 response.
                pending_response_start = message
                return
            if limit_exceeded:
                return
            if pending_response_start is not None:
                await send(pending_response_start)
                pending_response_start = None
                response_committed = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_committed:
                raise
            await _send_json_error(
                send, 413, "request_too_large", "Request body exceeds the configured limit."
            )
            return

        if limit_exceeded:
            if response_committed:
                raise RequestBodyTooLarge
            await _send_json_error(
                send, 413, "request_too_large", "Request body exceeds the configured limit."
            )
            return
        if pending_response_start is not None:
            await send(pending_response_start)


class RequestBodyTooLarge(Exception):
    pass


async def _send_json_error(
    send: Callable[[dict], Awaitable[None]],
    status: int,
    code: str,
    message: str,
) -> None:
    import json

    body = json.dumps({
        "error": {"code": code, "message": message},
    }).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})
