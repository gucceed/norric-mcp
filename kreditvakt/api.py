"""
kreditvakt/api.py

Kreditvakt FastAPI sub-application.

Mount into a parent FastAPI app or run standalone:
    uvicorn kreditvakt.api:app --port 8001

Endpoints:
    GET  /api/score/{orgnr}           — single company score + display fields
    POST /api/score/batch             — batch scoring (body: {"orgnr_list": [...]})
    GET  /api/portfolio               — all tracked companies with current scores
    GET  /api/alerts                  — companies that moved to Band 4+ since last check
    GET  /api/company/{orgnr}/debt    — tier-gated debt breakdown
    GET  /health                      — service health

Tier gating:
    X-Kreditvakt-Tier header (set by auth middleware): free|silver|guld|premium|enterprise
    Absent header → 'free' (safe default, most restricted view)

Score display convention:
    Boundaries are lower-inclusive / upper-exclusive.
    distress_probability=0.20 → band 2 (not band 1).
    See scoring/display.py for full documentation.

Deprecated fields (sunset 2027-05):
    insolvency_score — use display_score instead
    risk_band        — use band instead
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

log = logging.getLogger(__name__)

_TIER_ORDER = {"free": 0, "silver": 1, "guld": 2, "premium": 3, "enterprise": 4}


def _tier(request: Request) -> str:
    t = request.headers.get("X-Kreditvakt-Tier", "free").lower()
    return t if t in _TIER_ORDER else "free"


def _tier_gte(request: Request, required: str) -> bool:
    return _TIER_ORDER.get(_tier(request), 0) >= _TIER_ORDER[required]


# ── DB ─────────────────────────────────────────────────────────────────────────

def _get_db():
    from ingestion.db import Session
    db = Session()
    try:
        yield db
    finally:
        db.close()


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Norric Kreditvakt API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── GET /api/score/{orgnr} ─────────────────────────────────────────────────────

_FREE_SEARCHES_LIMIT = 10
_UPGRADE_URL = "mailto:hej@norric.io?subject=Silver-abonnemang%20Kreditvakt&body=Hej,%0A%0AJag%20vill%20teckna%20Silver-abonnemang%20(4%20900%20kr/mån).%0A%0AFöretag:%20%0AOrgnr:%20%0AKontaktperson:%20%0A"


def _raw_key_from_request(request: Request) -> str | None:
    """Extract the raw API key from Authorization or X-Norric-Key header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip()
    return request.headers.get("x-norric-key", "").strip() or None


@app.get("/api/score/{orgnr}", summary="Single company risk score")
def get_score(orgnr: str, request: Request):
    """
    Score a company and return display fields.

    New fields (v2.1): display_score, band, band_label, band_action.
    internal_score is included for Premium+ only (deprecated alias, sunset 2027-05).
    Free tier: lifetime cap of 10 searches. Returns 402 when cap reached.
    """
    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    tier = _tier(request)

    # ── Free-tier lifetime cap ────────────────────────────────────────────────
    if tier == "free":
        raw_key = _raw_key_from_request(request)
        if raw_key:
            import hashlib
            from core.db_auth import check_and_increment_searches
            import asyncio
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            allowed, used, limit = check_and_increment_searches(key_hash)
            if not allowed:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "error": "Search limit reached",
                        "message": f"Du har använt dina {limit} sökningar. Uppgradera till Silver för obegränsade sökningar.",
                        "searches_used": used,
                        "searches_limit": limit,
                        "upgrade_url": _UPGRADE_URL,
                    },
                )
            searches_remaining = limit - used
        else:
            searches_remaining = None
    else:
        searches_remaining = None

    # ── Score lookup ──────────────────────────────────────────────────────────
    db = Session()
    try:
        result = score_from_db(db, orgnr)
        write_score(db, result)
    except Exception as e:
        log.error(f"[{orgnr}] GET /api/score error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scoring error — try again")
    finally:
        db.close()

    response = _enrich_response(result, request)
    if searches_remaining is not None:
        response["searches_remaining"] = searches_remaining
        response["searches_limit"] = _FREE_SEARCHES_LIMIT
    return response


# ── POST /api/score/batch ──────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    orgnr_list: list[str]


