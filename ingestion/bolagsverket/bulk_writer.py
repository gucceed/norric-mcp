"""
Batched upsert writer for norric_entities.
On conflict on orgnr: updates mutable fields and last_seen_at.
After each batch, writes snapshots for ALL entities via the batched
snapshot API (2 round-trips per 500 entities instead of ~1000).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion.snapshots.writer import write_snapshots_batch

log = logging.getLogger(__name__)

BATCH_SIZE = 500


def upsert_entities(
    db: Session,
    records: Iterator[dict],
    run_id: UUID,
    snapshot_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    snap_date = snapshot_date or date.today()
    stats = {"inserted": 0, "updated": 0, "skipped": 0,
             "snapshots_inserted": 0, "snapshots_skipped": 0}

    batch: list[dict] = []

    def flush(batch: list[dict]) -> None:
        if not batch or dry_run:
            return

        values_sql = ", ".join(
            f"(:orgnr_{i}, :orgnr_display_{i}, :name_{i}, :orgform_{i}, "
            f":is_active_{i}, :deregistered_at_{i}, :street_{i}, :city_{i}, "
            f":postcode_{i}, :kommunkod_{i}, :county_{i}, :raw_address_{i})"
            for i in range(len(batch))
        )
        params: dict = {}
        for i, r in enumerate(batch):
            for k, v in r.items():
                params[f"{k}_{i}"] = v

        result = db.execute(
            text(f"""
                INSERT INTO norric_entities
                    (orgnr, orgnr_display, name, orgform, is_active,
                     deregistered_at, street, city, postcode, kommunkod,
                     county, raw_address)
                VALUES {values_sql}
                ON CONFLICT (orgnr) DO UPDATE SET
                    name            = EXCLUDED.name,
                    is_active       = EXCLUDED.is_active,
                    deregistered_at = EXCLUDED.deregistered_at,
                    street          = EXCLUDED.street,
                    city            = EXCLUDED.city,
                    postcode        = EXCLUDED.postcode,
                    kommunkod       = EXCLUDED.kommunkod,
                    last_seen_at    = now(),
                    last_updated_at = now()
                RETURNING orgnr, (xmax = 0) AS is_insert
            """),
            params,
        )

        for row in result:
            if row.is_insert:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1

        snap_stats = write_snapshots_batch(
            db=db,
            records=batch,
            entity_type="company",
            source="bolagsverket",
            snapshot_date=snap_date,
            pipeline_run_id=run_id,
            entity_id_key="orgnr",
        )
        stats["snapshots_inserted"] += snap_stats["inserted"]
        stats["snapshots_skipped"]  += snap_stats["skipped"]

        db.commit()

    for record in records:
        batch.append(record)
        if len(batch) >= BATCH_SIZE:
            flush(batch)
            log.info(
                "flushed batch: inserted=%d updated=%d snapshots=%d/skipped=%d",
                stats["inserted"], stats["updated"],
                stats["snapshots_inserted"], stats["snapshots_skipped"],
            )
            batch = []

    flush(batch)
    return stats
