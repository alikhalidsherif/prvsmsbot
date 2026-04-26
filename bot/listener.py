"""
bot/listener.py
~~~~~~~~~~~~~~~
Lightweight async HTTP server that receives inbound webhook events from
SMSGate and forwards them to allowed Telegram users.

SMSGate POSTs to WEBHOOK_URL when:
  - a new SMS arrives    → {"type": "sms_received", ...}
  - a delivery report    → {"type": "delivery_report", ...}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from aiohttp import web
from telegram import Bot, Update

from .categories import MessageCategoryRules, classify_origin, normalize_sender

log = logging.getLogger(__name__)

_RULES = MessageCategoryRules()

_CATEGORY_ICON: dict[str, str] = {
    "service:bank": "🏦",
    "service:telecom": "📡",
    "service:otp": "🔐",
    "service:service": "🏢",
    "personal": "👤",
    "unknown": "❓",
}


def _short_date(s: str) -> str:
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return s[:16] if len(s) > 16 else s


# ── Notification formatters ───────────────────────────────────────────────────


def _fmt_sms_received(payload: dict[str, Any]) -> str:
    phone = normalize_sender(str(payload.get("phone", "?")))
    content = str(payload.get("content", "")).strip() or "(empty)"
    date = _short_date(str(payload.get("date", "")))
    cls = classify_origin(phone, content, _RULES)
    icon = _CATEGORY_ICON.get(cls["label"], "❓")
    preview = content[:400] + ("…" if len(content) > 400 else "")
    return f"📩 New SMS  {icon}\nFrom: {phone}\n{date}\n\n{preview}"


def _fmt_delivery_report(payload: dict[str, Any]) -> str:
    phone = normalize_sender(str(payload.get("phone", "?")))
    content = str(payload.get("content", "")).strip() or "(empty)"
    date = _short_date(str(payload.get("date", "")))
    return f"📬 Delivery report\nTo: {phone}\n{date}\n{content[:300]}"


# ── Broadcast helper ──────────────────────────────────────────────────────────


async def _notify_all(
    bot: Bot,
    user_ids: tuple[int, ...],
    text: str,
) -> None:
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text)
        except Exception as exc:
            log.warning("Failed to notify user %s: %s", uid, exc)


# ── Request handler ───────────────────────────────────────────────────────────


async def _handle_smsgate_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    user_ids: tuple[int, ...] = request.app["user_ids"]
    notify_dr: bool = request.app["notify_delivery_reports"]

    try:
        raw = await request.read()
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        log.warning("Webhook received non-JSON body")
        return web.json_response({"ok": False, "error": "bad json"}, status=400)

    if not isinstance(data, dict):
        return web.json_response(
            {"ok": False, "error": "json object required"}, status=400
        )

    event_type = str(data.get("type", "")).strip().lower()
    log.info(
        "Webhook event: type=%s id=%s phone=%s",
        event_type,
        data.get("id"),
        data.get("phone"),
    )

    if event_type == "sms_received":
        await _notify_all(bot, user_ids, _fmt_sms_received(data))

    elif event_type == "delivery_report":
        if notify_dr:
            await _notify_all(bot, user_ids, _fmt_delivery_report(data))

    else:
        log.debug("Ignoring unknown webhook event type: %s", event_type)

    return web.json_response({"ok": True})


async def _handle_telegram_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    process_update = request.app["telegram_process_update"]
    expected_secret = request.app["telegram_webhook_secret"]

    if expected_secret:
        got_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got_secret != expected_secret:
            log.warning("Rejected Telegram webhook request with invalid secret token")
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    try:
        payload = await request.json()
    except Exception:
        log.warning("Telegram webhook received non-JSON body")
        return web.json_response({"ok": False, "error": "bad json"}, status=400)

    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "json object required"}, status=400
        )

    try:
        update = Update.de_json(payload, bot)
        if update is None:
            return web.json_response({"ok": True})
        await process_update(update)
    except Exception as exc:
        log.exception("Failed to process Telegram webhook update: %s", exc)
        return web.json_response({"ok": False, "error": "processing failed"}, status=500)

    return web.json_response({"ok": True})


# ── App factory ───────────────────────────────────────────────────────────────


def build_webhook_app(
    *,
    bot: Bot,
    user_ids: tuple[int, ...],
    notify_delivery_reports: bool,
    telegram_process_update: Callable[[Update], Awaitable[None]] | None = None,
    telegram_webhook_path: str | None = None,
    telegram_webhook_secret: str = "",
) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["user_ids"] = user_ids
    app["notify_delivery_reports"] = notify_delivery_reports
    app["telegram_process_update"] = telegram_process_update
    app["telegram_webhook_secret"] = telegram_webhook_secret
    app.router.add_post("/webhook", _handle_smsgate_webhook)
    if telegram_process_update and telegram_webhook_path:
        app.router.add_post(telegram_webhook_path, _handle_telegram_webhook)
    return app


# ── Runner ────────────────────────────────────────────────────────────────────


async def start_webhook_server(
    *,
    bot: Bot,
    user_ids: tuple[int, ...],
    notify_delivery_reports: bool,
    host: str,
    port: int,
    telegram_process_update: Callable[[Update], Awaitable[None]] | None = None,
    telegram_webhook_path: str | None = None,
    telegram_webhook_secret: str = "",
) -> web.AppRunner:
    app = build_webhook_app(
        bot=bot,
        user_ids=user_ids,
        notify_delivery_reports=notify_delivery_reports,
        telegram_process_update=telegram_process_update,
        telegram_webhook_path=telegram_webhook_path,
        telegram_webhook_secret=telegram_webhook_secret,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    if telegram_process_update and telegram_webhook_path:
        log.info(
            "Webhook listener started on %s:%s (POST /webhook, POST %s)",
            host,
            port,
            telegram_webhook_path,
        )
    else:
        log.info("Webhook listener started on %s:%s (POST /webhook)", host, port)
    return runner
