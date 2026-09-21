"""finnish_company_verify_v1 - official PRH/YTJ verification."""
from __future__ import annotations
import re
from datetime import datetime,timezone
from sqlalchemy import text
from ingestion.prh.normalize import normalize_business_id
TOOL_NAME='finnish_company_verify_v1'
ENTITY='SELECT business_id,name,legal_form_code,legal_form_label,is_active,registered_at,dissolved_at,company_situations,industry_code,industry_label,street,city,postcode,country_code,website,latest_source_update,source,first_seen_at,last_seen_at,last_updated_at FROM norric_fi_entities WHERE business_id=:bid'
NAME='SELECT business_id,name,is_active FROM norric_fi_entities WHERE name ILIKE :pattern ORDER BY is_active DESC,name LIMIT 5'
CHANGES='SELECT snapshot_date,field_name,old_value,new_value,source FROM norric_fi_field_changes WHERE entity_id=:bid ORDER BY snapshot_date DESC LIMIT 5'
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def verify_company(db,query):
 q=(query or '').strip()
 if not q:raise ValueError('query must be a Finnish Business ID or company name')
 if re.fullmatch(r'\d{7}-\d',q):bid=normalize_business_id(q);e=db.execute(text(ENTITY),{'bid':bid}).fetchone()
 else:
  rows=list(db.execute(text(NAME),{'pattern':f'%{q}%'}))
  if len(rows)>1:return {'data':{'query':q,'found':False,'match':'ambiguous','verified':None,'candidates':[{'business_id':r.business_id,'name':r.name,'is_active':r.is_active} for r in rows]},'sources':['prh_ytj'],'confidence':.3,'warnings':['ambiguous name match - retry with the Business ID']}
  e=db.execute(text(ENTITY),{'bid':rows[0].business_id}).fetchone() if rows else None;bid=rows[0].business_id if rows else None
 if not e:return {'data':{'query':q,'found':False,'match':'none','verified':False,**({'business_id':bid} if bid else {})},'sources':['prh_ytj'],'confidence':.3,'warnings':['not found in the PRH/YTJ mirror']}
 ls=e.last_seen_at
 if ls and ls.tzinfo is None:ls=ls.replace(tzinfo=timezone.utc)
 age=(datetime.now(timezone.utc)-ls).total_seconds()/3600 if ls else None;confidence=.95 if age is not None and age<=48 else .7
 changes=[{'snapshot_date':iso(r.snapshot_date),'field':r.field_name,'from':r.old_value,'to':r.new_value,'source':r.source} for r in db.execute(text(CHANGES),{'bid':e.business_id})]
 data={'query':q,'found':True,'match':'exact','verified':bool(e.is_active),'country':'FI','identity':{'business_id':e.business_id,'name':e.name,'legal_form':{'code':e.legal_form_code,'label':e.legal_form_label},'registered_address':{'street':e.street,'postcode':e.postcode,'city':e.city,'country_code':e.country_code},'industry':{'code':e.industry_code,'label':e.industry_label},'website':e.website,'registry_source':e.source,'registry_last_confirmed_at':iso(e.last_seen_at)},'legal_status':{'is_active':e.is_active,'registered_at':iso(e.registered_at),'dissolved_at':iso(e.dissolved_at),'situations':e.company_situations},'registrations':{'vat':{'status':'not_tracked'},'employer':{'status':'not_tracked'}},'latest_changes':changes,'evidence':{'basis':'Norric mirror of the official PRH/YTJ daily open-data snapshot','reference_links':{'api':'https://avoindata.prh.fi/opendata-ytj-api/v3/schema?lang=en'},'license':'CC BY 4.0 - attribution: Finnish Patent and Registration Office / Finnish Tax Administration'}}
 return {'data':data,'sources':['prh_ytj'],'confidence':confidence,'warnings':[]}
