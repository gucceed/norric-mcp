"""
watch/tasks.py — Celery tasks for Norric Watch (registered in celeryapp).

    watch.diff_emit        daily 05:45, after the 05:30 portfolio rescore:
                           detect changes for active watches, write events
    watch.deliver_pending  every minute: signed delivery sweep with
                           retry/backoff, dead-letter and auto-pause

Both run on the kreditvakt queue beside the scoring worker (celeryconfig).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _get_db():
    from ingestion.db import Session
    return Session()


def diff_emit() -> dict:
    from ingestion.pipeline_run import pipeline_run
    from .diff import emit_diff_events

    db = _get_db()
    try:
        with pipeline_run(db, "watch_diff") as ctx:
            result = emit_diff_events(db, ctx["run_id"])
            ctx["rows_processed"] = result["orgnrs"]
            ctx["rows_inserted"] = result["emitted"]
            ctx["rows_skipped"] = result["deduped"]
        log.info("watch diff: %s", result)
        return result
    finally:
        db.close()


def deliver_pending_sweep() -> dict:
    from .worker import deliver_pending

    db = _get_db()
    try:
        result = deliver_pending(db)
        if result["attempted"]:
            log.info("watch delivery: %s", result)
        return result
    finally:
        db.close()


def register_tasks(celery_app):
    """Register watch tasks with the Celery app (mirrors kreditvakt.tasks)."""

    @celery_app.task(name="watch.diff_emit", bind=True, max_retries=1)
    def _diff_emit_task(self) -> dict:
        try:
            return diff_emit()
        except Exception as exc:
            log.error("watch.diff_emit failed: %s", exc)
            raise self.retry(exc=exc)

    @celery_app.task(name="watch.deliver_pending")
    def _deliver_pending_task() -> dict:
        return deliver_pending_sweep()

    return _diff_emit_task, _deliver_pending_task
