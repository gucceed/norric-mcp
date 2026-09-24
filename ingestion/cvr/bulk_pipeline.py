"""
CVR bulk baseline pipeline - Denmark country two.

1. Download the latest weekly total downloads (current JSON) for the company
   spine entities from Datafordeler Fildownload
2. Build side indexes (Navn, Adressering, Branche, Virksomhedsform)
3. Upsert norric_dk_entities and diff tracked fields into
   norric_dk_field_changes (snapshot_date = run date)
4. Update norric_dk_ingest_state and record a norric_pipeline_runs row
   (pipeline = 'cvr_bulk')

Cadence: weekly (total downloads are generated Saturday night 03:00-06:00 and
archived after 7 days). Between baselines, CVR_Events carry the deltas.

CLI: python -m ingestion.cvr.bulk_pipeline [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
from datetime import date
from pathlib import Path

from sqlalchemy import text

from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.cvr import client
from ingestion.cvr.normalize import build_side_index, map_virksomhed_row

log = logging.getLogger(__name__)

_DIFF_FIELDS = (
    "name", "legal_form_code", "status_code", "is_active", "ceased_at",
    "industry_code", "street", "city", "postcode", "municipality_code",
    "phone", "email", "website",
)

_UPSERT_SQL = """
    INSERT INTO norric_dk_entities (
        cvr_number, name, legal_form_code, legal_form_label, status_code,
        status_label, is_active, started_at, ceased_at, industry_code,
        industry_label, street, city, postcode, municipality_code,
        country_code, raw_address, phone, email, website,
        registrering_fra, registrering_til, virkning_fra, virkning_til,
        datafordeler_row_id, source, raw, last_seen_at, last_updated_at
    ) VALUES (
        :cvr_number, :name, :legal_form_code, :legal_form_label, :status_code,
        :status_label, :is_active, :started_at, :ceased_at, :industry_code,
        :industry_label, :street, :city, :postcode, :municipality_code,
        :country_code, :raw_address, :phone, :email, :website,
        :registrering_fra, :registrering_til, :virkning_fra, :virkning_til,
        :datafordeler_row_id, :source, CAST(:raw AS jsonb), now(), now()
    )
    ON CONFLICT (cvr_number) DO UPDATE SET
        name = EXCLUDED.name,
        legal_form_code = EXCLUDED.legal_form_code,
        legal_form_label = EXCLUDED.legal_form_label,
        status_code = EXCLUDED.status_code,
        status_label = EXCLUDED.status_label,
        is_active = EXCLUDED.is_active,
        started_at = EXCLUDED.started_at,
        ceased_at = EXCLUDED.ceased_at,
        industry_code = EXCLUDED.industry_code,
        industry_label = EXCLUDED.industry_label,
        street = EXCLUDED.street,
        city = EXCLUDED.city,
        postcode = EXCLUDED.postcode,
        municipality_code = EXCLUDED.municipality_code,
        country_code = EXCLUDED.country_code,
        raw_address = EXCLUDED.raw_address,
        phone = EXCLUDED.phone,
        email = EXCLUDED.email,
        website = EXCLUDED.website,
        registrering_fra = EXCLUDED.registrering_fra,
        registrering_til = EXCLUDED.registrering_til,
        virkning_fra = EXCLUDED.virkning_fra,
        virkning_til = EXCLUDED.virkning_til,
        datafordeler_row_id = EXCLUDED.datafordeler_row_id,
        source = EXCLUDED.source,
        raw = EXCLUDED.raw,
        last_seen_at = now(),
        last_updated_at = now()
"""

_EXISTING_SQL = """
    SELECT cvr_number, name, legal_form_code, status_code, is_active,
           ceased_at, industry_code, street, city, postcode,
           municipality_code, phone, email, website
    FROM norric_dk_entities
"""

_CHANGE_SQL = """
    INSERT INTO norric_dk_field_changes
        (entity_id, entity_type, snapshot_date, field_name, old_value,
         new_value, source, source_run)
    VALUES
        (:entity_id, 'company', :snapshot_date, :field_name, :old_value,
         :new_value, :source, :source_run)
