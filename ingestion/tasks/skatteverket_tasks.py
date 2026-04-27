import asyncio
from celery import shared_task

from ingestion.db import Session
from ingestion.skatteverket.restanslangd_scraper import fetch_restanslangd
from ingestion.skatteverket.restanslangd_writer import reconcile_restanslangd
from ingestion.pipeline_run import pipeline_run


@shared_task(
    name="skatteverket.restanslangd_ingest",
    bind=True,
    max_retries=3,
    default_retry_delay=3600,
    autoretry_for=(Exception,),
)
def restanslangd_ingest(self):
    """Weekly — Monday 04:00 Europe/Stockholm."""
    scraped = asyncio.run(fetch_restanslangd())
    db = Session()
    try:
        with pipeline_run(db, "skatteverket_restanslangd") as ctx:
            stats = reconcile_restanslangd(db, scraped, ctx["run_id"])
            ctx["rows_processed"] = len(scraped)
            ctx["rows_inserted"]  = stats["inserted"]
            ctx["rows_updated"]   = stats["updated"]
        return stats
    finally:
        db.close()
