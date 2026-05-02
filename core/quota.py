"""
Monthly quota enforcement for Free-tier API keys.

Quota: 50 calls/month. Resets on the 1st at 00:00 UTC.
State is persisted in the quota_usage table (T2_008).

Call check_and_increment_quota() inside asyncio.to_thread() — it is synchronous.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text


_FREE_MONTHLY_LIMIT = 50


def _month_boundaries(now: datetime) -> tuple[datetime, datetime]:
    """Return (period_start, reset_at) for the month containing now."""
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period_start.month == 12:
        reset_at = period_start.replace(year=period_start.year + 1, month=1)
    else:
        reset_at = period_start.replace(month=period_start.month + 1)
    return period_start, reset_at


def check_and_increment_quota(key_hash: str) -> bool:
    """
    Returns True if the call is within the monthly quota and records it.
    Returns False if the caller has hit 50 calls for the current month.

    Handles period reset automatically when reset_at has passed.
    Uses FOR UPDATE to be safe under concurrent requests.
    """
    from ingestion.db import Session

    now = datetime.now(timezone.utc)
    period_start, reset_at = _month_boundaries(now)

    db = Session()
    try:
        row = db.execute(
            text("SELECT call_count, reset_at FROM quota_usage WHERE key_hash = :h FOR UPDATE"),
            {"h": key_hash},
        ).fetchone()

        if row is None:
            db.execute(
                text("""
                    INSERT INTO quota_usage (key_hash, call_count, period_start, reset_at)
                    VALUES (:h, 1, :ps, :ra)
                """),
                {"h": key_hash, "ps": period_start, "ra": reset_at},
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
                    WHERE key_hash=:h
                """),
                {"h": key_hash, "ps": period_start, "ra": reset_at},
            )
            db.commit()
            return True

        if row.call_count >= _FREE_MONTHLY_LIMIT:
            return False

        db.execute(
            text("UPDATE quota_usage SET call_count=call_count+1 WHERE key_hash=:h"),
            {"h": key_hash},
        )
        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
