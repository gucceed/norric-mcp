import asyncio
from celery import shared_task

from ingestion.db import Session
from ingestion.kronofogden.scraper import fetch_payment_orders
from ingestion.kronofogden.writer import write_payment_cases
from ingestion.pipeline_run import pipeline_run


@shared_task(
    name="kronofogden.payment_ingest",
    bind=True,
    max_retries=3,
    default_retry_delay=3600,
    autoretry_for=(Exception,),
)
def kronofogden_payment_ingest(self):
    """Weekly — Tuesday 04:00 Europe/Stockholm."""
    cases = asyncio.run(fetch_payment_orders())
    db = Session()
    try:
        with pipeline_run(db, "kronofogden_betalning") as ctx:
            stats = write_payment_cases(db, cases, ctx["run_id"])
            ctx["rows_processed"] = len(cases)
            ctx["rows_inserted"]  = stats["inserted"]
        return stats
    finally:
        db.close()
