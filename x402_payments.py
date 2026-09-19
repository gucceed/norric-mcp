"""x402 v2 testnet payment gate for selected MCP tools.

This proof is deliberately testnet-only. It refuses every network except Base
Sepolia and is disabled unless all required environment variables are present.
No wallet private key belongs in this service: buyers sign their own payment,
and settlement goes to the configured public receiving address.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

BASE_SEPOLIA = "eip155:84532"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
DEFAULT_FACILITATOR_URL = "https://x402.org/facilitator"
PRICE_BANDS_ATOMIC = {
    "lookup": 2_000,
    "signal": 5_000,
    "evidence": 10_000,
    "feed_batch": 20_000,
    "heavy": 50_000,
}
TOOL_PRICE_BANDS = {
    "kreditvakt_score_company_v1": "lookup",
}
_WALLET_WINDOW_SECONDS = 3600
_WALLET_MAX_CALLS_PER_WINDOW = 30
_wallet_calls: dict[str, deque[float]] = defaultdict(deque)


def _payment_payer(payload: Any) -> str:
    """Extract the EVM payer from an already verified exact payment payload."""
    data = getattr(payload, "payload", {}) or {}
    authorization = data.get("authorization", {}) if isinstance(data, dict) else {}
    return str(authorization.get("from", "")).lower()


def _allow_wallet_payment(payload: Any, now: float | None = None) -> bool:
    """Bound a wallet to 30 paid tool executions/hour in this process."""
    payer = _payment_payer(payload)
    if not payer:
        return False
    timestamp = time.monotonic() if now is None else now
    calls = _wallet_calls[payer]
    while calls and calls[0] <= timestamp - _WALLET_WINDOW_SECONDS:
        calls.popleft()
    if len(calls) >= _WALLET_MAX_CALLS_PER_WINDOW:
        return False
    calls.append(timestamp)
    return True


class X402ConfigurationError(RuntimeError):
    pass


def _enabled(env: dict[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return values.get("X402_TESTNET_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def validate_testnet_config(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return validated testnet config, refusing mainnet or incomplete setup."""
    values = env if env is not None else os.environ
    network = values.get("X402_NETWORK", BASE_SEPOLIA).strip()
    if network != BASE_SEPOLIA:
        raise X402ConfigurationError(
            f"x402 proof is Base Sepolia only ({BASE_SEPOLIA}); got {network!r}"
        )

    pay_to = values.get("X402_PAY_TO", "").strip()
    if not pay_to:
        raise X402ConfigurationError("X402_PAY_TO is required when the testnet gate is enabled")
    if not (pay_to.startswith("0x") and len(pay_to) == 42):
        raise X402ConfigurationError("X402_PAY_TO must be a 20-byte EVM address")

    facilitator_url = values.get("X402_FACILITATOR_URL", "").strip()
    if not facilitator_url:
        raise X402ConfigurationError(
            "X402_FACILITATOR_URL is required; deploy the facilitator in the EU and pass its URL"
        )
    if not facilitator_url.startswith("https://"):
        raise X402ConfigurationError("X402_FACILITATOR_URL must use HTTPS")

    return {
        "network": network,
        "pay_to": pay_to,
        "facilitator_url": facilitator_url,
    }


def validate_price_bands() -> None:
    """Fail closed on malformed or non-increasing exact-price bands."""
    expected = ("lookup", "signal", "evidence", "feed_batch", "heavy")
    if tuple(PRICE_BANDS_ATOMIC) != expected:
        raise X402ConfigurationError("x402 price bands must use the approved order")
    prices = tuple(PRICE_BANDS_ATOMIC.values())
    if any(not isinstance(price, int) or price <= 0 for price in prices):
        raise X402ConfigurationError("x402 price bands must be positive atomic integers")
    if prices != tuple(sorted(set(prices))):
        raise X402ConfigurationError("x402 price bands must be unique and increasing")
    if any(band not in PRICE_BANDS_ATOMIC for band in TOOL_PRICE_BANDS.values()):
        raise X402ConfigurationError("every paid tool must reference a known price band")


def build_tool_payment_wrapper(tool_name: str, env: dict[str, str] | None = None) -> Callable[[Callable], Callable]:
    """Build a payment decorator, or a no-op while the proof is disabled.

    Tool-to-band assignment is data in ``TOOL_PRICE_BANDS``. Only explicitly
    assigned tools are payable; discovery, status and freshness remain free.
    """
    if not _enabled(env):
        return lambda handler: handler

    config = validate_testnet_config(env)
    validate_price_bands()
    band = TOOL_PRICE_BANDS.get(tool_name)
    if band is None:
        raise X402ConfigurationError(f"no approved x402 price band for {tool_name!r}")
    price_atomic = PRICE_BANDS_ATOMIC[band]

    from x402 import AssetAmount, ResourceConfig, x402ResourceServer
    from x402.http import HTTPFacilitatorClient
    from x402.mcp import PaymentWrapperHooks, create_payment_wrapper
    from fastmcp import Context
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.schemas import ResourceInfo

    facilitator = HTTPFacilitatorClient({"url": config["facilitator_url"]})
    resource_server = x402ResourceServer(facilitator)
    resource_server.register(BASE_SEPOLIA, ExactEvmServerScheme())
    resource_server.initialize()
    accepts = resource_server.build_payment_requirements(
        ResourceConfig(
            scheme="exact",
            network=BASE_SEPOLIA,
            payTo=config["pay_to"],
            price=AssetAmount(amount=str(price_atomic), asset=BASE_SEPOLIA_USDC),
            maxTimeoutSeconds=120,
        )
    )
    payment_wrapper = create_payment_wrapper(
        resource_server,
        accepts=accepts,
        hooks=PaymentWrapperHooks(
            on_before_execution=lambda context: _allow_wallet_payment(
                context.payment_payload
            )
        ),
        resource=ResourceInfo(
            url=f"mcp://tool/{tool_name}",
            description=f"Norric paid tool: {tool_name}",
            mime_type="application/json",
            service_name="Norric",
            tags=["sweden", "company-data", "freshness"],
        ),
    )

    def fastmcp_context_compatible(handler: Callable) -> Callable:
        """Bridge x402's legacy MCP types to standalone FastMCP 3."""
        import functools
        import inspect

        from fastmcp.tools import ToolResult
        from mcp.types import CallToolResult

        x402_wrapped = payment_wrapper(handler)

        @functools.wraps(x402_wrapped)
        async def compatible(**kwargs: Any) -> Any:
            result = await x402_wrapped(**kwargs)
            if isinstance(result, CallToolResult):
                return ToolResult(
                    content=result.content,
                    structured_content=result.structuredContent,
                    meta=result.meta,
                )
            return result

        signature = inspect.signature(x402_wrapped, follow_wrapped=False)
        compatible.__signature__ = signature.replace(
            parameters=[
                parameter.replace(annotation=Context)
                if parameter.name == "ctx"
                else parameter
                for parameter in signature.parameters.values()
            ],
            return_annotation=ToolResult,
        )
        compatible.__annotations__ = {
            **getattr(x402_wrapped, "__annotations__", {}),
            "ctx": Context,
            "return": ToolResult,
        }
        return compatible

    return fastmcp_context_compatible


# Backwards-compatible import for old callers; freshness is intentionally free.
def build_data_freshness_wrapper(env=None):
    return lambda handler: handler
