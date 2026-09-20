from sqlalchemy import text
from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.brreg import client
def run_reconcile():
 db=Session()
 try:
  with pipeline_run(db,'brreg_reconcile') as ctx:
   remote=client.latest_update_id();row=db.execute(text("SELECT s.last_update_id,(SELECT MAX(last_seen_at) FROM norric_no_entities) last_seen,(SELECT MAX(completed_at) FROM norric_pipeline_runs WHERE pipeline='brreg_bulk' AND status='success') last_bulk FROM norric_no_ingest_state s WHERE s.id=1")).fetchone();local=int(row.last_update_id or 0) if row else 0
   report={'remote_update_id':remote,'local_update_id':local,'update_lag':max(remote-local,0),'entities_last_seen':str(row.last_seen) if row else None,'last_bulk_success':str(row.last_bulk) if row else None};ctx['rows_processed']=1
   db.execute(text('UPDATE norric_no_ingest_state SET last_reconcile_at=now(),updated_at=now() WHERE id=1'));db.commit();return {**ctx,**report}
 finally:db.close()
