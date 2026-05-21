"""
kreditvakt/intelligence.py

Read-only helpers powering the norric_*_v1 MCP tools (server.py):

  - build_score_intelligence(orgnr, db) → full intelligence package
  - search_entities(q, db, limit)        → name/orgnr prefix search
  - build_contagion_map(orgnr, db)       → blast-radius shape w/ lat/lng

All queries are tuned to be fast against Supabase (sub-200ms aggregate).
Every helper accepts an open SQLAlchemy session and never closes it —
the caller owns the session lifecycle. None of these functions write.

Data gaps that are surfaced as nulls rather than synthesised:
  - norric_entities has no sni_code column → company.sni_code = None
  - sector is per-contract on signal_contracts → derive most-frequent
    or None for companies with no procurement history
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import text

log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Median time from first active signal to konkursansökan. Research estimate
# from Bolagsverket konkurs filings + Kronofogden onset data; refine when
# the survival model lands. Used to compute timeline.days_remaining.
MEDIAN_DAYS_TO_KONKURS = 210

# Surfaced in the score response's data.meta block. Bump when the scoring
# model meaningfully changes; consumers may key on this for compat.
MODEL_VERSION = "kv-2026-01"
API_VERSION   = "v1"

# Match the contagion engine's ring labels (Swedish, user-visible).
_RING_LABELS = {
    "same_sector_kommunkod": "Direkt sektor · samma kommun",
    "same_sector_county":    "Sektor · samma län",
}
_RING_PROXIMITY = {
    "same_sector_kommunkod": 1.0,
    "same_sector_county":    0.7,
}

_ORGNR_PREFIX_RE = re.compile(r"^\d[\d-]*$")


# ── Geography (norric_entities + municipalities) ──────────────────────────────

def get_company_geography(db, orgnr: str) -> Optional[dict]:
    """Return basic identity + geographic anchor for a company.

    Joins norric_entities → municipalities by kommunkod (cast to integer,
    guarded against non-numeric values). Returns None when the orgnr isn't
    in the monitored universe.
    """
    row = db.execute(text("""
        SELECT
            ne.orgnr_display    AS orgnr,
            ne.name             AS name,
            ne.orgform          AS orgform,
            ne.kommunkod        AS kommunkod,
            ne.county           AS county,
            ne.city             AS city,
            m.name              AS municipality,
            m.lat               AS lat,
            m.lng               AS lng
        FROM norric_entities ne
        LEFT JOIN municipalities m ON m.id = CASE
            WHEN ne.kommunkod ~ '^\\d+$' THEN ne.kommunkod::INTEGER
            ELSE NULL
        END
        WHERE ne.orgnr_display = :orgnr
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()

    if row is None:
        return None

    return {
        "orgnr":        row.orgnr,
        "name":         row.name,
        "orgform":      row.orgform,
        "kommunkod":    row.kommunkod,
        "county":       row.county,
        "city":         row.city,
        "municipality": row.municipality or row.city,
        "lat":          row.lat,
        "lng":          row.lng,
    }


def derive_supplier_sector(db, orgnr: str) -> Optional[str]:
    """Most-frequent signal_contracts.sector for this supplier, or None."""
    row = db.execute(text("""
        SELECT sector, COUNT(*) AS freq
        FROM signal_contracts
        WHERE supplier_orgnr = :orgnr AND sector IS NOT NULL
        GROUP BY sector
        ORDER BY freq DESC
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()
    return row.sector if row else None


# ── Score trajectory + percentile ─────────────────────────────────────────────

def compute_band_history(db, orgnr: str) -> dict:
    """Return delta_7d (band change over the last 7 days) + trajectory label.

    Compares the current company_scores.risk_band to the most recent row in
    company_score_history older than 7 days. Positive delta = worsening.
    """
    row = db.execute(text("""
        WITH cur AS (
            SELECT risk_band FROM company_scores WHERE orgnr = :orgnr
        ),
        prev AS (
            SELECT risk_band
            FROM company_score_history
            WHERE orgnr = :orgnr
              AND scored_at < now() - INTERVAL '7 days'
            ORDER BY scored_at DESC
            LIMIT 1
        )
        SELECT cur.risk_band AS current_band,
               prev.risk_band AS previous_band
        FROM cur LEFT JOIN prev ON TRUE
    """), {"orgnr": orgnr}).fetchone()

    if row is None or row.current_band is None:
        return {"delta_7d": None, "trajectory": None}

    if row.previous_band is None:
        return {"delta_7d": 0, "trajectory": "stable"}

    delta = int(row.current_band) - int(row.previous_band)
    if delta > 0:
        traj = "deteriorating"
    elif delta < 0:
        traj = "improving"
    else:
        traj = "stable"
    return {"delta_7d": delta, "trajectory": traj}


def compute_percentile(db, distress_probability: Optional[float]) -> Optional[int]:
    """Return 0–100 percentile (higher = worse) within the scored universe.

    Cheap on small populations (a few thousand scored companies). Returns
    None if distress_probability is None.
    """
    if distress_probability is None:
        return None
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE distress_probability < :p)::FLOAT
                / NULLIF(COUNT(*), 0) AS frac
        FROM company_scores
    """), {"p": distress_probability}).fetchone()
    if row is None or row.frac is None:
        return None
    return int(round(row.frac * 100))


