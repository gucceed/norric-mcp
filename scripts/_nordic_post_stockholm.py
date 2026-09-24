"""Shared fail-closed runner for the paced DK/NO/FI post-Stockholm baselines.

Same guard pattern as scripts/run_ee_post_stockholm_load.py (PR #41):
exact Stockholm host check and a chain confirmation string before any
database import. On top of that, the Nordic runners:
  * refuse to start while another run of the same pipeline is 'running',
  * load through ingestion.pacing.Pacer (small batch commits, a pause between
    batches, progress written to the country's ingest-state row),
  * mark the ingest-state row 'failed' if the load raises.
"""
from __future__ import annotations

import argparse
import importlib
import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_BATCH_SIZE = 1000
DEFAULT_PAUSE_SECONDS = 30.0


@dataclass(frozen=True)
class Country:
    code: str
    confirmation: str
    migration: str
    tables: tuple[str, ...]
    state_table: str
    pipeline_name: str
    pipeline_module: str


DK = Country("dk", "STOCKHOLM_FLIP_CONFIRMED", "migrations/DK_001_cvr_core.sql",
             ("norric_dk_entities", "norric_dk_field_changes", "norric_dk_events", "norric_dk_ingest_state"),
             "norric_dk_ingest_state", "cvr_bulk", "ingestion.cvr.bulk_pipeline")
NO = Country("no", "STOCKHOLM_FLIP_CONFIRMED_AND_DK_LOAD_FINISHED", "migrations/NO_001_brreg_core.sql",
             ("norric_no_entities", "norric_no_field_changes", "norric_no_events", "norric_no_ingest_state"),
             "norric_no_ingest_state", "brreg_bulk", "ingestion.brreg.bulk_pipeline")
FI = Country("fi", "STOCKHOLM_FLIP_CONFIRMED_AND_NO_LOAD_FINISHED", "migrations/FI_001_prh_core.sql",
             ("norric_fi_entities", "norric_fi_field_changes", "norric_fi_ingest_state"),
             "norric_fi_ingest_state", "prh_bulk", "ingestion.prh.bulk_pipeline")


def _safe_target(url: str, expected_host: str) -> str:
    host = (urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1)).hostname or "").lower()
    expected = expected_host.strip().lower()
    if not host or not expected or host != expected:
        raise SystemExit(f"Refusing target host {host!r}; expected Stockholm host {expected!r}")
    return host


def parse_args(country: Country, argv=None):
    parser = argparse.ArgumentParser(description=f"Paced {country.code.upper()} post-Stockholm baseline")
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--expected-db-host", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    args = parser.parse_args(argv)
    if args.confirm != country.confirmation:
        raise SystemExit(f"Refusing to run: --confirm must equal {country.confirmation}")
    if args.batch_size < 1 or args.batch_size > 5000:
        raise SystemExit("Refusing to run: --batch-size must be between 1 and 5000")
    if args.pause_seconds < 1:
        raise SystemExit("Refusing to run: --pause-seconds must be at least 1 (slow and safe)")
    return args


def run(country: Country, argv=None) -> dict:
    args = parse_args(country, argv)
    _safe_target(os.environ.get("DATABASE_URL", ""), args.expected_db_host)

    # Import only after the guards pass: ingestion.db builds the engine at
    # import time from DATABASE_URL.
    from sqlalchemy import text
    from ingestion.db import engine, execute_sql_file
    from ingestion.pacing import PROGRESS_COLUMNS_SQL, Pacer

    execute_sql_file(country.migration)
    with engine.connect() as conn:
        regs = ", ".join(f"to_regclass('public.{t}')" for t in country.tables)
        if not all(conn.execute(text(f"SELECT {regs}")).one()):
            raise SystemExit(f"{country.code.upper()} migration verification failed")
        conn.execute(text(PROGRESS_COLUMNS_SQL.format(table=country.state_table)))
        running = conn.execute(text(
            "SELECT count(*) FROM norric_pipeline_runs WHERE pipeline=:p AND status='running' "
            "AND started_at > now() - interval '36 hours'"), {"p": country.pipeline_name}).scalar()
        conn.commit()
    if running:
        raise SystemExit(f"Refusing to run: a {country.pipeline_name} run is already in progress")

    pipeline = importlib.import_module(country.pipeline_module)
    pacer = Pacer(country.state_table, batch_size=args.batch_size, pause_seconds=args.pause_seconds)
    try:
        result = pipeline.run_bulk_pipeline(dry_run=False, pacer=pacer)
    except BaseException:
        with engine.connect() as conn:
            conn.execute(text(f"UPDATE {country.state_table} SET load_status='failed', "
                              "load_progress_at=now(), updated_at=now() WHERE id=1"))
            conn.commit()
        raise
    print(result)
    return result
