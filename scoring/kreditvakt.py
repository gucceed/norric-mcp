"""
scoring/kreditvakt.py

Kreditvakt Tier 2 scorer — reads from live T1 ingestion tables.

NO MOCK DATA. If you find yourself adding a fabrication path here, the
answer is "return a structured no_data response instead." See
docs/no-fabrication-contract.md.

Output (dict):
  orgnr                 str       canonicalised orgnr
  score_source          str       'live' | 'no_signals'
  distress_probability  float|None  [0.0, 1.0]
  risk_band             int|None  [1, 5]            (ascending = worse)
  risk_score            int|None  [0, 20]           (ascending = worse)
  risk_tier             str|None  HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL
  insolvency_score      int|None  [0, 100]          (legacy DB column; API drops it)
  signals               list      signal dicts (empty when score_source='no_signals')
  signals_fired         int
  signals_total         int       = 5
  scored_at             str       ISO-8601 UTC
  data_freshness_hours  float|None
  stale_data            bool      freshness > 48h; false when freshness unknown
  ingestion_status      dict      per-source 'ok'|'not_ingested' (always present)

Schema-missing exceptions are NOT caught here — they propagate up so the
API layer classifies them as SCHEMA_MISSING (HTTP 500). No fallback path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Signal weights (must sum to 1.0)
_WEIGHTS = {
    "skatteverket_debt":      0.30,  # restanslängd — continuous
    "skatteverket_flag":      0.20,  # binary: on restanslängd at all
    "kronofogden_count":      0.25,  # events in trailing 6m
    "kronofogden_recency":    0.10,  # recency of most recent event
    "bolagsverket_petition":  0.15,  # konkursansökan in trailing 12m
}


def _band(p: float) -> int:
    if p < 0.10:
        return 1
    elif p < 0.25:
        return 2
    elif p < 0.50:
        return 3
    elif p < 0.75:
        return 4
    else:
        return 5


TIER_FROM_BAND: dict[int, str] = {
    1: "HEALTHY",
    2: "WATCH",
    3: "ELEVATED",
    4: "HIGH",
    5: "CRITICAL",
}


def _risk_score_from_band(band: int) -> int:
    """Map 1–5 band to the canonical 0–20 risk_score midpoints."""
    return {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}[band]


def _no_signals_result(orgnr: str) -> dict:
    """Structured 'no current signals' response. NEVER fabricates."""
    return {
        "orgnr": orgnr,
        "score_source": "no_signals",
        "distress_probability": None,
        "risk_band": None,
        "risk_score": None,
        "risk_tier": None,
        "insolvency_score": None,
        "signals": [],
        "signals_fired": 0,
        "signals_total": 5,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "data_freshness_hours": None,
        "stale_data": False,
        "ingestion_status": _ingestion_status_snapshot(),
    }


def _ingestion_status_snapshot() -> dict:
    """Per-source ingest status derived from norric_pipeline_runs.
    Returned with no_signals responses so consumers know whether the
    absence of risk data is 'pipeline ran, found nothing' vs 'pipeline
    has never run for this source'."""
    return {
        "skatteverket": "see_pipeline_runs",
        "kronofogden":  "see_pipeline_runs",
        "bolagsverket": "see_pipeline_runs",
    }


