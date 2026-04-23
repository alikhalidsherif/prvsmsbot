"""
bot/config.py
~~~~~~~~~~~~~
Settings parsed from environment variables.

Required variables
------------------
  TELEGRAM_BOT_TOKEN        Bot token from BotFather
  SMSGATE_ADMIN_KEY         Matches ADMIN_KEY in SMSGate .env
  ALLOWED_TELEGRAM_USER_IDS Comma-separated Telegram user IDs

Optional variables (with defaults)
------------------------------------
  SMSGATE_BASE_URL          http://smsgate:5000
  GATEWAY_TIMEOUT_SECONDS   30
  WEBHOOK_HOST              0.0.0.0
  WEBHOOK_PORT              8090
  NOTIFY_DELIVERY_REPORTS   true
  SERVICE_SENDER_PATTERNS   127,251,Ethio,telebirr,CBE,Awash,Dashen,BOA,bank,otp,code
  PERSONAL_SENDER_MIN_DIGITS 10
  DEFAULT_PAGE_LIMIT        20
"""
from __future__ import annotations

import os
from dataclasses import dataclass


# ── primitive parsers ─────────────────────────────────────────────────────────

def _parse_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_int_csv(name: str, default: str) -> tuple[int, ...]:
    raw = os.getenv(name, default)
    result: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            continue
    return tuple(dict.fromkeys(result))   # preserve order, deduplicate


# ── Settings ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_bot_token: str
    allowed_telegram_user_ids: tuple[int, ...]

    # SMSGate
    smsgate_base_url: str
    smsgate_admin_key: str
    gateway_timeout_seconds: float

    # Inbound webhook listener
    webhook_host: str
    webhook_port: int
    notify_delivery_reports: bool

    # Message categorisation
    service_sender_patterns: tuple[str, ...]
    personal_sender_min_digits: int
    default_page_limit: int

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token         = os.getenv("TELEGRAM_BOT_TOKEN", ""),
            allowed_telegram_user_ids  = _parse_int_csv("ALLOWED_TELEGRAM_USER_IDS", ""),
            smsgate_base_url           = os.getenv(
                                             "SMSGATE_BASE_URL", "http://smsgate:5000"
                                         ).rstrip("/"),
            smsgate_admin_key          = os.getenv("SMSGATE_ADMIN_KEY", ""),
            gateway_timeout_seconds    = float(
                                             max(5, _parse_int("GATEWAY_TIMEOUT_SECONDS", 30))
                                         ),
            webhook_host               = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0",
            webhook_port               = max(1, min(65535, _parse_int("WEBHOOK_PORT", 8090))),
            notify_delivery_reports    = _parse_bool("NOTIFY_DELIVERY_REPORTS", True),
            service_sender_patterns    = _parse_csv(
                                             "SERVICE_SENDER_PATTERNS",
                                             "127,251,Ethio,telebirr,CBE,Awash,Dashen,BOA,bank,otp,code",
                                         ),
            personal_sender_min_digits = max(8, _parse_int("PERSONAL_SENDER_MIN_DIGITS", 10)),
            default_page_limit         = max(5, min(200, _parse_int("DEFAULT_PAGE_LIMIT", 20))),
        )

    # ── validation ────────────────────────────────────────────────────────────

    def validate(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.smsgate_admin_key:
            missing.append("SMSGATE_ADMIN_KEY")
        if not self.allowed_telegram_user_ids:
            missing.append("ALLOWED_TELEGRAM_USER_IDS")
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
