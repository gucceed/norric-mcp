from celery import shared_task
from ingestion.ariregister.bulk_pipeline import run_bulk_pipeline
@shared_task(name='ariregister.bulk_ingest',bind=True,max_retries=2,default_retry_delay=1800,autoretry_for=(Exception,))
def ariregister_bulk_ingest(self):return run_bulk_pipeline()
