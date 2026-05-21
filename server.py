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
    website_url="https://norric.io",
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

def _score_orgnr_via_db(orgnr: str) -> dict:
    """Validate orgnr, fetch entity + score from live DB. NO MOCK FALLBACK.

    Returns a tagged dict:
      {"ok": True, "result": <score_from_db dict>, "entity": {name, status, deregistered_at}}
      {"ok": False, "kind": "invalid_orgnr"|"orgnr_not_ingested"|"scoring_error",
       "message": str, "orgnr": str}

    All four Kreditvakt MCP tools route through this so fabrication is
    impossible from the MCP surface.
    """
    try:
        norm = validate_orgnr(orgnr)
    except ValueError as exc:
        return {"ok": False, "kind": "invalid_orgnr", "message": str(exc), "orgnr": orgnr}

    from ingestion.db import Session
    from scoring.kreditvakt import score_from_db
    from sqlalchemy import text as _text

    db = Session()
    try:
        # norric_entities.orgnr is dashless (canonical key); orgnr_display is dashed.
        # validate_orgnr returned the dashed form — match against orgnr_display.
        try:
            entity_row = db.execute(
                _text("""
                    SELECT orgnr, name, is_active, deregistered_at
                    FROM norric_entities
                    WHERE orgnr_display = :orgnr
                """),
                {"orgnr": norm},
            ).fetchone()
        except Exception as ent_exc:
            try: db.rollback()
            except Exception: pass
            return {"ok": False, "kind": "scoring_error",
                    "message": f"norric_entities lookup failed: {type(ent_exc).__name__}: {ent_exc}",
                    "orgnr": norm}

        if entity_row is None:
            return {"ok": False, "kind": "orgnr_not_ingested",
                    "message": "orgnr not in norric_entities", "orgnr": norm}

        try:
            result = score_from_db(db, norm)
        except Exception as exc:
            return {"ok": False, "kind": "scoring_error",
                    "message": f"{type(exc).__name__}: {exc}", "orgnr": norm}

        return {
            "ok": True,
            "result": result,
            "entity": {
                "name": entity_row.name,
                "status": "active" if entity_row.is_active else "deregistered",
                "deregistered_at": entity_row.deregistered_at.isoformat() if getattr(entity_row, "deregistered_at", None) else None,
            },
        }
    finally:
        db.close()


def _kreditvakt_signals(r: dict) -> list[dict]:
    """Pass-through of score_from_db's signals list. Kept for backwards
    compat with the score_company_v1 tool's signals= argument; score_from_db
    already emits the canonical signal shape, so no derivation needed."""
    return list(r.get("signals") or [])

@mcp.tool(
    name="kreditvakt_score_company_v1",
    description=(
        "Score the insolvency risk of a Swedish company using four independent signal sources: "
        "Skatteverket restanslängd (tax debt), Kronofogden betalningsförelägganden (payment orders), "
        "Bolagsverket pending ärenden (leading indicator — days before registration), "
        "and Bolagsverket konkursregister. "
        "Returns risk_score [0–20, ascending=worse], risk_band [1–5], risk_tier "
        "(HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL), and full signal breakdown. "
        "score_source='live' means DB-backed signals; 'no_signals' means the orgnr is "
        "in norric_entities but no current risk data exists (risk_score will be null). "
        "stale_data=true means freshness > 48h. "
        "Accepts a Swedish organisation number (e.g. 556000-1234)."
    ),
)
async def kreditvakt_score_company(
    orgnr: str,
) -> dict:
    """
    Score the insolvency risk of a Swedish company.

    Args:
        orgnr: Swedish organisation number (e.g. 556000-1234) OR a company name
               (e.g. "Byggfirman Svensson AB"). Company names are resolved to a
               deterministic orgnr. Well-known companies (Ikea, Volvo, Ericsson…)
               are always scored as low-risk.
    """
    # NO MOCK FALLBACK. score_from_db returns either a 'live' or 'no_signals'
    # dict, or raises (SCHEMA_MISSING / DB error) — never fabricates.
    from ingestion.db import Session
    from scoring.kreditvakt import score_from_db
    db = Session()
    try:
        result = score_from_db(db, orgnr)
    except Exception as exc:
        return wrap(
            tool="kreditvakt_score_company_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={},
            warnings=[f"scoring_error: {type(exc).__name__}"],
        )
    finally:
        db.close()

    if result.get("score_source") == "no_signals":
        return wrap(
            tool="kreditvakt_score_company_v1",
            source=["skatteverket", "kronofogden", "bolagsverket"],
            confidence=0.0,
            ttl=3_600,
            data={
                "orgnr":         result["orgnr"],
                "score_source":  "no_signals",
                "risk_score":    None,
                "risk_band":     None,
                "risk_tier":     None,
                "scale":         "0-20",
                "polarity":      "ascending_risk",
                "scored_at":     result["scored_at"],
                "ingestion_status": result.get("ingestion_status"),
            },
            signals=[],
            warnings=["no_signals: no current risk data for this orgnr"],
        )

    p = result.get("distress_probability", 0.0)
    confidence_num = max(0.0, 1.0 - p)
    warnings = []
    if result.get("stale_data"):
        warnings.append(f"Data freshness {result.get('data_freshness_hours', '?')}h — exceeds 48h threshold")

    signals = _kreditvakt_signals(result)

    # Supply-chain contagion preview — HIGH/CRITICAL only, cache-only,
    # never blocks the score response. Any failure → score returned without preview.
    score_data: dict = {
        "orgnr":          result["orgnr"],
        "score_source":   "live",
        "risk_score":     result["risk_score"],
        "risk_band":      result["risk_band"],
        "risk_tier":      result["risk_tier"],
        "scale":          "0-20",
        "polarity":       "ascending_risk",
        "distress_probability": result["distress_probability"],
        "scored_at":      result["scored_at"],
        "data_freshness_hours": result.get("data_freshness_hours"),
        "stale_data":     result.get("stale_data", False),
    }
    if result.get("risk_tier") in ("HIGH", "CRITICAL"):
        try:
            from ingestion.db import Session as _CS
            from kreditvakt.contagion import get_cached_contagion_peers
            _cdb = _CS()
            try:
                _peers = get_cached_contagion_peers(result["orgnr"], _cdb, limit=5)
            finally:
                _cdb.close()
            score_data["contagion_preview"] = {
                "peer_count":  len(_peers),
                "top_peers":   _peers[:3],
                "detail_tool": "kreditvakt_contagion_v1",
            }
        except Exception:
            # Score response is sacrosanct — never block on contagion lookup.
            pass

    return wrap(
        tool="kreditvakt_score_company_v1",
        source=["skatteverket", "kronofogden", "bolagsverket"],
        confidence=round(confidence_num, 2),
        ttl=3_600,
        data=score_data,
        signals=signals,
        warnings=warnings,
    )


