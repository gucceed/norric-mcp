"""norwegian_company_verify_v1 - official Enhetsregisteret verification."""
from __future__ import annotations
import re
from datetime import datetime,timezone
from sqlalchemy import text
from ingestion.brreg.normalize import normalize_org_number
TOOL_NAME='norwegian_company_verify_v1'
ENTITY="""SELECT org_number,name,legal_form_code,legal_form_label,is_active,registered_at,founded_at,bankruptcy,under_liquidation,forced_liquidation,industry_code,industry_label,street,city,postcode,municipality_code,country_code,phone,email,website,source,first_seen_at,last_seen_at,last_updated_at FROM norric_no_entities WHERE org_number=:org"""
NAME="SELECT org_number,name,is_active FROM norric_no_entities WHERE name ILIKE :pattern ORDER BY is_active DESC,name LIMIT 5"
CHANGES="SELECT snapshot_date,field_name,old_value,new_value,source FROM norric_no_field_changes WHERE entity_id=:org ORDER BY snapshot_date DESC LIMIT 5"
PIPES="SELECT pipeline,MAX(completed_at) FILTER(WHERE status='success') last_success,MAX(started_at) last_attempt FROM norric_pipeline_runs WHERE pipeline IN ('brreg_bulk','brreg_updates','brreg_reconcile') GROUP BY pipeline"
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def verify_company(db,query):
 q=(query or '').strip()
 if not q:raise ValueError('query must be a 9-digit organisation number or company name')
 warnings=[]
 if re.fullmatch(r'[\\d -]{9,12}',q):org=normalize_org_number(q);e=db.execute(text(ENTITY),{'org':org}).fetchone()
 else:
  rows=list(db.execute(text(NAME),{'pattern':f'%{q}%'}))
  if len(rows)>1:return {'data':{'query':q,'found':False,'match':'ambiguous','verified':None,'candidates':[{'org_number':r.org_number,'name':r.name,'is_active':r.is_active} for r in rows]},'sources':['brreg'],'confidence':.3,'signals':[],'warnings':['ambiguous name match - retry with the organisation number']}
  e=db.execute(text(ENTITY),{'org':rows[0].org_number}).fetchone() if rows else None;org=rows[0].org_number if rows else None
 if not e:return {'data':{'query':q,'found':False,'match':'none','verified':False,**({'org_number':org} if org else {})},'sources':['brreg'],'confidence':.3,'signals':[],'warnings':['not found in the Enhetsregisteret mirror']}
 ls=e.last_seen_at
 if ls and ls.tzinfo is None:ls=ls.replace(tzinfo=timezone.utc)
 age=(datetime.now(timezone.utc)-ls).total_seconds()/3600 if ls else None;confidence=.95 if age is not None and age<=48 else .8 if age is not None and age<=31*24 else .5
 if age and age>31*24:warnings.append(f'registry mirror stale: last confirmed {age/24:.0f} days ago')
 changes=[{'snapshot_date':iso(r.snapshot_date),'field':r.field_name,'from':r.old_value,'to':r.new_value,'source':r.source} for r in db.execute(text(CHANGES),{'org':e.org_number})]
 freshness={r.pipeline:{'last_success':iso(r.last_success),'last_attempt':iso(r.last_attempt)} for r in db.execute(text(PIPES))}
 signals=[]
 for key,label,val in [('bankruptcy','Konkurs',e.bankruptcy),('under_liquidation','Under avvikling',e.under_liquidation),('forced_liquidation','Under tvangsavvikling eller tvangsoppløsning',e.forced_liquidation)]:
  if val:signals.append({'key':key,'label':label,'value':True,'source':'brreg','direction':'risk'})
 data={'query':q,'found':True,'match':'exact','verified':bool(e.is_active),'country':'NO','identity':{'org_number':e.org_number,'name':e.name,'legal_form':{'code':e.legal_form_code,'label':e.legal_form_label},'registered_address':{'street':e.street,'postcode':e.postcode,'city':e.city,'municipality_code':e.municipality_code,'country_code':e.country_code},'industry':{'code':e.industry_code,'label':e.industry_label},'contact':{'phone':e.phone,'email':e.email,'website':e.website},'registry_source':e.source,'registry_first_seen_at':iso(e.first_seen_at),'registry_last_confirmed_at':iso(e.last_seen_at)},'legal_status':{'is_active':e.is_active,'bankruptcy':e.bankruptcy,'under_liquidation':e.under_liquidation,'forced_liquidation':e.forced_liquidation,'registered_at':iso(e.registered_at),'founded_at':iso(e.founded_at)},'registrations':{'vat':{'status':'not_tracked'},'employer':{'status':'not_tracked'}},'risk':None,'latest_changes':changes,'sources':freshness,'evidence':{'basis':'Norric mirror of Brønnøysund Enhetsregisteret daily bulk and update feed','registry_last_confirmed_at':iso(e.last_seen_at),'reference_links':{'documentation':'https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html','open_data':'https://www.brreg.no/en/use-of-data-from-the-bronnoysund-register-centre/open-data/'},'license':'NLOD 2.0 - attribution: Brønnøysundregistrene'}}
 return {'data':data,'sources':['brreg'],'confidence':confidence,'signals':signals,'warnings':warnings}
