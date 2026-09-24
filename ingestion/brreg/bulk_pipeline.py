from __future__ import annotations
import argparse,json,logging,tempfile
from datetime import date
from pathlib import Path
from sqlalchemy import text
from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from ingestion.brreg import client
from ingestion.brreg.normalize import map_entity
log=logging.getLogger(__name__)
DIFF_FIELDS=('name','legal_form_code','is_active','bankruptcy','under_liquidation','forced_liquidation','industry_code','street','city','postcode','municipality_code','phone','email','website')
UPSERT_SQL="""INSERT INTO norric_no_entities (org_number,name,legal_form_code,legal_form_label,is_active,registered_at,founded_at,bankruptcy,under_liquidation,forced_liquidation,industry_code,industry_label,street,city,postcode,municipality_code,country_code,raw_address,phone,email,website,source,raw,last_seen_at,last_updated_at) VALUES (:org_number,:name,:legal_form_code,:legal_form_label,:is_active,:registered_at,:founded_at,:bankruptcy,:under_liquidation,:forced_liquidation,:industry_code,:industry_label,:street,:city,:postcode,:municipality_code,:country_code,CAST(:raw_address AS jsonb),:phone,:email,:website,:source,CAST(:raw AS jsonb),now(),now()) ON CONFLICT(org_number) DO UPDATE SET name=EXCLUDED.name,legal_form_code=EXCLUDED.legal_form_code,legal_form_label=EXCLUDED.legal_form_label,is_active=EXCLUDED.is_active,registered_at=EXCLUDED.registered_at,founded_at=EXCLUDED.founded_at,bankruptcy=EXCLUDED.bankruptcy,under_liquidation=EXCLUDED.under_liquidation,forced_liquidation=EXCLUDED.forced_liquidation,industry_code=EXCLUDED.industry_code,industry_label=EXCLUDED.industry_label,street=EXCLUDED.street,city=EXCLUDED.city,postcode=EXCLUDED.postcode,municipality_code=EXCLUDED.municipality_code,country_code=EXCLUDED.country_code,raw_address=EXCLUDED.raw_address,phone=EXCLUDED.phone,email=EXCLUDED.email,website=EXCLUDED.website,source=EXCLUDED.source,raw=EXCLUDED.raw,last_seen_at=now(),last_updated_at=now()"""
EXISTING_SQL="SELECT org_number,name,legal_form_code,is_active,bankruptcy,under_liquidation,forced_liquidation,industry_code,street,city,postcode,municipality_code,phone,email,website FROM norric_no_entities"
CHANGE_SQL="INSERT INTO norric_no_field_changes(entity_id,snapshot_date,field_name,old_value,new_value,source,source_run) VALUES(:entity_id,:snapshot_date,:field_name,:old_value,:new_value,:source,:source_run)"
def diff_and_write(db,existing,record,run_date,source,run_id):
 old=existing.get(record['org_number']); count=0
 if old is None:return 0
 for field in DIFF_FIELDS:
  ov=getattr(old,field,None); nv=record.get(field); os=None if ov is None else str(ov); ns=None if nv is None else str(nv)
  if os!=ns: db.execute(text(CHANGE_SQL),{'entity_id':record['org_number'],'snapshot_date':run_date,'field_name':field,'old_value':os,'new_value':ns,'source':source,'source_run':str(run_id)});count+=1
 return count
def prepare(r,source):
 r['source']=source;r['raw_address']=json.dumps(r['raw_address'],ensure_ascii=False,default=str);r['raw']=json.dumps(r['raw'],ensure_ascii=False,default=str);return r
def run_bulk_pipeline(dry_run=False,pacer=None):
 db=Session()
 try:
  with pipeline_run(db,'brreg_bulk') as ctx:
   run_id=ctx['run_id']
   if pacer is not None and not dry_run:pacer.bind(db).start()
   existing={r.org_number:r for r in db.execute(text(EXISTING_SQL)).fetchall()}; changes=0
   with tempfile.TemporaryDirectory() as tmp:
    path=client.download_entities(Path(tmp))
    for row in client.iter_download(path):
     rec=map_entity(row);ctx['rows_processed']+=1
     if not rec:ctx['rows_skipped']+=1;continue
     rec=prepare(rec,'brreg_bulk')
     if not dry_run:
      changes+=diff_and_write(db,existing,rec,date.today(),'brreg_bulk',run_id);db.execute(text(UPSERT_SQL),rec)
      if rec['org_number'] in existing:ctx['rows_updated']+=1
      else:ctx['rows_inserted']+=1
      if pacer is not None:pacer.tick()
    if not dry_run and pacer is not None:pacer.finish()
    if not dry_run: db.execute(text("UPDATE norric_no_ingest_state SET last_bulk_at=now(),updated_at=now() WHERE id=1"));db.commit()
   return {**ctx,'run_id':str(run_id),'field_changes':changes}
 finally:db.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');run_bulk_pipeline(parser.parse_args().dry_run)
