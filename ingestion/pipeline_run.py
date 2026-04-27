"""
Context manager that records norric_pipeline_runs rows.
All T1 pipelines use this for telemetry + data freshness reporting.
"""
import traceback
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


@contextmanager
def pipeline_run(db: Session, pipeline: str):
    """
    Yields a run_id (uuid str). On exit, marks the run success or failed.

    Usage:
        with pipeline_run(db, "bolagsverket_bulk") as ctx:
            ctx["rows_processed"] += 1
    """
    row = db.execute(
        text("""
            INSERT INTO norric_pipeline_runs (pipeline, status)
            VALUES (:pipeline, 'running')
            RETURNING id
        """),
        {"pipeline": pipeline},
    ).fetchone()
    db.commit()

    run_id: UUID = row.id
    ctx = {
        "run_id": run_id,
        "rows_processed": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
    }

    try:
        yield ctx
        db.execute(
            text("""
                UPDATE norric_pipeline_runs
                SET status = 'success',
                    completed_at = now(),
                    rows_processed = :rp,
                    rows_inserted  = :ri,
                    rows_updated   = :ru,
                    rows_skipped   = :rs
                WHERE id = :id
            """),
            {
                "rp": ctx["rows_processed"],
                "ri": ctx["rows_inserted"],
                "ru": ctx["rows_updated"],
                "rs": ctx["rows_skipped"],
                "id": run_id,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        db.execute(
            text("""
                UPDATE norric_pipeline_runs
                SET status = 'failed',
                    completed_at = now(),
                    error_message = :err,
                    rows_processed = :rp
                WHERE id = :id
            """),
            {
                "err": traceback.format_exc()[:4000],
                "rp": ctx["rows_processed"],
                "id": run_id,
            },
        )
        db.commit()
        raise
