from __future__ import annotations

import unittest
from dataclasses import replace
from typing import cast

from prvsmsbot.commands import BotCommandService
from prvsmsbot.config import Settings
from prvsmsbot.n8n_client import N8NClient


class FakeN8NClient:
    def send_sms(self, to: str, message: str):
        return {
            "ok": True,
            "state": "success",
            "reason": "all recipients succeeded",
            "to": [to],
        }

    def inbox(
        self,
        *,
        page: int,
        limit: int,
        sender: str | None,
        search: str | None,
        msg_type: str,
    ):
        return {
            "total": 3,
            "messages": [
                {
                    "phone": "127",
                    "content": "CBE OTP 1234",
                    "date": "2026-04-18 10:00:00",
                },
                {
                    "phone": "+251911000111",
                    "content": "hello",
                    "date": "2026-04-18 09:00:00",
                },
                {
                    "phone": "EthioTel",
                    "content": "bundle info",
                    "date": "2026-04-18 08:00:00",
                },
            ],
        }

    def outbox(self, *, page: int, limit: int):
        return {
            "total": 1,
            "messages": [
                {
                    "recipients": '["+251911000111"]',
                    "content": "ok",
                    "sent_at": "2026-04-18 11:00:00",
                }
            ],
        }

    def health(self):
        return {
            "status": "healthy",
            "consecutive_failures": 0,
            "total_failures": 1,
            "last_poll_success_at": "now",
            "last_sms_received_at": "now",
        }

    def ussd_single(self, code: str):
        return {"code": code, "response": "balance: 12 ETB"}

    def ussd_session(self, steps: list[str]):
        return {"history": [{"step": 1, "input": steps[0], "response": "menu"}]}

    def ussd_live(self, action: str, chat_id: int, value: str | None = None):
        return {
            "status": "active",
            "menu": "next",
            "action": action,
            "chat_id": chat_id,
            "value": value,
        }


def _settings() -> Settings:
    base = Settings.from_env()
    return replace(
        base,
        telegram_bot_token="token",
        prv_bot_token="token",
    )


class CommandServiceTests(unittest.TestCase):
    def test_inbox_bank_filter(self) -> None:
        service = BotCommandService(
            settings=_settings(),
            n8n_client=cast(N8NClient, FakeN8NClient()),
        )
        out = service.inbox_view(
            title="Bank", mode="bank", sender=None, search=None, page=1, limit=20
        )
        joined = "\n".join(out)
        self.assertIn("service:bank", joined)

    def test_senders_view(self) -> None:
        service = BotCommandService(
            settings=_settings(),
            n8n_client=cast(N8NClient, FakeN8NClient()),
        )
        out = service.senders_view(page=1, limit=20, mode="all")
        self.assertTrue(any("Top Senders" in chunk for chunk in out))


if __name__ == "__main__":
    unittest.main()
