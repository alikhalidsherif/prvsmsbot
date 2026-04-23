"""
bot/handlers.py
~~~~~~~~~~~~~~~
One async function per Telegram command.
All SMSGate calls go through ``SMSGateClient`` in gateway.py.

Live USSD (/ussdlive):
    The WebSocket connection is kept open in a per-chat asyncio Task.
    The Task feeds menu replies back into the bot via ``bot.send_message``.
    Subsequent Telegram messages from the same chat are forwarded as USSD
    inputs by the /ussdinput command (or any plain text handled by the
    conversation filter set up in main.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
import websockets.exceptions
from telegram import Update
from telegram.ext import ContextTypes

from .gateway import (
    GatewayBusy,
    GatewayError,
    GatewayModemError,
    GatewayTimeout,
    GatewayUnavailable,
    SMSGateClient,
)

log = logging.getLogger(__name__)

# ── helpers ───────────────────────────────────────────────────────────────────

# Context key where the active USSD-live task is stored per-chat.
_USSD_TASK_KEY = "ussd_live_task"
# Queue used to send user inputs into the WS task.
_USSD_QUEUE_KEY = "ussd_live_queue"


def _gw(context: ContextTypes.DEFAULT_TYPE) -> SMSGateClient:
    """Pull the shared SMSGateClient from bot_data."""
    return context.bot_data["gateway"]


def _fmt_error(exc: Exception) -> str:
    if isinstance(exc, GatewayUnavailable):
        return "Gateway unavailable – check that SMSGate is running."
    if isinstance(exc, GatewayBusy):
        return "Another USSD session is active – try again shortly."
    if isinstance(exc, GatewayTimeout):
        return "Modem did not respond in time (504)."
    if isinstance(exc, GatewayModemError):
        return "Modem / API error (502)."
    if isinstance(exc, GatewayError):
        return f"Gateway error: {exc}"
    return f"Unexpected error: {exc}"


def _page_limit(args: list[str], default_limit: int = 20) -> tuple[int, int]:
    page, limit = 1, default_limit
    if len(args) >= 1:
        try:
            page = max(1, int(args[0]))
        except ValueError:
            pass
    if len(args) >= 2:
        try:
            limit = max(5, min(200, int(args[1])))
        except ValueError:
            pass
    return page, limit


def _chunk(lines: list[str], max_chars: int = 3800) -> list[str]:
    """Split a list of rendered lines into Telegram-safe message chunks."""
    chunks: list[str] = []
    buf: list[str] = []
    length = 0
    for line in lines:
        if length + len(line) + 1 > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, length = [], 0
        buf.append(line)
        length += len(line) + 1
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks or ["(no content)"]


async def _reply_many(update: Update, chunks: list[str]) -> None:
    for text in chunks:
        await update.effective_message.reply_text(text)  # type: ignore[union-attr]


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *prvsmsbot* – direct SMSGate control\n\n"
        "Quick commands:\n"
        "• /send \\+2519XXXXXXXX \\<msg\\>\n"
        "• /inbox \\[page\\] \\[limit\\]\n"
        "• /outbox \\[page\\] \\[limit\\]\n"
        "• /health\n"
        "• /ussd \\*804\\#\n"
        "• /ussdsession \\*804\\# 1 2\n"
        "• /ussdlive  — interactive USSD over Telegram\n"
        "• /ussdcancel\n"
        "• /ping\n"
        "• /help"
    )
    await update.effective_message.reply_text(text, parse_mode="MarkdownV2")  # type: ignore[union-attr]


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Commands\n"
        "/send <phone> <message>          — send SMS\n"
        "/inbox [page] [limit]            — received SMS history\n"
        "/outbox [page] [limit]           — sent SMS history\n"
        "/health                          — modem health + signal\n"
        "/ussd <code>                     — single-shot USSD\n"
        "/ussdsession <s1> <s2> ...       — automated multi-step USSD\n"
        "/ussdlive <code>                 — start live USSD session\n"
        "  (reply with any text to send USSD inputs)\n"
        "/ussdcancel                      — cancel live USSD session\n"
        "/ping                            — bot liveness check\n"
        "/help                            — this message"
    )
    await update.effective_message.reply_text(text)  # type: ignore[union-attr]


# ── /ping ─────────────────────────────────────────────────────────────────────

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("pong 🏓")  # type: ignore[union-attr]


# ── /health ───────────────────────────────────────────────────────────────────

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Checking modem health…")  # type: ignore[union-attr]
    try:
        data = await _gw(context).health_modem()
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    status      = data.get("status", "unknown")
    signal      = data.get("signal_strength", data.get("signal", "?"))
    operator    = data.get("operator", data.get("network_name", "?"))
    cons_fail   = data.get("consecutive_failures", "?")
    total_fail  = data.get("total_failures", "?")
    last_ok     = data.get("last_poll_success_at", "-")
    last_sms    = data.get("last_sms_received_at", "-")
    last_back   = data.get("last_backoff_seconds", "-")

    text = (
        f"📡 Modem health\n"
        f"Status:              {status}\n"
        f"Operator:            {operator}\n"
        f"Signal:              {signal}\n"
        f"Consecutive failures:{cons_fail}\n"
        f"Total failures:      {total_fail}\n"
        f"Last poll success:   {last_ok}\n"
        f"Last SMS received:   {last_sms}\n"
        f"Last backoff (s):    {last_back}"
    )
    await update.effective_message.reply_text(text)  # type: ignore[union-attr]


# ── /send ─────────────────────────────────────────────────────────────────────

async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("Usage: /send <phone> <message>")  # type: ignore[union-attr]
        return

    phone   = args[0]
    message = " ".join(args[1:]).strip()
    if not message:
        await update.effective_message.reply_text("Message is empty.")  # type: ignore[union-attr]
        return

    await update.effective_message.reply_text("Sending…")  # type: ignore[union-attr]
    try:
        data = await _gw(context).sms_send(phone, message)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    result = data.get("result", "?")
    to     = ", ".join(str(r) for r in data.get("to", [phone]))
    dr     = "yes" if data.get("delivery_report") else "no"
    text   = (
        f"Send result: {result}\n"
        f"To: {to}\n"
        f"Delivery report: {dr}\n"
        f"Message: {data.get('message', message)}"
    )
    await update.effective_message.reply_text(text)  # type: ignore[union-attr]


# ── /inbox ────────────────────────────────────────────────────────────────────

async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args         = context.args or []
    page, limit  = _page_limit(args)
    gw           = _gw(context)

    await update.effective_message.reply_text(f"Fetching inbox (page {page}, limit {limit})…")  # type: ignore[union-attr]
    try:
        data = await gw.sms_history(page=page, limit=limit)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    messages = data.get("messages") or []
    total    = data.get("total", "?")

    if not messages:
        await update.effective_message.reply_text("Inbox: no messages found.")  # type: ignore[union-attr]
        return

    lines = []
    for msg in messages:
        phone   = str(msg.get("phone", "?"))
        content = str(msg.get("content", "")).replace("\n", " ")[:120]
        date    = str(msg.get("date", ""))
        lines.append(f"📨 {phone} | {date}\n{content}")

    header = f"Inbox (page {page}, showing {len(messages)}, total {total})"
    chunks = _chunk(lines)
    await _reply_many(update, [f"{header}\n\n{chunks[0]}"] + chunks[1:])


# ── /outbox ───────────────────────────────────────────────────────────────────

async def cmd_outbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args         = context.args or []
    page, limit  = _page_limit(args)
    gw           = _gw(context)

    await update.effective_message.reply_text(f"Fetching outbox (page {page}, limit {limit})…")  # type: ignore[union-attr]
    try:
        data = await gw.sms_sent(page=page, limit=limit)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    messages = data.get("messages") or []
    total    = data.get("total", "?")

    if not messages:
        await update.effective_message.reply_text("Outbox: no messages found.")  # type: ignore[union-attr]
        return

    lines = []
    for msg in messages:
        # SMSGate /sms/sent items use "recipients" or "to"
        recipients = msg.get("recipients") or msg.get("to") or "?"
        if isinstance(recipients, list):
            recipients = ", ".join(str(r) for r in recipients)
        content = str(msg.get("content") or msg.get("message", "")).replace("\n", " ")[:120]
        date    = str(msg.get("sent_at") or msg.get("date", ""))
        lines.append(f"📤 {recipients} | {date}\n{content}")

    header = f"Outbox (page {page}, showing {len(messages)}, total {total})"
    chunks = _chunk(lines)
    await _reply_many(update, [f"{header}\n\n{chunks[0]}"] + chunks[1:])


# ── /ussd ─────────────────────────────────────────────────────────────────────

async def cmd_ussd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Usage: /ussd <code>  e.g. /ussd *804#")  # type: ignore[union-attr]
        return

    code = args[0]
    await update.effective_message.reply_text(f"Running USSD {code}…")  # type: ignore[union-attr]
    try:
        data = await _gw(context).ussd_send(code)
    except GatewayBusy:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Another USSD session is active – try again shortly."
        )
        return
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    response = str(data.get("response") or data)
    await update.effective_message.reply_text(f"USSD {code}\n\n{response}")  # type: ignore[union-attr]


# ── /ussdsession ──────────────────────────────────────────────────────────────

async def cmd_ussdsession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ussdsession <step1> <step2> ...

    Each whitespace-separated argument is treated as one USSD step, so:
        /ussdsession *804# 1 2
    sends steps ["*804#", "1", "2"].
    """
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /ussdsession <step1> <step2> …\n"
            "Example: /ussdsession *804# 1"
        )
        return

    steps = [a.strip() for a in args if a.strip()]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"Running USSD session ({len(steps)} steps)…"
    )
    try:
        data = await _gw(context).ussd_session(steps)
    except GatewayBusy:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Another USSD session is active – try again shortly."
        )
        return
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    history = data.get("history") or []
    if not history:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"No history in response.\nRaw: {data}"
        )
        return

    lines = []
    for row in history:
        step      = row.get("step")
        inp       = row.get("input", "")
        response  = str(row.get("response") or row.get("error") or "-")
        lines.append(f"Step {step} [{inp}]\n{response}")

    header = f"USSD Session ({data.get('steps_run', '?')} steps run)"
    chunks = _chunk(lines)
    await _reply_many(update, [f"{header}\n\n{chunks[0]}"] + chunks[1:])


