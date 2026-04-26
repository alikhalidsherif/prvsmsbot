"""
bot/gateway.py
~~~~~~~~~~~~~~
Async HTTP client for the self-hosted SMSGate gateway.
All calls go directly to SMSGate – no n8n in the middle.

Auth: every protected endpoint requires the header ``X-Admin-Key: <ADMIN_KEY>``.
The WebSocket /ussd/live endpoint is secured by network boundary only (no header).
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

import httpx
import websockets
import websockets.exceptions

log = logging.getLogger(__name__)

# ── Sentinel error ────────────────────────────────────────────────────────────


class GatewayError(RuntimeError):
    """Raised for any SMSGate call that cannot be completed."""


class GatewayUnavailable(GatewayError):
    """Raised when SMSGate is unreachable (network / connection error)."""


class GatewayBusy(GatewayError):
    """Raised on HTTP 423 – another USSD session is active."""


class GatewayTimeout(GatewayError):
    """Raised on HTTP 504 – modem did not respond in time."""


class GatewayModemError(GatewayError):
    """Raised on HTTP 502 – underlying modem / API error."""


# ── Client ────────────────────────────────────────────────────────────────────


class SMSGateClient:
    """
    Thin async wrapper around the SMSGate REST API.

    Parameters
    ----------
    base_url:
        SMSGate base URL, e.g. ``http://smsgate:5000``.
    admin_key:
        Value for the ``X-Admin-Key`` header.
    timeout:
        HTTP request timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        timeout: float = 30.0,
        proxy_url: str = "",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {
            "X-Admin-Key": admin_key,
            "Content-Type": "application/json",
        }
        self._client_kwargs: dict[str, Any] = {"timeout": self._timeout}
        if proxy_url:
            proxy_key = (
                "proxy"
                if "proxy" in inspect.signature(httpx.AsyncClient.__init__).parameters
                else "proxies"
            )
            self._client_kwargs[proxy_key] = proxy_url

    # ── low-level helpers ─────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    def _ws_url(self, path: str) -> str:
        """Convert http(s) base URL to ws(s) for the WebSocket endpoint."""
        base = self._base
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return f"{base}/{path.lstrip('/')}"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._url(path)
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                resp = await client.get(url, headers=self._headers, params=params)
        except httpx.TransportError as exc:
            raise GatewayUnavailable(f"Gateway unreachable: {exc}") from exc
        return self._parse(resp, path)

    async def _post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = self._url(path)
        headers = dict(self._headers)
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                resp = await client.post(url, headers=headers, json=body or {})
        except httpx.TransportError as exc:
            raise GatewayUnavailable(f"Gateway unreachable: {exc}") from exc
        return self._parse(resp, path)

    async def _delete(
        self,
        path: str,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = self._url(path)
        headers = dict(self._headers)
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                resp = await client.delete(url, headers=headers)
        except httpx.TransportError as exc:
            raise GatewayUnavailable(f"Gateway unreachable: {exc}") from exc
        return self._parse(resp, path)

    @staticmethod
    def _parse(resp: httpx.Response, path: str) -> Any:
        status = resp.status_code
        if status == 423:
            raise GatewayBusy("Another USSD session is active – try again shortly.")
        if status == 504:
            raise GatewayTimeout("Modem did not respond in time (504).")
        if status == 502:
            raise GatewayModemError("Modem / API error (502).")
        if status >= 400:
            snippet = resp.text.strip()[:400] or "(empty body)"
            raise GatewayError(f"SMSGate returned {status} for {path}: {snippet}")
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except Exception as exc:
            raise GatewayError("SMSGate did not return JSON.") from exc
        return data

    # ── Public API ────────────────────────────────────────────────────────────

    # Health
    async def health_modem(self) -> dict[str, Any]:
        """GET /health/modem – modem health and signal status."""
        return await self._get("/health/modem")

    # SMS – inbox / history
    async def sms_history(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        phone: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """
        GET /sms/history – full SQLite history (paginated).

        SMSGate accepts ``page``, ``limit``, ``phone``, and ``search`` as query params.
        Returns a dict that includes a ``messages`` list and ``total`` count.
        """
        params: dict[str, Any] = {"page": page, "limit": limit}
        if phone:
            params["phone"] = phone
        if search:
            params["search"] = search
        return await self._get("/sms/history", params=params)

    async def sms_unread_count(self) -> dict[str, Any]:
        """GET /sms/unread/count – count of unread messages."""
        return await self._get("/sms/unread/count")

    # SMS – sent / outbox
    async def sms_sent(self, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        """GET /sms/sent – sent message history (paginated)."""
        params: dict[str, Any] = {"page": page, "limit": limit}
        return await self._get("/sms/sent", params=params)

    # SMS – send
    async def sms_send(
        self,
        to: str,
        message: str,
        delivery_report: bool = True,
    ) -> dict[str, Any]:
        """
        POST /sms/send

        Response shape::

            {"result": "OK", "to": ["+2519XXXXXXXX"], "message": "...", "delivery_report": true}
        """
        body = {"to": to, "message": message, "delivery_report": delivery_report}
        return await self._post("/sms/send", body)

    # USSD – single-shot
    async def ussd_send(self, code: str) -> dict[str, Any]:
        """
        POST /ussd/send – single-shot USSD.

        Response shape::

            {"code": "*804#", "response": "menu text..."}

        Raises ``GatewayBusy`` (423), ``GatewayTimeout`` (504), ``GatewayModemError`` (502).
        """
        return await self._post("/ussd/send", {"code": code})

    # USSD – automated multi-step session
    async def ussd_session(self, steps: list[str]) -> dict[str, Any]:
        """
        POST /ussd/session – automated multi-step USSD.

        Response shape::

            {
                "steps_run": 2,
                "history": [
                    {"step": 1, "input": "*804#", "response": "Welcome ..."},
                    {"step": 2, "input": "1",    "response": "Your balance is ..."}
                ]
            }
        """
        return await self._post("/ussd/session", {"steps": steps})

    # Device
    async def device_reboot(self) -> dict[str, Any]:
        """POST /device/reboot – reboots modem (requires X-Confirm: yes)."""
        return await self._post("/device/reboot", extra_headers={"X-Confirm": "yes"})

    # Runtime config
    async def set_config(self, **kwargs: Any) -> dict[str, Any]:
        """POST /config – update runtime config (e.g. webhook_url, poll_interval)."""
        return await self._post("/config", kwargs)

    # USSD – live WebSocket
    def ws_url_ussd_live(self) -> str:
        """Return the WebSocket URL for /ussd/live (no auth header, network-secured)."""
        return self._ws_url("/ussd/live")

    # ── Config ────────────────────────────────────────────────────────────────

    async def config_get(self) -> dict[str, Any]:
        """GET /config – all runtime config key/value pairs."""
        return await self._get("/config")

    # ── SMS – live modem inbox ────────────────────────────────────────────────

    async def sms_list(
        self,
        *,
        box: str = "inbox",
        page: int = 1,
        count: int = 20,
    ) -> dict[str, Any]:
        """GET /sms – live messages direct from modem (not SQLite history)."""
        return await self._get(
            "/sms", params={"box": box, "page": page, "count": count}
        )

    async def sms_get(self, index: int) -> dict[str, Any]:
        """GET /sms/{index} – fetch and mark-read a single modem message."""
        return await self._get(f"/sms/{index}")

    async def sms_mark_read(self, index: int) -> dict[str, Any]:
        """POST /sms/mark-read/{index} – mark a modem message as read."""
        return await self._post(f"/sms/mark-read/{index}")

    async def sms_delete(self, index: int) -> dict[str, Any]:
        """DELETE /sms/{index} – delete a single message from the modem."""
        return await self._delete(f"/sms/{index}")

    async def sms_delete_all_inbox(self) -> dict[str, Any]:
        """DELETE /sms/inbox/all – wipe entire modem inbox (DB copy kept)."""
        return await self._delete("/sms/inbox/all", extra_headers={"X-Confirm": "yes"})

    # ── Device ────────────────────────────────────────────────────────────────

    async def device_info(self) -> dict[str, Any]:
        """GET /device/info – device details, signal and network status."""
        return await self._get("/device/info")
