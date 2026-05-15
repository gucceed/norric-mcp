"""
kreditvakt/signal_cross.py

SIGNAL ↔ Kreditvakt cross-signal engine.

  score_unscored(batch_size)  — score new signal_contracts from company_scores
  rescore_active()            — refresh active contracts, log tier escalations

Reads from company_scores (T2-01 Kreditvakt output), norric_tax_signals,
norric_payment_signals; writes kv_score / kv_tier / kv_flags back to
signal_contracts. Same database, zero network hops.
"""

import json
import logging

from celery import shared_task
from sqlalchemy import text

from ingestion.db import Session

log = logging.getLogger(__name__)


# Risk-band (1–5) → 0–20 Norric SIGNAL score.
BAND_TO_SCORE = {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}

TIER_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def score_to_tier(score: int) -> str:
    if score >= 17: return "CRITICAL"
    if score >= 13: return "HIGH"
    if score >= 8:  return "MEDIUM"
    return "LOW"


def _compute_flags(db, orgnr: str) -> dict:
    # Konkurs filings live in norric_payment_signals with status_code starting
    # 'KK' per the Bolagsverket kodlista (e.g. KK-AVOMFO = konkurs inledd),
    # added by migration 2026_05_13_konkurs_signals.sql. Non-KK active rows
    # are ordinary betalningsförelägganden.
    res = db.execute(text("""
        SELECT
            EXISTS (
                SELECT 1 FROM norric_tax_signals
                WHERE orgnr = :orgnr AND is_active = true
            ) AS restanglangd,
            EXISTS (
                SELECT 1 FROM norric_payment_signals
                WHERE orgnr = :orgnr AND is_active = true
                  AND (status_code IS NULL OR status_code NOT LIKE 'KK%')
            ) AS betalningsforelaggande,
            EXISTS (
                SELECT 1 FROM norric_payment_signals
                WHERE orgnr = :orgnr AND is_active = true
                  AND status_code LIKE 'KK%'
            ) AS konkursansokan
    """), {"orgnr": orgnr}).fetchone()
    return {
        "restanglangd":           bool(res.restanglangd),
        "betalningsforelaggande": bool(res.betalningsforelaggande),
        "konkursansokan":         bool(res.konkursansokan),
    }


