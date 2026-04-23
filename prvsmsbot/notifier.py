from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .categories import MessageCategoryRules, classify_origin, normalize_sender
from .config import Settings


@dataclass
class IncomingSmsNotifier:
    settings: Settings

    @property
    def _rules(self) -> MessageCategoryRules:
        return MessageCategoryRules()

    def notify(self, payload: dict[str, Any]) -> None:
        sms_type = str(payload.get("type", "")).strip().lower()
        if sms_type == "delivery_report":
            if not self.settings.notify_delivery_reports:
                return
            self._notify_delivery_report(payload)
            return

        if sms_type != "sms_received":
            return

        phone = normalize_sender(str(payload.get("phone", "")).strip())
        content = str(payload.get("content", "")).strip()
        date = str(payload.get("date", "")).strip()
        if not content:
            content = "(empty)"

        cls = classify_origin(phone, content, self._rules)
        category = cls.get("label", "unknown")
        preview = content[:120] + ("..." if len(content) > 120 else "")

        message = (
            "New SMS received\n"
            f"From: {phone}\n"
            f"Category: {category}\n"
            f"Date: {date}\n"
            f"Message: {preview}"
        )

        api = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        for user_id in self.settings.allowed_telegram_user_ids:
            try:
                requests.post(
                    api,
                    json={"chat_id": user_id, "text": message},
                    timeout=self.settings.n8n_timeout_seconds,
                )
            except requests.RequestException:
                continue

    def _notify_delivery_report(self, payload: dict[str, Any]) -> None:
        phone = normalize_sender(str(payload.get("phone", "")).strip())
        content = str(payload.get("content", "")).strip() or "(empty)"
        date = str(payload.get("date", "")).strip()

        message = (
            f"Delivery report\nFrom: {phone}\nDate: {date}\nContent: {content[:180]}"
        )

        api = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        for user_id in self.settings.allowed_telegram_user_ids:
            try:
                requests.post(
                    api,
                    json={"chat_id": user_id, "text": message},
                    timeout=self.settings.n8n_timeout_seconds,
                )
            except requests.RequestException:
                continue
