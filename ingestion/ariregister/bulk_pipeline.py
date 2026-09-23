from __future__ import annotations
import json, tempfile
from datetime import date
from pathlib import Path
from sqlalchemy import text
from ingestion.db import Session
from ingestion.pipeline_run import pipeline_run
from .client import download_companies, iter_download
from .normalize import map_company
FIELDS = ('name','legal_form_code','is_active','registered_at','dissolved_at','industry_code','street','city','postcode','website')
EXISTING = 'SELECT registry_code,name,legal_form_code,is_active,registered_at,dissolved_at,industry_code,street,city,postcode,website FROM norric_ee_entities'
UPSERT = '''INSERT INTO norric_ee_entities(registry_code,name,legal_form_code,legal_form_label,is_active,registered_at,dissolved_at,company_situations,industry_code,industry_label,street,city,postcode,country_code,website,latest_source_update,source,raw,last_seen_at,last_updated_at) VALUES(:registry_code,:name,:legal_form_code,:legal_form_label,:is_active,:registered_at,:dissolved_at,CAST(:company_situations AS jsonb),:industry_code,:industry_label,:street,:city,:postcode,:country_code,:website,:latest_update,'ariregister',CAST(:raw AS jsonb),now(),now()) ON CONFLICT(registry_code) DO UPDATE SET name=EXCLUDED.name,legal_form_code=EXCLUDED.legal_form_code,legal_form_label=EXCLUDED.legal_form_label,is_active=EXCLUDED.is_active,registered_at=EXCLUDED.registered_at,dissolved_at=EXCLUDED.dissolved_at,company_situations=EXCLUDED.company_situations,industry_code=EXCLUDED.industry_code,industry_label=EXCLUDED.industry_label,street=EXCLUDED.street,city=EXCLUDED.city,postcode=EXCLUDED.postcode,country_code=EXCLUDED.country_code,website=EXCLUDED.website,latest_source_update=EXCLUDED.latest_source_update,raw=EXCLUDED.raw,last_seen_at=now(),last_updated_at=now()'''
CHANGE = "INSERT INTO norric_ee_field_changes(entity_id,snapshot_date,field_name,old_value,new_value,source,source_run) VALUES(:entity_id,:day,:field,:old,:new,'ariregister',:run)"

def run_bulk_pipeline(path=None, dry_run=False):
    db = Session()
    try:
        with pipeline_run(db, 'ariregister_bulk') as ctx:
            p = Path(path) if path else download_companies(Path(tempfile.mkdtemp(prefix='ariregister-')))
            old = {r.registry_code: r for r in db.execute(text(EXISTING))}
            seen = changes = 0
            for raw in iter_download(p):
                rec = map_company(raw)
                if not rec: continue
                seen += 1
                prev = old.get(rec['registry_code'])
                if prev:
                    for f in FIELDS:
                        a = getattr(prev, f, None); b = rec.get(f)
                        if str(a or '') != str(b or ''):
                            changes += 1
                            if not dry_run: db.execute(text(CHANGE), {'entity_id': rec['registry_code'], 'day': date.today(), 'field': f, 'old': None if a is None else str(a), 'new': None if b is None else str(b), 'run': ctx['run_id']})
                if not dry_run:
                    vals = {**rec, 'company_situations': json.dumps(rec['company_situations'], ensure_ascii=False), 'raw': json.dumps(rec['raw'], ensure_ascii=False)}
                    db.execute(text(UPSERT), vals)
                if seen % 1000 == 0 and not dry_run: db.commit()
            if not dry_run:
                db.execute(text('UPDATE norric_ee_ingest_state SET last_bulk_at=now(),updated_at=now() WHERE id=1'))
                db.commit()
            return {**ctx, 'companies_seen': seen, 'changes': changes, 'dry_run': dry_run}
    finally: db.close()
