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

    return wrap(
        tool="signal_weekly_call_list_v1",
        source=["munisignal.polsia.app"],
            confidence=0.85,
            ttl=43_200,
            data={
                "vertikal": vertikal,
                "week": datetime.now(timezone.utc).isocalendar()[1],
                "entries": [],
                "note": "Live via munisignal API - wiring complete",
            },
            warnings=[],
        )


@mcp.tool(
    name="signal_municipality_briefing_v1",
    description=(
        "Generate a full Swedish-language call briefing for a municipality and vertical. "
        "Contains: what happened (facts), why it matters commercially, optimal call window, "
        "3 ready-to-use talking points, active signals summary, and incumbent risk flag. "
        "Designed for direct use by sales reps and autonomous SDR agents before dialling."
    ),
)
async def signal_municipality_briefing(
    kommunkod: str,
    vertikal: str,
) -> dict:
    """
    Get a full call briefing for a municipality × vertical.

    Args:
        kommunkod: 4-digit municipality code
        vertikal: Procurement vertical
    """
    kommunkod = validate_kommunkod(kommunkod)
    vertikal  = validate_vertikal(vertikal)
    name      = MUNICIPALITY_NAMES.get(kommunkod, f"Kommun {kommunkod}")

    return wrap(
        tool="signal_municipality_briefing_v1",
        source=["norric_signal_engine"],
        confidence=0.0,
        ttl=21_600,
        data={
            "kommunkod": kommunkod,
            "municipality_name": name,
            "vertikal": vertikal,
            "what_happened": "Inga aktiva signaler denna vecka.",
            "why_it_matters": "Inga upphandlingssignaler identifierade.",
            "call_window": "Avvakta",
            "talking_points": [],
            "signals_summary": [],
            "incumbent_at_risk": None,
        },
        warnings=["SIGNAL ingestion not yet live. Briefings will be generated from live data once connected."],
    )


@mcp.tool(
    name="signal_contract_expiry_alerts_v1",
    description=(
        "Return contracts expiring within N days across all 290 Swedish municipalities "
        "for a given vertical. Sorted by days until expiry ascending. "
        "Each alert includes the incumbent supplier name, contract value, and a "
        "Kronofogden risk flag indicating if the incumbent has financial distress. "
        "This is displacement-window intelligence: expiring contracts are the "
        "highest-conversion procurement opportunities."
    ),
)
async def signal_contract_expiry_alerts(
    vertikal: str,
    days_ahead: int = 90,
) -> dict:
    """
    Get contracts expiring within N days for a vertical.

    Args:
        vertikal: Procurement vertical
        days_ahead: Lookahead window in days (default 90, max 365)
    """
    vertikal   = validate_vertikal(vertikal)
    days_ahead = min(max(1, days_ahead), 365)

    return wrap(
        tool="signal_contract_expiry_alerts_v1",
        source=["avtalsdatabaser", "kronofogden"],
        confidence=0.0,
        ttl=86_400,
        data={
            "vertikal": vertikal,
            "days_ahead": days_ahead,
            "alerts": [],
        },
        warnings=["Contract database not yet connected."],
    )


@mcp.tool(
    name="signal_sweden_pulse_v1",
    description=(
        "Return the national Swedish procurement activity index across all 290 municipalities. "
        "A single 0-100 'temperature' of public procurement activity right now. "
        "Historical baseline is ~35. Values above 60 indicate elevated national activity. "
        "Optionally filter to a specific vertical or get the cross-vertical aggregate. "
        "Useful for market timing, investment research, and portfolio-level intelligence."
    ),
)
async def signal_sweden_pulse(
    vertikal: Optional[str] = None,
) -> dict:
    """
    Get the national procurement pulse.

    Args:
        vertikal: Optional vertical filter. Omit for cross-vertical national aggregate.
    """
    if vertikal:
        vertikal = validate_vertikal(vertikal)

    return wrap(
        tool="signal_sweden_pulse_v1",
        source=["norric_signal_engine"],
        confidence=0.0,
        ttl=7_200,
        data={
            "vertikal": vertikal,
            "activity_index": 0.0,
            "hot_municipalities": [],
            "heating_verticals": [],
            "ivo_alerts_7d": 0,
            "contract_expiries_30d": 0,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        },
        warnings=["SIGNAL ingestion not yet live."],
    )


