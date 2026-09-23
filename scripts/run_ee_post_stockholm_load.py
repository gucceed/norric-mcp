#!/usr/bin/env python3
"""Apply EE_001 then run the one-shot Estonia bulk baseline after Stockholm flip.

This command is intentionally fail-closed. It requires explicit confirmation that
Finland finished and the target database is the approved Stockholm project.
It never starts scheduling; the beat entry owns the daily cadence only after
the baseline completes.
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import urlparse

from sqlalchemy import text

CONFIRMATION = "STOCKHOLM_FLIP_CONFIRMED_AND_FI_LOAD_FINISHED"


def _safe_target(url: str, expected_host: str) -> str:
    host = (urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1)).hostname or "").lower()
    expected = expected_host.strip().lower()
    if not host or not expected or host != expected:
        raise SystemExit(f"Refusing target host {host!r}; expected Stockholm host {expected!r}")
    return host


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--expected-db-host", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"Refusing to run: --confirm must equal {CONFIRMATION}")
    db_url = os.environ.get("DATABASE_URL", "")
    _safe_target(db_url, args.expected_db_host)

    # Import only after the target guard passes: ingestion.db constructs the
    # production engine at import time from DATABASE_URL.
    from ingestion.db import engine, execute_sql_file
    from ingestion.ariregister.bulk_pipeline import run_bulk_pipeline

    execute_sql_file("migrations/EE_001_ariregister_core.sql")
    with engine.connect() as conn:
        present = conn.execute(text("""
            SELECT to_regclass('public.norric_ee_entities'),
                   to_regclass('public.norric_ee_ingest_state')
        """)).one()
        if not all(present):
            raise SystemExit("EE_001 verification failed")
    result = run_bulk_pipeline(dry_run=False)
    print(result)


if __name__ == "__main__":
    main()
