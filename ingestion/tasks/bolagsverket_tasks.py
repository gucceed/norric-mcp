from celery import shared_task
from ingestion.bolagsverket.bulk_pipeline import run_bulk_pipeline
from ingestion.bolagsverket.konkurs_ingester import run_konkurs_ingest


@shared_task(
    name="bolagsverket.bulk_ingest",
    bind=True,
    max_retries=3,
    default_retry_delay=3600,
    autoretry_for=(Exception,),
)
def bolagsverket_bulk_ingest(self):
    """Scheduled daily at 03:00 Europe/Stockholm via Celery beat."""
    return run_bulk_pipeline()


@shared_task(
    name="bolagsverket.konkurs_ingest",
    bind=True,
    max_retries=3,
    default_retry_delay=3600,
    autoretry_for=(Exception,),
)
def bolagsverket_konkurs_ingest(self):
    """
    Scheduled daily at 03:15 Europe/Stockholm via Celery beat.
    Bolagsverket publishes the bulkfil weekly (Sunday→Monday early UTC).
    Daily check is cheap (cache reuse if zip unchanged) and gives same-day
    visibility on the weekly drop.
    """
    return run_konkurs_ingest()