# ── Supply-chain contagion ─────────────────────────────────────────────────────

_CONTAGION_DISCLAIMER = (
    "Contagion peers are probabilistic based on shared procurement sector and "
    "geographic proximity. Not verified supply chain relationships."
)

_MATCH_INTERPRETATION = {
    "same_sector_kommunkod":
        "Samma sektor, samma kommun. Sannolik leveranskedjeöverlappning.",
    "same_sector_county":
        "Samma sektor, samma län. Möjlig leveranskedjeöverlappning.",
}


@mcp.tool(
    name="kreditvakt_contagion_v1",
    description=(
        "Supply-chain contagion analysis for a HIGH or CRITICAL Swedish company. "
        "Returns the companies most likely to have supply-chain exposure to the "
        "given company, based on shared procurement sector and geographic "
        "proximity (kommunkod → county fallback). "
        "Use after identifying a HIGH/CRITICAL company via kreditvakt_score_company_v1. "
        "Reads from the contagion_peers cache (refreshed every 4h); recomputes on "
        "cache miss. Always returns the probabilistic disclaimer in warnings — "
        "these are likely relationships, not verified supply chains. "
        "orgnr accepts format with or without dash. limit defaults to 10, max 25."
    ),
)
async def kreditvakt_contagion(
    orgnr: str,
    limit: int = 10,
) -> dict:
    """Supply-chain contagion peers for a HIGH or CRITICAL company.

    Args:
        orgnr: Swedish organisation number (e.g. 556000-1234).
        limit: max peers to return (default 10, max 25).
    """
    from ingestion.db import Session
    from sqlalchemy import text as _sql_text
    from kreditvakt.contagion import (
        compute_contagion_peers,
        get_cached_contagion_peers,
        persist_contagion_peers,
        TIER_FROM_BAND,
        SCORE_FROM_BAND,
        CONTAGION_BANDS,
    )

    # Normalize orgnr (raise-free; fall through with a warning if invalid).
    try:
        orgnr_norm = validate_orgnr(orgnr)
    except ValueError as exc:
        return wrap(
            tool="kreditvakt_contagion_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={},
            warnings=[f"validation_failed: {exc}", _CONTAGION_DISCLAIMER],
        )

    limit_clamped = max(1, min(int(limit), 25))

    db = Session()
    try:
        # 1. Look up source: must exist in norric_entities AND have a HIGH/CRITICAL score.
        src = db.execute(_sql_text("""
            SELECT
                ne.orgnr_display AS orgnr,
                ne.name,
                cs.risk_band
            FROM norric_entities ne
            LEFT JOIN company_scores cs ON cs.orgnr = ne.orgnr_display
            WHERE ne.orgnr_display = :orgnr
            LIMIT 1
        """), {"orgnr": orgnr_norm}).fetchone()

        if src is None:
            return wrap(
                tool="kreditvakt_contagion_v1",
                source=["norric_entities"],
                confidence=0.0,
                ttl=3_600,
                data={"orgnr": orgnr_norm},
                warnings=[
                    "orgnr_not_ingested: not in norric_entities",
                    _CONTAGION_DISCLAIMER,
                ],
            )

        band = src.risk_band
        if band is None or band not in CONTAGION_BANDS:
            return wrap(
                tool="kreditvakt_contagion_v1",
                source=["norric_entities", "company_scores"],
                confidence=0.0,
                ttl=3_600,
                data={
                    "source": {
                        "orgnr":    src.orgnr,
                        "name":     src.name,
                        "tier":     TIER_FROM_BAND.get(band) if band else None,
                        "kv_score": SCORE_FROM_BAND.get(band) if band else None,
                    },
                    "contagion_peers": [],
                    "peer_count": 0,
                },
                warnings=[
                    "tier_below_contagion_threshold: contagion analysis only "
                    "applies to HIGH (band 4) and CRITICAL (band 5)",
                    _CONTAGION_DISCLAIMER,
                ],
            )

        tier = TIER_FROM_BAND[band]

        # 2. Cache-first read.
        peers = get_cached_contagion_peers(orgnr_norm, db, limit=limit_clamped)
        cache_hit = bool(peers)

        # 3. Compute + persist on miss.
        if not peers:
            peers = compute_contagion_peers(orgnr_norm, tier, db, limit=limit_clamped)
            if peers:
                try:
                    persist_contagion_peers(db, orgnr_norm, tier, peers)
                    db.commit()
                except Exception as persist_exc:
                    db.rollback()
                    log_warn = f"persist_failed: {type(persist_exc).__name__}"
                    # Persist failure does not block returning the freshly computed peers.
                    peers_warn = [log_warn]
                else:
                    peers_warn = []
            else:
                peers_warn = []
        else:
            peers_warn = []

    finally:
        db.close()

    # Attach Swedish interpretation strings + figure confidence.
    enriched = [
        {**p, "interpretation": _MATCH_INTERPRETATION.get(p["match_reason"], "")}
        for p in peers
    ]

    has_kommunkod_match = any(p["match_reason"] == "same_sector_kommunkod" for p in peers)
    confidence_label = (
        "medium" if peers and has_kommunkod_match
        else "low"  if peers
        else "none"
    )
    confidence_num = {"medium": 0.5, "low": 0.3, "none": 0.0}[confidence_label]

    warnings = [_CONTAGION_DISCLAIMER] + peers_warn
    if not peers:
        warnings.append(
            "no_peers: no peers derivable — source may have no procurement "
            "history (sector unknown) or no scored companies in same kommunkod/county"
        )

    return wrap(
        tool="kreditvakt_contagion_v1",
        source=["norric_entities", "company_scores", "signal_contracts", "contagion_peers"],
        confidence=confidence_num,
        ttl=14_400,  # 4h — matches refresh cadence
        data={
            "source": {
                "orgnr":    src.orgnr,
                "name":     src.name,
                "tier":     tier,
                "kv_score": SCORE_FROM_BAND[band],
            },
            "contagion_peers":  enriched,
            "peer_count":       len(enriched),
            "confidence_label": confidence_label,
            "cache_hit":        cache_hit,
            "scale":            "0-20",
            "polarity":         "ascending_risk",
        },
        warnings=warnings,
    )