def _lookup_score(db, orgnr: str):
    """Return (risk_band, distress_probability) or None if no score on file."""
    row = db.execute(text("""
        SELECT risk_band, distress_probability
        FROM company_scores
        WHERE orgnr = :orgnr
        ORDER BY updated_at DESC
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()
    return row


# ── Task: score signal_contracts that have never been scored ──────────────────

@shared_task(
    name="signal.score_unscored",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def score_unscored(self, batch_size: int = 200) -> dict:
    """
    For every signal_contract where supplier_orgnr IS NOT NULL and kv_score
    IS NULL: look up company_scores, write back kv_score, kv_tier, kv_flags,
    kv_checked_at, scored_at.
    """
    log.info("signal.score_unscored: starting (batch_size=%d)", batch_size)

    scored = 0
    not_found = 0
    critical = 0
    errors = 0

    db = Session()
    try:
        rows = db.execute(text("""
            SELECT id, supplier_orgnr
            FROM signal_contracts
            WHERE supplier_orgnr IS NOT NULL AND kv_score IS NULL
            ORDER BY scraped_at DESC
            LIMIT :batch_size
        """), {"batch_size": batch_size}).fetchall()

        log.info("signal.score_unscored: %d candidates", len(rows))

        for row in rows:
            try:
                score_row = _lookup_score(db, row.supplier_orgnr)
                if score_row is None:
                    not_found += 1
                    continue

                score = BAND_TO_SCORE.get(int(score_row.risk_band))
                if score is None:
                    log.warning(
                        "signal.score_unscored: unknown risk_band=%s for %s",
                        score_row.risk_band, row.supplier_orgnr,
                    )
                    errors += 1
                    continue
                tier = score_to_tier(score)
                flags = _compute_flags(db, row.supplier_orgnr)

                db.execute(text("""
                    UPDATE signal_contracts
                    SET kv_score      = :score,
                        kv_tier       = :tier,
                        kv_flags      = CAST(:flags AS jsonb),
                        kv_checked_at = now(),
                        scored_at     = now()
                    WHERE id = :contract_id
                """), {
                    "score": score,
                    "tier":  tier,
                    "flags": json.dumps(flags),
                    "contract_id": row.id,
                })
                db.commit()

                scored += 1
                if tier == "CRITICAL":
                    critical += 1
            except Exception as exc:
                db.rollback()
                log.warning(
                    "signal.score_unscored: row %s (%s) failed: %s",
                    row.id, row.supplier_orgnr, exc,
                )
                errors += 1
                continue
    except Exception as exc:
        log.error("signal.score_unscored: DB failure: %s", exc, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        log.error("signal.score_unscored: retries exhausted, returning partial")
    finally:
        db.close()

    log.info(
        "signal.score_unscored: done scored=%d not_found=%d critical=%d errors=%d",
        scored, not_found, critical, errors,
    )
    return {
        "scored":    scored,
        "not_found": not_found,
        "critical":  critical,
        "errors":    errors,
    }


# ── Task: re-score active contracts and detect tier escalations ───────────────

@shared_task(
    name="signal.rescore_active",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def rescore_active(self) -> dict:
    """
    Re-score all suppliers holding active contracts. Active = contract_end >
    today OR contract_end IS NULL. Tier escalations are written to
    signal_delivery_log for audit (delivery_type='escalation_detected').
    """
    log.info("signal.rescore_active: starting")

    checked = 0
    escalations = 0
    de_escalations = 0
    errors = 0

    db = Session()
    try:
        rows = db.execute(text("""
            SELECT id, supplier_orgnr, supplier_name, municipality,
                   contract_value_sek, contract_end, kv_score, kv_tier
            FROM signal_contracts
            WHERE supplier_orgnr IS NOT NULL
              AND (contract_end > CURRENT_DATE OR contract_end IS NULL)
              AND (kv_checked_at IS NULL OR kv_checked_at < now() - INTERVAL '6 hours')
            ORDER BY contract_value_sek DESC NULLS LAST
            LIMIT 500
        """)).fetchall()

        log.info("signal.rescore_active: %d active contracts due", len(rows))

        for row in rows:
            try:
                prev_tier = row.kv_tier or "LOW"
                score_row = _lookup_score(db, row.supplier_orgnr)

                if score_row is None:
                    db.execute(text("""
                        UPDATE signal_contracts
                        SET kv_checked_at = now()
                        WHERE id = :contract_id
                    """), {"contract_id": row.id})
                    db.commit()
                    checked += 1
                    continue

                new_score = BAND_TO_SCORE.get(int(score_row.risk_band))
                if new_score is None:
                    log.warning(
                        "signal.rescore_active: unknown risk_band=%s for %s",
                        score_row.risk_band, row.supplier_orgnr,
                    )
                    errors += 1
                    continue
                new_tier = score_to_tier(new_score)
                flags = _compute_flags(db, row.supplier_orgnr)

                db.execute(text("""
                    UPDATE signal_contracts
                    SET kv_score      = :score,
                        kv_tier       = :tier,
                        kv_flags      = CAST(:flags AS jsonb),
                        kv_checked_at = now(),
                        scored_at     = now()
                    WHERE id = :contract_id
                """), {
                    "score": new_score,
                    "tier":  new_tier,
                    "flags": json.dumps(flags),
                    "contract_id": row.id,
                })
                checked += 1

                prev_idx = TIER_ORDER.index(prev_tier) if prev_tier in TIER_ORDER else 0
                new_idx  = TIER_ORDER.index(new_tier)

                if new_idx > prev_idx:
                    escalations += 1
                    db.execute(text("""
                        INSERT INTO signal_delivery_log
                            (subscription_id, contract_id, delivery_type,
                             http_status, error_message)
                        VALUES (
                            CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                            :contract_id, 'escalation_detected',
                            200, :msg
                        )
                    """), {
                        "contract_id": row.id,
                        "msg": (
                            f"{prev_tier} → {new_tier} | score={new_score} | "
                            f"{row.supplier_name} | {row.municipality}"
                        ),
                    })
                elif new_idx < prev_idx:
                    de_escalations += 1

                db.commit()
            except Exception as exc:
                db.rollback()
                log.warning(
                    "signal.rescore_active: row %s (%s) failed: %s",
                    row.id, row.supplier_orgnr, exc,
                )
                errors += 1
                continue
    except Exception as exc:
        log.error("signal.rescore_active: DB failure: %s", exc, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        log.error("signal.rescore_active: retries exhausted, returning partial")
    finally:
        db.close()

    log.info(
        "signal.rescore_active: done checked=%d escalations=%d "
        "de_escalations=%d errors=%d",
        checked, escalations, de_escalations, errors,
    )
    return {
        "checked":        checked,
        "escalations":    escalations,
        "de_escalations": de_escalations,
        "errors":         errors,
    }
