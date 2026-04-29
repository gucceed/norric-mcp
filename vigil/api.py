"""
vigil/api.py

Vigil FastAPI sub-application.

Endpoints:
    GET  /api/signals                 — events for current subscriber tier (tier lock enforced)
    GET  /api/signals/{orgnr}         — events for one company
    GET  /api/new-companies           — F-skatt registrations (new businesses)
    GET  /health
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

log = logging.getLogger(__name__)


def _get_db():
    from ingestion.db import Session
    db = Session()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Norric Vigil API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple tier resolution from X-Norric-Tier header (replace with real auth in prod)
def _resolve_tier(x_norric_tier: Optional[str]) -> int:
    try:
        return int(x_norric_tier or "1")
    except ValueError:
        return 1


# ── GET /api/signals ───────────────────────────────────────────────────────────

@app.get("/api/signals")
def get_signals(
    event_type: Optional[str] = Query(None),
    days_back: int = Query(30, ge=1, le=365),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    x_norric_tier: Optional[str] = Header(None),
):
    """
    Return lifecycle events for the subscriber's tier.

    Tier lock: events at higher tiers are NEVER hidden — their event_count is
    always visible (the revenue mechanic), but payload is locked.
    """
    subscriber_tier = _resolve_tier(x_norric_tier)

    from ingestion.db import Session
    db = Session()
    try:
        where = "detected_at >= now() - interval '1 day' * :days_back"
        params: dict = {"days_back": days_back, "limit": limit, "offset": offset,
                        "sub_tier": subscriber_tier}

        if event_type:
            where += " AND event_type = :event_type"
            params["event_type"] = event_type

        # Fetch all events in window regardless of tier (for lock counts)
        rows = db.execute(
            text(f"""
                SELECT
                    id,
                    orgnr,
                    fastighet_id,
                    event_type,
                    detected_at,
                    source,
                    payload,
                    tier_required
                FROM vigil_events
                WHERE {where}
                ORDER BY detected_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).fetchall()

        total = db.execute(
            text(f"SELECT COUNT(*) FROM vigil_events WHERE {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).scalar()

    finally:
        db.close()

    events = []
    for row in rows:
        r = dict(row._mapping)
        if r["tier_required"] > subscriber_tier:
            # Tier lock: show event exists but lock payload
            events.append({
                "id": str(r["id"]),
                "event_type": r["event_type"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "locked": True,
                "tier_required": r["tier_required"],
            })
        else:
            events.append({
                "id": str(r["id"]),
                "orgnr": r["orgnr"],
                "fastighet_id": r["fastighet_id"],
                "event_type": r["event_type"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "source": r["source"],
                "payload": r["payload"],
                "locked": False,
                "tier_required": r["tier_required"],
            })

    # Aggregate locked counts by event_type for upsell display
    locked_counts: dict[str, int] = {}
    for e in events:
        if e.get("locked"):
            locked_counts[e["event_type"]] = locked_counts.get(e["event_type"], 0) + 1

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "subscriber_tier": subscriber_tier,
        "events": events,
        "locked_signal_counts": locked_counts,
    }


# ── GET /api/signals/{orgnr} ──────────────────────────────────────────────────

@app.get("/api/signals/{orgnr}")
def get_signals_for_orgnr(
    orgnr: str,
    x_norric_tier: Optional[str] = Header(None),
):
    subscriber_tier = _resolve_tier(x_norric_tier)

    from ingestion.db import Session
    db = Session()
    try:
        rows = db.execute(
            text("""
                SELECT id, orgnr, event_type, detected_at, source, payload, tier_required
                FROM vigil_events
                WHERE orgnr = :orgnr
                ORDER BY detected_at DESC
                LIMIT 100
            """),
            {"orgnr": orgnr},
        ).fetchall()

        profile_row = db.execute(
            text("SELECT * FROM company_profiles WHERE orgnr = :orgnr"),
            {"orgnr": orgnr},
        ).fetchone()
    finally:
        db.close()

    events = []
    for row in rows:
        r = dict(row._mapping)
        if r["tier_required"] > subscriber_tier:
            events.append({
                "event_type": r["event_type"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "locked": True,
                "tier_required": r["tier_required"],
            })
        else:
            events.append({
                "id": str(r["id"]),
                "event_type": r["event_type"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "source": r["source"],
                "payload": r["payload"],
                "locked": False,
            })

    return {
        "orgnr": orgnr,
        "events": events,
        "profile": dict(profile_row._mapping) if profile_row else None,
    }


# ── GET /api/new-companies ─────────────────────────────────────────────────────

@app.get("/api/new-companies")
def get_new_companies(
    kommunkod: Optional[str] = Query(None),
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(50, le=200),
):
    """F-skatt registrations — newly detected businesses."""
    from ingestion.db import Session
    db = Session()
    try:
        where = "detected_at >= now() - interval '1 day' * :days_back"
        params: dict = {"days_back": days_back, "limit": limit}

        if kommunkod:
            where += " AND payload->>'kommunkod' = :kommunkod"
            params["kommunkod"] = kommunkod

        rows = db.execute(
            text(f"""
                SELECT vf.orgnr, vf.approved_at, vf.detected_at,
                       ne.name AS company_name, ne.city, ne.orgform, ne.kommunkod
                FROM vigil_fskatt_registrations vf
                LEFT JOIN norric_entities ne ON ne.orgnr = vf.orgnr
                WHERE vf.{where}
                ORDER BY vf.detected_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()
    finally:
        db.close()

    return {
        "count": len(rows),
        "companies": [dict(r._mapping) for r in rows],
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
                    COUNT(*) AS active_events_30d,
                    MAX(detected_at) AS last_ingested
                FROM vigil_events
                WHERE detected_at >= now() - interval '30 days'
            """)
        ).fetchone()
        db_ok = True
    except Exception as e:
        log.error(f"Vigil health DB error: {e}")
        row = None
        db_ok = False
    finally:
        db.close()

    return {
        "status": "ok" if db_ok else "degraded",
        "product": "vigil",
        "version": "2.0.0",
        "active_events_30d": int(row.active_events_30d) if row else 0,
        "last_ingested": row.last_ingested.isoformat() if row and row.last_ingested else None,
    }