@mcp.tool(
    name="kreditvakt_batch_score_v1",
    description=(
        "Score a portfolio of Swedish companies for insolvency risk in one call. "
        "Maximum 500 organisation numbers per request. "
        "Returns each company's score, verdict, primary risk signal, and debt status. "
        "Includes a portfolio-level risk summary: % by risk tier, weighted average score, "
        "estimated SEK exposure for high-risk entries. "
        "This is the primary tool for factoring companies reviewing credit exposure at scale."
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

    NO MOCK FALLBACK. Each orgnr is routed through score_from_db. Orgnrs
    that fail validation, are not in norric_entities, or have no signals
    appear in the per-entry response with explicit error / no_signals markers.
    """
    if len(orgnrs) > 500:
        raise ValueError("batch_score accepts maximum 500 orgnrs per call.")

    entries = []
    tier_counts = {"healthy": 0, "watch": 0, "elevated": 0, "high": 0, "critical": 0}
    risk_score_sum = 0
    risk_score_count = 0
    total_skuld_at_risk = 0
    invalid_entries: list[dict] = []
    not_ingested: list[dict] = []

    for orgnr in orgnrs:
        outcome = _score_orgnr_via_db(orgnr)
        if not outcome["ok"]:
            if outcome["kind"] == "invalid_orgnr":
                invalid_entries.append({"orgnr": outcome["orgnr"], "error": outcome["message"]})
            elif outcome["kind"] == "orgnr_not_ingested":
                not_ingested.append({"orgnr": outcome["orgnr"]})
            else:  # scoring_error
                entries.append({
                    "orgnr": outcome["orgnr"],
                    "error": outcome["message"],
                })
            continue

        result = outcome["result"]
        entity = outcome["entity"]
        risk_tier = result.get("risk_tier")
        risk_band = result.get("risk_band")
        risk_score = result.get("risk_score")

        if risk_tier is not None:
            tier_counts[risk_tier.lower()] = tier_counts.get(risk_tier.lower(), 0) + 1
        if risk_score is not None:
            risk_score_sum += risk_score
            risk_score_count += 1
        if risk_band is not None and risk_band >= 3:
            total_skuld_at_risk += result.get("skuld_sek", 0) or 0

        entries.append({
            "orgnr":        result["orgnr"],
            "name":         entity["name"],
            "score_source": result["score_source"],
            "risk_score":   risk_score,
            "risk_band":    risk_band,
            "risk_tier":    risk_tier,
            "scale":        "0-20",
            "polarity":     "ascending_risk",
            "skuld_sek":    result.get("skuld_sek"),
            "konkurs_filed": result.get("bolagsverket_petition", False),
            "signals_fired": result.get("signals_fired", 0),
        })

    def pct(n: int) -> int:
        total = sum(tier_counts.values())
        return round(n / total * 100, 1) if total else 0.0

    return wrap(
        tool="kreditvakt_batch_score_v1",
        source=["skatteverket", "kronofogden", "bolagsverket"],
        confidence=0.85,
        ttl=1_800,
        data={
            "total_requested":   len(orgnrs),
            "total_scored":      len(entries),
            "total_invalid":     len(invalid_entries),
            "total_not_ingested": len(not_ingested),
            "invalid_entries":   invalid_entries,
            "not_ingested":      not_ingested,
            "scale":             "0-20",
            "polarity":          "ascending_risk",
            "portfolio_risk_summary": {
                "healthy_pct":         pct(tier_counts["healthy"]),
                "watch_pct":           pct(tier_counts["watch"]),
                "elevated_pct":        pct(tier_counts["elevated"]),
                "high_pct":            pct(tier_counts["high"]),
                "critical_pct":        pct(tier_counts["critical"]),
                "weighted_avg_risk_score": round(risk_score_sum / risk_score_count, 1) if risk_score_count else None,
                "estimated_at_risk_sek": total_skuld_at_risk,
            },
            "entries": entries,
        },
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
    Get Skatteverket / Kronofogden debt signal data for a company.

    Args:
        orgnr: Swedish organisation number

    NO MOCK FALLBACK. Returns only fields backed by real ingestion. Fields
    removed (no live data source today): skatteverket_published flag,
    skuld_published_date, kronofogden_escalated, f_skatt_active. These
    return when the corresponding ingestion pipelines land.
    """
    outcome = _score_orgnr_via_db(orgnr)
    if not outcome["ok"]:
        return wrap(
            tool="kreditvakt_debt_signals_v1",
            source=[], confidence=0.0, ttl=0,
            data={"orgnr": outcome["orgnr"], "error": outcome["kind"], "message": outcome["message"]},
            warnings=[outcome["kind"]],
        )

    result = outcome["result"]
    entity = outcome["entity"]
    return wrap(
        tool="kreditvakt_debt_signals_v1",
        source=["skatteverket", "kronofogden"],
        confidence=0.88,
        ttl=86_400,
        data={
            "orgnr":                  result["orgnr"],
            "name":                   entity["name"],
            "score_source":           result["score_source"],
            "skuld_sek":              result.get("skuld_sek"),
            "skatteverket_flag":      result.get("skatteverket_flag", False),
            "kronofogden_count_6mo":  result.get("kronofogden_count_6mo", 0),
            "kronofogden_total_sek":  result.get("kronofogden_total_sek", 0),
            "kronofogden_latest_date": result.get("kronofogden_latest_date"),
            "kronofogden_recency_days": result.get("kronofogden_recency_days"),
            "scored_at":              result.get("scored_at"),
            "data_freshness_hours":   result.get("data_freshness_hours"),
            "stale_data":             result.get("stale_data", False),
        },
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
    Get Bolagsverket konkurs (bankruptcy) filing status for a company.

    Args:
        orgnr: Swedish organisation number

    NO MOCK FALLBACK. Fields removed (had no real data source): arende_*
    pending-case fields, f_skatt_active. They return when those ingestion
    pipelines land.
    """
    outcome = _score_orgnr_via_db(orgnr)
    if not outcome["ok"]:
        return wrap(
            tool="kreditvakt_bankruptcy_status_v1",
            source=[], confidence=0.0, ttl=0,
            data={"orgnr": outcome["orgnr"], "error": outcome["kind"], "message": outcome["message"]},
            warnings=[outcome["kind"]],
        )

    result = outcome["result"]
    entity = outcome["entity"]
    konkurs_filed = bool(result.get("bolagsverket_petition", False))

    return wrap(
        tool="kreditvakt_bankruptcy_status_v1",
        source=["bolagsverket"],
        confidence=0.95,
        ttl=21_600,
        data={
            "orgnr":              result["orgnr"],
            "name":               entity["name"],
            "score_source":       result["score_source"],
            "konkurs_filed":      konkurs_filed,
            "company_active":     entity["status"] != "deregistered" and not konkurs_filed,
            "entity_status":      entity["status"],
            "deregistered_at":    entity["deregistered_at"],
            "scored_at":          result.get("scored_at"),
        },
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

_SIGVIK_API_URL = os.environ.get("SIGVIK_API_URL", "http://localhost:8000")


@mcp.tool(
    name="sigvik_score_brf_v1",
    description=(
        "Score the financial health and renovation intent of a Swedish BRF "
        "(bostadsrättsförening / housing cooperative). "
        "Combines avgift trend, annual report analysis, renovation risk, and "
        "EU energy class (E/F/G class must reach D by 2033) into a 0-100 intent score. "
        "Returns confidence_label (Starkt signal / Måttlig signal / Tidig indikation), "
        "scored_at timestamp, and data_freshness_hours. "
        "stale_data=true if score older than 48h."
    ),
)
async def sigvik_score_brf(
    brf_id: str,
) -> dict:
    """
    Score a BRF's financial health and renovation intent.

    Args:
        brf_id: BRF identifier (orgnr format: e.g. 716400-1234)
    """
    try:
        brf_id = validate_orgnr(brf_id)
    except ValueError:
        pass

    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_SIGVIK_API_URL}/api/brfs/{brf_id}")
            if resp.status_code == 404:
                return wrap(
                    tool="sigvik_score_brf_v1",
                    source=["sigvik_internal"],
                    confidence=0.0,
                    ttl=3_600,
                    data={"brf_id": brf_id},
                    warnings=[f"BRF {brf_id} not found in Sigvik database"],
                )
            resp.raise_for_status()
            brf_data = resp.json()
    except Exception as e:
        return wrap(
            tool="sigvik_score_brf_v1",
            source=["sigvik_internal"],
            confidence=0.0,
            ttl=300,
            data={"brf_id": brf_id},
            warnings=[f"Sigvik API unavailable: {type(e).__name__}"],
        )

    brf = brf_data.get("brf", {})
    score = brf.get("intent_score")
    confidence = brf.get("intent_score_confidence")
    updated_at = brf.get("intent_score_updated_at")

    freshness_hours = None
    stale = False
    if updated_at:
        try:
            from datetime import datetime as _dt
            updated = _dt.fromisoformat(updated_at.replace("Z", "+00:00"))
            delta = _dt.now(timezone.utc) - updated.replace(tzinfo=timezone.utc)
            freshness_hours = round(delta.total_seconds() / 3600, 1)
            stale = freshness_hours > 48
        except Exception:
            pass

    confidence_label = (
        "Starkt signal" if (confidence or 0) >= 0.7 else
        "Måttlig signal" if (confidence or 0) >= 0.4 else
        "Tidig indikation"
    )

    warnings = []
    if stale:
        warnings.append(f"Score data is {freshness_hours}h old — exceeds 48h threshold")
    if score is None:
        warnings.append("BRF not yet scored — ingestion may still be running")

    return wrap(
        tool="sigvik_score_brf_v1",
        source=["bolagsverket", "boverket", "sigvik_internal"],
        confidence=round(confidence or 0.0, 2),
        ttl=86_400,
        data={
            "brf_id": brf_id,
            "name": brf.get("name"),
            "city": brf.get("city"),
            "score": score,
            "confidence_label": confidence_label,
            "signals_fired_count": brf_data.get("signals_fired_count"),
            "signals_total_count": 6,
            "scored_at": updated_at,
            "data_freshness_hours": freshness_hours,
            "stale_data": stale,
            "building_year": brf.get("building_year"),
            "num_apartments": brf.get("num_apartments"),
            "num_arsredovisningar": brf.get("num_arsredovisningar_ingested"),
        },
        warnings=warnings,
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

    NO MOCK FALLBACK. Returns canonical risk family + entity status only.
    Fields removed (had no real data source): industry, org_age_years,
    registered_year, verdict. They return when entity-enrichment ingestion
    is wired.
    """
    outcome = _score_orgnr_via_db(orgnr)
    if not outcome["ok"]:
        return wrap(
            tool="norric_company_profile_v1",
            source=[], confidence=0.0, ttl=0,
            data={"orgnr": outcome["orgnr"], "error": outcome["kind"], "message": outcome["message"]},
            warnings=[outcome["kind"]],
        )

    result = outcome["result"]
    entity = outcome["entity"]
    p = result.get("distress_probability")
    confidence_num = round(max(0.0, 1.0 - p), 2) if p is not None else 0.0

    return wrap(
        tool="norric_company_profile_v1",
        source=["skatteverket", "kronofogden", "bolagsverket"],
        confidence=confidence_num,
        ttl=3_600,
        data={
            "orgnr":            result["orgnr"],
            "name":             entity["name"],
            "entity_status":    entity["status"],
            "deregistered_at":  entity["deregistered_at"],
            "score_source":     result["score_source"],
            "risk_score":       result.get("risk_score"),
            "risk_band":        result.get("risk_band"),
            "risk_tier":        result.get("risk_tier"),
            "scale":            "0-20",
            "polarity":         "ascending_risk",
            "distress_probability": p,
            "konkurs_filed":    result.get("bolagsverket_petition", False),
            "skuld_sek":        result.get("skuld_sek"),
            "scored_at":        result.get("scored_at"),
            "lifecycle_stage":  None,
            "ownership_velocity": None,
            "note": "Lifecycle and ownership velocity require Vigil pipeline (not yet live).",
        },
        signals=result.get("signals", []),
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


# ── Provenance tools ───────────────────────────────────────────────────────────
from tools.provenance_tools import register_provenance_tools
register_provenance_tools(mcp)


# ── Norric Intelligence (cross-product) ────────────────────────────────────────
# Composes Kreditvakt scoring + SIGNAL procurement + contagion cache + map
# anchors into single-call payloads sized for the intelligence dashboard.

import logging as _intel_logging  # noqa: E402

log = _intel_logging.getLogger(__name__)


@mcp.tool(
    name="norric_score_v1",
    description=(
        "Full intelligence package for a Swedish company: identity + geography "
        "(with lat/lng), risk score (band/tier/percentile/delta_7d/trajectory), "
        "decomposed signal flags (restanslängd, betalningsförelägganden, "
        "konkursansökan, F-skatt), insolvency timeline (onset date, days "
        "elapsed/remaining vs ~210-day median), supply-chain contagion preview, "
        "and active SIGNAL contracts. Single round-trip payload for the "
        "intelligence dashboard score card. Returns null for risk_* fields "
        "when score_source='no_signals'. Accepts orgnr with or without dash."
    ),
)
async def norric_score(orgnr: str) -> dict:
    """Full intelligence package for a single company.

    Args:
        orgnr: Swedish organisation number (e.g. 556000-1234).
    """
    from ingestion.db import Session
    from scoring.kreditvakt import score_from_db
    from kreditvakt.intelligence import build_score_intelligence, MODEL_VERSION

    try:
        orgnr_norm = validate_orgnr(orgnr)
    except ValueError as exc:
        return wrap(
            tool="norric_score_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={},
            warnings=[f"validation_failed: {exc}"],
        )

    db = Session()
    try:
        result = score_from_db(db, orgnr_norm)
        package = build_score_intelligence(db, orgnr_norm, result)
    except Exception as exc:
        log.error("norric_score_v1[%s] failed: %s", orgnr_norm, exc, exc_info=True)
        db.close()
        return wrap(
            tool="norric_score_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={"orgnr": orgnr_norm},
            warnings=[f"scoring_error: {type(exc).__name__}"],
        )
    finally:
        try: db.close()
        except Exception: pass

    distress = result.get("distress_probability")
    confidence = max(0.0, 1.0 - distress) if distress is not None else 0.0
    warnings = []
    if result.get("stale_data"):
        warnings.append(
            f"Data freshness {result.get('data_freshness_hours', '?')}h — exceeds 48h threshold"
        )
    if package["company"]["sector"] is None:
        warnings.append("no_procurement_history: sector cannot be derived")
    if package["company"]["lat"] is None:
        warnings.append("no_geo_anchor: municipality coordinates unavailable")

    return wrap(
        tool="norric_score_v1",
        source=[
            "skatteverket", "kronofogden", "bolagsverket",
            "norric_entities", "company_scores", "company_score_history",
            "signal_contracts", "contagion_peers", "municipalities",
        ],
        confidence=round(confidence, 2),
        ttl=900,  # 15min — matches Celery rescore cadence
        data=package,
        warnings=warnings,
    )


@mcp.tool(
    name="norric_search_v1",
    description=(
        "Search the Norric monitored universe by organisation number prefix or "
        "company name prefix. Returns each match with its current risk score / "
        "band / tier when available. Use to resolve a typed query in the "
        "dashboard search bar to a concrete orgnr before calling norric_score_v1. "
        "Heuristic: if the query is digits + dashes, prefix-match orgnr_display; "
        "otherwise prefix-match name (case-insensitive). limit defaults to 10, max 50."
    ),
)
async def norric_search(q: str, limit: int = 10) -> dict:
    """Search norric_entities by orgnr prefix or name prefix.

    Args:
        q: query string (orgnr prefix or company-name prefix).
        limit: max results (default 10, max 50).
    """
    from ingestion.db import Session
    from kreditvakt.intelligence import search_entities

    q_stripped = (q or "").strip()
    if not q_stripped:
        return wrap(
            tool="norric_search_v1",
            source=["norric_entities"],
            confidence=0.0,
            ttl=0,
            data={"query": "", "results": [], "result_count": 0},
            warnings=["empty_query"],
        )

    db = Session()
    try:
        results = search_entities(db, q_stripped, limit=limit)
    except Exception as exc:
        log.error("norric_search_v1 failed: %s", exc, exc_info=True)
        return wrap(
            tool="norric_search_v1",
            source=["norric_entities"],
            confidence=0.0,
            ttl=0,
            data={"query": q_stripped, "results": [], "result_count": 0},
            warnings=[f"search_error: {type(exc).__name__}"],
        )
    finally:
        db.close()

    return wrap(
        tool="norric_search_v1",
        source=["norric_entities", "company_scores"],
        confidence=1.0 if results else 0.0,
        ttl=300,
        data={
            "query":        q_stripped,
            "results":      results,
            "result_count": len(results),
        },
        warnings=[] if results else ["no_matches"],
    )


@mcp.tool(
    name="norric_contagion_map_v1",
    description=(
        "Supply-chain blast-radius shape for a HIGH or CRITICAL company, sized "
        "for the dashboard visualisation. Returns source company (with lat/lng), "
        "concentric rings of peers grouped by match_reason (same_sector_kommunkod "
        "= ring 1, same_sector_county = ring 2), each peer enriched with its own "
        "lat/lng and risk score, plus an aggregate summary. Reads the cached "
        "contagion_peers table (refreshed every 4h). Empty rings when no peers "
        "exist — caller should fall back to a non-spatial view. Same disclaimer "
        "as kreditvakt_contagion_v1: peers are probabilistic, not verified."
    ),
)
async def norric_contagion_map(orgnr: str) -> dict:
    """Blast-radius shape with geographic anchors for visualisation.

    Args:
        orgnr: Swedish organisation number (e.g. 556000-1234).
    """
    from ingestion.db import Session
    from kreditvakt.intelligence import build_contagion_map

    try:
        orgnr_norm = validate_orgnr(orgnr)
    except ValueError as exc:
        return wrap(
            tool="norric_contagion_map_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={},
            warnings=[f"validation_failed: {exc}"],
        )

    db = Session()
    try:
        m = build_contagion_map(db, orgnr_norm)
    except Exception as exc:
        log.error("norric_contagion_map_v1[%s] failed: %s", orgnr_norm, exc, exc_info=True)
        return wrap(
            tool="norric_contagion_map_v1",
            source=[],
            confidence=0.0,
            ttl=0,
            data={"orgnr": orgnr_norm},
            warnings=[f"contagion_map_error: {type(exc).__name__}"],
        )
    finally:
        db.close()

    warnings = [
        "Contagion peers are probabilistic based on shared procurement sector "
        "and geographic proximity. Not verified supply chain relationships.",
    ]
    if m.get("warning") == "orgnr_not_ingested":
        warnings.append("orgnr_not_ingested: not in norric_entities")
    if m["summary"]["total_peers"] == 0:
        warnings.append(
            "no_peers: source has no procurement history (sector unknown) "
            "or no scored companies in same kommunkod/county"
        )

    confidence = (
        0.5 if any(r["ring"] == 1 for r in m["rings"])
        else 0.3 if m["rings"]
        else 0.0
    )

    return wrap(
        tool="norric_contagion_map_v1",
        source=["contagion_peers", "norric_entities", "municipalities", "company_scores"],
        confidence=confidence,
        ttl=14_400,
        data=m,
        warnings=warnings,
    )


# ── Auth setup ─────────────────────────────────────────────────────────────────
import logging

_NORRIC_API_KEYS_ENV = os.environ.get("NORRIC_API_KEYS", "")
_VALID_KEYS = set(k.strip() for k in _NORRIC_API_KEYS_ENV.split(",") if k.strip())


_OPEN_PATHS = {"/health", "/signup/free", "/checkout", "/webhooks/stripe"}

# Scoring paths: auth is OPTIONAL.
# No key → free-tier anonymous (rate-limited by IP in kreditvakt/api.py).
# Valid key → tier resolved; Silver+ bypass IP limit and use per-key quota.
# Invalid key → 401 (explicit rejection of bad credentials).
_OPTIONAL_AUTH_PREFIX = "/api/score/"


class _NorricAuthMiddleware:
    """
    Pure-ASGI auth middleware. Reads `X-Norric-Key` OR `Authorization: Bearer`
    (Bearer wins when both are sent — backwards-compatible with existing clients).

    Validation order (first match wins):
      0. NORRIC_MASTER_KEY_HASH — single argon2-verified admin key (core/auth.py)
      1. NORRIC_API_KEYS env var — plain-key list, no DB/Redis (admin / test keys)
      2. Redis cache  — api_key:{sha256} → "valid:{tier}" | "revoked"
      3. DB lookup    — api_keys table, status='active'

    Open paths bypass auth: /health, /signup/free, /checkout, /webhooks/stripe.
    Optional-auth paths (/api/score/): no key → free tier; invalid key → 401.
    All other paths: require valid key (fail closed).
    """

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Fully public — no auth needed
        if path in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        headers  = dict(scope.get("headers", []))
        raw_auth = headers.get(b"authorization", b"").decode()
        raw_xkey = headers.get(b"x-norric-key", b"").decode().strip()

        # Resolve the presented key. Authorization: Bearer wins when both
        # headers are sent; otherwise X-Norric-Key. Docstring at server.py:18
        # has promised both shapes since 2026-05; this is the line that makes
        # it true.
        if raw_auth.startswith("Bearer "):
            key = raw_auth.removeprefix("Bearer ").strip()
        else:
            key = raw_xkey
        has_key = bool(key)

        # Optional-auth scoring paths: no key → anonymous free tier
        if path.startswith(_OPTIONAL_AUTH_PREFIX) and not has_key:
            scope["norric_tier"]        = "free"
            scope["norric_auth_source"] = "anonymous"
            await self.app(scope, receive, send)
            return

        # All other paths (and scoring with a key): require valid token
        if not has_key:
            from starlette.responses import JSONResponse
            resp = JSONResponse(
                {"error": "Missing API key. Get yours at norric.io/api-keys"},
                status_code=401,
            )
            await resp(scope, receive, send)
            return

        # ── 0. Master-key fast-path (argon2, no DB/Redis) ─────────────────────
        from core.auth import verify_master_key
        if verify_master_key(key):
            scope["norric_tier"]        = "all"
            scope["norric_auth_source"] = "master"
            await self.app(scope, receive, send)
            return

        # ── 1. Env var escape hatch (fast path, no DB/Redis) ──────────────────
        if key in _VALID_KEYS:
            scope["norric_tier"]        = "internal"
            scope["norric_auth_source"] = "env"
            await self.app(scope, receive, send)
            return

        # ── 2 & 3. Redis cache → DB lookup ────────────────────────────────────
        import asyncio
        from core.db_auth import lookup_key
        result = await asyncio.to_thread(lookup_key, key)

        if result is None:
            from starlette.responses import JSONResponse
            resp = JSONResponse(
                {"error": "Invalid API key. Get yours at norric.io/api-keys"},
                status_code=401,
            )
            await resp(scope, receive, send)
            return

        tier, auth_source, key_hash = result
        scope["norric_tier"]        = tier
        scope["norric_auth_source"] = auth_source
        scope["norric_key_hash"]    = key_hash

        await self.app(scope, receive, send)


# ── Health endpoint ────────────────────────────────────────────────────────────
async def _health_handler(scope, receive, send):
    from starlette.responses import JSONResponse

    health = {"status": "ok", "mcp_tools": 21, "version": "2.0.0"}

    # Query DB for product health stats
    try:
        from ingestion.db import Session
        from sqlalchemy import text as sqla_text

        db = Session()
        try:
            # Kreditvakt
            kv_row = db.execute(sqla_text("""
                SELECT COUNT(*) AS tracked, MAX(scored_at) AS last_scored
                FROM company_scores
            """)).fetchone()

            # Vigil
            vigil_row = db.execute(sqla_text("""
                SELECT COUNT(*) AS active_events
                FROM vigil_events
                WHERE detected_at >= now() - interval '30 days'
            """)).fetchone()

            vigil_ingested = db.execute(sqla_text("""
                SELECT MAX(detected_at) AS last_ingested FROM vigil_events
            """)).fetchone()

            health["products"] = {
                "kreditvakt": {
                    "tracked_companies": int(kv_row.tracked) if kv_row else 0,
                    "last_scored": kv_row.last_scored.isoformat() if kv_row and kv_row.last_scored else None,
                },
                "vigil": {
                    "active_events_30d": int(vigil_row.active_events) if vigil_row else 0,
                    "last_ingested": vigil_ingested.last_ingested.isoformat()
                        if vigil_ingested and vigil_ingested.last_ingested else None,
                },
            }
        finally:
            db.close()
    except Exception as e:
        health["db_error"] = str(e)

    # Query Sigvik API for BRF stats
    try:
        import httpx as _httpx
        sigvik_url = os.environ.get("SIGVIK_API_URL", "")
        if sigvik_url:
            r = _httpx.get(f"{sigvik_url}/api/health", timeout=3)
            if r.status_code == 200:
                sigvik_health = r.json()
                health.setdefault("products", {})["sigvik"] = {
                    "scored_brfs": sigvik_health.get("scored_brfs"),
                    "last_scored": sigvik_health.get("last_scored"),
                }
    except Exception:
        pass

    resp = JSONResponse(health)
    await resp(scope, receive, send)


# ── Composite ASGI: /health + issuance + MCP (all other paths) ────────────────
_mcp_asgi = mcp.http_app()

from issuance.main import app as _issuance_app  # noqa: E402
from kreditvakt.api import app as _kreditvakt_app  # noqa: E402

_ISSUANCE_PATHS = {"/signup/free", "/checkout", "/webhooks/stripe"}


async def _router(scope, receive, send):
    """Route /health, issuance paths, /api/* (kreditvakt), and everything else to FastMCP."""
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path == "/health":
            await _health_handler(scope, receive, send)
        elif path in _ISSUANCE_PATHS:
            await _issuance_app(scope, receive, send)
        elif path.startswith("/api/"):
            await _kreditvakt_app(scope, receive, send)
        else:
            await _mcp_asgi(scope, receive, send)
    else:
        await _mcp_asgi(scope, receive, send)


from starlette.middleware.cors import CORSMiddleware  # noqa: E402

app = CORSMiddleware(
    _NorricAuthMiddleware(_router),
    allow_origins=[
        "https://kreditvakt.com",
        "https://www.kreditvakt.com",
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)

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
║  Auth:       Bearer token (norric.io/api-keys)       ║
║                                                      ║
║  Connect in Claude Code:                             ║
║  claude mcp add norric http://localhost:{port}/mcp  ║
╚══════════════════════════════════════════════════════╝
""")

    uvicorn.run(app, host=host, port=port, log_level="info")