# ── Signal state + timeline ───────────────────────────────────────────────────

def compute_signal_state(db, orgnr: str) -> dict:
    """Decompose the four signal flags + onset date + active debt total.

    Konkurs filings live in norric_payment_signals with status_code LIKE 'KK%'
    per the Bolagsverket kodlista (migration 2026_05_13_konkurs_signals.sql).
    Other active payment rows are betalningsförelägganden.
    """
    row = db.execute(text("""
        WITH tax AS (
            SELECT
                COUNT(*) FILTER (WHERE is_active) > 0          AS restanglangd,
                COALESCE(SUM(amount_sek) FILTER (WHERE is_active), 0) AS skuld_tax,
                MIN(first_seen_at) FILTER (WHERE is_active)    AS tax_onset
            FROM norric_tax_signals WHERE orgnr = :orgnr
        ),
        pay AS (
            SELECT
                COUNT(*) FILTER (
                    WHERE is_active AND (status_code IS NULL OR status_code NOT LIKE 'KK%')
                ) > 0                                          AS betalningsforelaggande,
                COUNT(*) FILTER (
                    WHERE is_active AND status_code LIKE 'KK%'
                ) > 0                                          AS konkursansokan,
                COALESCE(
                    SUM(claim_amount_sek) FILTER (
                        WHERE is_active
                          AND (status_code IS NULL OR status_code NOT LIKE 'KK%')
                    ), 0
                )                                              AS skuld_pay,
                MIN(filed_at) FILTER (WHERE is_active)         AS pay_onset
            FROM norric_payment_signals WHERE orgnr = :orgnr
        ),
        fsk AS (
            SELECT
                f_skatt_active_at IS NOT NULL
                  AND f_skatt_revoked_at IS NULL               AS f_skatt_active
            FROM company_profiles WHERE orgnr = :orgnr
        )
        SELECT
            COALESCE(tax.restanglangd,           FALSE) AS restanglangd,
            COALESCE(pay.betalningsforelaggande, FALSE) AS betalningsforelaggande,
            COALESCE(pay.konkursansokan,         FALSE) AS konkursansokan,
            COALESCE(fsk.f_skatt_active,         FALSE) AS f_skatt_active,
            COALESCE(tax.skuld_tax, 0) + COALESCE(pay.skuld_pay, 0) AS skuld_sek,
            LEAST(tax.tax_onset, pay.pay_onset::TIMESTAMPTZ)        AS onset_at
        FROM tax, pay
        LEFT JOIN fsk ON TRUE
    """), {"orgnr": orgnr}).fetchone()

    onset_at: Optional[datetime] = getattr(row, "onset_at", None) if row else None
    onset_date = onset_at.date() if onset_at else None
    onset_days = (datetime.now(timezone.utc) - onset_at).days if onset_at else None

    return {
        "restanglangd":           bool(row.restanglangd) if row else False,
        "betalningsforelaggande": bool(row.betalningsforelaggande) if row else False,
        "konkursansokan":         bool(row.konkursansokan) if row else False,
        "f_skatt_active":         bool(row.f_skatt_active) if row else False,
        "skuld_sek":              int(row.skuld_sek) if row and row.skuld_sek else 0,
        "signal_onset_date":      onset_date.isoformat() if onset_date else None,
        "onset_days":             onset_days,
    }


