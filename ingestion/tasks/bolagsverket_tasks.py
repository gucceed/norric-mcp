from celery import shared_task
from ingestion.bolagsverket.bulk_pipeline import run_bulk_pipeline


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
