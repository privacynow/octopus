#!/usr/bin/env python3
"""Minimal Telegram Bot API stub for Compose E2E.

Provides enough of the Bot API for PTB webhook startup and worker-owned output:
- getMe
- setWebhook/deleteWebhook/getWebhookInfo
- sendMessage/sendChatAction
- editMessageText/editMessageReplyMarkup
- answerCallbackQuery
- sendPhoto/sendDocument

This is intentionally a small stdlib-only test stub.
"""
from __future__ import annotations

import argparse
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from urllib.parse import parse_qs, urlparse

_MESSAGE_IDS = count(1)


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _next_message_id() -> int:
    return next(_MESSAGE_IDS)


class _Handler(BaseHTTPRequestHandler):
    server_version = "telegram-api-stub/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_params(self) -> dict[str, object]:
        parsed = urlparse(self.path)
        params: dict[str, object] = {}
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
            params[key] = values[-1] if values else ""

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return params

        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                body = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}
            if isinstance(body, dict):
                params.update(body)
            return params

        if "application/x-www-form-urlencoded" in content_type:
            for key, values in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items():
                params[key] = values[-1] if values else ""
            return params

        # Multipart uploads are not parsed; return query params only.
        return params

    def _write_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _message_result(self, params: dict[str, object], *, text_key: str = "text") -> dict[str, object]:
        chat_id_raw = params.get("chat_id", 0)
        try:
            chat_id = int(chat_id_raw)
        except (TypeError, ValueError):
            chat_id = 0
        text = str(params.get(text_key, "") or params.get("caption", "") or "")
        return {
            "message_id": _next_message_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        }

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._write_json({"ok": True})
            return

        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            self._write_json({"ok": False, "description": "unknown path"}, status=HTTPStatus.NOT_FOUND)
            return
        if segments[0] == "file":
            segments = segments[1:]
        method = segments[1]
        params = self._read_params()

        if method == "getMe":
            self._write_json(
                {
                    "ok": True,
                    "result": {
                        "id": 123456,
                        "is_bot": True,
                        "first_name": "Stub Bot",
                        "username": "stub_bot",
                    },
                }
            )
            return

        if method in {"setWebhook", "deleteWebhook"}:
            self._write_json({"ok": True, "result": True})
            return

        if method == "getWebhookInfo":
            self._write_json(
                {
                    "ok": True,
                    "result": {
                        "url": str(params.get("url", "")),
                        "has_custom_certificate": False,
                        "pending_update_count": 0,
                    },
                }
            )
            return

        if method == "sendMessage":
            self._write_json({"ok": True, "result": self._message_result(params)})
            return

        if method in {"sendPhoto", "sendDocument"}:
            self._write_json({"ok": True, "result": self._message_result(params, text_key="caption")})
            return

        if method == "sendChatAction":
            self._write_json({"ok": True, "result": True})
            return

        if method == "editMessageText":
            self._write_json({"ok": True, "result": self._message_result(params)})
            return

        if method == "editMessageReplyMarkup":
            self._write_json({"ok": True, "result": self._message_result(params)})
            return

        if method == "answerCallbackQuery":
            self._write_json({"ok": True, "result": True})
            return

        if method == "getUpdates":
            self._write_json({"ok": True, "result": []})
            return

        self._write_json({"ok": True, "result": True})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Bot API stub")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
