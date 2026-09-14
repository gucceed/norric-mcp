"""
watch/worker.py — delivery with retry, dead-letter and auto-pause (spec §6).

    Attempts:   5 total - immediately, +1 min, +5 min, +30 min, +2 h.
    Delivered:  any 2xx. Everything else retries.
    Dead-letter: after the 5th failure, status='dead' (retrievable 30 days).
    Auto-pause: 50 consecutive failures on the watch flips it to 'paused'
                (store.record_delivery owns the counter) so one dead
                endpoint can't degrade the queue for everyone.

Ordering: per-orgnr best-effort - deliveries are claimed oldest-first, so
events for the same company go out in occurrence order within a run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import store
from .deliver import post_signed

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 1800, 7200]  # after failure of attempt 1..4
CLAIM_BATCH = 100


def next_attempt_delay(attempts_after_failure: int) -> timedelta | None:
    """
    Delay before the next attempt, given the attempt count after a failure.
    None means the event is exhausted (dead-letter).
    """
    if attempts_after_failure >= MAX_ATTEMPTS:
        return None
    return timedelta(seconds=BACKOFF_SECONDS[attempts_after_failure - 1])


def claim_due_events(db: Session, limit: int = CLAIM_BATCH) -> list:
    """Pending events whose time has come, on ACTIVE watches only."""
    return db.execute(
        text("""
            SELECT e.id, e.event_ref, e.event_type, e.attempts, e.payload,
                   w.watch_ref, w.callback_url, w.signing_secret
            FROM norric_watch_events e
            JOIN norric_watches w ON w.id = e.watch_id
            WHERE e.status = 'pending'
              AND e.next_attempt_at <= now()
              AND w.status = 'active'
            ORDER BY e.occurred_at ASC
            LIMIT :lim
            FOR UPDATE OF e SKIP LOCKED
        """),
        {"lim": limit},
    ).fetchall()


def deliver_pending(db: Session) -> dict:
    """One delivery sweep. Returns attempt/delivery/dead-letter counts."""
    rows = claim_due_events(db)
    attempted = delivered = dead = 0

    for r in rows:
        attempted += 1
        attempt_no = r.attempts + 1
        status, error = post_signed(
            r.callback_url, r.signing_secret, r.event_ref, r.event_type,
            r.payload, attempt=attempt_no,
        )
        ok = status is not None and 200 <= status < 300

        if ok:
            delivered += 1
            db.execute(
                text("""
                    UPDATE norric_watch_events
                    SET status = 'delivered', delivered_at = now(),
                        attempts = :n, last_http_status = :st, last_error = NULL
                    WHERE id = :id
                """),
                {"n": attempt_no, "st": status, "id": r.id},
            )
        else:
            delay = next_attempt_delay(attempt_no)
            if delay is None:
                dead += 1
                db.execute(
                    text("""
                        UPDATE norric_watch_events
                        SET status = 'dead', dead_at = now(),
                            attempts = :n, last_http_status = :st, last_error = :err
                        WHERE id = :id
                    """),
                    {"n": attempt_no, "st": status, "err": error, "id": r.id},
                )
            else:
                db.execute(
                    text("""
                        UPDATE norric_watch_events
                        SET attempts = :n, last_http_status = :st, last_error = :err,
                            next_attempt_at = :nxt
                        WHERE id = :id
                    """),
                    {
                        "n": attempt_no, "st": status, "err": error,
                        "nxt": datetime.now(timezone.utc) + delay, "id": r.id,
                    },
                )

        db.commit()  # per-event: one bad row must not poison the batch
        stats = store.record_delivery(db, r.watch_ref, ok)
        if stats["paused_now"]:
            log.warning(
                "watch %s auto-paused after %d consecutive failures",
                r.watch_ref, stats["consecutive_failures"],
            )

    return {
        "claimed": len(rows),
        "attempted": attempted,
        "delivered": delivered,
        "dead_lettered": dead,
        "retries_scheduled": attempted - delivered - dead,
    }
