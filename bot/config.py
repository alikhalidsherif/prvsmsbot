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
  SMSGATE_WEBHOOK_URL       (empty) URL SMSGate should POST events to,
                            e.g. http://prvsmsbot:8090/webhook
                            When set the bot registers it with SMSGate on startup.
  OUTBOUND_PROXY_URL        (empty) Legacy Telegram outbound proxy URL.
  TELEGRAM_PROXY_URL        (empty) Preferred Telegram outbound proxy URL.
                            Falls back to OUTBOUND_PROXY_URL when unset.
  TELEGRAM_UPDATE_MODE      polling | webhook (default: polling)
  TELEGRAM_WEBHOOK_PUBLIC_URL
                            (empty) Public HTTPS origin, e.g. https://bot.example.com
                            Required only when TELEGRAM_UPDATE_MODE=webhook.
  TELEGRAM_WEBHOOK_PATH     /telegram/webhook
  TELEGRAM_WEBHOOK_SECRET   (empty) Optional secret validated from
                            X-Telegram-Bot-Api-Secret-Token header.
  GATEWAY_PROXY_URL         (empty) Optional proxy URL for SMSGate HTTP calls.
                            Keep empty when SMSGate is on Docker/internal networks.
                            For SOCKS, prefer socks5h://... so DNS resolves via proxy.
  GATEWAY_TIMEOUT_SECONDS   30
  WEBHOOK_HOST              0.0.0.0
  WEBHOOK_PORT              8090
  NOTIFY_DELIVERY_REPORTS   true
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
    return tuple(dict.fromkeys(result))  # preserve order, deduplicate


# ── Settings ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_bot_token: str
    allowed_telegram_user_ids: tuple[int, ...]

    # SMSGate
    smsgate_base_url: str
    smsgate_admin_key: str
    smsgate_webhook_url: str
    outbound_proxy_url: str
    telegram_proxy_url: str
    telegram_update_mode: str
    telegram_webhook_public_url: str
    telegram_webhook_path: str
    telegram_webhook_secret: str
    gateway_proxy_url: str
    gateway_timeout_seconds: float

    # Inbound webhook listener
    webhook_host: str
    webhook_port: int
    notify_delivery_reports: bool

    # Pagination
    default_page_limit: int

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "Settings":
        raw_webhook_path = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook").strip()
        normalized_webhook_path = "/" + (raw_webhook_path.strip("/") or "telegram/webhook")
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            allowed_telegram_user_ids=_parse_int_csv("ALLOWED_TELEGRAM_USER_IDS", ""),
            smsgate_base_url=os.getenv(
                "SMSGATE_BASE_URL", "http://smsgate:5000"
            ).rstrip("/"),
            smsgate_admin_key=os.getenv("SMSGATE_ADMIN_KEY", ""),
            smsgate_webhook_url=os.getenv("SMSGATE_WEBHOOK_URL", "").strip(),
            outbound_proxy_url=os.getenv("OUTBOUND_PROXY_URL", "").strip(),
            telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", "").strip()
            or os.getenv("OUTBOUND_PROXY_URL", "").strip(),
            telegram_update_mode=os.getenv("TELEGRAM_UPDATE_MODE", "polling")
            .strip()
            .lower(),
            telegram_webhook_public_url=os.getenv(
                "TELEGRAM_WEBHOOK_PUBLIC_URL", ""
            ).strip(),
            telegram_webhook_path=normalized_webhook_path,
            telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip(),
            gateway_proxy_url=os.getenv("GATEWAY_PROXY_URL", "").strip(),
            gateway_timeout_seconds=float(
                max(5, _parse_int("GATEWAY_TIMEOUT_SECONDS", 30))
            ),
            webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0",
            webhook_port=max(1, min(65535, _parse_int("WEBHOOK_PORT", 8090))),
            notify_delivery_reports=_parse_bool("NOTIFY_DELIVERY_REPORTS", True),
            default_page_limit=max(5, min(200, _parse_int("DEFAULT_PAGE_LIMIT", 20))),
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
        if self.telegram_update_mode not in {"polling", "webhook"}:
            raise ValueError(
                "TELEGRAM_UPDATE_MODE must be either 'polling' or 'webhook'"
            )
        if self.telegram_update_mode == "webhook":
            if not self.telegram_webhook_public_url:
                raise ValueError(
                    "TELEGRAM_WEBHOOK_PUBLIC_URL is required when TELEGRAM_UPDATE_MODE=webhook"
                )
            if not (
                self.telegram_webhook_public_url.startswith("https://")
                or self.telegram_webhook_public_url.startswith("http://localhost")
                or self.telegram_webhook_public_url.startswith("http://127.0.0.1")
            ):
                raise ValueError(
                    "TELEGRAM_WEBHOOK_PUBLIC_URL must be https://... "
                    "(localhost/http allowed for local testing)"
                )
