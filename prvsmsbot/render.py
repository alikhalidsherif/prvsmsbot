from __future__ import annotations

from typing import Any

from .categories import MessageCategoryRules, classify_origin, normalize_sender
from .formatting import safe_markdown


def render_inbox_line(msg: dict[str, Any], rules: MessageCategoryRules) -> str:
    phone = normalize_sender(msg.get("phone"))
    content = str(msg.get("content", "")).replace("\n", " ").strip()
    content = safe_markdown(content)
    date = safe_markdown(str(msg.get("date", "")))
    classification = classify_origin(phone, content, rules)
    label = classification["label"]
    preview = content[:120] + ("..." if len(content) > 120 else "")
    return f"[{label}] {phone} | {date}\n{preview}"


def filter_messages(
    messages: list[dict[str, Any]],
    mode: str,
    rules: MessageCategoryRules,
) -> list[dict[str, Any]]:
    if mode == "all":
        return messages

    filtered: list[dict[str, Any]] = []
    for msg in messages:
        phone = normalize_sender(msg.get("phone"))
        content = str(msg.get("content", ""))
        classification = classify_origin(phone, content, rules)
        if mode == "service" and classification["kind"] == "service":
            filtered.append(msg)
        elif mode == "personal" and classification["kind"] == "personal":
            filtered.append(msg)
        elif mode in {"bank", "telecom", "otp"} and classification["origin"] == mode:
            filtered.append(msg)

    return filtered