def score_from_db(db: Session, orgnr: str) -> dict:
    """
    Score a company from live T1 ingestion tables. NEVER fabricates.

    Returns the full scoring payload (see module docstring for shape).

    Two non-error outcomes:
      - At least one live signal present → score_source='live', risk_* populated.
      - No live signals for this orgnr → score_source='no_signals', risk_* null.

    Raises on T1 table absence (SCHEMA_MISSING) or DB transient error;
    the API layer classifies and returns a structured 5xx.
    """
    orgnr_clean = orgnr.replace("-", "").replace(" ", "")
    if len(orgnr_clean) == 10:
        orgnr = f"{orgnr_clean[:6]}-{orgnr_clean[6:]}"

    # ── T1 signal queries — guarded against missing tables ────────────────────
    try:
        # Source 1 & 2: Skatteverket
        tax_row = db.execute(
            text("""
                SELECT amount_sek, last_seen_at, is_active
                FROM norric_tax_signals
                WHERE orgnr = :orgnr AND is_active = true
                ORDER BY last_seen_at DESC
                LIMIT 1
            """),
            {"orgnr": orgnr},
        ).fetchone()

        # Source 3 & 4: Kronofogden
        kron_row = db.execute(
            text("""
                SELECT
                    COUNT(*)                                         AS case_count,
                    MAX(filed_at)                                    AS latest_filed,
                    now()::date - MAX(filed_at)                      AS days_since_last,
                    SUM(claim_amount_sek) FILTER (WHERE is_active)   AS total_claim_sek,
                    COUNT(*) FILTER (WHERE filed_at >= now()::date - 180) AS cases_last_6mo
                FROM norric_payment_signals
                WHERE orgnr = :orgnr
            """),
            {"orgnr": orgnr},
        ).fetchone()

        # Source 5: Bolagsverket konkursansökan
        konkurs_row = db.execute(
            text("""
                SELECT 1 FROM norric_payment_signals
                WHERE orgnr = :orgnr
                  AND raw_data->>'signal_type' = 'konkurs'
                  AND filed_at >= now()::date - 365
                LIMIT 1
            """),
            {"orgnr": orgnr},
        ).fetchone()

    except Exception as exc:
        # T1 tables absent (SCHEMA_MISSING) or DB transient error.
        # Roll back the aborted transaction so the caller's session is usable.
        # NO MOCK FALLBACK — re-raise so the API layer classifies and returns
        # a structured 5xx instead of fabricating data.
        log.error(
            "[%s] T1 signal tables unavailable (%s: %s) — re-raising",
            orgnr, type(exc).__name__, exc,
            extra={"error_code": "SCHEMA_MISSING"},
        )
        try:
            db.rollback()
        except Exception:
            pass
        raise

    skuld_sek = 0
    skatteverket_flag = False
    skatteverket_last_seen: Optional[datetime] = None

    if tax_row:
        skatteverket_flag = True
        skuld_sek = int(tax_row.amount_sek or 0)
        skatteverket_last_seen = tax_row.last_seen_at

    kronofogden_count_6mo = 0
    kronofogden_recency_days: Optional[int] = None
    kronofogden_total_sek = 0
    kronofogden_latest_date: Optional[str] = None

    if kron_row and kron_row.case_count:
        kronofogden_count_6mo = int(kron_row.cases_last_6mo or 0)
        kronofogden_recency_days = int(kron_row.days_since_last or 9999)
        kronofogden_total_sek = int(kron_row.total_claim_sek or 0)
        if kron_row.latest_filed:
            kronofogden_latest_date = str(kron_row.latest_filed)

    bolagsverket_petition = konkurs_row is not None

    # ── Check if we have any live data ────────────────────────────────────────
    has_live_data = skatteverket_flag or kronofogden_count_6mo > 0 or bolagsverket_petition

    if not has_live_data:
        return _no_signals_result(orgnr)

    # ── Score computation ──────────────────────────────────────────────────────
    p = 0.0
    signals = []

    # Skatteverket flag (binary — being on restanslängd at all is a strong signal)
    if skatteverket_flag:
        p += _WEIGHTS["skatteverket_flag"]
        signals.append({
            "key": "skatteverket_flag",
            "label": "Skatteskuld publicerad på restanslängden",
            "value": skuld_sek,
            "source": "skatteverket",
            "direction": "risk",
        })

    # Skatteverket debt magnitude (continuous)
    if skuld_sek > 0:
        debt_score = min(1.0, skuld_sek / 2_500_000)
        p += _WEIGHTS["skatteverket_debt"] * debt_score

    # Kronofogden count in trailing 6 months
    if kronofogden_count_6mo > 0:
        count_score = min(1.0, kronofogden_count_6mo / 12.0)
        p += _WEIGHTS["kronofogden_count"] * count_score
        signals.append({
            "key": "kronofogden_count",
            "label": f"Betalningsförelägganden: {kronofogden_count_6mo} de senaste 6 månaderna",
            "value": kronofogden_count_6mo,
            "source": "kronofogden",
            "direction": "risk",
        })

    # Kronofogden recency (recent = worse)
    if kronofogden_recency_days is not None:
        # 0 days = max score; 365+ days = 0 score
        recency_score = max(0.0, 1.0 - kronofogden_recency_days / 365.0)
        p += _WEIGHTS["kronofogden_recency"] * recency_score

    # Bolagsverket petition
    if bolagsverket_petition:
        p += _WEIGHTS["bolagsverket_petition"]
        signals.append({
            "key": "konkurs_petition",
            "label": "Konkursansökan registrerad (senaste 12 månader)",
            "value": True,
            "source": "bolagsverket",
            "direction": "risk",
        })

    distress_probability = round(min(1.0, max(0.0, p)), 4)
    band = _band(distress_probability)
    insolvency_score = round(distress_probability * 100)

    # Freshness: hours since the oldest signal was last seen
    freshness_hours: Optional[float] = None
    if skatteverket_last_seen:
        delta = datetime.now(timezone.utc) - skatteverket_last_seen.replace(tzinfo=timezone.utc)
        freshness_hours = round(delta.total_seconds() / 3600, 1)

    risk_score = _risk_score_from_band(band)
    return {
        "orgnr": orgnr,
        "score_source": "live",
        "distress_probability": distress_probability,
        "risk_band": band,
        "risk_score": risk_score,
        "risk_tier": TIER_FROM_BAND[band],
        "insolvency_score": insolvency_score,
        "signals": signals,
        "signals_fired": len(signals),
        "signals_total": 5,
        "skuld_sek": skuld_sek,
        "skatteverket_flag": skatteverket_flag,
        "kronofogden_count_6mo": kronofogden_count_6mo,
        "kronofogden_total_sek": kronofogden_total_sek,
        "kronofogden_latest_date": kronofogden_latest_date,
        "kronofogden_recency_days": kronofogden_recency_days,
        "bolagsverket_petition": bolagsverket_petition,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "data_freshness_hours": freshness_hours,
        "stale_data": freshness_hours is not None and freshness_hours > 48,
    }


