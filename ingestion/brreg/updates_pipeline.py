from __future__ import annotations
import json,logging
from datetime import date
from sqlalchemy import text
from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.brreg import client
from ingestion.brreg.normalize import map_entity
from ingestion.brreg.bulk_pipeline import UPSERT_SQL,EXISTING_SQL,diff_and_write,prepare
log=logging.getLogger(__name__)
def run_updates_pipeline(batch_size=1000):
 db=Session()
 try:
  with pipeline_run(db,'brreg_updates') as ctx:
   run_id=ctx['run_id']; state=db.execute(text('SELECT last_update_id FROM norric_no_ingest_state WHERE id=1')).fetchone(); since=int(state.last_update_id or 0) if state else 0
   payload=client.fetch_updates(since,batch_size); rows=payload.get('_embedded',{}).get('oppdaterteEnheter',[]);existing={r.org_number:r for r in db.execute(text(EXISTING_SQL)).fetchall()}; max_id=since
   for ev in rows:
    uid=int(ev.get('oppdateringsid') or 0);org=str(ev.get('organisasjonsnummer') or '');ctx['rows_processed']+=1
    ins=db.execute(text("INSERT INTO norric_no_events(update_id,org_number,changed_at,change_type,payload,processed_at) VALUES(:id,:org,:at,:kind,CAST(:payload AS jsonb),now()) ON CONFLICT(update_id) DO NOTHING"),{'id':uid,'org':org,'at':ev.get('dato'),'kind':ev.get('endringstype'),'payload':json.dumps(ev,ensure_ascii=False)})
    if not ins.rowcount:ctx['rows_skipped']+=1;max_id=max(max_id,uid);continue
    row=client.fetch_entity(org)
    if row:
     rec=map_entity(row)
     if rec:
      rec=prepare(rec,'brreg_updates');diff_and_write(db,existing,rec,date.today(),'brreg_updates',run_id);db.execute(text(UPSERT_SQL),rec)
      if org in existing:ctx['rows_updated']+=1
      else:ctx['rows_inserted']+=1
    max_id=max(max_id,uid)
   db.execute(text('UPDATE norric_no_ingest_state SET last_update_id=:id,updated_at=now() WHERE id=1'),{'id':max_id});db.commit()
   return {**ctx,'run_id':str(run_id),'events':len(rows),'last_update_id':max_id}
 finally:db.close()
