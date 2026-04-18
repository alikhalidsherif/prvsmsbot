# PRVSMSBOT

Friendly Telegram bot for SMS/USSD operations through **n8n workflows** (not direct modem calls).

This repository is intentionally modular and open-source friendly:

- Telegram bot (Python) only talks to n8n webhook interfaces.
- n8n workflows are importable JSON files inside `workflows/`.
- n8n workflows talk to SMSGate.
- Secrets stay in local `.env` files and are gitignored.

## 0. Purpose (One sentence)

Provide a Telegram-first control plane for SMS and USSD operations using modular n8n workflows as stable interfaces.

## 1. System Overview (Block View)

- Hardware/IO Layer:
  - Huawei modem handled by SMSGate

- Core Gateway Layer:
  - SMSGate REST APIs (`/sms/send`, `/sms/history`, `/sms/sent`, `/ussd/send`, `/ussd/session`, `/health/modem`)

- Event/Automation Layer:
  - n8n workflows in `workflows/*.json`

- External Systems:
  - Telegram bot users
  - optional external automation callers

## 2. Signal Flow (Critical Path)

```text
Telegram command -> Python bot -> n8n webhook -> SMSGate -> modem/network -> response -> n8n -> bot reply
```

## 3. Module Pins (Interfaces)

### Module: Telegram Bot (Python)
- IN:
  - Telegram commands (`/send`, `/inbox`, `/ussd`, `/ussd_session`, ...)
- OUT:
  - POST to n8n webhooks with `X-Prv-Bot-Token`

### Module: n8n Workflow Interface
- IN:
  - Webhook payloads from bot
- OUT:
  - Calls to SMSGate API
  - normalized JSON back to bot

### Module: SMSGate
- IN:
  - REST API calls from n8n
- OUT:
  - SMS/USSD responses and health data

No hidden cross-module behavior is assumed.

## 4. Replaceability Rule

Each module is swappable:

- Replace Telegram transport -> keep same n8n webhook contracts.
- Replace n8n with another orchestrator -> preserve webhook/API contract.
- Replace modem/gateway internals -> keep SMSGate API stable.

## 5. Failure Behavior (Fuse Design)

- Bot treats n8n/network errors as contained user-facing errors.
- n8n token validation fails fast with 401/400.
- Gateway failures are returned to caller, not silently swallowed.
- Live USSD state is isolated per `chat_id` in n8n workflow static data.

## 6. State Model

- Stateless modules:
  - Bot command handlers (per request)

- Persistent storage:
  - SMSGate SQLite for SMS history/sent logs

- Ephemeral state:
  - n8n workflow static data for live USSD session state

## 7. Traceability

- Every command maps to a deterministic webhook endpoint.
- n8n execution logs provide hop-level trace.
- SMSGate logs provide modem interaction trace.

## 8. External Integrations

- Telegram Bot API
- n8n runtime
- SMSGate runtime
- Huawei modem/network

All treated as external and unreliable boundaries.

## 9. Minimal Run Instructions

1. Clone and enter repo:
   - `git clone https://github.com/alikhalidsherif/prvsmsbot.git`
   - `cd prvsmsbot`
2. Create env:
   - `cp .env.example .env`
   - fill values (`TELEGRAM_BOT_TOKEN`, `PRV_BOT_TOKEN`, n8n paths)
3. Install:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -e .[dev]`
4. Import workflows from `workflows/` into n8n.
5. Configure n8n env for SMSGate access:
   - `PRV_BOT_TOKEN`
   - `SMSGATE_BASE_URL`
   - `SMSGATE_ADMIN_KEY`
6. Run bot:
   - `prvsmsbot`

Health check:
- In Telegram: `/ping` then `/health`

## 10. Known Failure Modes

- n8n webhook not active or wrong path -> bot returns automation layer error
- wrong `PRV_BOT_TOKEN` -> unauthorized
- SMSGate unavailable -> upstream request failure
- modem/network instability -> degraded health or USSD timeout
- live USSD session conflict (gateway lock) -> 423 from SMSGate path

## 11. Version Philosophy

- Keep webhook interfaces stable.
- Add capabilities behind new commands/paths rather than break old ones.
- Internal refactors are free if external contracts remain intact.

## Commands

- `/start`
- `/help`
- `/ping`
- `/health`
- `/send <phone> <message>`
- `/inbox [page] [limit]`
- `/inbox_service [page] [limit]`
- `/inbox_personal [page] [limit]`
- `/inbox_bank [page] [limit]`
- `/inbox_telecom [page] [limit]`
- `/inbox_otp [page] [limit]`
- `/inbox_sender <sender> [page] [limit]`
- `/search <term> [page] [limit]`
- `/senders [all|service|personal|bank|telecom|otp] [page] [limit]`
- `/outbox [page] [limit]`
- `/ussd <code>`
- `/ussd_session <step1|step2|...>`
- `/ussd_live_start <code>`
- `/ussd_live_reply <input>`
- `/ussd_live_cancel`

## Quick Local Checks

- Syntax check:
  - `python3 -m compileall prvsmsbot tests`
- Unit tests (built-in unittest):
  - `python3 -m unittest discover -s tests -p "test_*.py"`
- CLI smoke examples:
  - `prvsmsbot-cli health`
  - `prvsmsbot-cli inbox --mode service --page 1 --limit 20`

## Workflows Included

- `workflows/01-prvsmsbot-send-sms.json`
- `workflows/02-prvsmsbot-inbox.json`
- `workflows/03-prvsmsbot-outbox.json`
- `workflows/04-prvsmsbot-ussd-single.json`
- `workflows/05-prvsmsbot-ussd-session-live.json`
- `workflows/06-prvsmsbot-health.json`

See detailed n8n wiring in `docs/N8N_SETUP.md`.

## Security Notes

- Never commit `.env`.
- Keep `PRV_BOT_TOKEN` and `SMSGATE_ADMIN_KEY` secret.
- Rotate tokens if accidentally exposed.
