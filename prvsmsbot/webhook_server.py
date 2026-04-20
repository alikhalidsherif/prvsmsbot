from __future__ import annotations

import json
import threading
from hmac import compare_digest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .notifier import IncomingSmsNotifier


@dataclass
class WebhookServerRunner:
    settings: Settings
    notifier: IncomingSmsNotifier

    def start_in_thread(self) -> ThreadingHTTPServer:
        token = self.settings.prv_bot_token
        notifier = self.notifier

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/webhook/smsgate":
                    self._send(404, {"ok": False, "error": "not found"})
                    return

                query = parse_qs(parsed.query)
                header_token = str(self.headers.get("X-Prv-Bot-Token", "")).strip()
                query_token = str((query.get("token") or [""])[0]).strip()
                provided = header_token or query_token
                if not compare_digest(provided, token):
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0

                try:
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    data = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    self._send(400, {"ok": False, "error": "bad json"})
                    return

                if not isinstance(data, dict):
                    self._send(400, {"ok": False, "error": "json object required"})
                    return

                notifier.notify(data)
                self._send(200, {"ok": True})

            def log_message(self, format: str, *args) -> None:
                return

        server = ThreadingHTTPServer(
            (self.settings.webhook_host, self.settings.webhook_port),
            Handler,
        )

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