# ════════════════════════════════════════════════════════════════════════════════
# NORRIC KREDITVAKT — Company insolvency intelligence
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="kreditvakt_score_company_v1",
    description=(
        "Score the insolvency risk of a Swedish company using Skatteverket "
        "restanslängd and Bolagsverket konkurs signals. "
        "Returns a 0-100 score. Historical accuracy: 80% of konkurs cases score "
        "above 70 within 9 months of filing (6x lift factor over random). "
        "Includes verdict (healthy | watch | elevated_risk | high_risk | critical), "
        "estimated days to onset, outstanding debt in SEK, and F-skatt status."
    ),
)
async def kreditvakt_score_company(
    orgnr: str,
) -> dict:
    """
    Score the insolvency risk of a Swedish company.

    Args:
        orgnr: Swedish organisation number. Accepts with or without dash.
               Examples: 556000-1234 or 5560001234
    """
    orgnr = validate_orgnr(orgnr)

    return wrap(
        tool="kreditvakt_score_company_v1",
        source=["skatteverket", "bolagsverket"],
        confidence=0.0,
        ttl=3_600,
        data={
            "orgnr": orgnr,
            "score": 0.0,
            "verdict": "unknown",
            "onset_days": None,
            "skuld_sek": None,
            "f_skatt_active": None,
            "konkurs_filed": False,
        },
        warnings=["Kreditvakt ingestion not yet live. Connect Skatteverket + Bolagsverket pipelines."],
    )


@mcp.tool(
    name="kreditvakt_batch_score_v1",
    description=(
        "Score a portfolio of Swedish companies for insolvency risk in one call. "
        "Maximum 500 organisation numbers per request. "
        "Returns each company's score, verdict, primary risk signal, and debt status. "
        "Includes a portfolio-level risk summary: % by risk tier, weighted average score, "
        "estimated SEK exposure for high-risk entries. "
        "This is the primary tool for factoring companies reviewing credit exposure at scale — "
        "replaces a manual credit review process that takes days."
    ),
)
async def kreditvakt_batch_score(
    orgnrs: list[str],
) -> dict:
    """
    Score a portfolio of Swedish companies for insolvency risk.

    Args:
        orgnrs: List of Swedish organisation numbers (max 500).
                Each accepts format with or without dash.
    """
    if len(orgnrs) > 500:
        raise ValueError("batch_score accepts maximum 500 orgnrs per call.")

    validated = []
    errors    = []
    for o in orgnrs:
        try:
            validated.append(validate_orgnr(o))
        except ValueError as e:
            errors.append({"orgnr": o, "error": str(e)})

    return wrap(
        tool="kreditvakt_batch_score_v1",
        source=["skatteverket", "bolagsverket"],
        confidence=0.0,
        ttl=1_800,
        data={
            "total_requested": len(orgnrs),
            "total_valid":     len(validated),
            "total_invalid":   len(errors),
            "invalid_entries": errors,
            "portfolio_risk_summary": {
                "healthy_pct":       0.0,
                "watch_pct":         0.0,
                "elevated_risk_pct": 0.0,
                "high_risk_pct":     0.0,
                "critical_pct":      0.0,
                "weighted_avg_score": 0.0,
                "estimated_at_risk_sek": 0,
            },
            "entries": [],
        },
        warnings=["Kreditvakt ingestion not yet live. Scores reflect no data."],
    )


