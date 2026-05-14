"""
Bolagsverket konkurs ingestion pipeline.

1. Download bulk zip from BOLAGSVERKET_DIRECT_URL (or reuse a local copy).
2. Extract `bolagsverket_bulkfil.txt`.
3. Stream-parse konkurs events via `konkurs_parser`.
4. Upsert into `norric_payment_signals` via `konkurs_writer`.
5. Record telemetry via the `pipeline_run` context manager.

CLI:
  python -m ingestion.bolagsverket.konkurs_ingester           # production run
  python -m ingestion.bolagsverket.konkurs_ingester --dry-run # parse only
  python -m ingestion.bolagsverket.konkurs_ingester --use-local <path>  # reuse zip

Idempotency:
  Same bulk file → same end state (upsert on UNIQUE (orgnr, case_ref)).
  Run telemetry recorded per execution in norric_pipeline_runs regardless.

Cleanup:
  Extracted .txt file is deleted at end of run. The downloaded .zip is kept
  in the local cache directory for 7-day retention (so re-runs avoid the
  ~245 MB re-download when --use-local is convenient).
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from ingestion.db import Session
from ingestion.bolagsverket.konkurs_parser import (
    DEFAULT_ORG_FORMS,
    parse_konkurs_events,
)
from ingestion.bolagsverket.konkurs_writer import upsert_konkurs_records
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)

DIRECT_DOWNLOAD_URL = os.environ.get("BOLAGSVERKET_DIRECT_URL", "")

CACHE_DIR = Path(os.environ.get("BOLAGSVERKET_CACHE_DIR", "/tmp/bolagsverket-cache"))
RETENTION_DAYS = int(os.environ.get("BOLAGSVERKET_RETENTION_DAYS", "7"))


def _prune_cache(retention_days: int = RETENTION_DAYS) -> None:
    if not CACHE_DIR.exists():
        return
    cutoff_ts = time.time() - retention_days * 86400
    for p in CACHE_DIR.iterdir():
        try:
            if p.stat().st_mtime < cutoff_ts:
                p.unlink()
                log.info("pruned cached file: %s", p)
        except OSError:
            pass


def _download_bulk_zip(dest_dir: Path) -> Path:
    """Download bulk zip to dest_dir. Uses BOLAGSVERKET_DIRECT_URL."""
    if not DIRECT_DOWNLOAD_URL:
        raise RuntimeError(
            "BOLAGSVERKET_DIRECT_URL not set on this service. "
            "Per Phase 2 of the konkurs ingestor build, set it to: "
            "https://vardefulla-datamangder.bolagsverket.se/bolagsverket/"
            "bolagsverket_bulkfil.zip"
        )

    zip_path = dest_dir / "bolagsverket_bulkfil.zip"
    log.info("downloading bulk file from %s", DIRECT_DOWNLOAD_URL)
    t0 = time.monotonic()
    with httpx.stream(
        "GET",
        DIRECT_DOWNLOAD_URL,
        follow_redirects=True,
        timeout=600,
    ) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)
    log.info(
        "download complete: %s (%.1f MB in %.1f s)",
        zip_path, zip_path.stat().st_size / 1_048_576, time.monotonic() - t0,
    )
    return zip_path


def _extract_txt(zip_path: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            raise RuntimeError(f"No .txt file found in {zip_path}")
        target = txt_names[0]
        extracted = dest_dir / target
        zf.extract(target, dest_dir)
        log.info(
            "extracted: %s (%.1f MB)",
            extracted, extracted.stat().st_size / 1_048_576,
        )
        return extracted


def run_konkurs_ingest(
    dry_run: bool = False,
    use_local: Optional[Path] = None,
    org_forms: Optional[list[str]] = None,
    cutoff_date: Optional[date] = None,
) -> dict:
    """
    Execute one konkurs ingestion run end-to-end.

    Args:
      dry_run: parse but do not upsert. Telemetry still recorded.
      use_local: path to a pre-existing bulkfil zip to reuse (skips download).
      org_forms: override DEFAULT_ORG_FORMS (e.g. ["AB-ORGFO"] only).
      cutoff_date: override the 24-month default filed_at cutoff.

    Returns:
      stats dict {inserted, updated, skipped, parsed, duration_s}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _prune_cache()

    db = Session()
    t0 = time.monotonic()
    parsed_count = 0
    try:
        with pipeline_run(db, "bolagsverket_konkurs") as ctx:
            run_id = ctx["run_id"]

            with tempfile.TemporaryDirectory(prefix="konkurs-") as tmp:
                tmp_path = Path(tmp)
                if use_local is not None:
                    log.info("using local bulk zip: %s", use_local)
                    zip_path = use_local
                else:
                    # Try cache first if a recent download exists
                    cached = CACHE_DIR / "bolagsverket_bulkfil.zip"
                    if (cached.exists()
                            and cached.stat().st_mtime > time.time() - 86400):
                        log.info("using fresh cached zip: %s", cached)
                        zip_path = cached
                    else:
                        zip_path = _download_bulk_zip(CACHE_DIR)

                txt_path = _extract_txt(zip_path, tmp_path)

                def parsed_iter():
                    nonlocal parsed_count
                    for rec in parse_konkurs_events(
                        path=txt_path,
                        org_forms=frozenset(org_forms) if org_forms else None,
                        cutoff_date=cutoff_date,
                    ):
                        parsed_count += 1
                        yield rec

                stats = upsert_konkurs_records(
                    db=db,
                    records=parsed_iter(),
                    run_id=run_id,
                    dry_run=dry_run,
                )

                # Tidy up: delete extracted txt (~977 MB)
                try:
                    txt_path.unlink()
                except OSError:
                    pass

            duration = time.monotonic() - t0
            stats["parsed"] = parsed_count
            stats["duration_s"] = round(duration, 1)

            ctx["rows_processed"] = parsed_count
            ctx["rows_inserted"]  = stats["inserted"]
            ctx["rows_updated"]   = stats["updated"]
            ctx["rows_skipped"]   = stats["skipped"]

        log.info("konkurs ingest complete: %s", stats)
        return stats
    finally:
        db.close()


def _parse_cli_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Parse, do not write.")
    p.add_argument("--use-local", type=Path,
                   help="Path to pre-downloaded bulkfil zip.")
    p.add_argument("--org-forms", nargs="+",
                   help=f"Org forms to ingest (default: {sorted(DEFAULT_ORG_FORMS)}).")
    p.add_argument("--cutoff-months", type=int,
                   help="Months back from today for filed_at cutoff (default: 24).")
    return p.parse_args(argv)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    args = _parse_cli_args(sys.argv[1:])
    cutoff = None
    if args.cutoff_months is not None:
        today = date.today()
        y, m = today.year, today.month - args.cutoff_months
        while m <= 0:
            m += 12
            y -= 1
        cutoff = date(y, m, min(today.day, 28))

    result = run_konkurs_ingest(
        dry_run=args.dry_run,
        use_local=args.use_local,
        org_forms=args.org_forms,
        cutoff_date=cutoff,
    )
    print(result)
