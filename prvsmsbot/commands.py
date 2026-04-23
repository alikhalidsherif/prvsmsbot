from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .categories import MessageCategoryRules, classify_origin, normalize_sender
from .config import Settings
from .formatting import chunk_lines, safe_markdown
from .n8n_client import N8NClient, N8NClientError
from .render import filter_messages, render_inbox_line


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, N8NClientError):
        return f"I could not reach the automation layer.\n\n{safe_markdown(str(exc))}"
    return f"Unexpected error: {safe_markdown(str(exc))}"


@dataclass
class BotCommandService:
    settings: Settings
    n8n_client: N8NClient

    @property
    def category_rules(self) -> MessageCategoryRules:
        return MessageCategoryRules()

    def read_page_limit(
        self, args: list[str], default_page: int = 1
    ) -> tuple[int, int]:
        page = default_page
        limit = self.settings.default_page_limit
        if len(args) >= 1:
            try:
                page = max(1, int(args[0]))
            except ValueError:
                page = default_page
        if len(args) >= 2:
            try:
                limit = max(5, min(200, int(args[1])))
            except ValueError:
                limit = self.settings.default_page_limit
        return page, limit

    def send_sms(self, phone: str, message: str) -> str:
        result = self.n8n_client.send_sms(phone, message)
        ok = bool(result.get("ok", False))
        state = safe_markdown(str(result.get("state", "unknown")))
        reason = safe_markdown(str(result.get("reason", "")))
        sent_to = safe_markdown(str(result.get("to", phone)))
        return (
            f"Send result: {'SUCCESS' if ok else 'NOT CONFIRMED'}\n"
            f"State: {state}\n"
            f"To: {sent_to}\n"
            f"Reason: {reason}"
        )

    def inbox_view(
        self,
        *,
        title: str,
        mode: str,
        sender: str | None,
        search: str | None,
        page: int,
        limit: int,
    ) -> list[str]:
        payload = self.n8n_client.inbox(
            page=page,
            limit=limit,
            sender=sender,
            search=search,
            msg_type="sms",
        )
        incoming = payload.get("messages") or []
        messages = filter_messages(incoming, mode, self.category_rules)
        if not messages:
            return [f"{title}: no messages found."]

        lines = [render_inbox_line(msg, self.category_rules) for msg in messages]
        chunks = chunk_lines(lines)
        total = payload.get("total", 0)
        header = f"{safe_markdown(title)} (page {page}, showing {len(messages)}, source total {total})"
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            out.append(f"{header}\n\n{chunk}" if idx == 0 else chunk)
        return out

    def outbox_view(self, *, page: int, limit: int) -> list[str]:
        payload = self.n8n_client.outbox(page=page, limit=limit)
        messages = payload.get("messages") or []
        if not messages:
            return ["Outbox is empty."]

        lines: list[str] = []
        for row in messages:
            recipients = safe_markdown(str(row.get("recipients", "")))
            content = safe_markdown(str(row.get("content", "")).replace("\n", " "))
            preview = content[:100] + ("..." if len(content) > 100 else "")
            sent_at = safe_markdown(str(row.get("sent_at", "")))
            lines.append(f"{sent_at} | {recipients}\n{preview}")

        chunks = chunk_lines(lines)
        header = f"Outbox (page {page}, showing {len(lines)}, total {payload.get('total', '?')})"
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            out.append(f"{header}\n\n{chunk}" if idx == 0 else chunk)
        return out

    def senders_view(self, *, page: int, limit: int, mode: str) -> list[str]:
        payload = self.n8n_client.inbox(
            page=page,
            limit=limit,
            sender=None,
            search=None,
            msg_type="sms",
        )
        messages = payload.get("messages") or []
        if not messages:
            return ["No messages available to build sender stats."]

        groups: dict[str, dict[str, Any]] = {}
        for msg in messages:
            sender = str(msg.get("phone", "")).strip() or "unknown"
            content = str(msg.get("content", ""))
            normalized = normalize_sender(sender)
            origin = classify_origin(normalized, content, self.category_rules)

            if mode == "service" and origin["kind"] != "service":
                continue
            if mode == "personal" and origin["kind"] != "personal":
                continue
            if mode in {"bank", "telecom", "otp"} and origin["origin"] != mode:
                continue

            key = normalized
            if key not in groups:
                groups[key] = {
                    "sender": normalized,
                    "label": origin["label"],
                    "count": 0,
                }
            groups[key]["count"] += 1

        if not groups:
            return ["No sender groups matched your selected filter."]

        ordered = sorted(
            groups.values(), key=lambda x: (-int(x["count"]), str(x["sender"]))
        )
        lines = [
            f"{idx + 1}. {row['sender']} [{row['label']}] - {row['count']} msg"
            for idx, row in enumerate(ordered)
        ]
        chunks = chunk_lines(lines, chunk_size=30)
        title = (
            f"Top Senders ({mode}) from page {page} sample ({len(messages)} messages)"
        )
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            out.append(f"{title}\n\n{chunk}" if idx == 0 else chunk)
        return out

    def health(self) -> str:
        data = self.n8n_client.health()
        return (
            f"Gateway status: {safe_markdown(str(data.get('status', 'unknown')))}\n"
            f"Consecutive failures: {data.get('consecutive_failures', '?')}\n"
            f"Total failures: {data.get('total_failures', '?')}\n"
            f"Last poll success: {safe_markdown(str(data.get('last_poll_success_at', '-')))}\n"
            f"Last SMS received: {safe_markdown(str(data.get('last_sms_received_at', '-')))}"
        )

    def ussd_single(self, code: str) -> str:
        payload = self.n8n_client.ussd_single(code)
        response = payload.get("response") or payload.get("error") or payload
        return f"USSD {safe_markdown(code)}\n\n{safe_markdown(str(response))}"

    def ussd_session(self, steps: list[str]) -> list[str]:
        payload = self.n8n_client.ussd_session(steps)
        history = payload.get("history") or []
        if not history:
            return [f"No USSD history returned. Raw: {safe_markdown(str(payload))}"]

        lines = []
        for row in history:
            step = row.get("step")
            user_input = safe_markdown(str(row.get("input", "")))
            response = row.get("response") or row.get("error") or "-"
            lines.append(f"Step {step} [{user_input}]\n{safe_markdown(str(response))}")

        chunks = chunk_lines(lines, chunk_size=12)
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            out.append(f"USSD Session Result\n\n{chunk}" if idx == 0 else chunk)
        return out

    def ussd_live_start(self, code: str, chat_id: int) -> str:
        payload = self.n8n_client.ussd_live("start", chat_id, code)
        menu = payload.get("menu") or payload.get("response") or payload
        return f"Live session started with {safe_markdown(code)}\n\n{safe_markdown(str(menu))}"

    def ussd_live_reply(self, value: str, chat_id: int) -> str:
        payload = self.n8n_client.ussd_live("reply", chat_id, value)
        menu = payload.get("menu") or payload.get("response") or payload
        return safe_markdown(str(menu))

    def ussd_live_cancel(self, chat_id: int) -> str:
        payload = self.n8n_client.ussd_live("cancel", chat_id)
        msg = payload.get("status") or payload
        return f"Live session: {safe_markdown(str(msg))}"
