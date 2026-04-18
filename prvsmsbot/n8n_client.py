from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings


class N8NClientError(RuntimeError):
    pass


@dataclass
class N8NClient:
    settings: Settings

    def _url(self, path: str) -> str:
        cleaned = path.strip("/")
        return f"{self.settings.n8n_webhook_base_url}/{cleaned}"

    def call(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Prv-Bot-Token": self.settings.prv_bot_token,
        }
        url = self._url(path)
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.settings.n8n_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise N8NClientError(f"n8n request failed: {exc}") from exc

        if resp.status_code >= 400:
            body = resp.text.strip()[:500]
            raise N8NClientError(
                f"n8n returned {resp.status_code} for {path}: {body or 'empty body'}"
            )

        if not resp.content:
            return {}
        try:
            parsed = resp.json()
        except ValueError as exc:
            raise N8NClientError("n8n did not return JSON") from exc
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    def send_sms(self, to: str, message: str) -> dict[str, Any]:
        return self.call(
            self.settings.n8n_send_sms_path, {"to": to, "message": message}
        )

    def inbox(
        self,
        *,
        page: int,
        limit: int,
        sender: str | None,
        search: str | None,
        msg_type: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "type": msg_type,
        }
        if sender:
            payload["phone"] = sender
        if search:
            payload["search"] = search
        return self.call(self.settings.n8n_inbox_path, payload)

    def outbox(self, *, page: int, limit: int) -> dict[str, Any]:
        return self.call(self.settings.n8n_outbox_path, {"page": page, "limit": limit})

    def ussd_single(self, code: str) -> dict[str, Any]:
        return self.call(self.settings.n8n_ussd_single_path, {"code": code})

    def ussd_session(self, steps: list[str]) -> dict[str, Any]:
        return self.call(self.settings.n8n_ussd_session_path, {"steps": steps})

    def ussd_live(
        self,
        action: str,
        chat_id: int,
        value: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": action,
            "chat_id": chat_id,
        }
        if value is not None:
            payload["value"] = value
        return self.call(self.settings.n8n_ussd_live_path, payload)

    def health(self) -> dict[str, Any]:
        return self.call(self.settings.n8n_health_path, {})
