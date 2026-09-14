"""
watch/diff.py — change detection over the Kreditvakt beats (spec §3.1).

Runs after the daily 05:30 portfolio rescore. For every active watch,
compares what the pipelines just wrote against what was there before and
emits norric_watch_events rows for the four v1 event types:

    company.risk_tier_changed        two latest company_score_history rows,
                                     band moved (tier = TIER_FROM_BAND[band])
    company.score_changed            same pair, |risk_score delta| >= the
                                     watch's min_score_delta (score is the
                                     canonical 0-20 band midpoint)
    company.debt_signal_new          norric_payment_signals (Kronofogden) or
                                     norric_tax_signals (Skatteverket) rows
                                     created since the previous diff run
    company.bankruptcy_status_changed
                                     new konkurs rows (case_ref bv-konkurs-*)
                                     created since the previous diff run.
                                     LIMITATION: status flips on an existing
                                     filing are upserts that don't move
                                     created_at, so v1 detects new petitions
                                     only - not their resolution.

Dedupe is deterministic: (watch_id, event_type, orgnr, occurred_at) -
occurred_at is the underlying row's own timestamp (score scored_at /
signal created_at), so a re-run of the diff never double-emits.

No fabrication: every emitted event carries the real previous/current
values and the pipeline_run_id of the diff run that produced it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from scoring.kreditvakt import TIER_FROM_BAND, _risk_score_from_band

from .refs import new_event_ref

log = logging.getLogger(__name__)

DIFF_PIPELINE = "watch_diff"
FIRST_RUN_LOOKBACK_HOURS = 25


# ── Watermark ────────────────────────────────────────────────────────────────

def last_diff_success(db: Session) -> datetime:
    """End of the previous successful diff run; 25h lookback on first run."""
    row = db.execute(
        text("""
            SELECT MAX(completed_at) AS last_ok
            FROM norric_pipeline_runs
            WHERE pipeline = :p AND status = 'success'
        """),
        {"p": DIFF_PIPELINE},
    ).fetchone()
    if row and row.last_ok:
        return row.last_ok
    return datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_LOOKBACK_HOURS)


# ── Pure detection (unit-tested without a DB) ────────────────────────────────

def detect_score_events(
    orgnr: str,
    prev: Optional[dict],
    curr: dict,
    event_types: set[str],
    min_score_delta: int,
) -> list[dict]:
    """
    Compare consecutive score rows for one orgnr. prev/curr carry
    risk_band + scored_at. Returns event dicts (type, occurred_at, data).
    No previous row → nothing to diff against → no events.
    """
    if prev is None:
        return []

    prev_score = _risk_score_from_band(prev["risk_band"])
    curr_score = _risk_score_from_band(curr["risk_band"])
    prev_tier = TIER_FROM_BAND[prev["risk_band"]]
    curr_tier = TIER_FROM_BAND[curr["risk_band"]]

    previous = {"risk_score": prev_score, "risk_tier": prev_tier,
                "scored_at": _iso(prev["scored_at"])}
    current = {"risk_score": curr_score, "risk_tier": curr_tier,
               "scored_at": _iso(curr["scored_at"])}

    out = []
    if curr_tier != prev_tier and "company.risk_tier_changed" in event_types:
        out.append({
            "event_type": "company.risk_tier_changed",
            "orgnr": orgnr,
            "occurred_at": curr["scored_at"],
            "data": {"orgnr": orgnr, "previous": previous, "current": current},
        })
    if (abs(curr_score - prev_score) >= min_score_delta
            and curr_score != prev_score
            and "company.score_changed" in event_types):
        out.append({
            "event_type": "company.score_changed",
            "orgnr": orgnr,
            "occurred_at": curr["scored_at"],
            "data": {
                "orgnr": orgnr,
                "previous": previous,
                "current": current,
                "score_delta": curr_score - prev_score,
                "min_score_delta": min_score_delta,
            },
        })
    return out


def detect_signal_events(
    orgnr: str,
    new_rows: list[dict],
    event_types: set[str],
) -> list[dict]:
    """
    New debt/bankruptcy signal rows for one orgnr. Each row carries
    source ('kronofogden' | 'skatteverket' | 'bolagsverket_konkurs'),
    signal_id, created_at, and a summary dict.
    """
    out = []
    for row in new_rows:
        if row["source"] == "bolagsverket_konkurs":
            et = "company.bankruptcy_status_changed"
        else:
            et = "company.debt_signal_new"
        if et not in event_types:
            continue
        out.append({
            "event_type": et,
            "orgnr": orgnr,
            "occurred_at": row["created_at"],
            "data": {
                "orgnr": orgnr,
                "signal_source": row["source"],
                "signal": row["summary"],
                "detected_at": _iso(row["created_at"]),
            },
        })
    return out


def _iso(dt) -> str:
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


# ── Emission ─────────────────────────────────────────────────────────────────

def insert_event(db: Session, watch: dict, event: dict,
                 pipeline_run_id, confidence: float = 0.87) -> Optional[str]:
    """
    Insert one norric_watch_events row with the full signed-body payload.
    Dedupe on (watch_id, event_type, orgnr, occurred_at): returns the new
    event_ref, or None when the event already exists (re-run safety).
    """
    ref = new_event_ref()
    payload = {
        "id": ref,
        "type": event["event_type"],
        "occurred_at": _iso(event["occurred_at"]),
        "watch_id": watch["watch_ref"],
        "data": event["data"],
        "metadata": {
            "source": ["skatteverket", "kronofogden", "bolagsverket"],
            "pipeline_run_id": str(pipeline_run_id),
            "confidence": confidence,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "signals": [],
        "warnings": [],
    }
    row = db.execute(
        text("""
            INSERT INTO norric_watch_events (
                event_ref, watch_id, event_type, orgnr, payload, occurred_at
            )
            SELECT :ref, :wid, :et, :orgnr, :payload, :occ
            WHERE NOT EXISTS (
                SELECT 1 FROM norric_watch_events
                WHERE watch_id = :wid AND event_type = :et
                  AND orgnr = :orgnr AND occurred_at = :occ
            )
            RETURNING event_ref
        """),
        {
            "ref": ref,
            "wid": watch["id"],
            "et": event["event_type"],
            "orgnr": event["orgnr"],
            "payload": json.dumps(payload),
            "occ": event["occurred_at"],
        },
    ).fetchone()
    return row.event_ref if row else None


def active_watches(db: Session) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT id, watch_ref, event_types, filters, callback_url, signing_secret
            FROM norric_watches
            WHERE status = 'active'
        """),
    ).fetchall()
    out = []
    for r in rows:
        f = r.filters if isinstance(r.filters, dict) else json.loads(r.filters)
        out.append({
            "id": r.id,
            "watch_ref": r.watch_ref,
            "event_types": set(r.event_types),
            "orgnrs": f.get("orgnrs") or [],
            "min_score_delta": f.get("min_score_delta", 3),
            "callback_url": r.callback_url,
            "signing_secret": r.signing_secret,
        })
    return out


