"""
scoring/kreditvakt.py

Kreditvakt Tier 2 scorer — reads from live T1 ingestion tables.

Output:
  distress_probability: float [0.0, 1.0]
  risk_band:            int   [1–5]
  insolvency_score:     int   [0–100]   (legacy compat for UI)
  signals:              list  of signal dicts
  score_source:         'live' | 'mock'

Band mapping:
  1: 0.00–0.10  Minimal
  2: 0.10–0.25  Low
  3: 0.25–0.50  Elevated
  4: 0.50–0.75  High
  5: 0.75–1.00  Critical

Falls back to deterministic mock engine when no live signals found.
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


def score_from_db(db: Session, orgnr: str) -> dict:
    """
    Score a company from live T1 ingestion tables.

    Returns the full scoring payload or raises RuntimeError if DB unavailable.
    When no signals are found (company not yet ingested), returns score_source='mock'
    via the deterministic fallback.
    """
    orgnr_clean = orgnr.replace("-", "").replace(" ", "")
    if len(orgnr_clean) == 10:
        orgnr = f"{orgnr_clean[:6]}-{orgnr_clean[6:]}"

    # ── Source 1 & 2: Skatteverket ─────────────────────────────────────────────
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

    skuld_sek = 0
    skatteverket_flag = False
    skatteverket_last_seen: Optional[datetime] = None

    if tax_row:
        skatteverket_flag = True
        skuld_sek = int(tax_row.amount_sek or 0)
        skatteverket_last_seen = tax_row.last_seen_at

    # ── Source 3 & 4: Kronofogden ──────────────────────────────────────────────
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

    # ── Source 5: Bolagsverket konkursansökan ──────────────────────────────────
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
    bolagsverket_petition = konkurs_row is not None

    # ── Check if we have any live data ────────────────────────────────────────
    has_live_data = skatteverket_flag or kronofogden_count_6mo > 0 or bolagsverket_petition

    if not has_live_data:
        return _mock_fallback(orgnr)

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

    return {
        "orgnr": orgnr,
        "distress_probability": distress_probability,
        "risk_band": band,
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
        "score_source": "live",
    }


def _mock_fallback(orgnr: str) -> dict:
    """No live signals — use deterministic mock. Always returns score_source='mock'."""
    from tools.kreditvakt_engine import score_company

    log.debug(f"[{orgnr}] No live signals — using deterministic mock fallback")
    r = score_company(orgnr)

    if "error" in r:
        return {
            "orgnr": orgnr,
            "distress_probability": 0.0,
            "risk_band": 1,
            "insolvency_score": 0,
            "signals": [],
            "signals_fired": 0,
            "signals_total": 5,
            "error": r["error"],
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "data_freshness_hours": None,
            "stale_data": False,
            "score_source": "mock",
        }

    s = r["insolvency_score"]
    return {
        "orgnr": r["orgnr"],
        "company_name": r.get("company_name"),
        "industry": r.get("industry"),
        "distress_probability": round(s / 100, 4),
        "risk_band": _band(s / 100),
        "insolvency_score": s,
        "signals": [],
        "signals_fired": r.get("signal_count", 0),
        "signals_total": 5,
        "skuld_sek": r.get("skuld_sek", 0),
        "skatteverket_flag": r.get("skuld_sek", 0) > 0,
        "kronofogden_count_6mo": r.get("betalning_count", 0),
        "kronofogden_total_sek": r.get("betalning_total_sek", 0),
        "kronofogden_latest_date": r.get("betalning_latest_date"),
        "kronofogden_recency_days": None,
        "bolagsverket_petition": r.get("konkurs_filed", False),
        "verdict": r.get("verdict"),
        "f_skatt_active": r.get("f_skatt_active"),
        "konkurs_filed": r.get("konkurs_filed"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "data_freshness_hours": None,
        "stale_data": True,
        "score_source": "mock",
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
