import asyncio
import inspect
from importlib.metadata import version
from types import SimpleNamespace

from fastmcp import Client, Context, FastMCP
from mcp.types import CallToolResult, TextContent

import x402_payments


def test_paid_retry_metadata_reaches_wrapper_and_returns_settlement(monkeypatch):
    """Exercise the production FastMCP request path, not just signature parsing."""
    assert version("fastmcp") == "3.2.3"
    class FakeFacilitator:
        def __init__(self, config):
            pass

    class FakeServer:
        def __init__(self, facilitator):
            pass
        def register(self, network, scheme):
            pass
        def initialize(self):
            pass
        def build_payment_requirements(self, config):
            return [SimpleNamespace(network=config.network, scheme="exact")]
        def get_registered_scheme(self, network, scheme):
            return SimpleNamespace(payment_flows=None)

    observed = {}

    def fake_payment_wrapper(*args, **kwargs):
        def decorate(handler):
            async def wrapped(*, ctx=None):
                payment = ctx.request_context.meta.model_extra["x402/payment"]
                observed["payment"] = payment
                observed["result"] = await handler()
                return CallToolResult(
                    content=[TextContent(type="text", text=observed["result"])],
                    _meta={"x402/payment-response": {"transaction": "0xsettled"}},
                )
            wrapped.__signature__ = inspect.Signature([
                inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, default=None)
            ])
            wrapped.__annotations__ = {"ctx": object}
            return wrapped
        return decorate

    monkeypatch.setattr("x402.http.HTTPFacilitatorClient", FakeFacilitator)
    monkeypatch.setattr("x402.x402ResourceServer", FakeServer)
    monkeypatch.setattr("x402.mcp.create_payment_wrapper", fake_payment_wrapper)

    decorator = x402_payments.build_data_freshness_wrapper({
        "X402_TESTNET_ENABLED": "true",
        "X402_NETWORK": "eip155:84532",
        "X402_PAY_TO": "0x" + "1" * 40,
        "X402_FACILITATOR_URL": "https://facilitator.example",
    })

    async def run_request():
        mcp = FastMCP("x402-context-test")

        @mcp.tool(name="paid")
        @decorator
        async def paid_handler():
            return "tool executed"

        async with Client(mcp) as client:
            return await client.call_tool_mcp(
                "paid", {}, meta={"x402/payment": {"signature": "signed"}}
            )

    result = asyncio.run(run_request())
    assert observed == {
        "payment": {"signature": "signed"},
        "result": "tool executed",
    }
    assert result.meta == {
        "x402/payment-response": {"transaction": "0xsettled"}
    }
    assert result.content[0].text == "tool executed"
    assert inspect.signature(decorator(lambda: None), follow_wrapped=False).parameters[
        "ctx"
    ].annotation is Context
