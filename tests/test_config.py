from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bot.config import Settings


class TestSettingsTelegramUpdateMode(unittest.TestCase):
    def _base_env(self) -> dict[str, str]:
        return {
            "TELEGRAM_BOT_TOKEN": "tkn",
            "SMSGATE_ADMIN_KEY": "adm",
            "ALLOWED_TELEGRAM_USER_IDS": "123456",
        }

    def test_defaults_to_polling(self) -> None:
        with patch.dict(os.environ, self._base_env(), clear=True):
            settings = Settings.from_env()
            settings.validate()
            self.assertEqual(settings.telegram_update_mode, "polling")

    def test_webhook_mode_requires_public_url(self) -> None:
        env = self._base_env()
        env["TELEGRAM_UPDATE_MODE"] = "webhook"
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()
            with self.assertRaisesRegex(ValueError, "TELEGRAM_WEBHOOK_PUBLIC_URL"):
                settings.validate()

    def test_webhook_mode_accepts_https_public_url(self) -> None:
        env = self._base_env()
        env["TELEGRAM_UPDATE_MODE"] = "webhook"
        env["TELEGRAM_WEBHOOK_PUBLIC_URL"] = "https://bot.example.com"
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()
            settings.validate()
            self.assertEqual(settings.telegram_webhook_path, "/telegram/webhook")

