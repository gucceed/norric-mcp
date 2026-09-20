"""
Nightly CVR reconciliation - Denmark country two.

The weekly bulk re-baseline is the true reconciliation. The nightly job is a
drift monitor, recorded as pipeline 'cvr_reconcile':

- event lag: DAF_RegisterImportStatus.lastSequenceNumber minus our checkpoint
  (a growing lag means the events consumer is falling behind)
- freshness: age of the newest norric_dk_entities.last_seen_at
- baseline age: days since the last successful cvr_bulk run

Findings land in the pipeline-run row and logs; nothing here mutates company
data.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.cvr import client

log = logging.getLogger(__name__)


def run_reconcile() -> dict:
    db = Session()
    try:
        with pipeline_run(db, "cvr_reconcile") as ctx:
            run_id = ctx["run_id"]
            status = client.fetch_register_import_status()
            remote_seq = int(status.get("lastSequenceNumber") or 0)

            row = db.execute(text("""
                SELECT s.last_sequence_number,
                       (SELECT MAX(e.last_seen_at) FROM norric_dk_entities e) AS last_seen,
                       (SELECT MAX(p.completed_at) FROM norric_pipeline_runs p
                         WHERE p.pipeline = 'cvr_bulk' AND p.status = 'success') AS last_bulk
                FROM norric_dk_ingest_state s WHERE s.id = 1
            """)).fetchone()

            local_seq = int(row.last_sequence_number or 0) if row else 0
            lag = max(remote_seq - local_seq, 0)
            report = {
                "remote_sequence": remote_seq,
                "local_sequence": local_seq,
                "event_lag": lag,
                "entities_last_seen": str(row.last_seen) if row else None,
                "last_bulk_success": str(row.last_bulk) if row else None,
            }
            ctx["rows_processed"] = 1
            if lag:
                log.warning("cvr reconcile: event lag %d (%s)", lag, report)
            else:
                log.info("cvr reconcile: in sync (%s)", report)

            db.execute(text(
                "UPDATE norric_dk_ingest_state SET last_reconcile_at = now(),"
                " updated_at = now() WHERE id = 1"))
            db.commit()
            return {**ctx, "run_id": str(run_id), **report}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_reconcile()