def compute_timeline(
    db, orgnr: str, distress_probability: Optional[float], onset_days: Optional[int]
) -> dict:
    """Position the company on the insolvency-arc timeline.

    Returns days elapsed / remaining vs MEDIAN_DAYS_TO_KONKURS, plus
    probability_12w (pass-through of distress_probability — the scorer
    already produces a probability over an implicit 12w window).
    """
    if onset_days is None:
        return {
            "median_days_to_konkurs": MEDIAN_DAYS_TO_KONKURS,
            "days_elapsed":           None,
            "days_remaining":         None,
            "probability_12w":        distress_probability,
        }

    return {
        "median_days_to_konkurs": MEDIAN_DAYS_TO_KONKURS,
        "days_elapsed":           int(onset_days),
        "days_remaining":         max(0, MEDIAN_DAYS_TO_KONKURS - int(onset_days)),
        "probability_12w":        distress_probability,
    }


# ── Contagion preview + active contracts ──────────────────────────────────────

def compute_contagion_summary(db, orgnr: str) -> dict:
    """Cached contagion peer counts + value-at-risk for the score response.

    Reads only the contagion_peers cache + joins active contracts of those
    peers. Returns zeros when no valid cache rows exist for this source.
    """
    summary = db.execute(text("""
        SELECT
            COUNT(*)                                                    AS peer_count,
            COUNT(*) FILTER (WHERE peer_tier = 'CRITICAL')              AS critical_peers,
            COUNT(*) FILTER (WHERE peer_tier = 'HIGH')                  AS high_peers
        FROM contagion_peers
        WHERE source_orgnr = :orgnr AND valid_until > now()
    """), {"orgnr": orgnr}).fetchone()

    at_risk = db.execute(text("""
        SELECT COALESCE(SUM(sc.contract_value_sek), 0) AS at_risk_value
        FROM contagion_peers cp
        JOIN signal_contracts sc ON sc.supplier_orgnr = cp.peer_orgnr
        WHERE cp.source_orgnr = :orgnr
          AND cp.valid_until > now()
          AND (sc.contract_end > CURRENT_DATE OR sc.contract_end IS NULL)
    """), {"orgnr": orgnr}).fetchone()

    return {
        "peer_count":      int(summary.peer_count) if summary else 0,
        "critical_peers":  int(summary.critical_peers) if summary else 0,
        "high_peers":      int(summary.high_peers) if summary else 0,
        "at_risk_contract_value_sek":
            int(at_risk.at_risk_value) if at_risk and at_risk.at_risk_value else 0,
    }


def compute_active_contracts(db, orgnr: str) -> dict:
    """Active SIGNAL contracts for this supplier (count, value, kommuner)."""
    row = db.execute(text("""
        SELECT
            COUNT(*)                                  AS contract_count,
            COALESCE(SUM(contract_value_sek), 0)      AS total_value_sek,
            COALESCE(
                ARRAY_AGG(DISTINCT municipality) FILTER (WHERE municipality IS NOT NULL),
                ARRAY[]::TEXT[]
            )                                         AS municipalities
        FROM signal_contracts
        WHERE supplier_orgnr = :orgnr
          AND (contract_end > CURRENT_DATE OR contract_end IS NULL)
    """), {"orgnr": orgnr}).fetchone()
    return {
        "count":           int(row.contract_count) if row else 0,
        "total_value_sek": int(row.total_value_sek) if row and row.total_value_sek else 0,
        "municipalities":  list(row.municipalities) if row and row.municipalities else [],
    }


# ── Full intelligence package (norric_score_v1) ───────────────────────────────