"""


def _diff_and_write(db, existing: dict, record: dict, run_date: date,
                    source: str, run_id) -> int:
    cvr = record["cvr_number"]
    old = existing.get(cvr)
    if old is None:
        return 0
    changes = 0
    for field in _DIFF_FIELDS:
        old_v = getattr(old, field, None) if not isinstance(old, dict) else old.get(field)
        new_v = record.get(field)
        old_s = None if old_v is None else str(old_v)
        new_s = None if new_v is None else str(new_v)
        if old_s != new_s:
            db.execute(text(_CHANGE_SQL), {
                "entity_id": cvr,
                "snapshot_date": run_date,
                "field_name": field,
                "old_value": old_s,
                "new_value": new_s,
                "source": source,
                "source_run": str(run_id),
            })
            changes += 1
    return changes


def _baseline_sequence() -> tuple[int | None, str | None]:
    """Checkpoint the events poll should resume from after this baseline.

    Called BEFORE the total files are downloaded. Prefer the sequence the total
    download itself reflects (no gap: later events replay idempotently). Fall
    back to DAF_RegisterImportStatus.lastSequenceNumber read now; that may skip
    events between file generation and now, which the next weekly baseline
    repairs. Never raises: a failure leaves the checkpoint unseeded, and the
    events poll then fails closed.
    """
    try:
        seq = client.total_download_sequence("Virksomhed")
        if seq:
            return seq, "file_download_metadata"
    except Exception as exc:  # noqa: BLE001
        log.warning("cvr bulk: file-download sequence metadata unavailable: %s", exc)
    try:
        seq = int(client.fetch_register_import_status().get("lastSequenceNumber") or 0)
        if seq > 0:
            return seq, "register_import_status_pre_download"
    except Exception as exc:  # noqa: BLE001
        log.warning("cvr bulk: DAF_RegisterImportStatus unavailable: %s", exc)
    return None, None


def run_bulk_pipeline(dry_run: bool = False, pacer=None) -> dict:
    """pacer: optional ingestion.pacing.Pacer for paced one-shot baselines."""
    db = Session()
    try:
        with pipeline_run(db, "cvr_bulk") as ctx:
            run_id = ctx["run_id"]
            run_date = date.today()
            if pacer is not None and not dry_run:
                pacer.bind(db).start()

            seed_seq, seed_source = _baseline_sequence()
            ctx["checkpoint_seed"] = seed_seq
            ctx["checkpoint_seed_source"] = seed_source

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                # 1. Side entities first
                sides: dict[str, dict] = {}
                for entity in ("Navn", "Adressering", "Branche", "Virksomhedsform"):
                    zip_path = client.download_latest_total(entity, tmp_path)
                    rows = client.extract_json_rows(zip_path)
                    ctx["rows_processed"] += len(rows)
                    for cvr, values in build_side_index(entity, rows).items():
                        sides.setdefault(cvr, {}).update(values)
                    log.info("cvr bulk: %s -> %d rows", entity, len(rows))

                # 2. Virksomhed spine
                v_zip = client.download_latest_total("Virksomhed", tmp_path)
                v_rows = client.extract_json_rows(v_zip)
                log.info("cvr bulk: Virksomhed -> %d rows", len(v_rows))
                ctx["rows_processed"] += len(v_rows)

                existing = {
                    r.cvr_number: r
                    for r in db.execute(text(_EXISTING_SQL)).fetchall()
                }

                change_count = 0
                for row in v_rows:
                    record = map_virksomhed_row(row, side=sides.get(
                        _safe_cvr(row), {}))
                    if record is None:
                        ctx["rows_skipped"] += 1
                        continue
                    record["source"] = "cvr_fildownload"
                    record["raw"] = json.dumps(record["raw"], ensure_ascii=False, default=str)
                    if not dry_run:
                        change_count += _diff_and_write(
                            db, existing, record, run_date, "cvr_fildownload", run_id)
                        db.execute(text(_UPSERT_SQL), record)
                        if record["cvr_number"] in existing:
                            ctx["rows_updated"] += 1
                        else:
                            ctx["rows_inserted"] += 1
                        if pacer is not None:
                            pacer.tick()

                if not dry_run:
                    if pacer is not None:
                        pacer.finish()
                    db.execute(text("""
                        UPDATE norric_dk_ingest_state
                        SET last_bulk_filename = :f, last_bulk_at = now(),
                            last_sequence_number = GREATEST(last_sequence_number,
                                                            COALESCE(:seq, 0)),
                            updated_at = now()
                        WHERE id = 1
                    """), {"f": v_zip.name, "seq": seed_seq})
                    db.commit()

                ctx["rows_skipped"] += 0
                log.info("cvr bulk done: %d inserted, %d updated, %d field changes",
                         ctx["rows_inserted"], ctx["rows_updated"], change_count)
                return {**ctx, "run_id": str(run_id), "field_changes": change_count}
    finally:
        db.close()


def _safe_cvr(row: dict):
    from ingestion.cvr.normalize import normalize_cvr_number, _pick
    v = _pick(row, "cvrNummer", "cvrnummer", "CVRNummer", "cvr", "cvr_number")
    if v is None:
        return None
    try:
        return normalize_cvr_number(v)
    except ValueError:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_bulk_pipeline(dry_run=args.dry_run)
