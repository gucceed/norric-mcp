"""
Kronofogden payment signals writer.

Cases are at the individual level — one entity may have many.
Reconciliation by case_ref (if available) or orgnr+filed_at composite.
"""
import logging
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion.snapshots.writer import write_snapshot

log = logging.getLogger(__name__)


def write_payment_cases(
    db: Session,
    cases: list[dict],
    run_id: UUID,
) -> dict:
    stats = {"inserted": 0, "updated": 0}
    snap_date = date.today()

    for case in cases:
        orgnr = case["orgnr"]
        case_ref = case.get("case_ref")
        filed_at = case.get("filed_at")

        # Check for existing case
        existing = None
        if case_ref:
            existing = db.execute(
                text("SELECT id FROM norric_payment_signals WHERE orgnr=:o AND case_ref=:c LIMIT 1"),
                {"o": orgnr, "c": case_ref},
            ).fetchone()
        elif filed_at:
            existing = db.execute(
                text("SELECT id FROM norric_payment_signals WHERE orgnr=:o AND filed_at=:f LIMIT 1"),
                {"o": orgnr, "f": filed_at},
            ).fetchone()

        if existing:
            stats["updated"] += 1
            continue

        db.execute(
            text("""
                INSERT INTO norric_payment_signals
                    (orgnr, case_ref, creditor_type, claim_amount_sek,
                     filed_at, source_run_id, raw_data)
                VALUES
                    (:orgnr, :case_ref, :creditor_type, :amount,
                     :filed_at, :run_id, :raw::jsonb)
                ON CONFLICT DO NOTHING
            """),
            {
                "orgnr":        orgnr,
                "case_ref":     case_ref,
                "creditor_type": case.get("creditor_type"),
                "amount":       case.get("claim_amount_sek"),
                "filed_at":     filed_at,
                "run_id":       str(run_id),
                "raw":          str(case),
            },
        )
        stats["inserted"] += 1

        write_snapshot(
            db=db,
            entity_id=orgnr,
            entity_type="company",
            source="kronofogden",
            snapshot_date=snap_date,
            data={
                "orgnr": orgnr,
                "case_ref": case_ref,
                "filed_at": str(filed_at) if filed_at else None,
                "claim_amount_sek": case.get("claim_amount_sek"),
                "creditor_type": case.get("creditor_type"),
            },
            pipeline_run_id=run_id,
        )

    db.commit()
    log.info("kronofogden cases written: %s", stats)
    return stats
