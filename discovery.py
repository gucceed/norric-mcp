"""Public marketplace discovery documents for Norric's x402 HTTP surface."""
from __future__ import annotations

import inspect
import os
from typing import Any, Awaitable, Callable

from starlette.responses import JSONResponse

from x402_payments import (
    BASE_SEPOLIA,
    BASE_SEPOLIA_USDC,
    PRICE_BANDS_ATOMIC,
    TOOL_PRICE_BANDS,
    validate_testnet_config,
)

ORIGIN = "https://mcp.norric.io"
CONTACT = "edgar@norric.io"

HTTP_PAID_ROUTES = {
    "/x402/company/score": {
        "tool": "kreditvakt_score_company_v1",
        "summary": "Score a Swedish company's insolvency risk",
        "description": "Returns source-backed Swedish company risk signals and freshness metadata.",
        "parameters": [
            {
                "name": "orgnr",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "minLength": 2},
                "description": "Swedish organisation number or company name.",
            }
        ],
    },
    "/x402/company/verify": {
        "tool": "swedish_company_verify_v1",
        "summary": "Verify a Swedish company against registry data",
        "description": "Returns normalized company identity, legal status, evidence and source timestamps.",
        "parameters": [
            {
                "name": "orgnr_or_name",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "minLength": 2},
                "description": "Swedish organisation number or company name.",
            }
        ],
    },
    "/x402/company/changes": {
        "tool": "swedish_company_changes_v1",
        "summary": "Read recent Swedish company registry changes",
        "description": "Returns source-backed registrations, closures, renames, address changes and mergers.",
        "parameters": [
            {"name": "days", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7}},
            {"name": "days", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}},
        ],
    },
}


def _price_usd(tool_name: str) -> str:
    band = TOOL_PRICE_BANDS[tool_name]
    return f"{PRICE_BANDS_ATOMIC[band] / 1_000_000:.6f}"


def openapi_document() -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "operationId": "getHealth",
                "summary": "Get service and pipeline health",
                "responses": {"200": {"description": "Current service health"}},
            }
        }
    }
    for path, route in HTTP_PAID_ROUTES.items():
        tool_name = route["tool"]
        paths[path] = {
            "get": {
                "operationId": tool_name,
                "summary": route["summary"],
                "description": route["description"],
                "tags": ["Paid Swedish company intelligence"],
                "parameters": route["parameters"],
                "x-payment-info": {
                    "price": {"mode": "fixed", "currency": "USD", "amount": _price_usd(tool_name)},
                    "protocols": [{"x402": {}}],
                },
                "responses": {
                    "200": {
                        "description": "Norric response envelope",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/NorricEnvelope"}}},
                    },
                    "402": {
                        "description": "Payment Required",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "422": {"description": "Invalid input"},
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Norric x402 Company Intelligence API",
            "version": "2.0.0",
            "description": "Pay-per-call Swedish registry verification, risk and change intelligence for autonomous agents. Test USDC on Base Sepolia only; mainnet is blocked.",
            "x-guidance": "Use /x402/company/verify first to resolve and verify a Swedish company. Use /x402/company/score for insolvency-risk signals and /x402/company/changes for recent registry changes. Every successful result uses the Norric envelope with source, confidence, freshness and warnings.",
            "contact": {"name": "Norric", "email": CONTACT, "url": "https://norric.io/docs"},
        },
        "servers": [{"url": ORIGIN}],
        "externalDocs": {"description": "Norric agent guide", "url": "https://norric.io/docs"},
        "paths": paths,
        "components": {
            "schemas": {
                "NorricEnvelope": {
                    "type": "object",
                    "required": ["data", "metadata", "signals", "warnings"],
                    "properties": {
                        "data": {"type": "object", "additionalProperties": True},
                        "metadata": {"type": "object", "additionalProperties": True},
                        "signals": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                    },
                }
            }
        },
    }


def well_known_document() -> dict[str, Any]:
    config = validate_testnet_config() if os.environ.get("X402_TESTNET_ENABLED", "").lower() in {"1", "true", "yes"} else None
    endpoints = []
    for path, route in HTTP_PAID_ROUTES.items():
        endpoints.append({
            "id": route["tool"],
            "method": "GET",
            "path": path,
            "description": route["description"],
            "priceUsd": float(_price_usd(route["tool"])),
        })
    return {
        "x402Version": 2,
        "service": {
            "name": "Norric",
            "description": "Swedish company registry verification and change intelligence for agents.",
            "url": ORIGIN,
            "homepage": "https://norric.io",
            "openapi": f"{ORIGIN}/openapi.json",
            "llmsTxt": "https://norric.io/llms.txt",
            "mcp": f"{ORIGIN}/mcp",
        },
        "settlement": {
            "network": BASE_SEPOLIA,
            "asset": "test USDC",
            "assetAddress": BASE_SEPOLIA_USDC,
            "treasury": config["pay_to"] if config else None,
            "facilitator": config["facilitator_url"] if config else None,
            "testnet": True,
        },
        "resources": [f"{ORIGIN}{path}" for path in HTTP_PAID_ROUTES],
        "endpoints": endpoints,
    }


def _query(scope: dict[str, Any]) -> dict[str, list[str]]:
    from urllib.parse import parse_qs
    return parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)


async def execute_route(path: str, scope: dict[str, Any], handlers: dict[str, Callable[..., Awaitable[Any]]], receive, send) -> None:
    route = HTTP_PAID_ROUTES[path]
    values = _query(scope)
    try:
        if path == "/x402/company/score":
            kwargs = {"orgnr": values["orgnr"][0]}
        elif path == "/x402/company/verify":
            kwargs = {"orgnr_or_name": values["orgnr_or_name"][0]}
        else:
            kwargs = {
                "days": int(values.get("days", ["7"])[0]),
                "event_types": values.get("event_types") or None,
                "limit": int(values.get("limit", ["25"])[0]),
                "orgnr": (values.get("orgnr") or [None])[0],
            }
            if not 1 <= kwargs["days"] <= 30 or not 1 <= kwargs["limit"] <= 100:
                raise ValueError("days must be 1-30 and limit must be 1-100")
    except (KeyError, ValueError) as exc:
        await JSONResponse({"error": str(exc)}, status_code=422)(scope, receive, send)
        return

    # HTTP payment middleware has already verified the request. Unwrap the MCP
    # payment adapter so this path executes exactly once and settles once.
    handler = inspect.unwrap(handlers[route["tool"]])
    result = await handler(**kwargs)
    await JSONResponse(result)(scope, receive, send)
