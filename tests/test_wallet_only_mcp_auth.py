import asyncio
import json

import pytest


async def _request(middleware, payload, headers=()):
    sent = []
    messages = [{
        "type": "http.request",
        "body": json.dumps(payload).encode(),
        "more_body": False,
    }]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await middleware(
        {"type": "http", "path": "/mcp", "headers": list(headers)},
        receive,
        send,
    )
    return sent


@pytest.fixture
def middleware(monkeypatch):
    monkeypatch.setattr("core.auth.verify_master_key", lambda key: key == "enterprise")
    import server

    observed = []

    async def downstream(scope, receive, send):
        body = await receive()
        observed.append((scope, json.loads(body["body"])))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return server._NorricAuthMiddleware(downstream), observed


def test_anonymous_can_initialize_and_discover(middleware):
    auth, observed = middleware
    for method in ("initialize", "tools/list"):
        sent = asyncio.run(_request(auth, {"jsonrpc": "2.0", "method": method, "params": {}}))
        assert sent[0]["status"] == 200
    assert all(item[0]["norric_auth_source"] == "anonymous_x402" for item in observed)


def test_anonymous_paid_tool_reaches_payment_wrapper(middleware):
    auth, observed = middleware
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "norric_data_freshness_v1", "arguments": {}},
    }
    sent = asyncio.run(_request(auth, payload))
    assert sent[0]["status"] == 200
    assert observed[0][1] == payload


def test_anonymous_public_status_is_allowed(middleware):
    auth, _ = middleware
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "norric_status_v1", "arguments": {}},
    }
    assert asyncio.run(_request(auth, payload))[0]["status"] == 200


def test_anonymous_cannot_reach_other_tools(middleware):
    auth, observed = middleware
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "norric_company_lookup_v1", "arguments": {}},
    }
    sent = asyncio.run(_request(auth, payload))
    assert sent[0]["status"] == 403
    assert not observed


def test_existing_api_key_path_is_unchanged(middleware):
    auth, observed = middleware
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "norric_company_lookup_v1", "arguments": {}},
    }
    headers = [(b"authorization", b"Bearer enterprise")]
    sent = asyncio.run(_request(auth, payload, headers))
    assert sent[0]["status"] == 200
    assert observed[0][0]["norric_auth_source"] == "master"
