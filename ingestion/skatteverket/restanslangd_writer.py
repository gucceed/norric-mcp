"""
Reconciliation writer for norric_tax_signals.

Each run:
1. Fetch active DB set
2. Fetch scraped set
3. INSERT new entries
4. UPDATE persisting entries (last_seen_at, amount_sek)
5. RESOLVE disappeared entries (is_active=false, resolved_at=now())

Idempotent — running twice has the same effect as running once.
"""
import logging
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion.snapshots.writer import write_snapshot

log = logging.getLogger(__name__)


def reconcile_restanslangd(
    db: Session,
    scraped: list[dict],
    run_id: UUID,
) -> dict:
    stats = {"inserted": 0, "updated": 0, "resolved": 0}
    snap_date = date.today()

    active_rows = db.execute(
        text("""
            SELECT orgnr, amount_sek FROM norric_tax_signals
            WHERE is_active = true AND signal_type = 'restanslangd'
        """)
    ).fetchall()
    active_db: dict[str, int | None] = {r.orgnr: r.amount_sek for r in active_rows}
    scraped_map: dict[str, dict] = {r["orgnr"]: r for r in scraped}

    # New entries
    for orgnr, entry in scraped_map.items():
        if orgnr not in active_db:
            db.execute(
                text("""
                    INSERT INTO norric_tax_signals
                        (orgnr, signal_type, amount_sek, source_run_id, raw_data)
                    VALUES
                        (:orgnr, 'restanslangd', :amount, :run_id, :raw::jsonb)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "orgnr": orgnr,
                    "amount": entry.get("amount_sek"),
                    "run_id": str(run_id),
                    "raw": str(entry),
                },
            )
            stats["inserted"] += 1

    # Persisting entries — update last_seen_at + amount
    for orgnr in set(active_db) & set(scraped_map):
        entry = scraped_map[orgnr]
        db.execute(
            text("""
                UPDATE norric_tax_signals
                SET last_seen_at = now(),
                    amount_sek   = :amount
                WHERE orgnr = :orgnr AND is_active = true AND signal_type = 'restanslangd'
            """),
            {"orgnr": orgnr, "amount": entry.get("amount_sek")},
        )
        stats["updated"] += 1

    # Resolved entries — disappeared from register
    for orgnr in set(active_db) - set(scraped_map):
        db.execute(
            text("""
                UPDATE norric_tax_signals
                SET is_active  = false,
                    resolved_at = now()
                WHERE orgnr = :orgnr AND is_active = true AND signal_type = 'restanslangd'
            """),
            {"orgnr": orgnr},
        )
        stats["resolved"] += 1
        write_snapshot(
            db=db,
            entity_id=orgnr,
            entity_type="company",
            source="skatteverket",
            snapshot_date=snap_date,
            data={"orgnr": orgnr, "restanslangd_resolved": True},
            pipeline_run_id=run_id,
        )

    # Snapshot active entries
    for orgnr, entry in scraped_map.items():
        write_snapshot(
            db=db,
            entity_id=orgnr,
            entity_type="company",
            source="skatteverket",
            snapshot_date=snap_date,
            data={"orgnr": orgnr, "amount_sek": entry.get("amount_sek"), "is_active": True},
            pipeline_run_id=run_id,
        )

    db.commit()
    log.info("restanslängd reconciled: %s", stats)
    return stats
