from celery import shared_task

from ingestion.cvr.bulk_pipeline import run_bulk_pipeline
from ingestion.cvr.events_pipeline import run_events_pipeline
from ingestion.cvr.reconcile import run_reconcile


@shared_task(
    name="cvr.bulk_ingest",
    bind=True,
    max_retries=2,
    default_retry_delay=3600,
    autoretry_for=(Exception,),
)
def cvr_bulk_ingest(self):
    """Weekly Saturday 08:00 Europe/Copenhagen, after Datafordeler generates
    the total downloads (Saturday night 03:00-06:00)."""
    return run_bulk_pipeline()


@shared_task(
    name="cvr.events_poll",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def cvr_events_poll(self):
    """Every 15 minutes. No public latency SLA exists for CVR_Events, so the
    cadence is an operational target, not a freshness guarantee."""
    return run_events_pipeline()


@shared_task(
    name="cvr.reconcile_nightly",
    bind=True,
    max_retries=2,
    default_retry_delay=1800,
    autoretry_for=(Exception,),
)
def cvr_reconcile_nightly(self):
    """Nightly drift monitor: event-lag, freshness, baseline age."""
    return run_reconcile()