@app.post("/api/score/batch", summary="Batch company scoring")
def batch_score(req: BatchRequest, request: Request):
    """Score up to 500 companies. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Batch scoring requires Silver tier or above")
    if len(req.orgnr_list) > 500:
        raise HTTPException(status_code=400, detail="Max 500 orgnr per batch")

    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    db = Session()
    results, errors = [], []
    try:
        for orgnr in req.orgnr_list:
            try:
                result = score_from_db(db, orgnr)
                write_score(db, result)
                results.append(_enrich_response(result, request))
            except Exception as e:
                log.error(f"[{orgnr}] batch error: {e}", exc_info=True)
                errors.append({"orgnr": orgnr, "error": str(e)})
    finally:
        db.close()

    return {
        "total_requested": len(req.orgnr_list),
        "scored": len(results),
        "errors": len(errors),
        "error_detail": errors,
        "results": results,
    }


# ── GET /api/portfolio ─────────────────────────────────────────────────────────

@app.get("/api/portfolio", summary="Portfolio view")
def get_portfolio(
    request: Request,
    min_band: int = Query(1, ge=1, le=5),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    """All tracked companies with current scores. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Portfolio view requires Silver tier or above")

    from ingestion.db import Session
    from scoring.display import to_display

    db = Session()
    try:
        rows = db.execute(
            text("""
                SELECT cs.orgnr, cs.distress_probability, cs.risk_band,
                       cs.insolvency_score, cs.signals_fired, cs.signals_total,
                       cs.scored_at, cs.data_freshness_hours, cs.score_source,
                       cs.last_displayed_band,
                       ne.name AS company_name, ne.city, ne.orgform
                FROM company_scores cs
                LEFT JOIN norric_entities ne ON ne.orgnr = cs.orgnr
                WHERE cs.risk_band >= :min_band
                ORDER BY cs.risk_band DESC, cs.distress_probability DESC
                LIMIT :limit OFFSET :offset
            """),
            {"min_band": min_band, "limit": limit, "offset": offset},
        ).fetchall()

        total = db.execute(
            text("SELECT COUNT(*) FROM company_scores WHERE risk_band >= :min_band"),
            {"min_band": min_band},
        ).scalar()
    finally:
        db.close()

    companies = []
    for r in rows:
        row = dict(r._mapping)
        ds, _ = to_display(
            row["distress_probability"],
            last_displayed_band=row.get("last_displayed_band"),
        )
        row["display_score"] = ds.display_score
        row["band"] = ds.band
        row["band_label"] = ds.band_label
        row["band_action"] = ds.band_action
        companies.append(row)

    return {"total": total, "limit": limit, "offset": offset, "companies": companies}


# ── GET /api/alerts ────────────────────────────────────────────────────────────

