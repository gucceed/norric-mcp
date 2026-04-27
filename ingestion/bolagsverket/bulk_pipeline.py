"""
Bolagsverket bulk ingestion pipeline.

1. Download bulk zip from Bolagsverket
2. Extract the .txt file
3. Parse line by line
4. Upsert to norric_entities + write snapshots
5. Record PipelineRun

CLI: python -m ingestion.bolagsverket.bulk_pipeline [--dry-run]
"""
import io
import logging
import os
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import httpx

from ingestion.db import Session
from ingestion.bolagsverket.bulk_parser import parse_bulk_file
from ingestion.bolagsverket.bulk_writer import upsert_entities
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)

BULK_URL = os.environ.get(
    "BOLAGSVERKET_BULK_URL",
    "https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/"
    "nedladdningsbarafiler.2517.html",
)

DIRECT_DOWNLOAD_URL = os.environ.get(
    "BOLAGSVERKET_DIRECT_URL",
    # The actual zip URL — set this env var to the real download link
    # obtained from Bolagsverket's open data page above.
    "",
)


def _download_bulk_file(dest_dir: Path) -> Path:
    url = DIRECT_DOWNLOAD_URL
    if not url:
        raise RuntimeError(
            "BOLAGSVERKET_DIRECT_URL not set. "
            "Obtain the bulk zip URL from the Bolagsverket open data page and set this variable."
        )

    log.info("downloading bulk file from %s", url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
        resp.raise_for_status()
        zip_path = dest_dir / "bolagsverket_bulk.zip"
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)

    log.info("download complete: %s", zip_path)
    return zip_path


def _extract_txt(zip_path: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            raise RuntimeError(f"No .txt file found in {zip_path}")
        target = txt_names[0]
        extracted = dest_dir / target
        zf.extract(target, dest_dir)
        log.info("extracted: %s", extracted)
        return extracted


def run_bulk_pipeline(dry_run: bool = False) -> dict:
    db = Session()
    try:
        with pipeline_run(db, "bolagsverket_bulk") as ctx:
            run_id = ctx["run_id"]

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                zip_path = _download_bulk_file(tmp_path)
                txt_path = _extract_txt(zip_path, tmp_path)

                records = parse_bulk_file(txt_path)
                stats = upsert_entities(
                    db=db,
                    records=records,
                    run_id=run_id,
                    snapshot_date=date.today(),
                    dry_run=dry_run,
                )

            ctx["rows_processed"] = stats["inserted"] + stats["updated"] + stats["skipped"]
            ctx["rows_inserted"]  = stats["inserted"]
            ctx["rows_updated"]   = stats["updated"]
            ctx["rows_skipped"]   = stats["skipped"]

        log.info("pipeline complete: %s", stats)
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv
    result = run_bulk_pipeline(dry_run=dry_run)
    print(result)
