"""
Single source of truth for per-source ingestion status.

/health, norric_status_v1 and norric_data_freshness_v1 all report from
norric_pipeline_runs, so they cannot contradict each other.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# pipeline name (or prefix ending in "*") -> source agency id
PIPELINE_AGENCY = {
    "bolagsverket_bulk": "bolagsverket",
    "bolagsverket_konkurs": "bolagsverket",
    "kronofogden_betalning": "kronofogden",
    "skatteverket_restanslangd": "skatteverket",
    "lantmateriet_open": "lantmateriet",
    "boverket_*": "boverket",
    "klimatklivet": "boverket",
    "scb_*": "scb",
}

_SQL = """
    SELECT pipeline, MAX(completed_at) AS last_success, COUNT(*) AS success_runs
    FROM norric_pipeline_runs
    WHERE status = 'success'
    GROUP BY pipeline
"""


def agency_for_pipeline(pipeline: str) -> Optional[str]:
    if pipeline in PIPELINE_AGENCY:
        return PIPELINE_AGENCY[pipeline]
    for key, agency in PIPELINE_AGENCY.items():
        if key.endswith("*") and pipeline.startswith(key[:-1]):
            return agency
    return None


def summarize(rows, now: Optional[datetime] = None) -> dict:
    """rows: iterable of (pipeline, last_success, success_runs).
    Returns {agency_id: {last_success, success_runs}} using the newest
    success across that agency's pipelines. Unmapped pipelines are ignored."""
    out: dict = {}
    for pipeline, last_success, runs in rows:
        agency = agency_for_pipeline(pipeline)
        if agency is None or last_success is None:
            continue
        cur = out.get(agency)
        if cur is None:
            out[agency] = {"last_success": last_success, "success_runs": int(runs or 0)}
        else:
            cur["success_runs"] += int(runs or 0)
            if last_success > cur["last_success"]:
                cur["last_success"] = last_success
    return out


def load_agency_status() -> Optional[dict]:
    """Query norric_pipeline_runs. Returns None if the DB is unreachable
    (callers must say "unknown", never "stale" or "live", in that case)."""
    try:
        from ingestion.db import Session
        from sqlalchemy import text

        db = Session()
        try:
            rows = db.execute(text(_SQL)).fetchall()
            return summarize((r.pipeline, r.last_success, r.success_runs) for r in rows)
        finally:
            db.close()
    except Exception:
        return None


def age_days(last_success: datetime, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    return (now - last_success).days
