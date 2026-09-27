"""Guarded DK metadata validation/backfill from fresh Datafordeler total files.

Default mode is validation-only: no database session or writes. `--apply` is a
separate, owner-confirmed operation; it repeats the same checks against fresh
files before updating only side-derived columns. It never moves the events
checkpoint or rewrites the Virksomhed raw/status fields.
"""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from urllib.parse import urlparse

from ingestion.cvr import client
from ingestion.cvr.normalize import build_side_index

log = logging.getLogger(__name__)
ENTITIES = ("Navn", "Adressering", "Branche", "Virksomhedsform")
EXPECTED_HOST = "aws-0-eu-north-1.pooler.supabase.com"
MIN_NAME_MATCH = 0.90


def inspect_files(dest: Path) -> tuple[dict, dict]:
    """Read sanctioned files and print only structural aggregates, no person data."""
    sides = {}
    counts = {}
    for entity in ENTITIES:
        path = client.download_latest_total(entity, dest)
        rows = client.extract_json_rows(path)
        index = build_side_index(entity, rows)
        with_ids = sum(r.get("CVREnhedsId") is not None for r in rows)
        counts[entity] = {"rows": len(rows), "with_entity_id": with_ids,
                          "current_indexed": len(index), "zip_bytes": path.stat().st_size,
                          "keys": sorted({k for r in rows[:100] for k in r})}
        if not rows or not index or with_ids < len(rows) * 0.95:
            raise RuntimeError(f"{entity} failed structural validation: {counts[entity]}")
        for entity_id, values in index.items():
            sides.setdefault(entity_id, {}).update(values)
        del rows, index

    path = client.download_latest_total("Virksomhed", dest)
    rows = client.extract_json_rows(path)
    ids = {str(r["id"]) for r in rows if r.get("id") is not None}
    if not rows or len(ids) < len(rows) * 0.95:
        raise RuntimeError("Virksomhed file missing rows or entity IDs")
    matched = {entity: sum(bool(sides.get(str(r.get("id")), {}).get(field))
                          for r in rows)
               for entity, field in (("Navn", "name"), ("Adressering", "address"),
                                     ("Branche", "industry"), ("Virksomhedsform", "legal_form"))}
    counts["Virksomhed"] = {"rows": len(rows), "unique_ids": len(ids),
                            "zip_bytes": path.stat().st_size,
                            "keys": sorted({k for r in rows[:100] for k in r}),
                            "matched": matched,
                            "matched_percent": {k: round(n * 100 / len(rows), 2)
                                                for k, n in matched.items()}}
    print(json.dumps({"validation": counts}, sort_keys=True, ensure_ascii=False), flush=True)
    if matched["Navn"] < len(rows) * MIN_NAME_MATCH:
        raise RuntimeError("Current names match fewer than 90% of Virksomhed rows; no DB writes")
    by_cvr = {}
    for row in rows:
        entity_id = str(row.get("id"))
        if entity_id in sides and row.get("CVRNummer") is not None:
            cvr = str(row["CVRNummer"]).zfill(8)
            if cvr in by_cvr and by_cvr[cvr] != sides[entity_id]:
                raise RuntimeError("conflicting Virksomhed versions for same CVR; no DB writes")
            by_cvr[cvr] = sides[entity_id]
    if len(by_cvr) < matched["Navn"] * 0.95:
        raise RuntimeError("too few matched side entities have CVR numbers; no DB writes")
    return by_cvr, counts


