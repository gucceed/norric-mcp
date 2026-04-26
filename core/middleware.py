"""
Norric MCP — ASGI authentication and tier-enforcement middleware.

Pure ASGI (not BaseHTTPMiddleware) so streaming MCP responses are never buffered.

Auth flow:
  1. Exempt: GET /health, GET /, POST /mcp where body.method == "initialize"
  2. Extract key from Authorization: Bearer {key} or X-Norric-Key: {key}
  3. Validate key hash — 401 if absent or unknown
  4. For tools/call: check tool_allowed(tool_name, tier) — 403 if blocked
  5. Check daily rate limit — 429 if exceeded
  6. Attach ApiKey to ASGI scope["norric_api_key"] for downstream use
"""
import json
from typing import Callable

from core.api_keys import ApiKey, validate_key
from core.tier_policy import check_and_increment, tool_allowed

_EXEMPT_PATHS = {"/health", "/"}


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
        # Subsequent calls block indefinitely (client disconnect simulation)
        import asyncio
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
        # Pass through non-HTTP connections (WebSocket, lifespan)
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # Always exempt health and root
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # For /mcp POST, we must read the body to inspect method and tool name
        body = b""
        parsed = None
        if path == "/mcp" and method == "POST":
            body = await _read_body(receive)
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass

        # Exempt the MCP initialize handshake — client must open session before presenting key
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
                        "error": "Tool not available on your tier",
                        "upgrade_url": "https://norric.se/api",
                    },
                    403,
                )
                return

            if not check_and_increment(api_key.hash, api_key.tier):
                await _send_json(
                    send,
                    {
                        "error": "Daily rate limit exceeded",
                        "upgrade_url": "https://norric.se/api",
                    },
                    429,
                )
                return

        # Attach key to scope for downstream handlers (audit logging etc.)
        scope["norric_api_key"] = api_key

        # Forward request — reconstruct receive if body was consumed
        downstream_receive = _make_receive(body) if body else receive
        await self.app(scope, downstream_receive, send)