@app.get("/api/alerts", summary="Band 4/5 alert list")
def get_alerts(request: Request, hours_back: int = Query(24, ge=1, le=168)):
    """Companies that moved to Band 4 or 5 in the last N hours. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Alerts require Silver tier or above")

    from ingestion.db import Session

    db = Session()
    try:
        rows = db.execute(
            text("""
                WITH current AS (
                    SELECT orgnr, risk_band, distress_probability, scored_at,
                           last_displayed_band
                    FROM company_scores
                    WHERE risk_band >= 4
                ),
                previous AS (
                    SELECT DISTINCT ON (orgnr)
                        orgnr, risk_band AS prev_band, scored_at AS prev_scored_at
                    FROM company_score_history
                    WHERE scored_at < now() - interval '1 hour' * :hours_back
                    ORDER BY orgnr, scored_at DESC
                )
                SELECT
                    c.orgnr,
                    c.risk_band,
                    c.last_displayed_band,
                    c.distress_probability,
                    c.scored_at,
                    p.prev_band,
                    p.prev_scored_at,
                    ne.name AS company_name
                FROM current c
                LEFT JOIN previous p ON p.orgnr = c.orgnr
                LEFT JOIN norric_entities ne ON ne.orgnr = c.orgnr
                WHERE p.prev_band IS NULL OR p.prev_band < 4
                ORDER BY c.distress_probability DESC
            """),
            {"hours_back": hours_back},
        ).fetchall()
    finally:
        db.close()

    from scoring.display import to_display, _BAND_LABELS, _BAND_ACTIONS

    alerts = []
    for r in rows:
        row = dict(r._mapping)
        ds, _ = to_display(
            row["distress_probability"],
            last_displayed_band=row.get("last_displayed_band"),
        )
        row["display_score"] = ds.display_score
        row["band"] = ds.band
        row["band_label"] = ds.band_label
        row["band_action"] = ds.band_action
        alerts.append(row)

    return {"hours_back": hours_back, "alert_count": len(alerts), "alerts": alerts}


# ── GET /api/company/{orgnr}/debt ─────────────────────────────────────────────

@app.get("/api/company/{orgnr}/debt", summary="Tier-gated debt breakdown")
def get_debt(orgnr: str, request: Request):
    """
    Debt breakdown gated by tier:

    Free:    { active_flag_count: int }
    Silver:  totals by source (Skatteverket, Kronofogden) — no line items, no names
    Guld:    line items with amounts. Enskild firma creditors return a DPA-required
             placeholder instead of the creditor name (enforced at SQL layer).
             Full creditor identity requires a signed DPA (dpa_signatures table).
    Premium: Guld + explain_score decomposing the internal model by signal weight.
    """
    from ingestion.db import Session

    tier = _tier(request)
    db = Session()
    try:
        if tier == "free":
            return _debt_free(db, orgnr)
        elif tier == "silver":
            return _debt_silver(db, orgnr)
        elif tier == "guld":
            has_dpa = _has_dpa(db, request)
            return _debt_guld(db, orgnr, has_dpa=has_dpa)
        else:  # premium, enterprise
            has_dpa = _has_dpa(db, request)
            return _debt_premium(db, orgnr, has_dpa=has_dpa)
    finally:
        db.close()


def _debt_free(db, orgnr: str) -> dict:
    row = db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM norric_tax_signals
                 WHERE orgnr = :orgnr AND is_active = true) +
                (SELECT COUNT(*) FROM norric_payment_signals
                 WHERE orgnr = :orgnr AND is_active = true)
                AS active_flag_count
        """),
        {"orgnr": orgnr},
    ).fetchone()
    return {"orgnr": orgnr, "tier": "free", "active_flag_count": int(row.active_flag_count)}


def _debt_silver(db, orgnr: str) -> dict:
    tax = db.execute(
        text("""
            SELECT
                COALESCE(SUM(amount_sek) FILTER (WHERE is_active), 0) AS total_kr,
                COUNT(*) FILTER (WHERE is_active) AS case_count
            FROM norric_tax_signals WHERE orgnr = :orgnr
        """),
        {"orgnr": orgnr},
    ).fetchone()

    kfm = db.execute(
        text("""
            SELECT
                COALESCE(SUM(claim_amount_sek) FILTER (WHERE is_active), 0) AS total_kr,
                COUNT(*) FILTER (WHERE is_active) AS case_count
            FROM norric_payment_signals WHERE orgnr = :orgnr
        """),
        {"orgnr": orgnr},
    ).fetchone()

    return {
        "orgnr": orgnr,
        "tier": "silver",
        "skatteverket": {"total_kr": int(tax.total_kr), "case_count": int(tax.case_count)},
        "kronofogden": {"total_kr": int(kfm.total_kr), "case_count": int(kfm.case_count)},
    }


def _debt_guld(db, orgnr: str, has_dpa: bool) -> dict:
    """
    Line items with creditor name gating at SQL layer.

    Enskild firma creditors (raw_data->>'legal_form' = 'enskild_firma') have their
    name replaced with a DPA-required placeholder. This is enforced in the SELECT,
    not in Python post-processing — the name never leaves the DB for these rows
    unless has_dpa is True.
    """
    dpa_placeholder = "[Enskild näringsidkare — kräver DPA-tillägg]"

    tax_rows = db.execute(
        text("""
            SELECT signal_type, amount_sek, first_seen_at, is_active
            FROM norric_tax_signals
            WHERE orgnr = :orgnr
            ORDER BY first_seen_at DESC
        """),
        {"orgnr": orgnr},
    ).fetchall()

    kfm_rows = db.execute(
        text("""
            SELECT
                case_ref,
                claim_amount_sek,
                filed_at,
                is_active,
                creditor_type,
                CASE
                    WHEN :has_dpa OR COALESCE(raw_data->>'legal_form', '') != 'enskild_firma'
                    THEN COALESCE(raw_data->>'creditor_name', creditor_type)
                    ELSE :placeholder
                END AS creditor_name,
                COALESCE(raw_data->>'legal_form', '') = 'enskild_firma' AS is_enskild_firma
            FROM norric_payment_signals
            WHERE orgnr = :orgnr
            ORDER BY filed_at DESC
        """),
        {"orgnr": orgnr, "has_dpa": has_dpa, "placeholder": dpa_placeholder},
    ).fetchall()

    base = _debt_silver(db, orgnr)
    base["tier"] = "guld"
    base["dpa_active"] = has_dpa
    base["skatteverket"]["line_items"] = [dict(r._mapping) for r in tax_rows]
    base["kronofogden"]["line_items"] = [dict(r._mapping) for r in kfm_rows]
    return base