def build_score_intelligence(db, orgnr: str, score_result: dict) -> dict:
    """Compose the full intelligence package from a score_from_db result.

    Caller is responsible for handling score_source == 'no_signals' upstream;
    this function tolerates missing risk fields and surfaces them as None.
    """
    geo = get_company_geography(db, orgnr) or {}
    sector = derive_supplier_sector(db, orgnr)
    history = compute_band_history(db, orgnr)
    distress = score_result.get("distress_probability")
    percentile = compute_percentile(db, distress)
    signal_state = compute_signal_state(db, orgnr)
    timeline = compute_timeline(db, orgnr, distress, signal_state.get("onset_days"))
    contagion = compute_contagion_summary(db, orgnr)
    contracts = compute_active_contracts(db, orgnr)

    risk_band = score_result.get("risk_band")
    risk_score = score_result.get("risk_score")
    risk_tier  = score_result.get("risk_tier")

    return {
        "company": {
            "orgnr":        geo.get("orgnr") or orgnr,
            "name":         geo.get("name"),
            "orgform":      geo.get("orgform"),
            "sni_code":     None,  # not in norric_entities; surfaced as null
            "sector":       sector,
            "kommunkod":    geo.get("kommunkod"),
            "municipality": geo.get("municipality"),
            "county":       geo.get("county"),
            "lat":          geo.get("lat"),
            "lng":          geo.get("lng"),
        },
        "score": {
            "value":      risk_score,
            "tier":       risk_tier,
            "band":       risk_band,
            "percentile": percentile,
            "delta_7d":   history["delta_7d"],
            "trajectory": history["trajectory"],
            "scale":      "0-20",
            "polarity":   "ascending_risk",
        },
        "signals": {
            "restanglangd":           signal_state["restanglangd"],
            "betalningsforelaggande": signal_state["betalningsforelaggande"],
            "konkursansokan":         signal_state["konkursansokan"],
            "f_skatt_active":         signal_state["f_skatt_active"],
            "onset_days":             signal_state["onset_days"],
            "skuld_sek":              signal_state["skuld_sek"],
        },
        "timeline": {
            "signal_onset_date":      signal_state["signal_onset_date"],
            "median_days_to_konkurs": timeline["median_days_to_konkurs"],
            "days_elapsed":           timeline["days_elapsed"],
            "days_remaining":         timeline["days_remaining"],
            "probability_12w":        timeline["probability_12w"],
        },
        "contagion_preview": contagion,
        "active_contracts":  contracts,
        "meta": {
            "model_version":  MODEL_VERSION,
            "data_freshness": score_result.get("scored_at"),
            "data_freshness_hours": score_result.get("data_freshness_hours"),
            "score_source":   score_result.get("score_source"),
            "api_version":    API_VERSION,
        },
    }


# ── Company search (norric_search_v1) ─────────────────────────────────────────

def search_entities(db, q: str, limit: int = 10) -> list[dict]:
    """Search norric_entities by orgnr prefix or name.

    Heuristic: if q is digits + dash only, treat as orgnr prefix; otherwise
    case-insensitive name prefix. Results include the company's current
    score/tier when available (LEFT JOIN to company_scores).
    """
    q_stripped = (q or "").strip()
    if not q_stripped:
        return []

    limit = max(1, min(int(limit), 50))

    if _ORGNR_PREFIX_RE.match(q_stripped):
        # orgnr-shaped query — prefix-match on orgnr_display
        rows = db.execute(text("""
            SELECT
                ne.orgnr_display AS orgnr,
                ne.name          AS name,
                cs.risk_band     AS risk_band,
                cs.distress_probability AS distress_probability
            FROM norric_entities ne
            LEFT JOIN company_scores cs ON cs.orgnr = ne.orgnr_display
            WHERE ne.orgnr_display LIKE :q || '%'
            ORDER BY cs.risk_band DESC NULLS LAST, ne.name
            LIMIT :limit
        """), {"q": q_stripped, "limit": limit}).fetchall()
    else:
        # name-shaped query — prefix-match case-insensitive
        rows = db.execute(text("""
            SELECT
                ne.orgnr_display AS orgnr,
                ne.name          AS name,
                cs.risk_band     AS risk_band,
                cs.distress_probability AS distress_probability
            FROM norric_entities ne
            LEFT JOIN company_scores cs ON cs.orgnr = ne.orgnr_display
            WHERE ne.name ILIKE :q || '%'
            ORDER BY cs.risk_band DESC NULLS LAST, ne.name
            LIMIT :limit
        """), {"q": q_stripped, "limit": limit}).fetchall()

    # Lazy import to avoid module-load cost when search isn't called.
    from scoring.kreditvakt import TIER_FROM_BAND
    _SCORE_FROM_BAND = {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}

    out: list[dict] = []
    for r in rows:
        band = int(r.risk_band) if r.risk_band is not None else None
        out.append({
            "orgnr":      r.orgnr,
            "name":       r.name,
            "risk_band":  band,
            "risk_score": _SCORE_FROM_BAND.get(band) if band is not None else None,
            "risk_tier":  TIER_FROM_BAND.get(band) if band is not None else None,
            "distress_probability": float(r.distress_probability)
                                    if r.distress_probability is not None else None,
        })
    return out


