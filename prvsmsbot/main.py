from __future__ import annotations

import logging
import os

from .commands import BotCommandService
from .config import Settings
from .n8n_client import N8NClient
from .notifier import IncomingSmsNotifier
from .telegram_app import PrvSmsTelegramApp
from .webhook_server import WebhookServerRunner


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


def main() -> None:
    _load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    settings.validate()

    webhook_server = WebhookServerRunner(
        settings=settings,
        notifier=IncomingSmsNotifier(settings=settings),
    )
    webhook_server.start_in_thread()

    n8n_client = N8NClient(settings)
    commands = BotCommandService(settings=settings, n8n_client=n8n_client)
    telegram_app = PrvSmsTelegramApp(
        bot_token=settings.telegram_bot_token,
        command_service=commands,
        allowed_user_ids=settings.allowed_telegram_user_ids,
    )
    app = telegram_app.build_application()
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
