"""
Master-key auth — end-to-end against the live ASGI app.

Three cases gate the /mcp endpoint:
  1. no header           → 401
  2. wrong X-Norric-Key  → 401
  3. correct key         → 200 + mcp-session-id header on initialize

Fixture pins NORRIC_MASTER_KEY_HASH to argon2(MASTER_PLAINTEXT) at
session scope. Tests exercise server.app — same middleware stack
that ships to production.

Regression case 4 confirms `Authorization: Bearer <master>` continues
to work alongside the new X-Norric-Key alias.
"""
from __future__ import annotations

import json
import os

import pytest

MASTER_PLAINTEXT = "test_key_dev"


@pytest.fixture(scope="session", autouse=True)
def _master_key_env():
    """Pin NORRIC_MASTER_KEY_HASH for the duration of the test session.

    autouse=True so any test importing server.app gets the env var set
    before server.py's middleware reads it via core.auth.verify_master_key
    on first request.
    """
    from argon2 import PasswordHasher
    os.environ["NORRIC_MASTER_KEY_HASH"] = PasswordHasher().hash(MASTER_PLAINTEXT)
    # Ensure the env-key escape hatch is empty so it cannot mask a regression
    # in the master-key path.
    os.environ.pop("NORRIC_API_KEYS", None)
    yield


@pytest.fixture(scope="session")
def client():
    """Lazy-import server.app so the env-var fixture runs first."""
    from starlette.testclient import TestClient
    from server import app
    with TestClient(app) as c:
        yield c


def _initialize_body() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


_MCP_HEADERS_BASE = {
    "Content-Type":  "application/json",
    "Accept":        "application/json, text/event-stream",
}


def test_no_header_returns_401(client):
    r = client.post("/mcp", headers=_MCP_HEADERS_BASE, content=json.dumps(_initialize_body()))
    assert r.status_code == 401, r.text
    body = r.json()
    assert "Missing API key" in body.get("error", ""), body


def test_wrong_key_returns_401(client):
    headers = {**_MCP_HEADERS_BASE, "X-Norric-Key": "nk_master_wrong"}
    r = client.post("/mcp", headers=headers, content=json.dumps(_initialize_body()))
    assert r.status_code == 401, r.text
    body = r.json()
    assert "Invalid API key" in body.get("error", ""), body


def test_correct_x_norric_key_returns_session_id(client):
    headers = {**_MCP_HEADERS_BASE, "X-Norric-Key": MASTER_PLAINTEXT}
    r = client.post("/mcp", headers=headers, content=json.dumps(_initialize_body()))
    assert r.status_code == 200, r.text
    # FastMCP's Streamable HTTP returns the session id on the initialize response.
    # Header name is case-insensitive; httpx normalises to lower.
    session_id = r.headers.get("mcp-session-id")
    assert session_id, f"missing mcp-session-id; headers={dict(r.headers)}"


def test_correct_bearer_master_returns_session_id(client):
    """Regression: Authorization: Bearer <master> still works after the
    X-Norric-Key alias was added."""
    headers = {**_MCP_HEADERS_BASE, "Authorization": f"Bearer {MASTER_PLAINTEXT}"}
    r = client.post("/mcp", headers=headers, content=json.dumps(_initialize_body()))
    assert r.status_code == 200, r.text
    assert r.headers.get("mcp-session-id"), f"missing mcp-session-id; headers={dict(r.headers)}"