def backfill(sides: dict, counts: dict, *, batch_size: int, pause_seconds: float) -> int:
    import time
    from sqlalchemy import text
    from ingestion.db import Session
    from ingestion.pipeline_run import pipeline_run
    db = Session()
    # Guard the target against accidentally running the backfill without its
    # prerequisite code fix. The deployment gate is an operational check too.
    sql = text("""
        UPDATE norric_dk_entities SET
            name = COALESCE(:name, name),
            legal_form_code = COALESCE(:legal_form_code, legal_form_code),
            legal_form_label = COALESCE(:legal_form_label, legal_form_label),
            industry_code = COALESCE(:industry_code, industry_code),
            industry_label = COALESCE(:industry_label, industry_label),
            street = COALESCE(:street, street), city = COALESCE(:city, city),
            postcode = COALESCE(:postcode, postcode),
            municipality_code = COALESCE(:municipality_code, municipality_code),
            country_code = COALESCE(:country_code, country_code),
            raw_address = COALESCE(:raw_address, raw_address),
            last_updated_at = now()
        WHERE cvr_number = :cvr_number
          AND (name IS DISTINCT FROM COALESCE(:name, name)
            OR industry_code IS DISTINCT FROM COALESCE(:industry_code, industry_code)
            OR industry_label IS DISTINCT FROM COALESCE(:industry_label, industry_label)
            OR legal_form_code IS DISTINCT FROM COALESCE(:legal_form_code, legal_form_code)
            OR legal_form_label IS DISTINCT FROM COALESCE(:legal_form_label, legal_form_label)
            OR street IS DISTINCT FROM COALESCE(:street, street)
            OR city IS DISTINCT FROM COALESCE(:city, city)
            OR postcode IS DISTINCT FROM COALESCE(:postcode, postcode)
            OR municipality_code IS DISTINCT FROM COALESCE(:municipality_code, municipality_code)
            OR country_code IS DISTINCT FROM COALESCE(:country_code, country_code)
            OR raw_address IS DISTINCT FROM COALESCE(:raw_address, raw_address))
    """)
    total = 0
    try:
        with pipeline_run(db, "cvr_metadata_backfill") as ctx:
            for cvr_number, side in sides.items():
                addr = side.get("address") or {}
                ind = side.get("industry") or {}
                form = side.get("legal_form") or {}
                params = {"cvr_number": cvr_number, "name": side.get("name"),
                          "legal_form_code": form.get("code"), "legal_form_label": form.get("label"),
                          "industry_code": ind.get("code"), "industry_label": ind.get("label"),
                          "street": addr.get("street"), "city": addr.get("city"),
                          "postcode": addr.get("postcode"),
                          "municipality_code": addr.get("municipality_code"),
                          "country_code": addr.get("country_code"),
                          "raw_address": json.dumps(addr["raw"], ensure_ascii=False, default=str)
                          if addr.get("raw") else None}
                n = db.execute(sql, params).rowcount
                if n > 1:
                    raise RuntimeError("duplicate CVR rows encountered")
                total += n
                ctx["rows_processed"] += 1
                ctx["rows_updated"] += n
                if ctx["rows_processed"] % batch_size == 0:
                    db.commit()
                    print(json.dumps({"processed": ctx["rows_processed"],
                                      "updated": total}), flush=True)
                    time.sleep(pause_seconds)
            db.commit()
        return total
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm")
    p.add_argument("--expected-db-host")
    p.add_argument("--batch-size", type=int, default=1000)
    p.add_argument("--pause-seconds", type=float, default=30)
    args = p.parse_args()
    if args.apply:
        if args.confirm != "DK_METADATA_BACKFILL_APPROVED" or args.expected_db_host != EXPECTED_HOST:
            p.error("apply requires explicit confirmation and exact Stockholm host")
        from os import environ
        host = (urlparse(environ.get("DATABASE_URL", "").replace(
            "postgresql+psycopg2://", "postgresql://", 1)).hostname or "").lower()
        if host != EXPECTED_HOST or not (1 <= args.batch_size <= 5000) or args.pause_seconds < 1:
            p.error("refusing unsafe target or pacing")
    with tempfile.TemporaryDirectory() as tmp:
        sides, counts = inspect_files(Path(tmp))
        if args.apply:
            print(json.dumps({"backfill_updated": backfill(
                sides, counts, batch_size=args.batch_size,
                pause_seconds=args.pause_seconds)}), flush=True)
        else:
            print("Validation-only complete. No DB access or writes.", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
