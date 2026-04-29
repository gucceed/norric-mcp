"""
kreditvakt/tasks.py

Kreditvakt Celery tasks:
  score_single(orgnr)              — on-demand scoring for one company
  score_portfolio(orgnr_list)      — batch scoring
  send_daily_briefing()            — Telegram briefing at 07:00 CET for Band 4/5 companies
"""

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

def score_portfolio(orgnr_list: list[str]) -> dict:
    """Score a list of companies. Returns summary dict."""
    from scoring.kreditvakt import score_from_db, write_score

    db = _get_db()
    results = []
    errors = []

    try:
        for orgnr in orgnr_list:
            try:
                result = score_from_db(db, orgnr)
                write_score(db, result)
                results.append({
                    "orgnr": orgnr,
                    "risk_band": result["risk_band"],
                    "distress_probability": result["distress_probability"],
                })
            except Exception as e:
                log.error(f"[{orgnr}] portfolio scoring failed: {e}", exc_info=True)
                errors.append({"orgnr": orgnr, "error": str(e)})
    finally:
        db.close()

    return {
        "scored": len(results),
        "errors": len(errors),
        "error_detail": errors,
        "results": results,
    }


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
    def _score_portfolio_task(self, orgnr_list: list[str]) -> dict:
        try:
            return score_portfolio(orgnr_list)
        except Exception as exc:
            log.error(f"score_portfolio failed: {exc}")
            raise self.retry(exc=exc)

    @celery_app.task(name="kreditvakt.tasks.send_daily_briefing")
    def _briefing_task() -> dict:
        return send_daily_briefing()

    return _score_single_task, _score_portfolio_task, _briefing_task
