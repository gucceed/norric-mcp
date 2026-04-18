"""
norric-mcp/server.py

Norric AB — Live MCP Server
Built with FastMCP 3.x · Streamable HTTP transport

This is the single entry point. Run with:
    python server.py

Or in production (Railway / Render):
    uvicorn server:app --host 0.0.0.0 --port $PORT

Connects to Claude Code, Cursor, Windsurf, and any MCP-compatible client.

Architecture:
    FastMCP wraps the tool logic from servers/signal/ and servers/kreditvakt/.
    Every tool returns the NorricResponse envelope — consistent across all products.
    Auth is capability-scoped via X-Norric-Key header (or Bearer token).
    All mutating tools write to the audit trail.

Transport: Streamable HTTP (the 2026 standard — replaces SSE)
Post-AGI ready: streaming tools, versioned schemas, semantic tool descriptions.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastmcp import FastMCP

# ── Core envelope types (inline for single-file deployability) ─────────────────

from pydantic import BaseModel, Field
from enum import Enum


class SignalDirection(str, Enum):
    RISK    = "risk"
    HEALTH  = "health"
    NEUTRAL = "neutral"


class NorricSignal(BaseModel):
    key: str
    label: str
    value: object
    weight: float = Field(ge=0, le=1)
    direction: SignalDirection
    source: str
    observed_at: Optional[datetime] = None


class NorricMeta(BaseModel):
    response_id: str
    tool: str
    source: str | list[str]
    fetched_at: datetime
    confidence: float = Field(ge=0, le=1)
    cache_ttl_seconds: int
    is_cached: bool = False
    data_as_of: Optional[datetime] = None


def meta(tool: str, source: str | list[str], confidence: float, ttl: int) -> dict:
    """Build a standard metadata dict for every response."""
    import secrets
    return {
        "response_id": f"nrsp_{secrets.token_hex(6)}",
        "tool": tool,
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "confidence": confidence,
        "cache_ttl_seconds": ttl,
        "is_cached": False,
    }


def wrap(tool: str, source: str | list[str], confidence: float, ttl: int, data: dict,
         signals: list[dict] | None = None, warnings: list[str] | None = None) -> dict:
    """
    The Norric response envelope.
    Every tool returns this shape. No exceptions.
    Agents parse structure, not narrative.
    """
    return {
        "data": data,
        "metadata": meta(tool, source, confidence, ttl),
        "signals": signals or [],
        "warnings": warnings or [],
    }


# ── Shared types ───────────────────────────────────────────────────────────────

import re

def validate_orgnr(v: str) -> str:
    clean = v.replace("-", "").replace(" ", "")
    if not re.fullmatch(r"\d{10}", clean) or clean[0] == "0":
        raise ValueError(f"Invalid Swedish organisation number: {v!r}. Example: 556000-1234")
    return f"{clean[:6]}-{clean[6:]}"

def validate_kommunkod(v: str) -> str:
    clean = v.strip().zfill(4)
    # Spot check — full list in shared/schemas/types.py
    if not re.fullmatch(r"\d{4}", clean):
        raise ValueError(f"Invalid kommunkod: {v!r}")
    return clean

VERTIKAL_VALUES = {"aldreomsorg", "skola", "it_digital", "fastighet", "hr", "bygg", "annat"}

def validate_vertikal(v: str) -> str:
    norm = v.lower().replace(" ", "_").replace("/", "_")
    if norm not in VERTIKAL_VALUES:
        raise ValueError(f"Unknown vertikal: {v!r}. Valid: {', '.join(sorted(VERTIKAL_VALUES))}")
    return norm

MUNICIPALITY_NAMES = {
    "1280": "Malmö", "1281": "Lund", "1282": "Landskrona",
    "1283": "Helsingborg", "1284": "Höganäs", "1285": "Eslöv",
    "1286": "Ystad", "1287": "Trelleborg", "1290": "Kristianstad",
    "0180": "Stockholm", "0181": "Södertälje", "0182": "Nacka",
    "1480": "Göteborg", "1481": "Mölndal", "1482": "Kungälv",
    "0381": "Uppsala", "0480": "Nyköping",
}


# ── FastMCP server ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="Norric Intelligence MCP",
    instructions=(
        "Norric AB — Swedish B2B intelligence infrastructure. "
        "Tools span municipal procurement signals (SIGNAL), company insolvency risk "
        "(Kreditvakt), business lifecycle detection (Vigil), website generation "
        "(SiteLoop), and BRF property intelligence (Sigvik). "
        "All tools return the Norric envelope: { data, metadata, signals, warnings }. "
        "metadata.confidence (0-1) indicates data reliability. "
        "metadata.cache_ttl_seconds tells you how long to trust the response. "
        "Every Swedish company is identified by orgnr (e.g. 556000-1234). "
        "Municipalities use 4-digit kommunkod (e.g. 1280 for Malmö). "
        "Available verticals: aldreomsorg, skola, it_digital, fastighet, hr, bygg, annat."
    ),
    version="0.1.0",
    website_url="https://norric.se",
)


# ════════════════════════════════════════════════════════════════════════════════
# NORRIC SIGNAL — Municipal procurement intelligence
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="signal_score_municipality_v1",
    description=(
        "Score the procurement readiness of a Swedish municipality for a given vertical. "
        "Combines 7 signal components (IVO decisions, protocol signals, budget motions, "
        "contract expiries, SCB demographics, Kronofogden incumbent risk, SKR benchmarks) "
        "into a 0-100 composite score. "
        "Scores above 70 indicate actionable procurement intent — contact this week. "
        "Scores 50-70 are warm — contact this month. Below 50, monitor only."
    ),
)
async def signal_score_municipality(
    kommunkod: str,
    vertikal: str,
) -> dict:
    """
    Score a municipality × vertical for procurement readiness.

    Args:
        kommunkod: 4-digit Swedish municipality code (e.g. 1280 for Malmö,
                   0180 for Stockholm, 1480 for Göteborg)
        vertikal: Procurement vertical. One of: aldreomsorg, skola, it_digital,
                  fastighet, hr, bygg, annat
    """
    kommunkod = validate_kommunkod(kommunkod)
    vertikal  = validate_vertikal(vertikal)
    name      = MUNICIPALITY_NAMES.get(kommunkod, f"Kommun {kommunkod}")

    # TODO: replace stub with real DB query against SIGNAL ingestion pipeline
    return wrap(
        tool="signal_score_municipality_v1",
        source=["kommunala_protokoll", "ivo", "upphandlingsregistret",
                "scb", "kronofogden", "avtalsdatabaser", "skr"],
        confidence=0.0,
        ttl=14_400,
        data={
            "kommunkod": kommunkod,
            "municipality_name": name,
            "vertikal": vertikal,
            "composite_score": 0.0,
            "urgency": "quiet",
            "components": [],
            "note": "Ingestion pipeline not yet connected. Score reflects no live data.",
        },
        warnings=["SIGNAL ingestion pipeline not yet live. Connect database to activate scoring."],
    )


@mcp.tool(
    name="signal_weekly_call_list_v1",
    description=(
        "Return the ranked list of Swedish municipalities to contact this week for a given vertical. "
        "Sorted by composite procurement score descending. "
        "This is the core Norric SIGNAL product output — the Monday morning call list "
        "for sales teams and autonomous SDR agents. "
        "Each entry includes the primary signal, suggested call window, and opening talking point. "
        "Maximum 50 results. Updated every Monday at 06:00 CET."
    ),
)
async def signal_weekly_call_list(
    vertikal: str,
    limit: int = 10,
) -> dict:
    """
    Get this week's ranked municipality call list for a vertical.

    Args:
        vertikal: Procurement vertical (aldreomsorg | skola | it_digital |
                  fastighet | hr | bygg | annat)
        limit: Number of results to return (default 10, max 50)
    """
    vertikal = validate_vertikal(vertikal)
    limit    = min(max(1, limit), 50)

    import httpx
    VMAP={"aldreomsorg":"eldercare","skola":"edtech","it_digital":"it_digital","fastighet":"facilities","hr":"hr_workforce","bygg":"construction","annat":None}
    av=VMAP.get(vertikal)
    params={"limit":limit}
    if av: params["vertical"]=av
    async with httpx.AsyncClient(timeout=12.0) as cl:
        r=(await cl.get("https://munisignal.polsia.app/api/v1/intelligence/priority",headers={"Authorization":"Bearer bcab14902e793026eb3007a68f6396ec"},params=params)).json()
    items=r if isinstance(r,list) else(r.get("municipalities") or r.get("data") or [])
    def gs(m): return float(m.get("signal_score") or m.get("score") or 0)
    entries=[{"rank":i+1,"kommunkod":m.get("municipality_kod") or m.get("kod",""),"municipality_name":m.get("municipality_name") or m.get("name",""),"vertikal":vertikal,"composite_score":round(gs(m),1),"urgency":"hot" if gs(m)>=80 else "warm" if gs(m)>=60 else "quiet","components":m.get("signal_drivers") or []} for i,m in enumerate(sorted(items,key=gs,reverse=True)[:limit])]
    return wrap(tool="signal_weekly_call_list_v1",source=["munisignal.polsia.app"],confidence=0.85,ttl=43_200,data={"vertikal":vertikal,"week":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isocalendar()[1],"entries":entries,"total":len(entries)},warnings=[])

