from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str


def check_user_access(
    allowed_user_ids: tuple[int, ...],
    telegram_user_id: int | None,
) -> AccessDecision:
    if telegram_user_id is None:
        return AccessDecision(False, "missing telegram user id")
    if telegram_user_id in allowed_user_ids:
        return AccessDecision(True, "ok")
    return AccessDecision(False, "user not allowed")
