from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping
from typing import Any


INITIALIZE_REQUEST_ID = 1
THREAD_START_REQUEST_ID = 2
TURN_START_REQUEST_ID = 3
MAX_SERVER_LINE_BYTES = 8 * 1024 * 1024


def _emit(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def _send(
    process: asyncio.subprocess.Process,
    payload: Mapping[str, Any],
) -> None:
    if process.stdin is None:
        raise RuntimeError("Codex app-server stdin is unavailable")
    process.stdin.write(
        (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )


async def _forward_stderr(
    stream: asyncio.StreamReader | None,
) -> None:
    if stream is None:
        return
    while chunk := await stream.read(16_384):
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()


def _snake_case(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", text).replace("-", "_").lower()


def _normalized_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    result = dict(item)
    result["type"] = _snake_case(result.get("type"))
    if result["type"] == "user_message":
        # The full compiled context is already persisted as the ContextPack.
        # Do not duplicate it into bounded command output or provider events.
        result.pop("content", None)
        result.pop("text", None)
    return result


def _response_error(message: Mapping[str, Any]) -> str | None:
    error = message.get("error")
    if not isinstance(error, Mapping):
        return None
    return str(error.get("message") or "Codex app-server request failed.").strip()


async def _run(
    *,
    codex_bin: str,
    cwd: str,
    model: str | None,
    effort: str | None,
    prompt: str,
) -> int:
    process = await asyncio.create_subprocess_exec(
        codex_bin,
        "app-server",
        "--stdio",
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    stderr_task = asyncio.create_task(_forward_stderr(process.stderr))
    thread_id: str | None = None
    turn_started = False
    terminal_status: str | None = None

    _send(process, {
        "method": "initialize",
        "id": INITIALIZE_REQUEST_ID,
        "params": {
            "clientInfo": {
                "name": "context_engine",
                "title": "Context Engine",
                "version": "1",
            },
            "capabilities": {"experimentalApi": True},
        },
    })
    await process.stdin.drain()

    try:
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            if len(raw_line) > MAX_SERVER_LINE_BYTES:
                _emit({
                    "type": "error",
                    "message": "Codex app-server returned an oversized event.",
                })
                terminal_status = "failed"
                break
            try:
                message = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (TypeError, ValueError):
                continue
            if not isinstance(message, Mapping):
                continue

            request_id = message.get("id")
            error_message = _response_error(message)
            if error_message is not None:
                _emit({"type": "error", "message": error_message})
                terminal_status = "failed"
                break

            if request_id == INITIALIZE_REQUEST_ID:
                _send(process, {"method": "initialized", "params": {}})
                thread_params: dict[str, Any] = {
                    "cwd": cwd,
                    "sandbox": "workspace-write",
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "auto_review",
                    "ephemeral": False,
                }
                if model:
                    thread_params["model"] = model
                _send(process, {
                    "method": "thread/start",
                    "id": THREAD_START_REQUEST_ID,
                    "params": thread_params,
                })
                await process.stdin.drain()
                continue

            if request_id == THREAD_START_REQUEST_ID:
                result = message.get("result")
                thread = result.get("thread") if isinstance(result, Mapping) else None
                thread_id = (
                    str(thread.get("id") or "").strip()
                    if isinstance(thread, Mapping)
                    else ""
                )
                if not thread_id:
                    _emit({
                        "type": "error",
                        "message": "Codex app-server did not return a thread ID.",
                    })
                    terminal_status = "failed"
                    break
                _emit({
                    "type": "thread.started",
                    "thread_id": thread_id,
                    "visibility_ready": True,
                })
                turn_params: dict[str, Any] = {
                    "threadId": thread_id,
                    "cwd": cwd,
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "auto_review",
                    "input": [{"type": "text", "text": prompt}],
                }
                if model:
                    turn_params["model"] = model
                if effort:
                    turn_params["effort"] = effort
                _send(process, {
                    "method": "turn/start",
                    "id": TURN_START_REQUEST_ID,
                    "params": turn_params,
                })
                await process.stdin.drain()
                continue

            if request_id == TURN_START_REQUEST_ID:
                result = message.get("result")
                turn = result.get("turn") if isinstance(result, Mapping) else None
                turn_id = (
                    str(turn.get("id") or "").strip()
                    if isinstance(turn, Mapping)
                    else ""
                )
                turn_started = True
                _emit({
                    "type": "turn.started",
                    **({"turn_id": turn_id} if turn_id else {}),
                })
                continue

            method = str(message.get("method") or "").strip()
            params = message.get("params")
            params = params if isinstance(params, Mapping) else {}

            if request_id is not None and method:
                _send(process, {
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": (
                            "Interactive requests are unavailable during an "
                            "automatic continuation."
                        ),
                    },
                })
                await process.stdin.drain()
                continue

            if method == "turn/started":
                # The request response is the durable boundary: by then the
                # app-server has accepted the input and the desktop can render
                # the thread. Ignore the earlier notification if it races it.
                continue
            elif method in {"item/started", "item/completed"}:
                _emit({
                    "type": method.replace("/", "."),
                    "item": _normalized_item(params.get("item")),
                })
            elif method == "error":
                error = params.get("error")
                detail = (
                    str(error.get("message") or "").strip()
                    if isinstance(error, Mapping)
                    else str(params.get("message") or "").strip()
                )
                _emit({
                    "type": "error",
                    "message": detail or "Codex app-server reported an error.",
                })
            elif method == "turn/completed":
                turn = params.get("turn")
                turn = turn if isinstance(turn, Mapping) else {}
                terminal_status = str(turn.get("status") or "failed").strip()
                if terminal_status == "completed":
                    _emit({
                        "type": "turn.completed",
                        "status": terminal_status,
                    })
                else:
                    error = turn.get("error")
                    detail = (
                        str(error.get("message") or "").strip()
                        if isinstance(error, Mapping)
                        else ""
                    )
                    _emit({
                        "type": "error",
                        "subtype": f"turn_{terminal_status}",
                        "message": detail or f"Codex turn ended as {terminal_status}.",
                    })
                break

        if terminal_status is None:
            _emit({
                "type": "error",
                "message": (
                    "Codex app-server exited before the continuation turn "
                    f"{'started' if not turn_started else 'completed'}."
                ),
            })
            terminal_status = "failed"
        return 0 if terminal_status == "completed" else 1
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        await asyncio.gather(stderr_task, return_exceptions=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one persistent Codex app-server continuation turn.",
    )
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    return parser


def main() -> int:
    args = _parser().parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        _emit({"type": "error", "message": "Continuation context is empty."})
        return 2
    try:
        return asyncio.run(_run(
            codex_bin=args.codex_bin,
            cwd=args.cwd,
            model=args.model,
            effort=args.effort,
            prompt=prompt,
        ))
    except (OSError, RuntimeError, ValueError) as exc:
        _emit({"type": "error", "message": str(exc)})
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