# ── Blast-radius shape (norric_contagion_map_v1) ──────────────────────────────

def build_contagion_map(db, orgnr: str) -> dict:
    """Build the full blast-radius shape for visualization.

    Reads contagion_peers cache, joins each peer (and the source) to
    norric_entities + municipalities for lat/lng + kommun name. Peers are
    grouped into rings by match_reason. Returns the shape the dashboard
    visualization consumes directly.
    """
    src_geo = get_company_geography(db, orgnr)
    if src_geo is None:
        return {
            "source":  None,
            "rings":   [],
            "summary": {"total_peers": 0, "critical_peers": 0, "high_peers": 0,
                        "geographic_spread": None},
            "warning": "orgnr_not_ingested",
        }

    src_score = db.execute(text("""
        SELECT risk_band, distress_probability
        FROM company_scores WHERE orgnr = :orgnr
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()

    from scoring.kreditvakt import TIER_FROM_BAND
    _SCORE_FROM_BAND = {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}
    src_band = int(src_score.risk_band) if src_score and src_score.risk_band is not None else None

    source = {
        "orgnr":        src_geo["orgnr"],
        "name":         src_geo["name"],
        "tier":         TIER_FROM_BAND.get(src_band) if src_band else None,
        "score":        _SCORE_FROM_BAND.get(src_band) if src_band else None,
        "lat":          src_geo["lat"],
        "lng":          src_geo["lng"],
        "kommunkod":    src_geo["kommunkod"],
        "municipality": src_geo["municipality"],
        "county":       src_geo["county"],
    }

    # Pull all valid cached peers joined to their geography in one round-trip.
    peer_rows = db.execute(text("""
        SELECT
            cp.peer_orgnr      AS orgnr,
            cp.peer_name       AS name,
            cp.peer_tier       AS tier,
            cp.peer_kv_score   AS score,
            cp.match_reason    AS match_reason,
            cp.proximity_score AS proximity_score,
            ne.kommunkod       AS kommunkod,
            ne.county          AS county,
            m.name             AS municipality,
            m.lat              AS lat,
            m.lng              AS lng
        FROM contagion_peers cp
        LEFT JOIN norric_entities ne ON ne.orgnr_display = cp.peer_orgnr
        LEFT JOIN municipalities m ON m.id = CASE
            WHEN ne.kommunkod ~ '^\\d+$' THEN ne.kommunkod::INTEGER
            ELSE NULL
        END
        WHERE cp.source_orgnr = :orgnr
          AND cp.valid_until > now()
        ORDER BY cp.proximity_score DESC, cp.peer_kv_score DESC NULLS LAST
    """), {"orgnr": orgnr}).fetchall()

    rings_map: dict[str, list[dict]] = {}
    kommunkods_seen: set[str] = set()
    counties_seen:   set[str] = set()
    critical = high = 0
    for r in peer_rows:
        peer = {
            "orgnr":        r.orgnr,
            "name":         r.name,
            "tier":         r.tier,
            "score":        r.score,
            "lat":          r.lat,
            "lng":          r.lng,
            "kommunkod":    r.kommunkod,
            "municipality": r.municipality,
            "county":       r.county,
        }
        rings_map.setdefault(r.match_reason, []).append(peer)
        if r.kommunkod:
            kommunkods_seen.add(r.kommunkod)
        if r.county:
            counties_seen.add(r.county)
        if r.tier == "CRITICAL":
            critical += 1
        elif r.tier == "HIGH":
            high += 1

    # Build ordered rings: kommunkod (ring 1) then county (ring 2).
    ring_order = ("same_sector_kommunkod", "same_sector_county")
    rings = []
    for idx, reason in enumerate(ring_order, start=1):
        if reason in rings_map:
            rings.append({
                "ring":         idx,
                "match_reason": reason,
                "proximity":    _RING_PROXIMITY[reason],
                "label":        _RING_LABELS[reason],
                "peers":        rings_map[reason],
            })

    if len(kommunkods_seen) <= 1 and len(counties_seen) <= 1:
        spread = "municipality"
    elif len(counties_seen) <= 1:
        spread = "county"
    else:
        spread = "region"

    return {
        "source":  source,
        "rings":   rings,
        "summary": {
            "total_peers":       len(peer_rows),
            "critical_peers":    critical,
            "high_peers":        high,
            "geographic_spread": spread if peer_rows else None,
        },
    }
