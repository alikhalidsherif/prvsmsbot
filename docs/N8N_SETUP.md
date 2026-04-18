# n8n Setup

This project expects the Telegram bot to call n8n webhook interfaces, and n8n to call SMSGate.

## Required n8n Environment Variables

Set these in your n8n runtime:

- `PRV_BOT_TOKEN`
- `SMSGATE_BASE_URL`
- `SMSGATE_ADMIN_KEY`

Example values:

- `PRV_BOT_TOKEN=replace_with_shared_secret`
- `SMSGATE_BASE_URL=http://smsgate:5000`
- `SMSGATE_ADMIN_KEY=replace_with_gateway_admin_key`

## Import Order

Import all files in `workflows/`:

1. `01-prvsmsbot-send-sms.json`
2. `02-prvsmsbot-inbox.json`
3. `03-prvsmsbot-outbox.json`
4. `04-prvsmsbot-ussd-single.json`
5. `05-prvsmsbot-ussd-session-live.json`
6. `06-prvsmsbot-health.json`

Then activate them.

## Webhook Paths

Configured defaults (from `.env.example`):

- `prvsmsbot/send-sms`
- `prvsmsbot/inbox`
- `prvsmsbot/outbox`
- `prvsmsbot/ussd/single`
- `prvsmsbot/ussd/session` (batch + live actions)
- `prvsmsbot/health`

If you change paths, update both:

- bot `.env` (`N8N_*_PATH`)
- imported workflow webhook path value

## Live USSD Notes

`05-prvsmsbot-ussd-session-live.json` supports both:

- batch: payload includes `steps`
- live: payload includes `action`, `chat_id`, and optional `value`

Live session state is stored in n8n workflow static data (`global.ussdSessions`) keyed by `chat_id`.