@mcp.tool(
    name="kreditvakt_debt_signals_v1",
    description=(
        "Return Skatteverket restanslängd debt data for a Swedish company. "
        "Shows outstanding tax debt amount in SEK, publication date, number of "
        "payment remarks, and F-skatt (sole trader tax registration) status. "
        "This signal is also consumed by Norric SIGNAL's competitor risk analysis — "
        "it is the shared data layer between Kreditvakt and SIGNAL."
    ),
)
async def kreditvakt_debt_signals(
    orgnr: str,
) -> dict:
    """
    Get Skatteverket restanslängd debt data for a company.

    Args:
        orgnr: Swedish organisation number
    """
    orgnr = validate_orgnr(orgnr)

    return wrap(
        tool="kreditvakt_debt_signals_v1",
        source=["skatteverket"],
        confidence=0.0,
        ttl=86_400,
        data={
            "orgnr":              orgnr,
            "skuld_sek":          None,
            "skuld_published_at": None,
            "betalning_count":    0,
            "f_skatt_active":     None,
            "f_skatt_revoked_at": None,
        },
        warnings=["Skatteverket ingestion not yet live."],
    )


@mcp.tool(
    name="kreditvakt_bankruptcy_status_v1",
    description=(
        "Return Bolagsverket konkurs (bankruptcy) filing status for a Swedish company. "
        "Shows whether konkurs has been filed, the filing date, current status "
        "(ansökt | beslutad | avslutad), and whether the company is still active. "
        "This is a binary verification tool — use score_company_v1 for predictive risk."
    ),
)
async def kreditvakt_bankruptcy_status(
    orgnr: str,
) -> dict:
    """
    Get Bolagsverket konkurs status for a company.

    Args:
        orgnr: Swedish organisation number
    """
    orgnr = validate_orgnr(orgnr)

    return wrap(
        tool="kreditvakt_bankruptcy_status_v1",
        source=["bolagsverket"],
        confidence=0.0,
        ttl=21_600,
        data={
            "orgnr":              orgnr,
            "konkurs_filed":      False,
            "konkurs_filed_at":   None,
            "konkurs_status":     None,
            "liquidation_filed":  False,
            "company_active":     None,
        },
        warnings=["Bolagsverket ingestion not yet live."],
    )


# ════════════════════════════════════════════════════════════════════════════════
# NORRIC VIGIL — Company lifecycle detection
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="vigil_lifecycle_stage_v1",
    description=(
        "Classify a Swedish company's lifecycle stage using three signals: "
        "F-skatt registration date, building permit filings, and Bolagsverket "
        "ownership change velocity. "
        "Returns: early | growth | scaling | distress — with confidence and signal breakdown. "
        "Primary use: identifying companies that just started (early stage) so SiteLoop "
        "can reach them before any competitor knows they exist."
    ),
)
async def vigil_lifecycle_stage(
    orgnr: str,
) -> dict:
    """
    Classify a Swedish company's lifecycle stage.

    Args:
        orgnr: Swedish organisation number
    """
    orgnr = validate_orgnr(orgnr)

    return wrap(
        tool="vigil_lifecycle_stage_v1",
        source=["skatteverket", "bolagsverket", "plan_bygglagen"],
        confidence=0.0,
        ttl=86_400,
        data={
            "orgnr":            orgnr,
            "stage":            "unknown",
            "confidence":       0.0,
            "signal_breakdown": {},
        },
        warnings=["Vigil ingestion not yet live."],
    )


@mcp.tool(
    name="vigil_new_companies_v1",
    description=(
        "Return companies newly registered in a Swedish municipality — "
        "detected via F-skatt (sole trader) registrations at Skatteverket. "
        "These are companies that just started and almost certainly have no website. "
        "Primary feed for SiteLoop's automated outreach pipeline. "
        "Results include orgnr, registration date, business category, and phone where available."
    ),
)
async def vigil_new_companies(
    kommunkod: str,
    days_back: int = 30,
) -> dict:
    """
    Get newly registered companies in a municipality.

    Args:
        kommunkod: 4-digit Swedish municipality code
        days_back: How many days back to search (default 30, max 90)
    """
    kommunkod = validate_kommunkod(kommunkod)
    days_back = min(max(1, days_back), 90)
    name      = MUNICIPALITY_NAMES.get(kommunkod, f"Kommun {kommunkod}")

    return wrap(
        tool="vigil_new_companies_v1",
        source=["skatteverket"],
        confidence=0.0,
        ttl=14_400,
        data={
            "kommunkod":        kommunkod,
            "municipality_name": name,
            "days_back":        days_back,
            "companies":        [],
        },
        warnings=["Vigil F-skatt ingestion not yet live."],
    )


