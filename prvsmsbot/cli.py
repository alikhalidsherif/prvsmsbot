from __future__ import annotations

import argparse

from .commands import BotCommandService
from .config import Settings
from .n8n_client import N8NClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prvsmsbot-cli",
        description="Local CLI smoke tests for prvsmsbot command service",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    send = sub.add_parser("send", help="Send SMS through n8n")
    send.add_argument("to")
    send.add_argument("message")

    inbox = sub.add_parser("inbox", help="Read inbox through n8n")
    inbox.add_argument("--mode", default="all")
    inbox.add_argument("--page", type=int, default=1)
    inbox.add_argument("--limit", type=int, default=20)
    inbox.add_argument("--search", default=None)
    inbox.add_argument("--sender", default=None)

    outbox = sub.add_parser("outbox", help="Read outbox through n8n")
    outbox.add_argument("--page", type=int, default=1)
    outbox.add_argument("--limit", type=int, default=20)

    ussd = sub.add_parser("ussd", help="Run single USSD")
    ussd.add_argument("code")

    ussds = sub.add_parser("ussd-session", help="Run USSD session")
    ussds.add_argument("steps", help="Pipe-separated steps like *999#|1|2")

    health = sub.add_parser("health", help="Get gateway health")
    _ = health

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.validate()
    service = BotCommandService(settings=settings, n8n_client=N8NClient(settings))

    if args.command == "send":
        print(service.send_sms(args.to, args.message))
        return

    if args.command == "inbox":
        chunks = service.inbox_view(
            title="Inbox CLI",
            mode=args.mode,
            sender=args.sender,
            search=args.search,
            page=args.page,
            limit=args.limit,
        )
        print("\n\n".join(chunks))
        return

    if args.command == "outbox":
        chunks = service.outbox_view(page=args.page, limit=args.limit)
        print("\n\n".join(chunks))
        return

    if args.command == "ussd":
        print(service.ussd_single(args.code))
        return

    if args.command == "ussd-session":
        steps = [s.strip() for s in str(args.steps).split("|") if s.strip()]
        chunks = service.ussd_session(steps)
        print("\n\n".join(chunks))
        return

    if args.command == "health":
        print(service.health())
        return


if __name__ == "__main__":
    main()
