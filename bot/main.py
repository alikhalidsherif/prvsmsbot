"""
bot/main.py
~~~~~~~~~~~
Entry point – wires the SMSGate gateway client, Telegram bot, and the
inbound webhook listener together inside a single asyncio event loop.

Startup sequence
----------------
1. Load .env (if present) and parse Settings.
2. Build the Telegram Application (python-telegram-bot v20+).
3. Register all command handlers and the USSD-live plain-text handler.
4. Inject the SMSGateClient into bot_data so handlers can reach it.
5. Start the aiohttp webhook listener concurrently.
6. Run Telegram polling until interrupted.
7. Clean up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from telegram import Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import Settings
from .gateway import SMSGateClient
from .handlers import (
    _USSD_TASK_KEY,
    cmd_health,
    cmd_help,
    cmd_inbox,
    cmd_outbox,
    cmd_ping,
    cmd_send,
    cmd_start,
    cmd_ussd,
    cmd_ussdcancel,
    cmd_ussdsession,
    cmd_ussdlive,
    handle_ussd_live_input,
)
from .listener import start_webhook_server


# ── .env loader ───────────────────────────────────────────────────────────────

def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key   = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


# ── Authorization filter ──────────────────────────────────────────────────────

def _build_user_filter(allowed_ids: tuple[int, ...]) -> filters.BaseFilter:
    """
    Return a filter that passes only private messages from allowed user IDs.
    Silently drops everything else.
    """
    return (
        filters.ChatType.PRIVATE
        & filters.User(user_id=list(allowed_ids))
    )


# ── USSD live input filter ────────────────────────────────────────────────────

class _UssdLiveActiveFilter(filters.MessageFilter):
    """
    Pass plain-text messages only when a /ussdlive session is active
    in the current chat.  This avoids catching every text message as
    a USSD input.
    """

    def filter(self, message):  # type: ignore[override]
        # context.chat_data is not available here, so we use a class-level set.
        # The set is populated/cleared by cmd_ussdlive / cleanup in _run_ws.
        return message.chat_id in _UssdLiveActiveFilter._active_chats

    _active_chats: set[int] = set()


def mark_ussd_active(chat_id: int) -> None:
    _UssdLiveActiveFilter._active_chats.add(chat_id)


def mark_ussd_inactive(chat_id: int) -> None:
    _UssdLiveActiveFilter._active_chats.discard(chat_id)


# ── Application builder ───────────────────────────────────────────────────────

def build_application(settings: Settings) -> Application:
    gw  = SMSGateClient(
        base_url  = settings.smsgate_base_url,
        admin_key = settings.smsgate_admin_key,
        timeout   = settings.gateway_timeout_seconds,
    )

    app: Application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Inject shared gateway into bot_data (available via context.bot_data)
    app.bot_data["gateway"] = gw

    user_filter = _build_user_filter(settings.allowed_telegram_user_ids)

    # ── Command handlers ──────────────────────────────────────────────────────
    for name, handler in [
        ("start",       cmd_start),
        ("help",        cmd_help),
        ("ping",        cmd_ping),
        ("health",      cmd_health),
        ("send",        cmd_send),
        ("inbox",       cmd_inbox),
        ("outbox",      cmd_outbox),
        ("ussd",        cmd_ussd),
        ("ussdsession", cmd_ussdsession),
        ("ussdlive",    cmd_ussdlive),
        ("ussdcancel",  cmd_ussdcancel),
    ]:
        app.add_handler(CommandHandler(name, handler, filters=user_filter))

    # ── Plain-text → USSD live input ──────────────────────────────────────────
    # Fires only when a live session is open (checked inside the handler).
    app.add_handler(
        MessageHandler(
            user_filter & filters.TEXT & ~filters.COMMAND,
            handle_ussd_live_input,
        )
    )

    return app


# ── Main ──────────────────────────────────────────────────────────────────────

async def _async_main(settings: Settings) -> None:
    log = logging.getLogger(__name__)

    tg_app = build_application(settings)

    # Start the inbound webhook listener (aiohttp) in the same event loop
    webhook_runner = await start_webhook_server(
        bot                     = tg_app.bot,
        user_ids                = settings.allowed_telegram_user_ids,
        notify_delivery_reports = settings.notify_delivery_reports,
        host                    = settings.webhook_host,
        port                    = settings.webhook_port,
    )

    log.info(
        "SMSGate base URL: %s  |  webhook listener: %s:%s",
        settings.smsgate_base_url,
        settings.webhook_host,
        settings.webhook_port,
    )

    try:
        # python-telegram-bot v20 + asyncio: use run_polling inside the loop
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]

        # Block until a stop signal is received
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            log.info("Stop signal received – shutting down.")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows: signal handlers not supported in asyncio loop
                pass

        await stop_event.wait()

    finally:
        await tg_app.updater.stop()    # type: ignore[union-attr]
        await tg_app.stop()
        await tg_app.shutdown()
        await webhook_runner.cleanup()
        log.info("Shutdown complete.")


def main() -> None:
    _load_dotenv()

    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    settings.validate()

    asyncio.run(_async_main(settings))


if __name__ == "__main__":
    main()