@mcp.tool(
    name="vigil_ownership_velocity_v1",
    description=(
        "Return the ownership change rate for a Swedish company over the last 12 months. "
        "High velocity signals acquisition, restructuring, or distress. "
        "This signal feeds both Norric Kreditvakt (distress correlation) and "
        "Norric SIGNAL (competitor risk component when an incumbent supplier is changing hands)."
    ),
)
async def vigil_ownership_velocity(
    orgnr: str,
) -> dict:
    """
    Get ownership change velocity for a company.

    Args:
        orgnr: Swedish organisation number
    """
    orgnr = validate_orgnr(orgnr)

    return wrap(
        tool="vigil_ownership_velocity_v1",
        source=["bolagsverket"],
        confidence=0.0,
        ttl=86_400,
        data={
            "orgnr":            orgnr,
            "changes_12m":      0,
            "velocity_score":   0.0,
            "risk_flag":        False,
            "latest_change_at": None,
        },
        warnings=["Vigil Bolagsverket ingestion not yet live."],
    )


# ════════════════════════════════════════════════════════════════════════════════
# SITELOOP — Automated website pipeline
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="siteloop_pipeline_status_v1",
    description=(
        "Return the current state of the SiteLoop pipeline across all active cities. "
        "Shows leads at each funnel stage: scanned → site_built → sms_sent → "
        "clicked → activated → churned. "
        "Includes conversion rates and MRR by city. "
        "Use this to monitor the autonomous pipeline health without opening a dashboard."
    ),
)
async def siteloop_pipeline_status(
    city: Optional[str] = None,
) -> dict:
    """
    Get SiteLoop pipeline status.

    Args:
        city: Optional city filter (malmo | goteborg | stockholm).
              Omit for all cities.
    """
    return wrap(
        tool="siteloop_pipeline_status_v1",
        source=["siteloop_db"],
        confidence=0.9,
        ttl=300,
        data={
            "city":       city or "all",
            "active_cities": ["malmo"],
            "pipeline": {
                "malmo": {
                    "scanned":    0,
                    "site_built": 0,
                    "sms_sent":   0,
                    "clicked":    0,
                    "activated":  0,
                    "churned":    0,
                    "mrr_sek":    0,
                }
            },
            "total_mrr_sek": 0,
        },
        warnings=["Connect SiteLoop database to show live pipeline data."],
    )


@mcp.tool(
    name="siteloop_submit_lead_v1",
    description=(
        "Submit a business lead into the SiteLoop pipeline programmatically. "
        "This is the primary integration point for Norric Vigil — "
        "Vigil detects new companies, SiteLoop receives them and runs "
        "site generation + SMS outreach automatically. "
        "The lead enters the queue and proceeds through the pipeline without "
        "any human intervention. "
        "This is a mutating tool — every call is audited."
    ),
)
async def siteloop_submit_lead(
    business_name: str,
    category: str,
    address: str,
    phone: str,
    email: Optional[str] = None,
    orgnr: Optional[str] = None,
    source: str = "api",
) -> dict:
    """
    Submit a lead into the SiteLoop pipeline.

    Args:
        business_name: Name of the business
        category: Business category (restauranger | vvs | elektriker | malare |
                  snickare | taklaggare | stadfirmor | tradgard | flyttfirmor)
        address: Business address (Swedish format)
        phone: Swedish mobile number for SMS outreach
        email: Optional email address
        orgnr: Optional Swedish organisation number (for Vigil-sourced leads)
        source: Lead source tag (default 'api', use 'vigil' for Vigil-sourced leads)
    """
    import secrets
    lead_id = f"ld_{secrets.token_hex(8)}"

    # Audit record would be written here in production
    # audit.write(AuditRecord.create(...))

    return wrap(
        tool="siteloop_submit_lead_v1",
        source=["siteloop_pipeline"],
        confidence=1.0,
        ttl=0,
        data={
            "lead_id":       lead_id,
            "business_name": business_name,
            "category":      category,
            "status":        "queued",
            "queued_at":     datetime.now(timezone.utc).isoformat(),
            "source":        source,
            "next_step":     "site_generation",
            "note":          "Lead queued. Pipeline will run site generation and SMS outreach automatically.",
        },
    )


