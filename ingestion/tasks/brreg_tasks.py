from celery import shared_task
from ingestion.brreg.bulk_pipeline import run_bulk_pipeline
from ingestion.brreg.updates_pipeline import run_updates_pipeline
from ingestion.brreg.reconcile import run_reconcile
@shared_task(name='brreg.bulk_ingest',bind=True,max_retries=2,default_retry_delay=1800,autoretry_for=(Exception,))
def brreg_bulk_ingest(self): return run_bulk_pipeline()
@shared_task(name='brreg.updates_poll',bind=True,max_retries=3,default_retry_delay=300,autoretry_for=(Exception,))
def brreg_updates_poll(self): return run_updates_pipeline()
@shared_task(name='brreg.reconcile_nightly',bind=True,max_retries=2,default_retry_delay=1800,autoretry_for=(Exception,))
def brreg_reconcile_nightly(self): return run_reconcile()
