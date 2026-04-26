"""
bot/main.py
~~~~~~~~~~~
Entry point – wires the SMSGate gateway client, Telegram bot, and the
inbound webhook listener together inside a single asyncio event loop.

Startup sequence
----------------
1. Load .env (if present) and parse Settings.
2. Build the Telegram Application (python-telegram-bot v20+).
3. Register all command + callback handlers.
4. Inject SMSGateClient into bot_data.
5. Optionally register the bot's webhook URL with SMSGate
   (if SMSGATE_WEBHOOK_URL is set in the environment).
6. Start the aiohttp webhook listener concurrently.
7. Run Telegram polling until interrupted.
8. Clean up.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import Settings
from .gateway import SMSGateClient
from .handlers import (
    _USSD_TASK_KEY,
    cb_confirm,
    cb_inbox,
    cb_outbox,
    cmd_clearinbox,
    cmd_config,
    cmd_delete,
    cmd_device,
    cmd_health,
    cmd_help,
    cmd_inbox,
    cmd_outbox,
    cmd_ping,
    cmd_reboot,
    cmd_send,
    cmd_smsview,
    cmd_start,
    cmd_unread,
    cmd_ussd,
    cmd_ussdcancel,
    cmd_ussdlive,
    cmd_ussdsession,
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
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


def _normalize_proxy_url(url: str) -> str:
    """Ensure socks5 URLs use socks5h so DNS resolution goes through the proxy."""
    raw = (url or "").strip()
    if raw.startswith("socks5://"):
        return "socks5h://" + raw[len("socks5://") :]
    return raw


def _build_telegram_application(
    token: str, proxy_url: str, log: logging.Logger
) -> Application:
    builder = Application.builder().token(token)
    if proxy_url:
        try:
            from telegram.request import HTTPXRequest  # type: ignore
        except Exception:
            log.warning(
                "OUTBOUND_PROXY_URL is set, but telegram.request.HTTPXRequest "
                "is unavailable in this runtime; Telegram may connect without proxy."
            )
        else:
            try:
                request = HTTPXRequest(proxy_url=proxy_url)
            except TypeError:
                request = HTTPXRequest(proxy=proxy_url)
            builder = builder.request(request)
    return builder.build()


# ── Application builder ───────────────────────────────────────────────────────


def build_application(settings: Settings) -> Application:
    log = logging.getLogger(__name__)
    proxy_url = _normalize_proxy_url(settings.outbound_proxy_url)

    gw = SMSGateClient(
        base_url=settings.smsgate_base_url,
        admin_key=settings.smsgate_admin_key,
        timeout=settings.gateway_timeout_seconds,
        proxy_url=proxy_url,
    )

    app: Application = _build_telegram_application(
        token=settings.telegram_bot_token,
        proxy_url=proxy_url,
        log=log,
    )

    app.bot_data["gateway"] = gw

    user_filter = filters.ChatType.PRIVATE & filters.User(
        user_id=list(settings.allowed_telegram_user_ids)
    )

    # ── Command handlers ──────────────────────────────────────────────────────
    for name, handler in [
        ("start", cmd_start),
        ("help", cmd_help),
        ("ping", cmd_ping),
        ("health", cmd_health),
        ("send", cmd_send),
        ("inbox", cmd_inbox),
        ("outbox", cmd_outbox),
        ("unread", cmd_unread),
        ("smsview", cmd_smsview),
        ("delete", cmd_delete),
        ("clearinbox", cmd_clearinbox),
        ("device", cmd_device),
        ("config", cmd_config),
        ("reboot", cmd_reboot),
        ("ussd", cmd_ussd),
        ("ussdsession", cmd_ussdsession),
        ("ussdlive", cmd_ussdlive),
        ("ussdcancel", cmd_ussdcancel),
    ]:
        app.add_handler(CommandHandler(name, handler, filters=user_filter))

    # ── Inline keyboard callbacks ─────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_inbox, pattern=r"^inbox\|"))
    app.add_handler(CallbackQueryHandler(cb_outbox, pattern=r"^outbox\|"))
    app.add_handler(CallbackQueryHandler(cb_confirm, pattern=r"^(yes|no)(\|.*)?$"))

    # ── Plain-text → live USSD input ──────────────────────────────────────────
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

    # ── Optionally register webhook URL with SMSGate ──────────────────────────
    if settings.smsgate_webhook_url:
        gw: SMSGateClient = tg_app.bot_data["gateway"]
        try:
            await gw.set_config(webhook_url=settings.smsgate_webhook_url)
            log.info("Registered SMSGate webhook URL: %s", settings.smsgate_webhook_url)
        except Exception as exc:
            log.warning("Could not register SMSGate webhook URL: %s", exc)

    # ── Start aiohttp inbound webhook listener ────────────────────────────────
    webhook_runner = await start_webhook_server(
        bot=tg_app.bot,
        user_ids=settings.allowed_telegram_user_ids,
        notify_delivery_reports=settings.notify_delivery_reports,
        host=settings.webhook_host,
        port=settings.webhook_port,
    )

    log.info(
        "SMSGate base URL: %s  |  webhook listener: %s:%s",
        settings.smsgate_base_url,
        settings.webhook_host,
        settings.webhook_port,
    )

    try:
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]

        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            log.info("Stop signal received – shutting down.")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass  # Windows

        await stop_event.wait()

    finally:
        await tg_app.updater.stop()  # type: ignore[union-attr]
        await tg_app.stop()
        await tg_app.shutdown()
        await webhook_runner.cleanup()
        log.info("Shutdown complete.")


def main() -> None:
    _load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    settings.validate()

    asyncio.run(_async_main(settings))


if __name__ == "__main__":
    main()
