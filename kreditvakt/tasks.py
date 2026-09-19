"""
kreditvakt/tasks.py

Kreditvakt Celery tasks:
  score_single(orgnr)              — on-demand scoring for one company
  score_portfolio(orgnr_list)      — batch scoring
  send_daily_briefing()            — Telegram briefing at 07:00 CET for Band 4/5 companies
"""

from __future__ import annotations

import logging
import os
from datetime import date

log = logging.getLogger(__name__)


def _get_celery():
    from celeryapp import app
    return app


def _get_db():
    from ingestion.db import Session
    return Session()


# ── Task: score one company ────────────────────────────────────────────────────

def score_single(orgnr: str) -> dict:
    """Score a single company and persist the result. Safe to call repeatedly (idempotent)."""
    from scoring.kreditvakt import score_from_db, write_score

    db = _get_db()
    try:
        result = score_from_db(db, orgnr)
        # Only persist real scores. A no_signals result carries null risk_*
        # fields, which violate company_scores' NOT NULL constraints on
        # distress_probability / risk_band / insolvency_score — no score to
        # cache, nothing to persist (same rule as kreditvakt/api.py).
        if result.get("score_source") == "live":
            write_score(db, result)
        return {
            "orgnr": orgnr,
            "risk_band": result["risk_band"],
            "distress_probability": result["distress_probability"],
            "score_source": result["score_source"],
        }
    except Exception as e:
        log.error(f"[{orgnr}] score_single failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


# ── Task: batch score portfolio ────────────────────────────────────────────────

def score_portfolio(
    orgnr_list: list[str] | None = None,
    incremental: bool = False,
    stale_days: int = 7,
) -> dict:
    """Score a batch of companies and record a norric_pipeline_runs row.

    When ``orgnr_list`` is empty/None the universe is loaded from the DB:

    * ``incremental=False`` — the full signal-bearing universe (~29k orgnrs).
      This is the old nightly behaviour and stays available for manual runs.
    * ``incremental=True`` — only orgnrs that plausibly need a new score:
      signals created since the last successful run, plus any score older
      than ``stale_days`` (the decay sweep), plus signal-bearing orgnrs with
      no score row at all. This is what the nightly beat now passes; it cuts
      the 05:30 full-universe rescore down to the actually-changed set, which
      is the main lever on the overnight disk-IO burst.

    In-place signal updates (e.g. konkurs ON CONFLICT upserts) do not bump
    ``created_at``; the ``stale_days`` sweep is the net that re-scores those
    companies within a week.
    """
    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.pipeline_run import pipeline_run

    db = _get_db()
    results = []
    errors = []
    no_signals = 0

    try:
        if not orgnr_list:
            if incremental:
                try:
                    orgnr_list = _incremental_orgnrs(db, stale_days=stale_days)
                except Exception as e:
                    # A failed universe query must not kill the nightly rescore.
                    # Fall back to the full signal-bearing universe (the old
                    # nightly behaviour) — more IO for one night, no missed scores.
                    db.rollback()
                    log.error(
                        "score_portfolio: incremental universe failed (%s) — falling back to full",
                        e,
                    )
                    orgnr_list = _signal_bearing_orgnrs(db)
                log.info(
                    "score_portfolio: incremental -> scoring %d changed/stale orgnrs",
                    len(orgnr_list),
                )
            else:
                orgnr_list = _signal_bearing_orgnrs(db)
                log.info(
                    "score_portfolio: empty list -> scoring %d signal-bearing orgnrs",
                    len(orgnr_list),
                )

        with pipeline_run(db, "kreditvakt_score_portfolio") as ctx:
            for orgnr in orgnr_list:
                try:
                    result = score_from_db(db, orgnr)
                    # Persist only real scores (see score_single). Orgnrs whose
                    # signals have all decayed out of the live windows score as
                    # no_signals and must not be written to company_scores.
                    if result.get("score_source") == "live":
                        write_score(db, result)
                        results.append({
                            "orgnr": orgnr,
                            "risk_band": result["risk_band"],
                            "distress_probability": result["distress_probability"],
                        })
                    else:
                        no_signals += 1
                except Exception as e:
                    # Roll back so one failing company doesn't leave the
                    # transaction aborted and poison every later statement in
                    # the run (the InFailedSqlTransaction cascade).
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    log.error(f"[{orgnr}] portfolio scoring failed: {e}", exc_info=True)
                    errors.append({"orgnr": orgnr, "error": str(e)})
            if no_signals:
                log.info(
                    "score_portfolio: %d orgnrs scored no_signals — not persisted",
                    no_signals,
                )
            ctx["rows_processed"] = len(orgnr_list)
            ctx["rows_updated"] = len(results)
            ctx["rows_skipped"] = len(errors) + no_signals
    finally:
        db.close()

    return {
        "scored": len(results),
        "no_signals": no_signals,
        "errors": len(errors),
        "error_detail": errors[:50],
        "results": results,
    }


def _signal_bearing_orgnrs(db) -> list[str]:
    """Scoring universe when no explicit list is given: every orgnr with at
    least one payment/konkurs signal (or an active tax signal). The scorer only
    emits 'live' for companies that have signals, so this set (~29k) gives full
    meaningful coverage without writing ~885k 'no_signals' rows."""
    from sqlalchemy import text

    orgnrs: set[str] = set()
    rows = db.execute(text("SELECT DISTINCT orgnr FROM norric_payment_signals")).fetchall()
    orgnrs.update(r[0] for r in rows if r[0])
    try:
        trows = db.execute(
            text("SELECT DISTINCT orgnr FROM norric_tax_signals WHERE is_active = true")
        ).fetchall()
        orgnrs.update(r[0] for r in trows if r[0])
    except Exception:
        db.rollback()  # tax table empty/unavailable — payment signals suffice
    return sorted(orgnrs)


# ── Task: Telegram daily briefing ─────────────────────────────────────────────

def send_daily_briefing() -> dict:
    """
    Fetch all companies at Band 4 or 5, format a Swedish Telegram message, send it.
    Graceful no-op if no companies at elevated risk or env vars not set.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping briefing")
        return {"status": "skipped", "reason": "env_vars_missing"}

    db = _get_db()
    try:
        from sqlalchemy import text
        rows = db.execute(
            text("""
                SELECT cs.orgnr, cs.risk_band, cs.distress_probability,
                       cs.insolvency_score, cs.signals,
                       ne.name AS company_name
                FROM company_scores cs
                LEFT JOIN norric_entities ne ON ne.orgnr = cs.orgnr
                WHERE cs.risk_band >= 4
                ORDER BY cs.risk_band DESC, cs.distress_probability DESC
                LIMIT 50
            """)
        ).fetchall()
    finally:
        db.close()

    if not rows:
        log.info("Daily briefing: no companies at Band 4/5 — no message sent")
        return {"status": "no_op", "reason": "no_high_risk_companies"}

    today = date.today().strftime("%Y-%m-%d")
    lines = [
        f"🔴 *Norric Kreditvakt — Daglig briefing*",
        f"{today}",
        "",
        f"_{len(rows)} bolag med förhöjd risk:_",
        "",
    ]

    import json

    for row in rows:
        name = row.company_name or row.orgnr
        band = row.risk_band
        signals = row.signals if isinstance(row.signals, list) else json.loads(row.signals or "[]")
        signal_summary = _format_signal_summary(row.orgnr, row.insolvency_score, signals)
        lines.append(f"• *{name}* ({row.orgnr}) — Band {band}")
        if signal_summary:
            lines.append(f"  ↑ {signal_summary}")
        lines.append("")

    message = "\n".join(lines)

    import httpx
    resp = httpx.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        },
        timeout=10,
    )

    if resp.status_code != 200:
        log.error(f"Telegram send failed: {resp.status_code} {resp.text}")
        return {"status": "error", "telegram_status": resp.status_code}

    log.info(f"Daily briefing sent: {len(rows)} companies at Band 4/5")
    return {"status": "sent", "companies_included": len(rows)}


def _format_signal_summary(orgnr: str, score: int, signals: list) -> str:
    """Build a short Swedish signal summary from the signals list."""
    parts = []
    for s in signals[:3]:
        key = s.get("key", "")
        value = s.get("value")
        if key == "skatteverket_flag" and value:
            parts.append(f"Skatteverket skuld {value:,} kr".replace(",", "\u00a0"))
        elif key == "kronofogden_count":
            parts.append(f"Kronofogden {value}× senaste 90 dagar")
        elif key == "konkurs_petition":
            parts.append("Konkursansökan registrerad")
    return " + ".join(parts) if parts else f"Insolvenspoäng: {score}"


# ── Celery task wrappers (registered in celeryapp) ────────────────────────────

def register_tasks(celery_app):
    """Register all kreditvakt tasks with the Celery app."""

    @celery_app.task(
        name="kreditvakt.tasks.score_single",
        bind=True,
        max_retries=2,
        default_retry_delay=30,
    )
    def _score_single_task(self, orgnr: str) -> dict:
        try:
            return score_single(orgnr)
        except Exception as exc:
            log.error(f"[{orgnr}] score_single_task failed: {exc}")
            raise self.retry(exc=exc)

    @celery_app.task(
        name="kreditvakt.tasks.score_portfolio",
        bind=True,
        max_retries=1,
    )
    def _score_portfolio_task(
        self,
        orgnr_list: list[str],
        incremental: bool = False,
        stale_days: int = 7,
    ) -> dict:
        try:
            return score_portfolio(
                orgnr_list, incremental=incremental, stale_days=stale_days
            )
        except Exception as exc:
            log.error(f"score_portfolio failed: {exc}")
            raise self.retry(exc=exc)

    @celery_app.task(name="kreditvakt.tasks.send_daily_briefing")
    def _briefing_task() -> dict:
        return send_daily_briefing()

    return _score_single_task, _score_portfolio_task, _briefing_task


def _incremental_orgnrs(db, stale_days: int = 7) -> list[str]:
    """Universe for the nightly incremental rescore.

    Three buckets, UNIONed:

    1. changed  — orgnrs with payment/konkurs or active tax signals created
       since the last successful ``kreditvakt_score_portfolio`` run (fallback
       window: 36h, so a missed day does not silently drop changes).
    2. stale    — orgnrs whose company_scores row is older than ``stale_days``.
       Signal scores decay over time windows, so scores must be refreshed even
       when nothing new was ingested; this spreads that refresh over a week
       instead of one nightly burst. It also catches in-place signal updates
       (konkurs upserts) that bucket 1 cannot see.
    3. unscored — signal-bearing orgnrs with no company_scores row at all.
    """
    from sqlalchemy import text

    rows = db.execute(
        text("""
            WITH last_run AS (
                SELECT completed_at
                FROM norric_pipeline_runs
                WHERE pipeline = 'kreditvakt_score_portfolio'
                  AND status = 'success'
                  AND completed_at IS NOT NULL
                ORDER BY completed_at DESC
                LIMIT 1
            ),
            changed AS (
                SELECT DISTINCT orgnr FROM norric_payment_signals
                WHERE created_at >= COALESCE(
                    (SELECT completed_at FROM last_run), now() - interval '36 hours')
                UNION
                SELECT DISTINCT orgnr FROM norric_tax_signals
                WHERE is_active = true
                  AND created_at >= COALESCE(
                    (SELECT completed_at FROM last_run), now() - interval '36 hours')
            ),
            stale AS (
                SELECT orgnr FROM company_scores
                WHERE updated_at < now() - make_interval(days => :stale_days)
            ),
            unscored AS (
                SELECT DISTINCT p.orgnr FROM norric_payment_signals p
                WHERE NOT EXISTS (
                    SELECT 1 FROM company_scores cs WHERE cs.orgnr = p.orgnr)
                UNION
                SELECT DISTINCT t.orgnr FROM norric_tax_signals t
                WHERE t.is_active = true
                  AND NOT EXISTS (
                    SELECT 1 FROM company_scores cs WHERE cs.orgnr = t.orgnr)
            )
            SELECT orgnr FROM changed
            UNION
            SELECT orgnr FROM stale
            UNION
            SELECT orgnr FROM unscored
        """),
        {"stale_days": stale_days},
    ).fetchall()
    return sorted(r[0] for r in rows if r[0])
