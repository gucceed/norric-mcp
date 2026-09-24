"""
CVR events delta pipeline - Denmark country two.

Consumes the first-party CVR_Events entity via GraphQL every few minutes:

1. Read the checkpoint from norric_dk_ingest_state
2. Read DAF_RegisterImportStatus and only process events at or below
   lastSequenceNumber (fully imported packages, per the official docs)
3. Persist events idempotently in norric_dk_events
4. For CVR_Virksomhed events, refetch the company row by
   object_datafordelerRowId and upsert + diff tracked fields
   (snapshot_date = registreringFra date when present, else today)
5. Advance the checkpoint transactionally and record pipeline 'cvr_events'

The legacy Haendelser services (services.datafordeler.dk, zone 0) are being
phased out by 2027-01-15 and are not used.

CLI: python -m ingestion.cvr.events_pipeline
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import text

from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.cvr import client
from ingestion.cvr.bulk_pipeline import _UPSERT_SQL, _diff_and_write, _EXISTING_SQL
from ingestion.cvr.normalize import map_virksomhed_row

log = logging.getLogger(__name__)

_EVENT_INSERT_SQL = """
    INSERT INTO norric_dk_events (
        event_id, entity_name, event_action, sequence_number, object_id,
        object_row_id, object_status, registrering_fra, registrering_til,
        virkning_fra, virkning_til, payload, processed_at
    ) VALUES (
        :event_id, :entity_name, :event_action, :sequence_number, :object_id,
        :object_row_id, :object_status, :registrering_fra, :registrering_til,
        :virkning_fra, :virkning_til, CAST(:payload AS jsonb), now()
    )
    ON CONFLICT (event_id) DO NOTHING
"""

_STATE_SQL = ("SELECT last_sequence_number, last_event_id, last_bulk_at "
              "FROM norric_dk_ingest_state WHERE id = 1")

# True when the incoming row version is older than the one already stored.
_STALE_SQL = """
    SELECT CAST(:incoming AS timestamptz) < registrering_fra
    FROM norric_dk_entities WHERE cvr_number = :cvr
"""

_COMPANY_ENTITIES = {"CVR_Virksomhed", "Virksomhed"}


def _ts(value):
    return str(value) if value else None


def run_events_pipeline(batch_size: int = 1000) -> dict:
    db = Session()
    try:
        with pipeline_run(db, "cvr_events") as ctx:
            run_id = ctx["run_id"]
            state = db.execute(text(_STATE_SQL)).fetchone()
            since = int(state.last_sequence_number or 0) if state else 0
            # Fail closed: never walk CVR's event history from zero. The
            # checkpoint is seeded by the bulk baseline.
            if since <= 0 or state is None or state.last_bulk_at is None:
                log.warning("cvr events: checkpoint not seeded by a bulk baseline "
                            "(seq=%s); skipping poll", since)
                return {**ctx, "run_id": str(run_id), "events": 0,
                        "skipped": "checkpoint_not_seeded"}

            status = client.fetch_register_import_status()
            complete_through = int(status.get("lastSequenceNumber") or 0)
            if complete_through <= since:
                log.info("cvr events: no complete packages beyond %d", since)
                return {**ctx, "run_id": str(run_id), "events": 0}

            events = client.fetch_events(since, batch_size=batch_size)
            events = [e for e in events
                      if int(e.get("datafordelerRegisterImportSequenceNumber") or 0)
                      <= complete_through]
            ctx["rows_processed"] = len(events)
            if not events:
                return {**ctx, "run_id": str(run_id), "events": 0}

            existing = {
                r.cvr_number: r
                for r in db.execute(text(_EXISTING_SQL)).fetchall()
            }

            max_seq = since
            max_event = 0
            for ev in events:
                seq = int(ev.get("datafordelerRegisterImportSequenceNumber") or 0)
                event_id = int(ev.get("eventid") or 0)
                result = db.execute(text(_EVENT_INSERT_SQL), {
                    "event_id": event_id,
                    "entity_name": ev.get("entityname"),
                    "event_action": ev.get("eventaction"),
                    "sequence_number": seq,
                    "object_id": _ts(ev.get("object_id")),
                    "object_row_id": _ts(ev.get("object_datafordelerRowId")),
                    "object_status": ev.get("object_status"),
                    "registrering_fra": _ts(ev.get("object_registreringfra")),
                    "registrering_til": _ts(ev.get("object_registreringtil")),
                    "virkning_fra": _ts(ev.get("object_virkningfra")),
                    "virkning_til": _ts(ev.get("object_virkningtil")),
                    "payload": json.dumps(ev, ensure_ascii=False, default=str),
                })
                if result.rowcount:
                    ctx["rows_inserted"] += 1
                else:
                    ctx["rows_skipped"] += 1  # replay: already imported

                if ev.get("entityname") in _COMPANY_ENTITIES and ev.get("object_datafordelerRowId"):
                    row = client.fetch_virksomhed_by_row_id(ev["object_datafordelerRowId"])
                    if row:
                        record = map_virksomhed_row(row)
                        if record is not None and record.get("registrering_fra"):
                            stale = db.execute(text(_STALE_SQL), {
                                "incoming": record["registrering_fra"],
                                "cvr": record["cvr_number"],
                            }).scalar()
                            if stale:
                                ctx["rows_skipped"] += 1
                                record = None
                        if record is not None:
                            record["source"] = "cvr_events"
                            reg = record.get("registrering_fra")
                            snap = (str(reg)[:10] if reg else date.today().isoformat())
                            record["raw"] = json.dumps(record["raw"], ensure_ascii=False, default=str)
                            _diff_and_write(db, existing, record,
                                            date.fromisoformat(snap),
                                            "cvr_events", run_id)
                            db.execute(text(_UPSERT_SQL), record)
                            if record["cvr_number"] in existing:
                                ctx["rows_updated"] += 1
                            else:
                                ctx["rows_inserted"] += 1

                max_seq = max(max_seq, seq)
                max_event = max(max_event, event_id)

            db.execute(text("""
                UPDATE norric_dk_ingest_state
                SET last_sequence_number = :seq, last_event_id = :ev,
                    updated_at = now()
                WHERE id = 1
            """), {"seq": max_seq, "ev": max_event})
            db.commit()
            log.info("cvr events: %d events, checkpoint -> %d", len(events), max_seq)
            return {**ctx, "run_id": str(run_id), "events": len(events)}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_events_pipeline()
