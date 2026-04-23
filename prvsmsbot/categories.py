from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Rules container
# ---------------------------------------------------------------------------
# Only the *sub-classification* patterns live here now.  The top-level routing
# decision (service vs. personal) is derived purely from the sender's format
# and no longer needs to be configured via environment variables.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageCategoryRules:
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


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize_sender(sender: str | None) -> str:
    """Return a canonical sender string.

    * Bare ``251XXXXXXXXX`` (missing the leading ``+``) is normalised to
      ``+251XXXXXXXXX`` so every downstream check can assume the ``+`` prefix.
    * Everything else is returned as-is after stripping surrounding whitespace.
    """
    raw = str(sender or "").strip()
    if raw.startswith("251") and not raw.startswith("+"):
        return "+" + raw
    return raw


# ---------------------------------------------------------------------------
# Ethiopian mobile number pattern
# ---------------------------------------------------------------------------
# +251 followed by exactly 9 digits → full Ethiopian mobile number.
# Examples: +251911223344, +251912345678
# ---------------------------------------------------------------------------

_ET_MOBILE_RE = re.compile(r"^\+251\d{9}$")


# ---------------------------------------------------------------------------
# Sender-type predicates
# ---------------------------------------------------------------------------


def is_service_sender(sender: str) -> bool:
    """Return True when the sender looks like a service / business originator.

    Two cases qualify:

    1. **Named sender** – the string contains at least one letter.
       e.g. ``"CBE"``, ``"Telebirr"``, ``"Ethio"``, ``"BOA"``

    2. **Short code** – the string is made up purely of digits and has at most
       six of them.
       e.g. ``"127"``, ``"994"``, ``"12345"``
    """
    if any(ch.isalpha() for ch in sender):
        return True
    digits = "".join(ch for ch in sender if ch.isdigit())
    return bool(digits) and len(digits) <= 6


def is_personal_sender(sender: str) -> bool:
    """Return True when the sender is a full Ethiopian mobile number.

    After normalisation every such number has the form ``+251XXXXXXXXX``
    (the country code plus exactly nine subscriber digits).
    """
    return bool(_ET_MOBILE_RE.match(sender))


# ---------------------------------------------------------------------------
# Sub-classification helper
# ---------------------------------------------------------------------------


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(p.lower() in lowered for p in patterns)


# ---------------------------------------------------------------------------
# Main classification entry-point
# ---------------------------------------------------------------------------


def classify_origin(
    sender: str | None,
    content: str | None,
    rules: MessageCategoryRules,
) -> dict[str, str]:
    """Classify an incoming SMS by its sender and content.

    Returns a dict with three keys:

    * ``kind``   – ``"service"``, ``"personal"``, or ``"unknown"``
    * ``origin`` – finer-grained label (``"bank"``, ``"telecom"``, ``"otp"``,
                   ``"service"``, ``"personal"``, or ``"unknown"``)
    * ``label``  – human-readable ``"kind:origin"`` string (or ``"personal"``
                   / ``"unknown"`` for the non-service kinds)

    Routing logic
    -------------
    * Named senders (any letter) and short codes (≤ 6 pure digits) → service
    * Full Ethiopian mobile numbers (+251 + 9 digits)              → personal
    * Anything else                                                → unknown

    Service messages are further broken down by matching the combined sender +
    content text against the sub-classification patterns in *rules*.
    """
    normalized = normalize_sender(sender)
    if not normalized:
        return {"kind": "unknown", "origin": "unknown", "label": "unknown"}

    # Build a single text blob for sub-classification pattern matching.
    text = f"{normalized} {str(content or '')}".strip().lower()

    # ── service path ────────────────────────────────────────────────────────
    if is_service_sender(normalized):
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

    # ── personal path ───────────────────────────────────────────────────────
    if is_personal_sender(normalized):
        return {
            "kind": "personal",
            "origin": "personal",
            "label": "personal",
        }

    # ── fallback ────────────────────────────────────────────────────────────
    return {"kind": "unknown", "origin": "unknown", "label": "unknown"}
