"""french_company_verify_v1 - official Sirene (INSEE) verification."""
from __future__ import annotations
import re
from datetime import datetime,timezone
from sqlalchemy import text
from ingestion.sirene.normalize import normalize_siren
TOOL_NAME='french_company_verify_v1'
ENTITY='SELECT siren,name,legal_form_code,legal_form_label,is_active,registered_at,dissolved_at,company_situations,industry_code,industry_label,street,city,postcode,country_code,website,latest_source_update,source,first_seen_at,last_seen_at,last_updated_at FROM norric_fr_entities WHERE siren=:siren'
NAME='SELECT siren,name,is_active FROM norric_fr_entities WHERE name ILIKE :pattern ORDER BY is_active DESC,name LIMIT 5'
CHANGES='SELECT snapshot_date,field_name,old_value,new_value,source FROM norric_fr_field_changes WHERE entity_id=:siren ORDER BY snapshot_date DESC LIMIT 5'
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def verify_company(db,query):
 q=(query or '').strip()
 if not q:raise ValueError('query must be a French SIREN or company name')
 if re.fullmatch(r'\d{9}',q):siren=normalize_siren(q);e=db.execute(text(ENTITY),{'siren':siren}).fetchone()
 else:
  rows=list(db.execute(text(NAME),{'pattern':f'%{q}%'}))
  if len(rows)>1:return {'data':{'query':q,'found':False,'match':'ambiguous','verified':None,'candidates':[{'siren':r.siren,'name':r.name,'is_active':r.is_active} for r in rows]},'sources':['sirene'],'confidence':.3,'warnings':['ambiguous name match - retry with the SIREN']}
  e=db.execute(text(ENTITY),{'siren':rows[0].siren}).fetchone() if rows else None;siren=rows[0].siren if rows else None
 if not e:return {'data':{'query':q,'found':False,'match':'none','verified':False,**({'siren':siren} if siren else {})},'sources':['sirene'],'confidence':.3,'warnings':['not found in the Sirene mirror']}
 ls=e.last_seen_at
 if ls and ls.tzinfo is None:ls=ls.replace(tzinfo=timezone.utc)
 age=(datetime.now(timezone.utc)-ls).total_seconds()/3600 if ls else None;confidence=.95 if age is not None and age<=48 else .7
 changes=[{'snapshot_date':iso(r.snapshot_date),'field':r.field_name,'from':r.old_value,'to':r.new_value,'source':r.source} for r in db.execute(text(CHANGES),{'siren':e.siren})]
 data={'query':q,'found':True,'match':'exact','verified':bool(e.is_active),'country':'FR','identity':{'siren':e.siren,'name':e.name,'legal_form':{'code':e.legal_form_code,'label':e.legal_form_label},'registered_address':{'street':e.street,'postcode':e.postcode,'city':e.city,'country_code':e.country_code},'industry':{'code':e.industry_code,'label':e.industry_label},'website':e.website,'registry_source':e.source,'registry_last_confirmed_at':iso(e.last_seen_at)},'legal_status':{'is_active':e.is_active,'registered_at':iso(e.registered_at),'dissolved_at':iso(e.dissolved_at),'situations':e.company_situations},'registrations':{'vat':{'status':'not_tracked'},'employer':{'status':'not_tracked'}},'latest_changes':changes,'evidence':{'basis':'Norric mirror of the official INSEE Base Sirene stock files; non-diffusible natural persons (Art. A123-96 code de commerce) are excluded at ingest','reference_links':{'dataset':'https://www.data.gouv.fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret'},'license':'Licence Ouverte / Open Licence 2.0 (Etalab) - attribution: INSEE'}}
 return {'data':data,'sources':['sirene'],'confidence':confidence,'warnings':[]}