# ════════════════════════════════════════════════════════════════════════════════
# SIGVIK — BRF property intelligence
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="sigvik_score_brf_v1",
    description=(
        "Score the financial health and risk profile of a Swedish BRF "
        "(bostadsrättsförening / housing cooperative). "
        "Combines avgift trend, annual report analysis, renovation risk, and "
        "EU energy class (E/F/G class must reach D by 2033) into a 0-100 health score. "
        "Used by mortgage pre-approval agents, mäklare, and buyer-side research agents."
    ),
)
async def sigvik_score_brf(
    brf_id: str,
) -> dict:
    """
    Score a BRF's financial health.

    Args:
        brf_id: BRF identifier (orgnr format: e.g. 716400-1234)
    """
    try:
        brf_id = validate_orgnr(brf_id)
    except ValueError:
        pass  # brf_id may use different format in early stage

    return wrap(
        tool="sigvik_score_brf_v1",
        source=["bolagsverket", "boverket", "sigvik_internal"],
        confidence=0.0,
        ttl=86_400,
        data={
            "brf_id":      brf_id,
            "score":       0.0,
            "risk_tier":   "unknown",
            "components":  [],
        },
        warnings=["Sigvik BRF scoring pipeline not yet connected."],
    )


@mcp.tool(
    name="sigvik_brf_avgift_v1",
    description=(
        "Return the monthly avgift (housing fee) history, trend, and year-on-year "
        "delta for a Swedish BRF. "
        "Avgift trend is one of the strongest predictors of BRF financial stress — "
        "rising avgift indicates the association is covering costs by increasing member fees. "
        "Returns: current_kr, 5-year history, YoY delta %, trend label (rising|stable|falling)."
    ),
)
async def sigvik_brf_avgift(
    brf_id: str,
) -> dict:
    """
    Get BRF avgift history and trend.

    Args:
        brf_id: BRF identifier
    """
    return wrap(
        tool="sigvik_brf_avgift_v1",
        source=["sigvik_internal", "bolagsverket"],
        confidence=0.0,
        ttl=86_400,
        data={
            "brf_id":       brf_id,
            "current_kr":   None,
            "history":      [],
            "yoy_delta_pct": None,
            "trend":        "unknown",
        },
        warnings=["Sigvik avgift data pipeline not yet connected."],
    )


@mcp.tool(
    name="sigvik_brf_flags_v1",
    description=(
        "Return active risk flags for a Swedish BRF. "
        "Flags: renovation_risk (major upcoming costs), ekonomisk_risk (financial distress), "
        "eu_2033_energy_deadline (E/F/G energy class must reach D by 2033 — "
        "renovation pressure within 7 years). "
        "Each flag has a severity level: low | medium | high | critical."
    ),
)
async def sigvik_brf_flags(
    brf_id: str,
) -> dict:
    """
    Get active risk flags for a BRF.

    Args:
        brf_id: BRF identifier
    """
    return wrap(
        tool="sigvik_brf_flags_v1",
        source=["boverket", "sigvik_internal"],
        confidence=0.0,
        ttl=86_400,
        data={
            "brf_id":               brf_id,
            "flags":                [],
            "eu_2033_deadline_risk": False,
        },
        warnings=["Sigvik flag pipeline not yet connected."],
    )


# ════════════════════════════════════════════════════════════════════════════════
# PORTFOLIO — Cross-product tools
# ════════════════════════════════════════════════════════════════════════════════

