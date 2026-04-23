"""
bot/handlers.py
~~~~~~~~~~~~~~~
One async function per Telegram command.
All SMSGate calls go through SMSGateClient in gateway.py.

Key behaviours
--------------
* USSD codes are auto-normalised: bare digits like 804 → *804#
* Senders with names or short numeric codes are labelled as service;
  +251XXXXXXXXX numbers are labelled personal.
* /inbox and /outbox responses include ◀ Prev / Next ▶ inline buttons
  for pagination (pressing them edits the same message in-place).
* WebSocket sessions close gracefully: a clean server-side close
  (code 1000) shows "Session ended" rather than an error.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

import websockets
import websockets.exceptions
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .categories import MessageCategoryRules, classify_origin, normalize_sender
from .gateway import (
    GatewayBusy,
    GatewayError,
    GatewayModemError,
    GatewayTimeout,
    GatewayUnavailable,
    SMSGateClient,
)

log = logging.getLogger(__name__)

_USSD_TASK_KEY  = "ussd_live_task"
_USSD_QUEUE_KEY = "ussd_live_queue"

_RULES = MessageCategoryRules()

# ── USSD helpers ──────────────────────────────────────────────────────────────

_USSD_CHAR_RE = re.compile(r"^[*#\d]+$")


def _normalize_ussd_code(raw: str) -> str | None:
    """
    Accept any digit / * / # string and ensure it is wrapped in *…#.
    Returns None when the string contains letters or other invalid characters.

    Examples
    --------
    '804'   → '*804#'
    '*804'  → '*804#'
    '804#'  → '*804#'
    '*804#' → '*804#'   (no-op)
    'live'  → None
    """
    code = raw.strip()
    if not code or not _USSD_CHAR_RE.match(code):
        return None
    if not code.startswith("*"):
        code = "*" + code
    if not code.endswith("#"):
        code = code + "#"
    return code


def _ussd_invalid_msg(raw: str) -> str:
    if any(ch.isalpha() for ch in raw):
        return (
            f"❌ "{raw}" is not a USSD code — only digits, * and # are allowed.\n\n"
            f"Did you mean /ussdlive {raw}?"
        )
    return f"❌ "{raw}" is not a valid USSD code."


# ── Formatting helpers ────────────────────────────────────────────────────────

_CATEGORY_ICON: dict[str, str] = {
    "service:bank":    "🏦",
    "service:telecom": "📡",
    "service:otp":     "🔐",
    "service:service": "🏢",
    "personal":        "👤",
    "unknown":         "❓",
}


def _short_date(s: str) -> str:
    """'2026-04-23 12:56:08' or '2026-04-23T12:56:08Z' → 'Apr 23, 12:56'"""
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return s[:16] if len(s) > 16 else s


def _parse_recipients(raw: Any) -> str:
    """Normalise SMSGate's recipients field to a plain comma-separated string.

    SMSGate sometimes returns a JSON-encoded list as a string, e.g.
    '["+251911223344"]'.  This unwraps that back to '+251911223344'.
    """
    if isinstance(raw, list):
        return ", ".join(str(r) for r in raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return ", ".join(str(r) for r in parsed)
        except Exception:
            pass
        return raw.strip('[]"\' ')
    return str(raw)


def _fmt_inbox_entry(msg: dict[str, Any]) -> str:
    phone   = normalize_sender(str(msg.get("phone", "?")))
    content = str(msg.get("content", "")).strip().replace("\n", " ")
    date    = _short_date(str(msg.get("date", "")))
    cls     = classify_origin(phone, content, _RULES)
    icon    = _CATEGORY_ICON.get(cls["label"], "❓")
    preview = content[:160] + ("…" if len(content) > 160 else "")
    return f"{icon} {phone}  ·  {date}\n{preview}"


def _fmt_outbox_entry(msg: dict[str, Any]) -> str:
    recipients = _parse_recipients(msg.get("recipients") or msg.get("to") or "?")
    content    = str(msg.get("content") or msg.get("message", "")).strip().replace("\n", " ")
    date       = _short_date(str(msg.get("sent_at") or msg.get("date", "")))
    preview    = content[:160] + ("…" if len(content) > 160 else "")
    return f"📤 {recipients}  ·  {date}\n{preview}"


def _pagination_keyboard(
    action: str,
    page: int,
    limit: int,
    count: int,
    total: int | str,
) -> InlineKeyboardMarkup | None:
    """
    Build Prev / Next inline buttons.

    ``count`` is the number of messages actually returned in this page.
    ``total`` is the full record count from the API (may be "?" if unknown).
    """
    buttons: list[InlineKeyboardButton] = []
    if page > 1:
        buttons.append(
            InlineKeyboardButton("◀ Prev", callback_data=f"{action}|{page - 1}|{limit}")
        )
    has_more = (
        (isinstance(total, int) and page * limit < total)
        or (not isinstance(total, int) and count >= limit)
    )
    if has_more:
        buttons.append(
            InlineKeyboardButton("Next ▶", callback_data=f"{action}|{page + 1}|{limit}")
        )
    return InlineKeyboardMarkup([buttons]) if buttons else None


# ── Gateway / misc helpers ────────────────────────────────────────────────────


def _gw(context: ContextTypes.DEFAULT_TYPE) -> SMSGateClient:
    return context.bot_data["gateway"]  # type: ignore[index]


def _fmt_error(exc: Exception) -> str:
    if isinstance(exc, GatewayUnavailable):
        return "⚠️ Gateway unavailable – is SMSGate running?"
    if isinstance(exc, GatewayBusy):
        return "⚠️ Another USSD session is active – try again shortly."
    if isinstance(exc, GatewayTimeout):
        return "⚠️ Modem did not respond in time."
    if isinstance(exc, GatewayModemError):
        return "⚠️ Modem / API error."
    if isinstance(exc, GatewayError):
        return f"⚠️ Gateway error: {exc}"
    return f"⚠️ Unexpected error: {exc}"


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
    chunks: list[str] = []
    buf: list[str] = []
    length = 0
    for line in lines:
        if length + len(line) + 2 > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, length = [], 0
        buf.append(line)
        length += len(line) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks or ["(no content)"]


async def _reply_many(update: Update, chunks: list[str]) -> None:
    for text in chunks:
        await update.effective_message.reply_text(text)  # type: ignore[union-attr]


# ── /start ────────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "👋 prvsmsbot – direct SMSGate control\n\n"
        "📨 Messages\n"
        "  /inbox  /outbox\n\n"
        "✉️ Send\n"
        "  /send +2519XXXXXXXX <message>\n\n"
        "📟 USSD\n"
        "  /ussd *804#          — single-shot\n"
        "  /ussdsession *804# 1 2  — automated steps\n"
        "  /ussdlive *804#      — live interactive session\n\n"
        "🛠 Other\n"
        "  /health  /ping  /help"
    )


# ── /help ─────────────────────────────────────────────────────────────────────


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "📖 Commands\n\n"
        "/send <phone> <message>\n"
        "  Send an SMS.  Phone is auto-normalised (251… → +251…).\n\n"
        "/inbox [page] [limit]\n"
        "  Received messages with category icons and ◀▶ page buttons.\n\n"
        "/outbox [page] [limit]\n"
        "  Sent message history with ◀▶ page buttons.\n\n"
        "/health\n"
        "  Modem status, operator, signal and failure counts.\n\n"
        "/ussd <code>\n"
        "  Single-shot USSD.  Bare numbers are auto-wrapped: 804 → *804#\n\n"
        "/ussdsession <code> <step1> <step2> …\n"
        "  Automated multi-step USSD.\n\n"
        "/ussdlive <code>\n"
        "  Live interactive USSD – type menu choices as plain messages.\n"
        "  Use /ussdcancel to end the session.\n\n"
        "/ping  — bot liveness check"
    )


# ── /ping ─────────────────────────────────────────────────────────────────────


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("pong 🏓")  # type: ignore[union-attr]


# ── /health ───────────────────────────────────────────────────────────────────


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = await _gw(context).health_modem()
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    status   = str(data.get("status", "unknown"))
    signal   = data.get("signal_strength", data.get("signal", "?"))
    operator = data.get("operator", data.get("network_name", "?"))
    con_fail = data.get("consecutive_failures", 0)
    tot_fail = data.get("total_failures", "?")
    last_ok  = _short_date(str(data.get("last_poll_success_at", "-")))
    last_sms = _short_date(str(data.get("last_sms_received_at", "-")))
    backoff  = data.get("last_backoff_seconds", 0)

    status_icon = "✅" if status == "healthy" else ("⚠️" if "degrad" in status else "❌")

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📡 Modem health\n\n"
        f"{status_icon} {status}\n"
        f"📶 {operator}  ·  signal {signal}\n\n"
        f"Failures:   {con_fail} consecutive  /  {tot_fail} total\n"
        f"Backoff:    {backoff}s\n"
        f"Last OK:    {last_ok}\n"
        f"Last SMS:   {last_sms}"
    )


# ── /send ─────────────────────────────────────────────────────────────────────


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /send <phone> <message>\n"
            "Example: /send +251911223344 Hello there!"
        )
        return

    phone   = normalize_sender(args[0])
    message = " ".join(args[1:]).strip()
    if not message:
        await update.effective_message.reply_text("Message is empty.")  # type: ignore[union-attr]
        return

    await update.effective_message.reply_text(f"Sending to {phone}…")  # type: ignore[union-attr]
    try:
        data = await _gw(context).sms_send(phone, message)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    ok  = str(data.get("result", "")).upper() == "OK"
    to  = _parse_recipients(data.get("to", phone))
    dr  = "yes" if data.get("delivery_report") else "no"

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"{'✅ Sent' if ok else '⚠️ Not confirmed'}\n"
        f"To: {to}\n"
        f"Delivery report: {dr}\n"
        f"📋 {data.get('message', message)}"
    )


# ── /inbox ────────────────────────────────────────────────────────────────────


def _render_inbox(
    data: dict[str, Any], page: int, limit: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    messages = data.get("messages") or []
    total    = data.get("total", "?")

    if not messages:
        return "📭 Inbox is empty.", None

    lines    = [_fmt_inbox_entry(m) for m in messages]
    body     = "\n\n".join(lines)
    header   = f"📨 Inbox — page {page}  ({len(messages)} shown, {total} total)\n\n"
    keyboard = _pagination_keyboard("inbox", page, limit, len(messages), total)
    return header + body, keyboard


async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args        = context.args or []
    page, limit = _page_limit(args)
    try:
        data = await _gw(context).sms_history(page=page, limit=limit)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return
    text, keyboard = _render_inbox(data, page, limit)
    await update.effective_message.reply_text(text, reply_markup=keyboard)  # type: ignore[union-attr]


async def cb_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    _, page_s, limit_s = query.data.split("|")  # type: ignore[union-attr]
    page, limit = int(page_s), int(limit_s)
    try:
        data = await _gw(context).sms_history(page=page, limit=limit)
    except Exception as exc:
        await query.edit_message_text(_fmt_error(exc))  # type: ignore[union-attr]
        return
    text, keyboard = _render_inbox(data, page, limit)
    await query.edit_message_text(text, reply_markup=keyboard)  # type: ignore[union-attr]


# ── /outbox ───────────────────────────────────────────────────────────────────


def _render_outbox(
    data: dict[str, Any], page: int, limit: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    messages = data.get("messages") or []
    total    = data.get("total", "?")

    if not messages:
        return "📭 Outbox is empty.", None

    lines    = [_fmt_outbox_entry(m) for m in messages]
    body     = "\n\n".join(lines)
    header   = f"📤 Outbox — page {page}  ({len(messages)} shown, {total} total)\n\n"
    keyboard = _pagination_keyboard("outbox", page, limit, len(messages), total)
    return header + body, keyboard


async def cmd_outbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args        = context.args or []
    page, limit = _page_limit(args)
    try:
        data = await _gw(context).sms_sent(page=page, limit=limit)
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return
    text, keyboard = _render_outbox(data, page, limit)
    await update.effective_message.reply_text(text, reply_markup=keyboard)  # type: ignore[union-attr]


async def cb_outbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    _, page_s, limit_s = query.data.split("|")  # type: ignore[union-attr]
    page, limit = int(page_s), int(limit_s)
    try:
        data = await _gw(context).sms_sent(page=page, limit=limit)
    except Exception as exc:
        await query.edit_message_text(_fmt_error(exc))  # type: ignore[union-attr]
        return
    text, keyboard = _render_outbox(data, page, limit)
    await query.edit_message_text(text, reply_markup=keyboard)  # type: ignore[union-attr]


# ── /ussd ─────────────────────────────────────────────────────────────────────


async def cmd_ussd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /ussd <code>  e.g. /ussd *804#  or  /ussd 804"
        )
        return

    raw  = args[0]
    code = _normalize_ussd_code(raw)
    if code is None:
        await update.effective_message.reply_text(_ussd_invalid_msg(raw))  # type: ignore[union-attr]
        return

    await update.effective_message.reply_text(f"📟 Dialling {code}…")  # type: ignore[union-attr]
    try:
        data = await _gw(context).ussd_send(code)
    except GatewayBusy:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Another USSD session is active – try again shortly."
        )
        return
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    response = str(data.get("response") or data)
    await update.effective_message.reply_text(f"📟 {code}\n\n{response}")  # type: ignore[union-attr]


# ── /ussdsession ──────────────────────────────────────────────────────────────


async def cmd_ussdsession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /ussdsession <code> <step1> <step2> …\n"
            "Example: /ussdsession *804# 1 2"
        )
        return

    raw  = args[0]
    code = _normalize_ussd_code(raw)
    if code is None:
        await update.effective_message.reply_text(_ussd_invalid_msg(raw))  # type: ignore[union-attr]
        return

    steps = [code] + [a.strip() for a in args[1:] if a.strip()]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📟 Running {len(steps)}-step USSD session…"
    )
    try:
        data = await _gw(context).ussd_session(steps)
    except GatewayBusy:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Another USSD session is active – try again shortly."
        )
        return
    except Exception as exc:
        await update.effective_message.reply_text(_fmt_error(exc))  # type: ignore[union-attr]
        return

    history = data.get("history") or []
    if not history:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"No history returned.\nRaw: {data}"
        )
        return

    lines = []
    for row in history:
        inp      = row.get("input", "")
        response = str(row.get("response") or row.get("error") or "-")
        lines.append(f"[{inp}]\n{response}")

    header = f"📟 USSD Session — {data.get('steps_run', '?')} steps"
    chunks = _chunk(lines)
    await _reply_many(update, [f"{header}\n\n{chunks[0]}"] + chunks[1:])


# ── /ussdlive ─────────────────────────────────────────────────────────────────


async def cmd_ussdlive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Usage: /ussdlive <code>  e.g. /ussdlive *804#\n"
            "Type your menu choices as plain messages.\n"
            "Use /ussdcancel to end the session."
        )
        return

    raw  = args[0]
    code = _normalize_ussd_code(raw)
    if code is None:
        await update.effective_message.reply_text(_ussd_invalid_msg(raw))  # type: ignore[union-attr]
        return

    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    existing: asyncio.Task[Any] | None = context.chat_data.get(_USSD_TASK_KEY)  # type: ignore[union-attr]
    if existing and not existing.done():
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "A live USSD session is already running.\nUse /ussdcancel to end it first."
        )
        return

    input_queue: asyncio.Queue[str | None] = asyncio.Queue()
    context.chat_data[_USSD_QUEUE_KEY] = input_queue  # type: ignore[union-attr]

    ws_url = _gw(context).ws_url_ussd_live()

    async def _run_ws() -> None:
        try:
            async with websockets.connect(  # type: ignore[attr-defined]
                ws_url,
                open_timeout=10,
                ping_interval=25,
                ping_timeout=10,
            ) as ws:
                # ── handshake ────────────────────────────────────────────────
                raw_msg = await asyncio.wait_for(ws.recv(), timeout=10)
                srv = json.loads(raw_msg)
                if srv.get("status") == "busy":
                    await context.bot.send_message(
                        chat_id,
                        "⚠️ Modem is busy with another USSD session – try again shortly.",
                    )
                    return
                if srv.get("status") != "ready":
                    await context.bot.send_message(
                        chat_id, f"⚠️ Unexpected handshake message: {srv}"
                    )
                    return

                # ── start session ────────────────────────────────────────────
                await ws.send(json.dumps({"code": code}))
                await context.bot.send_message(
                    chat_id,
                    f"📟 Live session started: {code}\n"
                    "Send your menu choice as a message. /ussdcancel to stop.",
                )

                # ── read / respond loop ───────────────────────────────────────
                while True:
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=130)
                    except asyncio.TimeoutError:
                        await context.bot.send_message(
                            chat_id, "⏱ No response from modem – session timed out."
                        )
                        break
                    except websockets.exceptions.ConnectionClosedOK:
                        await context.bot.send_message(chat_id, "📟 Session ended.")
                        break
                    except websockets.exceptions.ConnectionClosed as exc:
                        await context.bot.send_message(
                            chat_id,
                            f"⚠️ Connection dropped (code {exc.code}).",
                        )
                        break

                    srv = json.loads(raw_msg)

                    if "menu" in srv:
                        await context.bot.send_message(chat_id, f"📟 {srv['menu']}")

                        # Wait for the user's next input (or cancel sentinel)
                        try:
                            user_input = await asyncio.wait_for(
                                input_queue.get(), timeout=120
                            )
                        except asyncio.TimeoutError:
                            await context.bot.send_message(
                                chat_id,
                                "⏱ No input for 2 minutes – session cancelled.",
                            )
                            try:
                                await ws.send(json.dumps({"action": "cancel"}))
                            except Exception:
                                pass
                            break

                        if user_input is None:  # /ussdcancel sentinel
                            try:
                                await ws.send(json.dumps({"action": "cancel"}))
                            except Exception:
                                pass
                            await context.bot.send_message(
                                chat_id, "📟 Session cancelled."
                            )
                            break

                        try:
                            await ws.send(json.dumps({"input": user_input}))
                        except websockets.exceptions.ConnectionClosedOK:
                            await context.bot.send_message(chat_id, "📟 Session ended.")
                            break
                        except websockets.exceptions.ConnectionClosed as exc:
                            await context.bot.send_message(
                                chat_id, f"⚠️ Connection dropped (code {exc.code})."
                            )
                            break

                    elif srv.get("status") == "cancelled":
                        await context.bot.send_message(chat_id, "📟 Session cancelled.")
                        break
                    elif srv.get("status") == "timeout":
                        await context.bot.send_message(
                            chat_id,
                            f"⏱ {srv.get('error', 'Session timed out on the modem side.')}",
                        )
                        break
                    elif "error" in srv:
                        await context.bot.send_message(
                            chat_id, f"⚠️ USSD error: {srv['error']}"
                        )
                        break
                    elif srv.get("status") == "pong":
                        pass  # keepalive – ignore

        except websockets.exceptions.ConnectionClosedOK:
            await context.bot.send_message(chat_id, "📟 Session ended.")
        except websockets.exceptions.ConnectionClosed as exc:
            log.warning("USSD live WS closed: %s", exc)
            await context.bot.send_message(
                chat_id, f"⚠️ Connection closed unexpectedly (code {exc.code})."
            )
        except Exception as exc:
            log.exception("USSD live WS error")
            await context.bot.send_message(chat_id, f"⚠️ USSD error: {exc}")
        finally:
            context.chat_data.pop(_USSD_TASK_KEY, None)   # type: ignore[union-attr]
            context.chat_data.pop(_USSD_QUEUE_KEY, None)  # type: ignore[union-attr]

    task = asyncio.create_task(_run_ws())
    context.chat_data[_USSD_TASK_KEY] = task  # type: ignore[union-attr]


# ── /ussdcancel ───────────────────────────────────────────────────────────────


async def cmd_ussdcancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    task: asyncio.Task[Any] | None  = context.chat_data.get(_USSD_TASK_KEY)   # type: ignore[union-attr]
    queue: asyncio.Queue | None     = context.chat_data.get(_USSD_QUEUE_KEY)  # type: ignore[union-attr]

    if task is None or task.done():
        await update.effective_message.reply_text("No active live USSD session.")  # type: ignore[union-attr]
        return

    if queue is not None:
        await queue.put(None)  # sentinel → _run_ws cancels cleanly

    await update.effective_message.reply_text("Cancelling…")  # type: ignore[union-attr]


# ── Plain-text → live USSD input ──────────────────────────────────────────────


async def handle_ussd_live_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Forward plain-text messages to the active USSD live session queue."""
    queue: asyncio.Queue | None    = context.chat_data.get(_USSD_QUEUE_KEY)  # type: ignore[union-attr]
    task: asyncio.Task[Any] | None = context.chat_data.get(_USSD_TASK_KEY)   # type: ignore[union-attr]

    if queue is None or task is None or task.done():
        return  # no active session – ignore silently

    text = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if text:
        await queue.put(text)
