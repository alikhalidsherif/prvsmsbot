from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageCategoryRules:
    service_patterns: tuple[str, ...]
    personal_min_digits: int
    bank_patterns: tuple[str, ...] = (
        "cbe",
        "awash",
        "dashen",
        "boa",
        "bank",
        "commercial bank",
        "telebirr",
    )
    telecom_patterns: tuple[str, ...] = (
        "ethio",
        "ethiotel",
        "telecom",
        "127",
        "994",
    )
    otp_patterns: tuple[str, ...] = (
        "otp",
        "verification",
        "code",
        "pin",
    )


def normalize_sender(sender: str | None) -> str:
    raw = str(sender or "").strip()
    if raw.startswith("251"):
        return "+" + raw
    return raw


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(part.lower() in lowered for part in patterns)


def is_service_sender(sender: str, rules: MessageCategoryRules) -> bool:
    if _contains_any(sender, rules.service_patterns):
        return True
    digits = "".join(ch for ch in sender if ch.isdigit())
    if digits and len(digits) <= 6:
        return True
    return False


def is_personal_sender(sender: str, rules: MessageCategoryRules) -> bool:
    digits = "".join(ch for ch in sender if ch.isdigit())
    return len(digits) >= rules.personal_min_digits


def classify_origin(
    sender: str | None, content: str | None, rules: MessageCategoryRules
) -> dict[str, str]:
    normalized = normalize_sender(sender)
    text = f"{normalized} {str(content or '')}".strip().lower()
    if not normalized:
        return {"kind": "unknown", "origin": "unknown", "label": "unknown"}

    service_like = is_service_sender(normalized, rules)
    personal_like = is_personal_sender(normalized, rules)

    if service_like:
        if _contains_any(text, rules.bank_patterns):
            origin = "bank"
        elif _contains_any(text, rules.telecom_patterns):
            origin = "telecom"
        elif _contains_any(text, rules.otp_patterns):
            origin = "otp"
        else:
            origin = "service"
        return {
            "kind": "service",
            "origin": origin,
            "label": f"service:{origin}",
        }

    if personal_like:
        return {
            "kind": "personal",
            "origin": "personal",
            "label": "personal",
        }

    return {"kind": "unknown", "origin": "unknown", "label": "unknown"}
