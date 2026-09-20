import asyncio
import json


def _request(asgi, path, query_string=b""):
    sent = []
    messages = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(asgi(
        {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
         "query_string": query_string, "headers": []},
        receive, send,
    ))
    return sent


def _body(sent):
    return json.loads(b"".join(x.get("body", b"") for x in sent if x["type"] == "http.response.body"))


def test_openapi_describes_all_paid_routes():
    from discovery import HTTP_PAID_ROUTES, openapi_document
    spec = openapi_document()
    assert spec["servers"] == [{"url": "https://mcp.norric.io"}]
    assert spec["info"]["x-guidance"]
    assert spec["info"]["contact"]["email"] == "edgar@norric.io"
    for path in HTTP_PAID_ROUTES:
        operation = spec["paths"][path]["get"]
        assert operation["responses"]["402"]
        assert operation["x-payment-info"]["protocols"] == [{"x402": {}}]
        assert operation["x-payment-info"]["price"]["currency"] == "USD"


def test_well_known_lists_public_resources(monkeypatch):
    monkeypatch.delenv("X402_TESTNET_ENABLED", raising=False)
    from discovery import HTTP_PAID_ROUTES, well_known_document
    doc = well_known_document()
    assert doc["settlement"]["network"] == "eip155:84532"
    assert doc["settlement"]["testnet"] is True
    assert doc["resources"] == [f"https://mcp.norric.io{p}" for p in HTTP_PAID_ROUTES]


def test_auth_bypasses_discovery_and_paid_http(monkeypatch):
    import server
    observed = []

    async def downstream(scope, receive, send):
        observed.append(scope["path"])
        from starlette.responses import JSONResponse
        await JSONResponse({"ok": True})(scope, receive, send)

    auth = server._NorricAuthMiddleware(downstream)
    for path in ("/openapi.json", "/.well-known/x402", "/x402/company/verify"):
        sent = _request(auth, path)
        assert sent[0]["status"] == 200
    assert observed == ["/openapi.json", "/.well-known/x402", "/x402/company/verify"]


def test_health_tool_count_is_dynamic(monkeypatch):
    import server

    async def fake_list_tools():
        return [object()] * 32

    monkeypatch.setattr(server.mcp, "list_tools", fake_list_tools)
    sent = _request(server._health_handler, "/health")
    assert _body(sent)["mcp_tools"] == 32
