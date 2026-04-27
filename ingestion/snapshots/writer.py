"""
Norric snapshot writer — used by ALL ingestion pipelines.

Computes sha256 of entity state, diffs against prior snapshot, and
only inserts when data has changed. Idempotent — safe to call twice.
"""
import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def _checksum(data: dict) -> str:
    serialised = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _compute_diff(prev: dict, curr: dict) -> dict:
    diff = {}
    for k in set(prev) | set(curr):
        old, new = prev.get(k), curr.get(k)
        if old != new:
            diff[k] = {"from": old, "to": new}
    return diff


def write_snapshot(
    db: Session,
    entity_id: str,
    entity_type: str,
    source: str,
    snapshot_date: date,
    data: dict,
    pipeline_run_id: UUID | None = None,
) -> str:
    """Insert snapshot if data changed since last write. Returns 'inserted' | 'skipped'."""
    checksum = _checksum(data)

    prev_row = db.execute(
        text("""
            SELECT data, checksum FROM norric_snapshots
            WHERE entity_id = :eid AND source = :src
            ORDER BY snapshot_date DESC
            LIMIT 1
        """),
        {"eid": entity_id, "src": source},
    ).fetchone()

    if prev_row and prev_row.checksum == checksum:
        return "skipped"

    diff = _compute_diff(dict(prev_row.data) if prev_row else {}, data) if prev_row else None

    db.execute(
        text("""
            INSERT INTO norric_snapshots
                (entity_id, entity_type, source, pipeline_run_id,
                 snapshot_date, data, diff_from_prev, checksum)
            VALUES
                (:eid, :etype, :src, :run_id,
                 :snap_date, :data::jsonb, :diff::jsonb, :checksum)
            ON CONFLICT (entity_id, source, snapshot_date, checksum) DO NOTHING
        """),
        {
            "eid": entity_id,
            "etype": entity_type,
            "src": source,
            "run_id": str(pipeline_run_id) if pipeline_run_id else None,
            "snap_date": snapshot_date,
            "data": json.dumps(data, default=str),
            "diff": json.dumps(diff, default=str) if diff else None,
            "checksum": checksum,
        },
    )
    return "inserted"
