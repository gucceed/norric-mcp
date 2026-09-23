"""estonian_company_verify_v1 - official e-Ariregister verification."""
from __future__ import annotations
import re
from datetime import datetime,timezone
from sqlalchemy import text
from ingestion.ariregister.normalize import normalize_registry_code
TOOL_NAME='estonian_company_verify_v1'
ENTITY='SELECT registry_code,name,legal_form_code,legal_form_label,is_active,registered_at,dissolved_at,company_situations,industry_code,industry_label,street,city,postcode,country_code,website,latest_source_update,source,first_seen_at,last_seen_at,last_updated_at FROM norric_ee_entities WHERE registry_code=:rc'
NAME='SELECT registry_code,name,is_active FROM norric_ee_entities WHERE name ILIKE :pattern ORDER BY is_active DESC,name LIMIT 5'
CHANGES='SELECT snapshot_date,field_name,old_value,new_value,source FROM norric_ee_field_changes WHERE entity_id=:rc ORDER BY snapshot_date DESC LIMIT 5'
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def verify_company(db,query):
 q=(query or '').strip()
 if not q:raise ValueError('query must be an Estonian registry code or company name')
 if re.fullmatch(r'\d{8}',q):rc=normalize_registry_code(q);e=db.execute(text(ENTITY),{'rc':rc}).fetchone()
 else:
  rows=list(db.execute(text(NAME),{'pattern':f'%{q}%'}))
  if len(rows)>1:return {'data':{'query':q,'found':False,'match':'ambiguous','verified':None,'candidates':[{'registry_code':r.registry_code,'name':r.name,'is_active':r.is_active} for r in rows]},'sources':['ariregister'],'confidence':.3,'warnings':['ambiguous name match - retry with the registry code']}
  e=db.execute(text(ENTITY),{'rc':rows[0].registry_code}).fetchone() if rows else None;rc=rows[0].registry_code if rows else None
 if not e:return {'data':{'query':q,'found':False,'match':'none','verified':False,**({'registry_code':rc} if rc else {})},'sources':['ariregister'],'confidence':.3,'warnings':['not found in the Ariregister mirror']}
 ls=e.last_seen_at
 if ls and ls.tzinfo is None:ls=ls.replace(tzinfo=timezone.utc)
 age=(datetime.now(timezone.utc)-ls).total_seconds()/3600 if ls else None;confidence=.95 if age is not None and age<=48 else .7
 changes=[{'snapshot_date':iso(r.snapshot_date),'field':r.field_name,'from':r.old_value,'to':r.new_value,'source':r.source} for r in db.execute(text(CHANGES),{'rc':e.registry_code})]
 data={'query':q,'found':True,'match':'exact','verified':bool(e.is_active),'country':'EE','identity':{'registry_code':e.registry_code,'name':e.name,'legal_form':{'code':e.legal_form_code,'label':e.legal_form_label},'registered_address':{'street':e.street,'postcode':e.postcode,'city':e.city,'country_code':e.country_code},'industry':{'code':e.industry_code,'label':e.industry_label},'website':e.website,'registry_source':e.source,'registry_last_confirmed_at':iso(e.last_seen_at)},'legal_status':{'is_active':e.is_active,'registered_at':iso(e.registered_at),'dissolved_at':iso(e.dissolved_at),'situations':e.company_situations},'registrations':{'vat':{'status':'not_tracked'},'employer':{'status':'not_tracked'}},'latest_changes':changes,'evidence':{'basis':'Norric mirror of the official e-Ariregister daily open-data snapshot','reference_links':{'portal':'https://avaandmed.ariregister.rik.ee/en/downloading-open-data'},'license':'CC BY 4.0 - attribution: Republic of Estonia, Centre of Registers and Information Systems'}}
 return {'data':data,'sources':['ariregister'],'confidence':confidence,'warnings':[]}