def _latest_score_pairs(db: Session, orgnrs: list[str]) -> dict[str, tuple]:
    """Two most recent company_score_history rows per orgnr."""
    if not orgnrs:
        return {}
    rows = db.execute(
        text("""
            SELECT orgnr, risk_band, scored_at, rn
            FROM (
                SELECT orgnr, risk_band, scored_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY orgnr ORDER BY scored_at DESC
                       ) AS rn
                FROM company_score_history
                WHERE orgnr = ANY(:orgs)
            ) t
            WHERE rn <= 2
            ORDER BY orgnr, rn
        """),
        {"orgs": orgnrs},
    ).fetchall()
    pairs: dict[str, list] = {}
    for r in rows:
        pairs.setdefault(r.orgnr, []).append(
            {"risk_band": r.risk_band, "scored_at": r.scored_at}
        )
    return {o: (v[1], v[0]) for o, v in pairs.items() if len(v) == 2}


def _new_signal_rows(db: Session, orgnrs: list[str], since: datetime) -> dict[str, list]:
    """Debt + konkurs signal rows created after the watermark, by orgnr."""
    if not orgnrs:
        return {}
    out: dict[str, list] = {}
    pay = db.execute(
        text("""
            SELECT orgnr, id, created_at, case_ref, creditor_type,
                   claim_amount_sek, filed_at, status_code
            FROM norric_payment_signals
            WHERE created_at > :since AND orgnr = ANY(:orgs)
        """),
        {"since": since, "orgs": orgnrs},
    ).fetchall()
    for r in pay:
        konkurs = bool(r.case_ref and str(r.case_ref).startswith("bv-konkurs-"))
        out.setdefault(r.orgnr, []).append({
            "source": "bolagsverket_konkurs" if konkurs else "kronofogden",
            "signal_id": str(r.id),
            "created_at": r.created_at,
            "summary": {
                "case_ref": r.case_ref,
                "status_code": r.status_code,
                "creditor_type": r.creditor_type,
                "claim_amount_sek": r.claim_amount_sek,
                "filed_at": _iso(r.filed_at) if r.filed_at else None,
            },
        })
    try:
        tax = db.execute(
            text("""
                SELECT orgnr, id, created_at, signal_type, amount_sek
                FROM norric_tax_signals
                WHERE created_at > :since AND orgnr = ANY(:orgs)
            """),
            {"since": since, "orgs": orgnrs},
        ).fetchall()
        for r in tax:
            out.setdefault(r.orgnr, []).append({
                "source": "skatteverket",
                "signal_id": str(r.id),
                "created_at": r.created_at,
                "summary": {"signal_type": r.signal_type, "amount_sek": r.amount_sek},
            })
    except Exception:
        db.rollback()  # tax table unavailable — payment signals suffice
    return out


def emit_diff_events(db: Session, pipeline_run_id) -> dict:
    """
    The beat entry point. Detects changes for every active watch and
    writes norric_watch_events rows. Returns emission counts.
    """
    watermark = last_diff_success(db)
    watches = [w for w in active_watches(db) if w["orgnrs"]]
    all_orgnrs = sorted({o for w in watches for o in w["orgnrs"]})

    pairs = _latest_score_pairs(db, all_orgnrs)
    signals = _new_signal_rows(db, all_orgnrs, watermark)

    emitted = 0
    deduped = 0
    for w in watches:
        for orgnr in w["orgnrs"]:
            events = []
            if orgnr in pairs:
                prev, curr = pairs[orgnr]
                events += detect_score_events(
                    orgnr, prev, curr, w["event_types"], w["min_score_delta"]
                )
            if orgnr in signals:
                events += detect_signal_events(orgnr, signals[orgnr], w["event_types"])
            for e in events:
                if insert_event(db, w, e, pipeline_run_id):
                    emitted += 1
                else:
                    deduped += 1
    db.commit()
    return {
        "watches": len(watches),
        "orgnrs": len(all_orgnrs),
        "watermark": watermark.isoformat(),
        "emitted": emitted,
        "deduped": deduped,
    }