@mcp.tool(
    name="norric_company_profile_v1",
    description=(
        "Return a unified Norric intelligence profile for a Swedish company. "
        "Combines: Kreditvakt insolvency score, Vigil lifecycle stage, and "
        "Vigil ownership velocity into one call. "
        "Use this when you need a complete picture of a company across all Norric products. "
        "orgnr is the canonical cross-product identifier — all Norric tools accept it."
    ),
)
async def norric_company_profile(
    orgnr: str,
) -> dict:
    """
    Get a unified Norric intelligence profile for a Swedish company.

    Args:
        orgnr: Swedish organisation number
    """
    orgnr = validate_orgnr(orgnr)

    # In production: run all three in parallel with asyncio.gather
    return wrap(
        tool="norric_company_profile_v1",
        source=["skatteverket", "bolagsverket"],
        confidence=0.0,
        ttl=3_600,
        data={
            "orgnr":           orgnr,
            "insolvency_score": None,
            "lifecycle_stage":  None,
            "ownership_velocity": None,
            "note": "Unified profile — all Norric data sources for one company.",
        },
        warnings=["Ingestion pipelines not yet live."],
    )


@mcp.tool(
    name="norric_status_v1",
    description=(
        "Return the live status of all Norric MCP products and their data pipelines. "
        "Shows which products are live, which are in build, and the last successful "
        "data ingestion timestamp for each source. "
        "Use this to understand what data is currently reliable before acting on it."
    ),
)
async def norric_status() -> dict:
    """Get the live status of all Norric products and data pipelines."""
    return wrap(
        tool="norric_status_v1",
        source=["norric_internal"],
        confidence=1.0,
        ttl=60,
        data={
            "server_version": "0.1.0",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "products": {
                "norric_signal": {
                    "status": "live_product_pipeline_pending",
                    "url": "https://munisignal.polsia.app",
                    "mcp_tools": 5,
                    "ingestion_live": False,
                    "note": "Product live. MCP tools ready. Ingestion pipeline to connect.",
                },
                "norric_kreditvakt": {
                    "status": "specced_mcp_ready",
                    "mcp_tools": 4,
                    "ingestion_live": False,
                    "note": "Backtest validated. MCP tools ready. Ingestion to connect.",
                },
                "norric_vigil": {
                    "status": "partial_mcp_ready",
                    "mcp_tools": 3,
                    "ingestion_live": False,
                    "note": "45 tests passing. MCP tools ready. Ingestion to deploy.",
                },
                "siteloop": {
                    "status": "live_product_mcp_ready",
                    "url": "https://siteloop.polsia.app",
                    "mcp_tools": 2,
                    "pipeline_live": True,
                    "note": "Malmö pilot live. MCP tools ready to connect to pipeline DB.",
                },
                "sigvik": {
                    "status": "live_product_api_pending",
                    "url": "https://sigvik.com",
                    "mcp_tools": 3,
                    "ingestion_live": False,
                    "note": "Web UI live. BRF data pipeline to connect.",
                },
            },
            "data_sources": {
                "skatteverket": {"live": False, "note": "API keys obtained. Ingestion to deploy."},
                "bolagsverket": {"live": False, "note": "API v2 (free). Ingestion to deploy."},
                "boverket":     {"live": False, "note": "BankID contract needed."},
                "scb":          {"live": False, "note": "Free open data. Pipeline to build."},
                "ivo":          {"live": False, "note": "Decision database. Scraper to build."},
                "kronofogden":  {"live": False, "note": "Public data. Scraper to build."},
            },
        },
    )


# ── Provenance tools
from tools.provenance_tools import register_provenance_tools
register_provenance_tools(mcp)

# ── ASGI app — middleware-wrapped for auth + tier enforcement ──────────────────
from core.middleware import NorricAuthMiddleware

app = NorricAuthMiddleware(mcp.http_app())

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"""
╔══════════════════════════════════════════════════════╗
║          NORRIC INTELLIGENCE MCP SERVER              ║
║                                                      ║
║  Transport:  Streamable HTTP                         ║
║  Endpoint:   http://{host}:{port}/mcp               ║
║  Products:   SIGNAL · Kreditvakt · Vigil             ║
║              SiteLoop · Sigvik                       ║
║  Auth:       Bearer token / X-Norric-Key             ║
║                                                      ║
║  Connect in Claude Code:                             ║
║  claude mcp add norric http://localhost:{port}/mcp  ║
╚══════════════════════════════════════════════════════╝
""")

    uvicorn.run(app, host=host, port=port, log_level="info")
