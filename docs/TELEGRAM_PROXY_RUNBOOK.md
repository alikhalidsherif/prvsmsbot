# Telegram Proxy Runbook (Ubuntu + Docker + WARP SOCKS)

## Purpose
Keep `prvsmsbot` reliably connected to Telegram when direct Telegram API access is blocked or unstable.

## Final Known-Good Setup
- Host OS: Ubuntu
- WARP mode: `proxy`
- WARP local SOCKS endpoint: `127.0.0.1:40000`
- Docker bridge proxy: host `0.0.0.0:40001` -> `127.0.0.1:40000` (via `socat`)
- Bot env:
  - `TELEGRAM_PROXY_URL=socks5h://host.docker.internal:40001`
  - `OUTBOUND_PROXY_URL=socks5h://host.docker.internal:40001` (legacy compatibility)
  - `GATEWAY_PROXY_URL=` (empty)

## Key Lessons Learned
1. There were two separate failures:
   - Missing SOCKS dependencies (`socksio` / PTB socks extras).
   - Later, proxy transport existed but was unreachable from container.
2. `GATEWAY_PROXY_URL` should stay empty when SMSGate is docker-internal (`http://smsgate:5000`).
3. `socks5h://` matters because DNS must resolve through the proxy.
4. `host.docker.internal` may resolve but still fail if nothing is listening on the host-reachable port.
5. Always validate each network hop independently:
   - Host -> WARP socket
   - Host -> bridge socket
   - Container -> host bridge socket
   - Bot -> Telegram API

## One-Time Host Setup
```bash
warp-cli connect
warp-cli mode proxy

docker rm -f warp-socks-bridge 2>/dev/null || true
docker run -d \
  --name warp-socks-bridge \
  --restart unless-stopped \
  --network host \
  alpine/socat \
  TCP-LISTEN:40001,fork,reuseaddr,bind=0.0.0.0 \
  TCP:127.0.0.1:40000
```

## Required `.env` Values
```env
TELEGRAM_PROXY_URL=socks5h://host.docker.internal:40001
OUTBOUND_PROXY_URL=socks5h://host.docker.internal:40001
GATEWAY_PROXY_URL=
```

## Verification Checklist
1. Host WARP socket is listening:
```bash
warp-cli status
ss -ltnp | grep ':40000'
nc -vz 127.0.0.1 40000
```

2. Host bridge socket is listening:
```bash
docker ps --filter name=warp-socks-bridge
nc -vz 127.0.0.1 40001
```

3. Container can reach host bridge:
```bash
docker run --rm --add-host host.docker.internal:host-gateway busybox sh -c "nc -vz host.docker.internal 40001"
```

4. Bot container has expected env:
```bash
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' prvsmsbot | grep -E 'TELEGRAM_PROXY_URL|OUTBOUND_PROXY_URL|GATEWAY_PROXY_URL'
```

5. Start bot:
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
docker logs -f prvsmsbot
```

## Healthy Log Signals
- `HTTP Request: POST http://smsgate:5000/config "HTTP/1.1 200 OK"`
- `Application started`
- Repeated successful `getUpdates` `HTTP/1.1 200 OK`

## Failure Signatures and Meaning
- `ImportError: ... 'socksio' package is not installed`
  - SOCKS extras missing in dependencies.
- `RuntimeError: ... python-telegram-bot[socks]`
  - PTB installed without SOCKS extras.
- `httpx.ConnectError: All connection attempts failed`
  - Proxy target unreachable.
- `host.docker.internal ... connection refused`
  - Port open check failed; nothing reachable from container on that host port.
- `telegram.error.TimedOut`
  - Upstream network path still unstable/blocked (or proxy path not healthy).

## Operations Notes
- Keep `warp-socks-bridge` running with `--restart unless-stopped`.
- Keep bot service `restart: unless-stopped`.
- If Telegram access breaks again:
  1. Re-run the verification checklist in order.
  2. Confirm WARP still in proxy mode.
  3. Confirm bridge container is up and reachable from Docker.