# ── /ussdlive – interactive WebSocket USSD ────────────────────────────────────

async def cmd_ussdlive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ussdlive <code>

    Opens a WebSocket to /ussd/live, sends the initial code, and streams
    menu replies back as Telegram messages.  The connection stays open:
    subsequent plain-text messages from the user are treated as USSD inputs
    (wired in main.py via a MessageHandler with a filter).

    Only one live session per chat is allowed.
    """
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /ussdlive <code>  — e.g. /ussdlive *804#\n"
            "Then type your menu choices as plain messages.\n"
            "Use /ussdcancel to end the session."
        )
        return

    code    = args[0]
    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    # Prevent double-start
    existing_task: asyncio.Task[Any] | None = context.chat_data.get(_USSD_TASK_KEY)  # type: ignore[union-attr]
    if existing_task and not existing_task.done():
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "A live USSD session is already running in this chat.\n"
            "Use /ussdcancel to end it first."
        )
        return

    input_queue: asyncio.Queue[str | None] = asyncio.Queue()
    context.chat_data[_USSD_TASK_KEY]  = None  # type: ignore[union-attr]
    context.chat_data[_USSD_QUEUE_KEY] = input_queue  # type: ignore[union-attr]

    ws_url = _gw(context).ws_url_ussd_live()

    async def _run_ws() -> None:
        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:  # type: ignore[attr-defined]
                # 1. Wait for ready
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                status = msg.get("status", "")
                if status == "busy":
                    await context.bot.send_message(
                        chat_id,
                        "The modem is busy with another USSD session – try again shortly.",
                    )
                    return
                if status != "ready":
                    await context.bot.send_message(
                        chat_id, f"Unexpected server message: {msg}"
                    )
                    return

                # 2. Send initial code
                await ws.send(json.dumps({"code": code}))
                await context.bot.send_message(
                    chat_id,
                    f"Live USSD session started ({code})\n"
                    "Type your menu choice and send. Use /ussdcancel to stop.",
                )

                # 3. Loop: recv menu, wait for user input, send input
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=130)
                    srv = json.loads(raw)

                    if "menu" in srv:
                        await context.bot.send_message(chat_id, f"📟 {srv['menu']}")
                        # Wait for user's next USSD input (or cancel sentinel None)
                        user_input = await asyncio.wait_for(
                            input_queue.get(), timeout=120
                        )
                        if user_input is None:
                            # User cancelled
                            await ws.send(json.dumps({"action": "cancel"}))
                            break
                        await ws.send(json.dumps({"input": user_input}))

                    elif srv.get("status") == "cancelled":
                        await context.bot.send_message(
                            chat_id, "Live USSD session cancelled."
                        )
                        break

                    elif srv.get("status") == "timeout":
                        err = srv.get("error", "session timed out")
                        await context.bot.send_message(
                            chat_id, f"Live USSD session timed out: {err}"
                        )
                        break

                    elif "error" in srv:
                        await context.bot.send_message(
                            chat_id, f"USSD error: {srv['error']}"
                        )
                        break

                    elif srv.get("status") == "pong":
                        pass  # keepalive – ignore silently

        except asyncio.TimeoutError:
            await context.bot.send_message(
                chat_id,
                "Live USSD session timed out waiting for modem response.",
            )
        except websockets.exceptions.ConnectionClosed as exc:
            log.warning("USSD live WS closed: %s", exc)
            await context.bot.send_message(
                chat_id, "Live USSD WebSocket connection closed."
            )
        except Exception as exc:
            log.exception("USSD live WS error: %s", exc)
            await context.bot.send_message(
                chat_id, f"Live USSD error: {exc}"
            )
        finally:
            context.chat_data.pop(_USSD_TASK_KEY, None)   # type: ignore[union-attr]
            context.chat_data.pop(_USSD_QUEUE_KEY, None)  # type: ignore[union-attr]

    task = asyncio.create_task(_run_ws())
    context.chat_data[_USSD_TASK_KEY] = task  # type: ignore[union-attr]


# ── /ussdcancel ───────────────────────────────────────────────────────────────

async def cmd_ussdcancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    task: asyncio.Task[Any] | None = context.chat_data.get(_USSD_TASK_KEY)  # type: ignore[union-attr]
    queue: asyncio.Queue[str | None] | None = context.chat_data.get(_USSD_QUEUE_KEY)  # type: ignore[union-attr]

    if task is None or task.done():
        await update.effective_message.reply_text("No active live USSD session.")  # type: ignore[union-attr]
        return

    # Signal cancellation via the queue (sentinel None)
    if queue is not None:
        await queue.put(None)

    await update.effective_message.reply_text("Cancelling live USSD session…")  # type: ignore[union-attr]


# ── Plain-text handler for live USSD inputs ───────────────────────────────────

async def handle_ussd_live_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Forwards plain-text user messages to the active USSD live session queue.
    Only called when a session is open (filtered in main.py).
    """
    queue: asyncio.Queue[str | None] | None = context.chat_data.get(_USSD_QUEUE_KEY)  # type: ignore[union-attr]
    task: asyncio.Task[Any] | None = context.chat_data.get(_USSD_TASK_KEY)  # type: ignore[union-attr]

    if queue is None or task is None or task.done():
        # No live session – ignore silently (or the MessageHandler filter already guards this)
        return

    text = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if text:
        await queue.put(text)
