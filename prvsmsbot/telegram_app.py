from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from .commands import BotCommandService, friendly_error
from .security import check_user_access


@dataclass
class PrvSmsTelegramApp:
    bot_token: str
    command_service: BotCommandService
    allowed_user_ids: tuple[int, ...]

    async def _reply_many(self, update: Any, chunks: list[str]) -> None:
        for text in chunks:
            await update.effective_message.reply_text(text)

    async def _authorize_or_reject(self, update: Any) -> bool:
        user = getattr(update, "effective_user", None)
        user_id = getattr(user, "id", None)
        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", None)
        chat_type = getattr(chat, "type", "")

        if chat_type != "private":
            await update.effective_message.reply_text(
                "Unauthorized. Private chat only."
            )
            return False

        if chat_id is None or user_id is None or int(chat_id) != int(user_id):
            await update.effective_message.reply_text(
                "Unauthorized. Invalid chat context."
            )
            return False

        decision = check_user_access(self.allowed_user_ids, user_id)
        if decision.allowed:
            return True

        await update.effective_message.reply_text(
            "Unauthorized. This bot only accepts approved users."
        )
        return False

    async def cmd_start(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        text = (
            "Hey! I am prvsmsbot.\n"
            "Friendly SMS/USSD control over n8n workflows.\n\n"
            "Quick commands:\n"
            "- /send +2519XXXXXXXX hello there\n"
            "- /inbox /inbox_service /inbox_personal\n"
            "- /inbox_bank /inbox_telecom /inbox_otp\n"
            "- /outbox\n"
            "- /ussd *804#\n"
            "- /ussd_session *999#|1|1|2\n"
            "- /ussd_live_start *999#, /ussd_live_reply 1, /ussd_live_cancel\n"
            "- /health\n"
            "- /help"
        )
        await update.effective_message.reply_text(text)

    async def cmd_help(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        text = (
            "Commands\n"
            "/send <phone> <message> send SMS\n"
            "/inbox [page] [limit] inbox mixed\n"
            "/inbox_service [page] [limit] service-only\n"
            "/inbox_personal [page] [limit] personal-only\n"
            "/inbox_bank [page] [limit] bank/service subset\n"
            "/inbox_telecom [page] [limit] Ethio/telecom subset\n"
            "/inbox_otp [page] [limit] OTP/verification subset\n"
            "/inbox_sender <sender> [page] [limit] sender filter\n"
            "/search <term> [page] [limit] text search\n"
            "/senders [all|service|personal|bank|telecom|otp] [page] [limit] sender leaderboard\n"
            "/outbox [page] [limit] sent history\n"
            "/ussd <code> one-shot USSD\n"
            "/ussd_session <s1|s2|s3> fire-and-return staged responses\n"
            "/ussd_live_start <code> begin live menu session\n"
            "/ussd_live_reply <input> send next step\n"
            "/ussd_live_cancel stop live session\n"
            "/health gateway health\n"
            "/ping bot liveness"
        )
        await update.effective_message.reply_text(text)

    async def cmd_ping(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        await update.effective_message.reply_text("pong")

    async def cmd_health(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        try:
            text = self.command_service.health()
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_send(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        if len(args) < 2:
            await update.effective_message.reply_text("Usage: /send <phone> <message>")
            return

        phone = args[0]
        message = " ".join(args[1:]).strip()
        if not message:
            await update.effective_message.reply_text("Message is empty.")
            return

        await update.effective_message.reply_text("Sending...")
        try:
            text = self.command_service.send_sms(phone, message)
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def _run_inbox(
        self,
        update: Any,
        args: list[str],
        *,
        title: str,
        mode: str,
        sender: str | None,
        search: str | None,
    ) -> None:
        if not await self._authorize_or_reject(update):
            return
        page, limit = self.command_service.read_page_limit(args)
        try:
            chunks = self.command_service.inbox_view(
                title=title,
                mode=mode,
                sender=sender,
                search=search,
                page=page,
                limit=limit,
            )
            await self._reply_many(update, chunks)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_inbox(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="Inbox",
            mode="all",
            sender=None,
            search=None,
        )

    async def cmd_inbox_service(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="Service Inbox",
            mode="service",
            sender=None,
            search=None,
        )

    async def cmd_inbox_personal(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="Personal Inbox",
            mode="personal",
            sender=None,
            search=None,
        )

    async def cmd_inbox_bank(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="Bank Inbox",
            mode="bank",
            sender=None,
            search=None,
        )

    async def cmd_inbox_telecom(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="Telecom Inbox",
            mode="telecom",
            sender=None,
            search=None,
        )

    async def cmd_inbox_otp(self, update: Any, context: Any) -> None:
        await self._run_inbox(
            update,
            context.args or [],
            title="OTP Inbox",
            mode="otp",
            sender=None,
            search=None,
        )

    async def cmd_inbox_sender(self, update: Any, context: Any) -> None:
        args = context.args or []
        if not args:
            await update.effective_message.reply_text(
                "Usage: /inbox_sender <sender> [page] [limit]"
            )
            return
        sender = args[0]
        await self._run_inbox(
            update,
            args[1:],
            title=f"Inbox for {sender}",
            mode="all",
            sender=sender,
            search=None,
        )

    async def cmd_search(self, update: Any, context: Any) -> None:
        args = context.args or []
        if not args:
            await update.effective_message.reply_text(
                "Usage: /search <term> [page] [limit]"
            )
            return
        term = args[0]
        await self._run_inbox(
            update,
            args[1:],
            title=f"Search: {term}",
            mode="all",
            sender=None,
            search=term,
        )

    async def cmd_outbox(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        page, limit = self.command_service.read_page_limit(context.args or [])
        try:
            chunks = self.command_service.outbox_view(page=page, limit=limit)
            await self._reply_many(update, chunks)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_senders(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        mode = "all"
        if args:
            possible = args[0].strip().lower()
            if possible in {"all", "service", "personal", "bank", "telecom", "otp"}:
                mode = possible
                args = args[1:]
        page, limit = self.command_service.read_page_limit(args)
        try:
            chunks = self.command_service.senders_view(
                page=page, limit=limit, mode=mode
            )
            await self._reply_many(update, chunks)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_ussd(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text("Usage: /ussd *804#")
            return
        code = args[0]
        await update.effective_message.reply_text("Running USSD...")
        try:
            text = self.command_service.ussd_single(code)
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_ussd_session(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text(
                "Usage: /ussd_session *999#|1|1|2"
            )
            return

        raw = " ".join(args)
        steps = [part.strip() for part in raw.split("|") if part.strip()]
        if not steps:
            await update.effective_message.reply_text(
                "No valid steps found. Example: /ussd_session *999#|1|1|2"
            )
            return

        await update.effective_message.reply_text(
            f"Running USSD session with {len(steps)} steps..."
        )
        try:
            chunks = self.command_service.ussd_session(steps)
            await self._reply_many(update, chunks)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_ussd_live_start(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text("Usage: /ussd_live_start *999#")
            return
        chat_id = update.effective_chat.id
        code = args[0]
        await update.effective_message.reply_text("Starting live USSD session...")
        try:
            text = self.command_service.ussd_live_start(code, chat_id)
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_ussd_live_reply(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text("Usage: /ussd_live_reply <input>")
            return
        chat_id = update.effective_chat.id
        value = " ".join(args).strip()
        await update.effective_message.reply_text("Sending live reply...")
        try:
            text = self.command_service.ussd_live_reply(value, chat_id)
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    async def cmd_ussd_live_cancel(self, update: Any, context: Any) -> None:
        if not await self._authorize_or_reject(update):
            return
        chat_id = update.effective_chat.id
        try:
            text = self.command_service.ussd_live_cancel(chat_id)
            await update.effective_message.reply_text(text)
        except Exception as exc:
            await update.effective_message.reply_text(friendly_error(exc))

    def build_application(self) -> Any:
        telegram_ext = importlib.import_module("telegram.ext")
        application_cls = getattr(telegram_ext, "Application")
        command_handler_cls = getattr(telegram_ext, "CommandHandler")

        app = application_cls.builder().token(self.bot_token).build()
        app.add_handler(command_handler_cls("start", self.cmd_start))
        app.add_handler(command_handler_cls("help", self.cmd_help))
        app.add_handler(command_handler_cls("ping", self.cmd_ping))
        app.add_handler(command_handler_cls("health", self.cmd_health))
        app.add_handler(command_handler_cls("send", self.cmd_send))
        app.add_handler(command_handler_cls("inbox", self.cmd_inbox))
        app.add_handler(command_handler_cls("inbox_service", self.cmd_inbox_service))
        app.add_handler(command_handler_cls("inbox_personal", self.cmd_inbox_personal))
        app.add_handler(command_handler_cls("inbox_bank", self.cmd_inbox_bank))
        app.add_handler(command_handler_cls("inbox_telecom", self.cmd_inbox_telecom))
        app.add_handler(command_handler_cls("inbox_otp", self.cmd_inbox_otp))
        app.add_handler(command_handler_cls("inbox_sender", self.cmd_inbox_sender))
        app.add_handler(command_handler_cls("search", self.cmd_search))
        app.add_handler(command_handler_cls("senders", self.cmd_senders))
        app.add_handler(command_handler_cls("outbox", self.cmd_outbox))
        app.add_handler(command_handler_cls("ussd", self.cmd_ussd))
        app.add_handler(command_handler_cls("ussd_session", self.cmd_ussd_session))
        app.add_handler(
            command_handler_cls("ussd_live_start", self.cmd_ussd_live_start)
        )
        app.add_handler(
            command_handler_cls("ussd_live_reply", self.cmd_ussd_live_reply)
        )
        app.add_handler(
            command_handler_cls("ussd_live_cancel", self.cmd_ussd_live_cancel)
        )
        return app