def _debt_premium(db, orgnr: str, has_dpa: bool) -> dict:
    """Guld + explain_score decomposing the internal model by signal weight."""
    from scoring.kreditvakt import score_from_db

    result = score_from_db(db, orgnr)
    base = _debt_guld(db, orgnr, has_dpa=has_dpa)
    base["tier"] = "premium"

    signals = result.get("signals", [])
    base["explain_score"] = {
        "distress_probability": result["distress_probability"],
        "signal_contributions": signals,
        "score_source": result.get("score_source", "live"),
        "note": "Signal weights: skatteverket_debt=0.30, skatteverket_flag=0.20, "
                "kronofogden_count=0.25, kronofogden_recency=0.10, bolagsverket_petition=0.15",
    }
    return base


def _has_dpa(db, request: Request) -> bool:
    """Check if the requesting user has a signed DPA."""
    user_id = request.headers.get("X-Kreditvakt-User-Id")
    if not user_id:
        return False
    row = db.execute(
        text("SELECT 1 FROM dpa_signatures WHERE user_id = :uid LIMIT 1"),
        {"uid": user_id},
    ).fetchone()
    return row is not None


# ── GET /health ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    from ingestion.db import Session

    db = Session()
    try:
        row = db.execute(
            text("""
                SELECT
                    COUNT(*) AS tracked_companies,
                    MAX(scored_at) AS last_scored,
                    COUNT(*) FILTER (WHERE risk_band >= 4) AS high_risk_count
                FROM company_scores
            """)
        ).fetchone()
        db_ok = True
        tracked = int(row.tracked_companies) if row else 0
        last_scored = row.last_scored.isoformat() if row and row.last_scored else None
        high_risk = int(row.high_risk_count) if row else 0
    except Exception as e:
        db_ok, tracked, last_scored, high_risk = False, 0, None, 0
        log.error(f"Health check DB error: {e}")
    finally:
        db.close()

    return {
        "status": "ok" if db_ok else "degraded",
        "product": "kreditvakt",
        "version": "2.1.0",
        "tracked_companies": tracked,
        "high_risk_count": high_risk,
        "last_scored": last_scored,
    }


# ── Response helpers ───────────────────────────────────────────────────────────

def _enrich_response(result: dict, request: Request) -> dict:
    """
    Add display fields to every score response.

    New fields (v2.1, additive):
        display_score  int [0–20]
        band           int [1–5]
        band_label     str (Swedish)
        band_action    str (Swedish recommended action)

    Deprecated fields (sunset 2027-05, kept for backwards compat):
        insolvency_score  — use display_score
        risk_band         — use band

    internal_score included only for Premium+ (contains distress_probability*100).
    """
    from scoring.display import to_display

    p = result.get("distress_probability", 0.0)
    last_band = result.get("last_displayed_band")

    ds, _ = to_display(p, last_displayed_band=last_band)

    out = dict(result)
    out["display_score"] = ds.display_score
    out["band"] = ds.band
    out["band_label"] = ds.band_label
    out["band_action"] = ds.band_action
    out["confidence_label"] = _confidence_label(result)

    if not _tier_gte(request, "premium"):
        out.pop("internal_score", None)

    return out


def _confidence_label(result: dict) -> str:
    fired = result.get("signals_fired", 0)
    source = result.get("score_source", "live")
    stale = result.get("stale_data", False)
    if source == "mock" or stale:
        return "Tidig indikation"
    if fired >= 3:
        return "Starkt signal"
    if fired >= 1:
        return "Måttlig signal"
    return "Tidig indikation"


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
