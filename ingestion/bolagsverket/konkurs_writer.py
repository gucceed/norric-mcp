"""
Batched upsert writer for `norric_payment_signals` from konkurs records.

Upsert key: (orgnr, case_ref) — UNIQUE INDEX added by migration
2026_05_13_konkurs_signals.sql.

On conflict: update status_code, filed_at, resolved_at, is_active, raw_data.
Preserve created_at (already-default-NOT-NULL via column default).
"""
from __future__ import annotations

import json
import logging
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

BATCH_SIZE = 500


def upsert_konkurs_records(
    db: Session,
    records: Iterator[dict],
    run_id: UUID,
    dry_run: bool = False,
) -> dict:
    """
    Stream records into norric_payment_signals. Returns stats dict.
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    batch: list[dict] = []

    def flush(batch: list[dict]) -> None:
        if not batch or dry_run:
            return

        values_sql = ", ".join(
            f"(:orgnr_{i}, :case_ref_{i}, :creditor_type_{i}, :filed_at_{i}, "
            f":resolved_at_{i}, :is_active_{i}, :status_code_{i}, "
            f":raw_data_{i}, :source_run_id_{i})"
            for i in range(len(batch))
        )
        params: dict = {}
        for i, r in enumerate(batch):
            params[f"orgnr_{i}"]         = r["orgnr"]
            params[f"case_ref_{i}"]      = r["case_ref"]
            params[f"creditor_type_{i}"] = r["raw_data"]["creditor_type"]
            params[f"filed_at_{i}"]      = r["filed_at"]
            params[f"resolved_at_{i}"]   = r["resolved_at"]
            params[f"is_active_{i}"]     = r["is_active"]
            params[f"status_code_{i}"]   = r["status_code"]
            params[f"raw_data_{i}"]      = json.dumps(r["raw_data"], ensure_ascii=False)
            params[f"source_run_id_{i}"] = str(run_id)

        result = db.execute(
            text(f"""
                INSERT INTO norric_payment_signals
                    (orgnr, case_ref, creditor_type, filed_at, resolved_at,
                     is_active, status_code, raw_data, source_run_id)
                VALUES {values_sql}
                ON CONFLICT (orgnr, case_ref) DO UPDATE SET
                    creditor_type = EXCLUDED.creditor_type,
                    filed_at      = EXCLUDED.filed_at,
                    resolved_at   = EXCLUDED.resolved_at,
                    is_active     = EXCLUDED.is_active,
                    status_code   = EXCLUDED.status_code,
                    raw_data      = EXCLUDED.raw_data,
                    source_run_id = EXCLUDED.source_run_id
                RETURNING (xmax = 0) AS is_insert
            """),
            params,
        )

        for row in result:
            if row.is_insert:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1

        db.commit()

    for record in records:
        batch.append(record)
        if len(batch) >= BATCH_SIZE:
            flush(batch)
            log.info(
                "konkurs flush: inserted=%d updated=%d",
                stats["inserted"], stats["updated"],
            )
            batch = []

    flush(batch)
    return stats
