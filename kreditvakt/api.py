"""
kreditvakt/api.py

Kreditvakt FastAPI sub-application.

Mount into a parent FastAPI app or run standalone:
    uvicorn kreditvakt.api:app --port 8001

Endpoints:
    GET  /api/score/{orgnr}           — single company score + signal breakdown
    POST /api/score/batch             — batch scoring (body: {"orgnr_list": [...]})
    GET  /api/portfolio               — all tracked companies with current scores
    GET  /api/alerts                  — companies that moved to Band 4+ since last check
    GET  /health                      — service health
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

log = logging.getLogger(__name__)

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

app = FastAPI(title="Norric Kreditvakt API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── GET /api/score/{orgnr} ─────────────────────────────────────────────────────

@app.get("/api/score/{orgnr}")
def get_score(orgnr: str):
    """Single company score with full signal breakdown."""
    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    db = Session()
    try:
        result = score_from_db(db, orgnr)
        write_score(db, result)
    except Exception as e:
        db.close()
        log.error(f"[{orgnr}] GET /api/score error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scoring error — try again")
    finally:
        if not db.is_active:
            pass
        db.close()

    return _enrich_response(result)


# ── POST /api/score/batch ──────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    orgnr_list: list[str]


@app.post("/api/score/batch")
def batch_score(req: BatchRequest):
    """Score up to 500 companies."""
    if len(req.orgnr_list) > 500:
        raise HTTPException(status_code=400, detail="Max 500 orgnr per batch")

    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    db = Session()
    results = []
    errors = []

    try:
        for orgnr in req.orgnr_list:
            try:
                result = score_from_db(db, orgnr)
                write_score(db, result)
                results.append(_enrich_response(result))
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

@app.get("/api/portfolio")
def get_portfolio(
    min_band: int = Query(1, ge=1, le=5),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    """All tracked companies with current scores, filterable by minimum risk band."""
    from ingestion.db import Session

    db = Session()
    try:
        rows = db.execute(
            text("""
                SELECT cs.orgnr, cs.distress_probability, cs.risk_band,
                       cs.insolvency_score, cs.signals_fired, cs.signals_total,
                       cs.scored_at, cs.data_freshness_hours, cs.stale_data,
                       cs.score_source,
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

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "companies": [dict(r._mapping) for r in rows],
    }


# ── GET /api/alerts ────────────────────────────────────────────────────────────

@app.get("/api/alerts")
def get_alerts(hours_back: int = Query(24, ge=1, le=168)):
    """Companies that moved to Band 4 or 5 in the last N hours."""
    from ingestion.db import Session

    db = Session()
    try:
        # Companies where current score is band 4/5 AND their previous score was lower
        rows = db.execute(
            text("""
                WITH current AS (
                    SELECT orgnr, risk_band, distress_probability, scored_at
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

    return {
        "hours_back": hours_back,
        "alert_count": len(rows),
        "alerts": [dict(r._mapping) for r in rows],
    }


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
    except Exception as e:
        db_ok = False
        tracked = 0
        last_scored = None
        log.error(f"Health check DB error: {e}")
    finally:
        db.close()

    return {
        "status": "ok" if db_ok else "degraded",
        "product": "kreditvakt",
        "version": "2.0.0",
        "tracked_companies": tracked,
        "last_scored": last_scored,
    }


# ── Response helpers ───────────────────────────────────────────────────────────

def _enrich_response(result: dict) -> dict:
    """Add confidence_label and band_label to every score response."""
    band = result.get("risk_band", 1)
    result["band_label"] = {
        1: "Minimal",
        2: "Låg",
        3: "Förhöjd",
        4: "Hög",
        5: "Kritisk",
    }.get(band, "Okänd")
    result["confidence_label"] = _confidence_label(result)
    return result


def _confidence_label(result: dict) -> str:
    fired = result.get("signals_fired", 0)
    total = result.get("signals_total", 5)
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
