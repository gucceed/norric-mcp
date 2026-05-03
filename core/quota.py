"""
Monthly quota enforcement for Free-tier API keys.

Quota is tracked at the organisation level (org_nr), not per key.
All keys under the same org_nr share one 50-call/month pool.

Quota: 50 calls/month. Resets on the 1st at 00:00 UTC.
State is persisted in the quota_usage table (T2_008, re-keyed in T2_010).

Call check_and_increment_quota() inside asyncio.to_thread() — it is synchronous.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text


_FREE_MONTHLY_LIMIT = 10


def _month_boundaries(now: datetime) -> tuple[datetime, datetime]:
    """Return (period_start, reset_at) for the month containing now."""
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period_start.month == 12:
        reset_at = period_start.replace(year=period_start.year + 1, month=1)
    else:
        reset_at = period_start.replace(month=period_start.month + 1)
    return period_start, reset_at


def check_and_increment_quota(org_nr: str) -> bool:
    """
    Returns True if the org's monthly quota has not been exhausted, and records the call.
    Returns False if the org has hit 50 calls for the current month.

    All keys under the same org_nr share this pool.
    Handles period reset automatically when reset_at has passed.
    Uses FOR UPDATE to be safe under concurrent requests.
    """
    from ingestion.db import Session

    now = datetime.now(timezone.utc)
    period_start, reset_at = _month_boundaries(now)

    db = Session()
    try:
        row = db.execute(
            text("SELECT call_count, reset_at FROM quota_usage WHERE org_nr = :o FOR UPDATE"),
            {"o": org_nr},
        ).fetchone()

        if row is None:
            db.execute(
                text("""
                    INSERT INTO quota_usage (org_nr, call_count, period_start, reset_at)
                    VALUES (:o, 1, :ps, :ra)
                """),
                {"o": org_nr, "ps": period_start, "ra": reset_at},
            )
            db.commit()
            return True

        stored_reset = row.reset_at
        if stored_reset.tzinfo is None:
            stored_reset = stored_reset.replace(tzinfo=timezone.utc)

        if now >= stored_reset:
            db.execute(
                text("""
                    UPDATE quota_usage
                    SET call_count=1, period_start=:ps, reset_at=:ra
                    WHERE org_nr=:o
                """),
                {"o": org_nr, "ps": period_start, "ra": reset_at},
            )
            db.commit()
            return True

        if row.call_count >= _FREE_MONTHLY_LIMIT:
            return False

        db.execute(
            text("UPDATE quota_usage SET call_count=call_count+1 WHERE org_nr=:o"),
            {"o": org_nr},
        )
        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
