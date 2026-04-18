from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(values)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    prv_bot_token: str
    n8n_webhook_base_url: str
    n8n_send_sms_path: str
    n8n_inbox_path: str
    n8n_outbox_path: str
    n8n_ussd_single_path: str
    n8n_ussd_session_path: str
    n8n_ussd_live_path: str
    n8n_health_path: str
    n8n_timeout_seconds: int
    service_sender_patterns: tuple[str, ...]
    personal_sender_min_digits: int
    default_page_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            prv_bot_token=os.getenv("PRV_BOT_TOKEN", ""),
            n8n_webhook_base_url=os.getenv(
                "N8N_WEBHOOK_BASE_URL", "http://localhost:5678/webhook"
            ).rstrip("/"),
            n8n_send_sms_path=os.getenv("N8N_SEND_SMS_PATH", "prvsmsbot/send-sms"),
            n8n_inbox_path=os.getenv("N8N_INBOX_PATH", "prvsmsbot/inbox"),
            n8n_outbox_path=os.getenv("N8N_OUTBOX_PATH", "prvsmsbot/outbox"),
            n8n_ussd_single_path=os.getenv(
                "N8N_USSD_SINGLE_PATH", "prvsmsbot/ussd/single"
            ),
            n8n_ussd_session_path=os.getenv(
                "N8N_USSD_SESSION_PATH", "prvsmsbot/ussd/session"
            ),
            n8n_ussd_live_path=os.getenv(
                "N8N_USSD_LIVE_PATH", "prvsmsbot/ussd/session"
            ),
            n8n_health_path=os.getenv("N8N_HEALTH_PATH", "prvsmsbot/health"),
            n8n_timeout_seconds=max(5, _parse_int("N8N_TIMEOUT_SECONDS", 25)),
            service_sender_patterns=_parse_csv(
                "SERVICE_SENDER_PATTERNS",
                "127,251,Ethio,telebirr,CBE,Awash,Dashen,BOA,bank,otp,code",
            ),
            personal_sender_min_digits=max(
                8, _parse_int("PERSONAL_SENDER_MIN_DIGITS", 10)
            ),
            default_page_limit=max(5, min(200, _parse_int("DEFAULT_PAGE_LIMIT", 20))),
        )

    def validate(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.prv_bot_token:
            missing.append("PRV_BOT_TOKEN")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")
