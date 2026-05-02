"""
Norric MCP — ASGI authentication and tier-enforcement middleware.

Pure ASGI (not BaseHTTPMiddleware) so streaming MCP responses are never buffered.

Auth flow:
  1. Exempt: GET /health, GET /, POST /mcp where body.method == "initialize"
  2. Extract key from Authorization: Bearer {key} or X-Norric-Key: {key}
  3. Validate key hash — 401 if absent or unknown
  4. For tools/call:
       a. check tool_allowed(tool_name, tier) — 403 if blocked
       b. Free tier only: check per-minute rate limit (5/min) — 429 if exceeded
       c. Free tier only: check+increment monthly quota in DB (50/month) — 429 if exceeded
  5. Attach ApiKey to ASGI scope["norric_api_key"] for downstream use
"""
import asyncio
import json
from typing import Callable

from core.api_keys import ApiKey, validate_key
from core.tier_policy import check_rate_limit, tool_allowed
from core.quota import check_and_increment_quota

_EXEMPT_PATHS = {"/health", "/"}
_UPGRADE_URL = "https://norric.io/pricing"


async def _send_json(send: Callable, body: dict, status: int) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


async def _read_body(receive: Callable) -> bytes:
    """Drain the ASGI receive channel and return the full request body."""
    body = b""
    while True:
        msg = await receive()
        if msg["type"] == "http.request":
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break
    return body


def _make_receive(body: bytes) -> Callable:
    """Reconstruct a one-shot receive callable from already-read bytes."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(1e9)

    return receive


class NorricAuthMiddleware:
    """
    ASGI middleware: authenticate every non-exempt request, enforce tier policy.

    Attach to the FastMCP ASGI app:
        app = NorricAuthMiddleware(mcp.http_app())
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        body = b""
        parsed = None
        if path == "/mcp" and method == "POST":
            body = await _read_body(receive)
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass

        if parsed is not None and parsed.get("method") == "initialize":
            await self.app(scope, _make_receive(body), send)
            return

        # ── Extract API key ───────────────────────────────────────────────────
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_key = ""

        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        if auth_header.startswith("Bearer "):
            raw_key = auth_header[7:].strip()

        if not raw_key:
            raw_key = headers.get(b"x-norric-key", b"").decode("latin-1").strip()

        if not raw_key:
            await _send_json(send, {"error": "Unauthorized", "code": 401}, 401)
            return

        api_key: ApiKey | None = validate_key(raw_key)
        if api_key is None:
            await _send_json(send, {"error": "Unauthorized", "code": 401}, 401)
            return

        # ── Tier enforcement (tools/call only) ────────────────────────────────
        if parsed is not None and parsed.get("method") == "tools/call":
            tool_name = (parsed.get("params") or {}).get("name", "")

            if not tool_allowed(tool_name, api_key.tier):
                await _send_json(
                    send,
                    {
                        "error": "tool_not_available",
                        "tier": api_key.tier,
                        "upgrade_url": _UPGRADE_URL,
                    },
                    403,
                )
                return

            if api_key.tier == "free":
                # Per-minute rate limit (in-memory, no DB)
                if not check_rate_limit(api_key.hash):
                    await _send_json(
                        send,
                        {
                            "error": "rate_limit_exceeded",
                            "limit": 5,
                            "window": "1 minute",
                            "tier": "free",
                            "upgrade_url": _UPGRADE_URL,
                        },
                        429,
                    )
                    return

                # Monthly quota (DB-backed)
                allowed = await asyncio.to_thread(check_and_increment_quota, api_key.hash)
                if not allowed:
                    await _send_json(
                        send,
                        {
                            "error": "monthly_quota_exceeded",
                            "limit": 50,
                            "tier": "free",
                            "upgrade_url": _UPGRADE_URL,
                        },
                        429,
                    )
                    return

        scope["norric_api_key"] = api_key

        downstream_receive = _make_receive(body) if body else receive
        await self.app(scope, downstream_receive, send)
