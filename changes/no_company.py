from __future__ import annotations
from collections import OrderedDict
from datetime import datetime,timezone,timedelta
from sqlalchemy import text
from ingestion.brreg.normalize import normalize_org_number
TOOL_NAME='norwegian_company_changes_v1';ALLOWED_EVENT_TYPES={'new_registration','closure','rename','address_change','bankruptcy','liquidation'}
SQL="""SELECT c.entity_id org_number,c.snapshot_date,c.field_name,c.old_value,c.new_value,c.source change_source,e.name,e.legal_form_code,e.is_active,e.last_seen_at FROM norric_no_field_changes c LEFT JOIN norric_no_entities e ON e.org_number=c.entity_id WHERE c.snapshot_date>=:since AND (:org IS NULL OR c.entity_id=:org) ORDER BY c.snapshot_date DESC,c.entity_id,c.field_name LIMIT :lim"""
PIPES="SELECT pipeline,MAX(completed_at) FILTER(WHERE status='success') last_success,MAX(started_at) last_attempt FROM norric_pipeline_runs WHERE pipeline IN ('brreg_bulk','brreg_updates') GROUP BY pipeline"
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def kind(field,old,new):
 f=(field or '').lower()
 if f=='name':return 'rename'
 if f in {'street','city','postcode','municipality_code','country_code','raw_address'}:return 'address_change'
 if f=='registered_at' and not old and new:return 'new_registration'
 if f=='bankruptcy' and str(new).lower() in {'true','1'}:return 'bankruptcy'
 if f in {'under_liquidation','forced_liquidation'} and str(new).lower() in {'true','1'}:return 'liquidation'
 if f=='is_active' and str(new).lower() in {'false','0'}:return 'closure'
def company_changes(db,*,days=7,event_types=None,limit=25,org_number=None):
 if not 1<=days<=30:raise ValueError('days must be between 1 and 30')
 if not 1<=limit<=100:raise ValueError('limit must be between 1 and 100')
 selected=set(event_types or ALLOWED_EVENT_TYPES);unknown=selected-ALLOWED_EVENT_TYPES
 if unknown:raise ValueError('unsupported event_types: '+', '.join(sorted(unknown)))
 org=normalize_org_number(org_number) if org_number else None;since=(datetime.now(timezone.utc)-timedelta(days=days)).date();grouped=OrderedDict()
 for r in db.execute(text(SQL),{'since':since,'org':org,'lim':min(limit*12,1200)}):
  k=kind(r.field_name,r.old_value,r.new_value)
  if not k or k not in selected:continue
  key=(r.org_number,iso(r.snapshot_date),k);ev=grouped.setdefault(key,{'event_type':k,'org_number':r.org_number,'company_name':r.name,'legal_form_code':r.legal_form_code,'is_active':r.is_active,'effective_on':iso(r.snapshot_date),'detected_on':iso(r.snapshot_date),'changes':[],'source':r.change_source or 'brreg','source_last_confirmed_at':iso(r.last_seen_at),'evidence':{'basis':'Norric Brønnøysund registry diff (daily bulk + update deltas)','reference_links':{'documentation':'https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html'},'license':'NLOD 2.0 - attribution: Brønnøysundregistrene'}});ev['changes'].append({'field':r.field_name,'from':r.old_value,'to':r.new_value})
 events=list(grouped.values())[:limit];fresh={r.pipeline:{'last_success':iso(r.last_success),'last_attempt':iso(r.last_attempt)} for r in db.execute(text(PIPES))};warnings=[] if events else ['No matching registry changes were recorded in this window.']
 return {'data':{'country':'NO','window':{'days':days,'since':since.isoformat()},'filters':{'event_types':sorted(selected),'org_number':org,'limit':limit},'count':len(events),'events':events,'source_freshness':fresh,'event_type_contract':sorted(ALLOWED_EVENT_TYPES)},'sources':['brreg'],'confidence':.95 if any(x['last_success'] for x in fresh.values()) else .7,'warnings':warnings}
