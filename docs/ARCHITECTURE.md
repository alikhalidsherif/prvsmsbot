# PRVSMSBOT Architecture

## 0. Purpose (One sentence)

Expose SMS and USSD capabilities through a Telegram bot using n8n as the integration boundary to SMSGate.

## 1. System Overview (Block View)

- Hardware/IO Layer:
  - Huawei modem (managed by SMSGate)

- Core Gateway Layer:
  - SMSGate REST endpoints for SMS, USSD, history, health

- Event/Automation Layer:
  - n8n workflow webhooks (`workflows/*.json`)

- External Systems:
  - Telegram users
  - optional third-party callers to the same webhook contracts

## 2. Signal Flow (Critical Path)

```text
Telegram Input -> Python Bot -> n8n Webhook -> SMSGate API -> Modem/Carrier -> n8n Response -> Telegram Reply
```

Incoming message flow:

```text
Carrier SMS -> SMSGate Poller -> SMSGate Webhook Push -> prvsmsbot /webhook/smsgate -> Telegram Alert
```

## 3. Module Pins (Interfaces)

### Module: Telegram Bot
- IN:
  - Telegram commands and arguments
- OUT:
  - HTTP POST to n8n webhook paths with `X-Prv-Bot-Token`

### Module: n8n Interface
- IN:
  - webhook payloads from bot (`send`, `inbox`, `outbox`, `ussd`, `health`)
- OUT:
  - HTTP calls to SMSGate endpoints
  - normalized JSON responses

### Module: SMSGate
- IN:
  - authenticated HTTP requests from n8n
- OUT:
  - SMS result, inbox/outbox data, USSD responses, modem health snapshots

## 4. Replaceability Rule

Checklist:
- Can implementation change without changing consumers? Yes, as long as webhook contracts stay stable.
- Are interfaces explicit? Yes, each action maps to a fixed webhook path + payload schema.
- Are dependencies declared? Yes, via `.env` and workflow configuration.

## 5. Failure Behavior (Fuse Design)

- Bot never talks to modem directly; failures are isolated to n8n boundary.
- n8n validates shared token before any gateway call.
- SMS/USSD failures are returned to caller; no hidden silent pass.
- Live USSD state is isolated by `chat_id` in n8n workflow static data.

Rule followed: failure does not cascade across modules.

## 6. State Model

- Stateless modules:
  - Python command handlers
  - n8n request validation nodes

- Persistent storage:
  - SMSGate SQLite (`messages`, `sent_messages`)

- Ephemeral state:
  - n8n live USSD session map per `chat_id`

## 7. Traceability

- Each command maps to one webhook path.
- n8n execution log tracks webhook -> gateway steps.
- SMSGate logs trace modem-level operations.

## 8. External Integrations

- Telegram Bot API
- n8n
- SMSGate HTTP API
- Huawei modem/carrier network

All are external, replaceable, and unreliable by design assumptions.

## 9. Minimal Run Instructions

1. `cp .env.example .env`
2. Fill `.env` tokens and paths
3. `pip install -e .[dev]`
4. Import all files in `workflows/` into n8n
5. Set n8n env: `PRV_BOT_TOKEN`, `SMSGATE_BASE_URL`, `SMSGATE_ADMIN_KEY`
6. Start bot: `prvsmsbot`
7. Check: `/ping` then `/health` in Telegram

## 10. Known Failure Modes

- Bad or missing shared token between bot and n8n
- Incorrect webhook path mapping in env
- n8n workflow inactive
- SMSGate down/unreachable
- Modem instability and carrier USSD timeout
- Live USSD lock/contention (busy session)

## 11. Version Philosophy

- Keep webhook contracts stable.
- Avoid breaking command semantics.
- Refactor internals freely when interfaces remain unchanged.
