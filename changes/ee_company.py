from __future__ import annotations
from collections import OrderedDict
from datetime import datetime,timezone,timedelta
from sqlalchemy import text
from ingestion.ariregister.normalize import normalize_registry_code
TOOL_NAME='estonian_company_changes_v1';ALLOWED_EVENT_TYPES={'new_registration','closure','rename','address_change','dissolution','legal_status'}
SQL='''SELECT c.entity_id registry_code,c.snapshot_date,c.field_name,c.old_value,c.new_value,c.source change_source,e.name,e.legal_form_code,e.is_active,e.last_seen_at FROM norric_ee_field_changes c LEFT JOIN norric_ee_entities e ON e.registry_code=c.entity_id WHERE c.snapshot_date>=:since AND (:rc IS NULL OR c.entity_id=:rc) ORDER BY c.snapshot_date DESC,c.entity_id,c.field_name LIMIT :lim'''
def iso(v):return None if v is None else (v.isoformat() if hasattr(v,'isoformat') else str(v))
def kind(f,o,n):
 if f=='name':return 'rename'
 if f in {'street','city','postcode'}:return 'address_change'
 if f=='registered_at' and not o and n:return 'new_registration'
 if f=='dissolved_at' and not o and n:return 'dissolution'
 if f=='is_active' and str(n).lower() in {'false','0'}:return 'closure'
 if f in {'legal_form_code'}:return 'legal_status'
def company_changes(db,*,days=7,event_types=None,limit=25,registry_code=None):
 if not 1<=days<=30:raise ValueError('days must be between 1 and 30')
 if not 1<=limit<=100:raise ValueError('limit must be between 1 and 100')
 selected=set(event_types or ALLOWED_EVENT_TYPES);unknown=selected-ALLOWED_EVENT_TYPES
 if unknown:raise ValueError('unsupported event_types: '+', '.join(sorted(unknown)))
 rc=normalize_registry_code(registry_code) if registry_code else None;since=(datetime.now(timezone.utc)-timedelta(days=days)).date();grouped=OrderedDict()
 for r in db.execute(text(SQL),{'since':since,'rc':rc,'lim':min(limit*12,1200)}):
  k=kind(r.field_name,r.old_value,r.new_value)
  if not k or k not in selected:continue
  key=(r.registry_code,iso(r.snapshot_date),k);ev=grouped.setdefault(key,{'event_type':k,'registry_code':r.registry_code,'company_name':r.name,'legal_form_code':r.legal_form_code,'is_active':r.is_active,'detected_on':iso(r.snapshot_date),'changes':[],'source':'ariregister','source_last_confirmed_at':iso(r.last_seen_at),'evidence':{'basis':'Norric diff of daily e-Ariregister snapshots','license':'CC BY 4.0'}});ev['changes'].append({'field':r.field_name,'from':r.old_value,'to':r.new_value})
 events=list(grouped.values())[:limit]
 return {'data':{'country':'EE','window':{'days':days,'since':since.isoformat()},'filters':{'event_types':sorted(selected),'registry_code':rc,'limit':limit},'count':len(events),'events':events,'event_type_contract':sorted(ALLOWED_EVENT_TYPES)},'sources':['ariregister'],'confidence':.95,'warnings':[] if events else ['No matching registry changes were recorded in this window.']}