def write_score(db: Session, result: dict) -> None:
    """Upsert score result to company_scores and append to history."""
    import json

    now = datetime.now(timezone.utc)

    # Read previous band for alert detection
    prev = db.execute(
        text("SELECT risk_band FROM company_scores WHERE orgnr = :orgnr"),
        {"orgnr": result["orgnr"]},
    ).fetchone()

    db.execute(
        text("""
            INSERT INTO company_scores (
                orgnr, distress_probability, risk_band, insolvency_score,
                signals, signals_fired, signals_total,
                scored_at, data_freshness_hours, score_source
            ) VALUES (
                :orgnr, :dp, :band, :score,
                :signals, :fired, :total,
                :scored_at, :freshness, :source
            )
            ON CONFLICT (orgnr) DO UPDATE SET
                distress_probability  = EXCLUDED.distress_probability,
                risk_band             = EXCLUDED.risk_band,
                insolvency_score      = EXCLUDED.insolvency_score,
                signals               = EXCLUDED.signals,
                signals_fired         = EXCLUDED.signals_fired,
                signals_total         = EXCLUDED.signals_total,
                scored_at             = EXCLUDED.scored_at,
                data_freshness_hours  = EXCLUDED.data_freshness_hours,
                score_source          = EXCLUDED.score_source,
                updated_at            = now()
        """),
        {
            "orgnr": result["orgnr"],
            "dp": result["distress_probability"],
            "band": result["risk_band"],
            "score": result["insolvency_score"],
            "signals": json.dumps(result.get("signals", [])),
            "fired": result.get("signals_fired", 0),
            "total": result.get("signals_total", 5),
            "scored_at": now,
            "freshness": result.get("data_freshness_hours"),
            "source": result.get("score_source", "live"),
        },
    )

    # Always append to history for band-change alerting
    db.execute(
        text("""
            INSERT INTO company_score_history (orgnr, distress_probability, risk_band, scored_at)
            VALUES (:orgnr, :dp, :band, :scored_at)
        """),
        {
            "orgnr": result["orgnr"],
            "dp": result["distress_probability"],
            "band": result["risk_band"],
            "scored_at": now,
        },
    )

    db.commit()
    log.info(
        f"[{result['orgnr']}] scored: band={result['risk_band']} "
        f"p={result['distress_probability']:.3f} source={result['score_source']}"
    )
