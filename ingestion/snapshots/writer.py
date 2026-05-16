"""Norric snapshot writer — used by ALL ingestion pipelines.

Two APIs:

  write_snapshot()         per-row. Small-volume ingestors (Skatteverket
                           restanslängd, Kronofogden, vigil). 1 SELECT +
                           up to 1 INSERT per call.

  write_snapshots_batch()  bulk-volume. Bolagsverket bulk (~700k–900k rows).
                           1 multi-row SELECT for prior checksums, Python-side
                           diff/checksum, 1 multi-row INSERT for changed rows.
                           2 round-trips per batch vs ~2N for the per-row API.

Both honour:
  - Skip-on-unchanged-checksum (idempotency).
  - ON CONFLICT (entity_id, source, snapshot_date, checksum) DO NOTHING
    (dedupe via the UNIQUE INDEX idx_snapshots_dedup).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Iterable, Sequence
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


def write_snapshots_batch(
    db: Session,
    records: Sequence[dict],
    *,
    entity_type: str,
    source: str,
    snapshot_date: date,
    pipeline_run_id: UUID | None = None,
    entity_id_key: str = "orgnr",
) -> dict:
    """Bulk-write snapshots in 2 round-trips per call.

    records: sequence of dicts. Each is the entity payload AND must contain
             entity_id_key (default 'orgnr') used as norric_snapshots.entity_id.

    Returns {'inserted': N, 'skipped': M}. Skipped = checksum unchanged since
    last snapshot for that entity from this source.
    """
    if not records:
        return {"inserted": 0, "skipped": 0}

    entity_ids = [r[entity_id_key] for r in records]

    # Round-trip 1: pull all prior checksums + data for these entities in one query.
    prior_rows = db.execute(
        text("""
            SELECT DISTINCT ON (entity_id)
                entity_id, checksum, data
            FROM norric_snapshots
            WHERE source = :src
              AND entity_id = ANY(:ids)
            ORDER BY entity_id, snapshot_date DESC
        """),
        {"src": source, "ids": entity_ids},
    ).fetchall()
    prior_map: dict[str, tuple[str, dict]] = {
        r.entity_id: (r.checksum, dict(r.data) if r.data else {})
        for r in prior_rows
    }

    # Compute checksums in Python; filter to changed rows only.
    inserts: list[dict] = []
    skipped = 0
    for rec in records:
        eid = rec[entity_id_key]
        cs = _checksum(rec)
        prior = prior_map.get(eid)
        if prior and prior[0] == cs:
            skipped += 1
            continue
        diff = _compute_diff(prior[1], rec) if prior else None
        inserts.append({
            "eid":      eid,
            "data":     json.dumps(rec, default=str),
            "diff":     json.dumps(diff, default=str) if diff else None,
            "checksum": cs,
        })

    if not inserts:
        return {"inserted": 0, "skipped": skipped}

    # Round-trip 2: one multi-row INSERT.
    values_sql = ", ".join(
        f"(:eid_{i}, :etype, :src, :run_id, :snap_date, "
        f"CAST(:data_{i} AS jsonb), CAST(:diff_{i} AS jsonb), :checksum_{i})"
        for i in range(len(inserts))
    )
    params: dict = {
        "etype":    entity_type,
        "src":      source,
        "run_id":   str(pipeline_run_id) if pipeline_run_id else None,
        "snap_date": snapshot_date,
    }
    for i, r in enumerate(inserts):
        params[f"eid_{i}"]      = r["eid"]
        params[f"data_{i}"]     = r["data"]
        params[f"diff_{i}"]     = r["diff"]
        params[f"checksum_{i}"] = r["checksum"]

    db.execute(
        text(f"""
            INSERT INTO norric_snapshots
                (entity_id, entity_type, source, pipeline_run_id,
                 snapshot_date, data, diff_from_prev, checksum)
            VALUES {values_sql}
            ON CONFLICT (entity_id, source, snapshot_date, checksum) DO NOTHING
        """),
        params,
    )
    return {"inserted": len(inserts), "skipped": skipped}
