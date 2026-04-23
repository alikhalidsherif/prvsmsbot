# prvsmsbot — SMSGate Direct Rewire Reference

## What changed

n8n has been removed entirely. The bot calls SMSGate REST directly via
`httpx` (HTTP) and `websockets` (`/ussd/live`). The event loop runs both
the Telegram poller and the inbound webhook listener concurrently.

---

## New project layout

```
bot/
├── __init__.py      package marker
├── config.py        Settings (env vars, no n8n fields)
├── gateway.py       SMSGateClient – async HTTP + WS helpers
├── handlers.py      one async function per Telegram command
├── listener.py      aiohttp inbound webhook server (SMSGate → Telegram)
└── main.py          async entry point wiring everything together
```

The old `prvsmsbot/` package is superseded.

---

## Commands

| Command | Gateway endpoint | Notes |
|---|---|---|
| `/start` | — | Welcome message |
| `/help` | — | All commands |
| `/ping` | — | Liveness |
| `/health` | `GET /health/modem` | Signal, failures, last poll |
| `/send <phone> <msg>` | `POST /sms/send` | delivery_report: true |
| `/inbox [page] [limit]` | `GET /sms/history` | SQLite history, paginated |
| `/outbox [page] [limit]` | `GET /sms/sent` | Sent history, paginated |
| `/ussd <code>` | `POST /ussd/send` | Single-shot USSD |
| `/ussdsession <s1> <s2>…` | `POST /ussd/session` | Args become steps array |
| `/ussdlive <code>` | `GET /ussd/live` (WS) | Interactive turn-based |
| `/ussdcancel` | — | Closes active WS session |

---

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — |
| `SMSGATE_ADMIN_KEY` | ✅ | — |
| `ALLOWED_TELEGRAM_USER_IDS` | ✅ | — |
| `SMSGATE_BASE_URL` | | `http://smsgate:5000` |
| `GATEWAY_TIMEOUT_SECONDS` | | `30` |
| `WEBHOOK_HOST` | | `0.0.0.0` |
| `WEBHOOK_PORT` | | `8090` |
| `NOTIFY_DELIVERY_REPORTS` | | `true` |
| `DEFAULT_PAGE_LIMIT` | | `20` |

---

## Point SMSGate at the bot webhook

```bash
curl -s -X POST http://smsgate:5000/config \
  -H "X-Admin-Key: <ADMIN_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"webhook_url":"http://prvsmsbot:8090/webhook"}'
```

Or set `WEBHOOK_URL=http://prvsmsbot:8090/webhook` in SMSGate's `.env`.

---

## Docker network

Both containers must share `smsgate-net` (declared `external: true`):

```bash
docker network create smsgate-net   # once
docker compose up -d --build
```

---

## Dependency changes

| Library | Status | Reason |
|---|---|---|
| `requests` | removed | sync; replaced by `httpx` |
| `httpx` | added | async HTTP to SMSGate |
| `aiohttp` | added | async inbound webhook server |
| `websockets` | kept | /ussd/live WS |
| `python-telegram-bot` | kept | Telegram (v20+ async) |

---

## Error classes (bot/gateway.py)

| Class | Trigger |
|---|---|
| `GatewayUnavailable` | Network/connection error |
| `GatewayBusy` | HTTP 423 – modem lock held |
| `GatewayTimeout` | HTTP 504 – modem no response |
| `GatewayModemError` | HTTP 502 – modem/API error |
| `GatewayError` | Any other 4xx/5xx |
