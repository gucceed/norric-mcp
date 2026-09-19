"""x402 v2 testnet payment gate for selected MCP tools.

This proof is deliberately testnet-only. It refuses every network except Base
Sepolia and is disabled unless all required environment variables are present.
No wallet private key belongs in this service: buyers sign their own payment,
and settlement goes to the configured public receiving address.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

BASE_SEPOLIA = "eip155:84532"
DEFAULT_FACILITATOR_URL = "https://x402.org/facilitator"


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
        "price": values.get("X402_DATA_FRESHNESS_PRICE", "$0.01").strip() or "$0.01",
    }


def build_data_freshness_wrapper(env: dict[str, str] | None = None) -> Callable[[Callable], Callable]:
    """Build a payment decorator, or a no-op while the proof is disabled.

    The wrapper is limited to ``norric_data_freshness_v1`` by its call site. API
    key auth remains in front of MCP during this proof, so no other tool becomes
    anonymous. A later migration can make paid MCP calls an alternative auth
    path after the testnet flow is proven.
    """
    if not _enabled(env):
        return lambda handler: handler

    config = validate_testnet_config(env)

    from x402 import ResourceConfig, x402ResourceServer
    from x402.http import HTTPFacilitatorClient
    from x402.mcp import create_payment_wrapper
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
            price=config["price"],
            maxTimeoutSeconds=120,
        )
    )
    payment_wrapper = create_payment_wrapper(
        resource_server,
        accepts=accepts,
        resource=ResourceInfo(
            url="mcp://tool/norric_data_freshness_v1",
            description="Current freshness of Norric public-data pipelines",
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
