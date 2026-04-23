"""
bot/listener.py
~~~~~~~~~~~~~~~
Lightweight async HTTP server that receives inbound webhook events from
SMSGate and forwards them to allowed Telegram users.

SMSGate POSTs to WEBHOOK_URL when:
  - a new SMS arrives    → {"type": "sms_received", ...}
  - a delivery report    → {"type": "delivery_report", ...}

The server is intentionally minimal – it trusts the network boundary
(same Docker network) rather than a shared secret, mirroring how
SMSGate itself secures /ussd/live.  If you need extra security you can
add an X-Admin-Key check here.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web
from telegram import Bot

log = logging.getLogger(__name__)


# ── Notification helpers ──────────────────────────────────────────────────────

def _fmt_sms_received(payload: dict[str, Any]) -> str:
    phone   = str(payload.get("phone", "?"))
    content = str(payload.get("content", "(empty)")).strip() or "(empty)"
    date    = str(payload.get("date", ""))
    preview = content[:400] + ("…" if len(content) > 400 else "")
    return (
        f"📩 New SMS\n"
        f"From: {phone}\n"
        f"Date: {date}\n"
        f"\n{preview}"
    )


def _fmt_delivery_report(payload: dict[str, Any]) -> str:
    phone   = str(payload.get("phone", "?"))
    content = str(payload.get("content", "(empty)")).strip() or "(empty)"
    date    = str(payload.get("date", ""))
    return (
        f"📬 Delivery report\n"
        f"From: {phone}\n"
        f"Date: {date}\n"
        f"{content[:300]}"
    )


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

async def _handle_webhook(request: web.Request) -> web.Response:
    bot: Bot                  = request.app["bot"]
    user_ids: tuple[int, ...] = request.app["user_ids"]
    notify_dr: bool           = request.app["notify_delivery_reports"]

    # Parse body
    try:
        raw  = await request.read()
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        log.warning("Webhook received non-JSON body")
        return web.json_response({"ok": False, "error": "bad json"}, status=400)

    if not isinstance(data, dict):
        return web.json_response({"ok": False, "error": "json object required"}, status=400)

    event_type = str(data.get("type", "")).strip().lower()
    log.info("Webhook event: type=%s id=%s phone=%s", event_type, data.get("id"), data.get("phone"))

    if event_type == "sms_received":
        text = _fmt_sms_received(data)
        await _notify_all(bot, user_ids, text)

    elif event_type == "delivery_report":
        if notify_dr:
            text = _fmt_delivery_report(data)
            await _notify_all(bot, user_ids, text)

    else:
        log.debug("Ignoring unknown webhook event type: %s", event_type)

    return web.json_response({"ok": True})


# ── App factory ───────────────────────────────────────────────────────────────

def build_webhook_app(
    *,
    bot: Bot,
    user_ids: tuple[int, ...],
    notify_delivery_reports: bool,
) -> web.Application:
    """
    Build and return the aiohttp Application.

    The app exposes a single endpoint:  POST /webhook
    """
    app = web.Application()
    app["bot"]                    = bot
    app["user_ids"]               = user_ids
    app["notify_delivery_reports"] = notify_delivery_reports

    app.router.add_post("/webhook", _handle_webhook)
    return app


# ── Runner ────────────────────────────────────────────────────────────────────

async def start_webhook_server(
    *,
    bot: Bot,
    user_ids: tuple[int, ...],
    notify_delivery_reports: bool,
    host: str,
    port: int,
) -> web.AppRunner:
    """
    Start the aiohttp webhook server in the current event loop.

    Returns the ``AppRunner`` so the caller can call ``runner.cleanup()``
    on shutdown if needed.
    """
    app    = build_webhook_app(
        bot=bot,
        user_ids=user_ids,
        notify_delivery_reports=notify_delivery_reports,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site   = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Webhook listener started on %s:%s (POST /webhook)", host, port)
    return runner
