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


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(values)


def _parse_int_csv(name: str, default: str) -> tuple[int, ...]:
    raw = os.getenv(name, default)
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError:
            continue
    # Preserve order, remove duplicates
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    prv_bot_token: str
    allowed_telegram_user_ids: tuple[int, ...]
    webhook_host: str
    webhook_port: int
    notify_delivery_reports: bool
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
            allowed_telegram_user_ids=_parse_int_csv("ALLOWED_TELEGRAM_USER_IDS", ""),
            webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0",
            webhook_port=max(1, min(65535, _parse_int("WEBHOOK_PORT", 8090))),
            notify_delivery_reports=_parse_bool("NOTIFY_DELIVERY_REPORTS", True),
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
        if not self.allowed_telegram_user_ids:
            missing.append("ALLOWED_TELEGRAM_USER_IDS")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")
