from __future__ import annotations
import re
_BID=re.compile(r'\d{7}-\d')
def normalize_business_id(value)->str:
 v=str(value or '').strip()
 if not _BID.fullmatch(v):raise ValueError(f'Invalid Finnish Business ID: {value!r}. Expected 1234567-8')
 return v

def _current(rows):
 rows=rows or []
 return next((x for x in rows if x.get('version')==1 or not x.get('endDate')),rows[0] if rows else {})
def _desc(obj):
 ds=(obj or {}).get('descriptions') or []
 return next((d.get('description') for d in ds if str(d.get('languageCode'))=='3'),None) or next((d.get('description') for d in ds),None)
def map_company(raw:dict)->dict|None:
 b=(raw or {}).get('businessId') or {};bid=b.get('value')
 if not bid:return None
 names=_current(raw.get('names'));form=_current(raw.get('companyForms'));addrs=raw.get('addresses') or []
 addr=next((a for a in addrs if str(a.get('type'))=='1' and not a.get('endDate')),next((a for a in addrs if not a.get('endDate')),{}))
 situs=raw.get('companySituations') or [];active_situs=[s for s in situs if not s.get('endDate')]
 labels=[(_desc(s) or '').lower() for s in active_situs]
 dissolved=bool(raw.get('dissolutionDate'));inactive=dissolved or any(x in ' '.join(labels) for x in ('bankrupt','liquidat','restructur'))
 ind=raw.get('mainBusinessLine') or {};town=addr.get('postOffices') or addr.get('postOffice')
 if isinstance(town,list):town=next((x.get('city') or x.get('name') for x in town if isinstance(x,dict)),None)
 return {'business_id':normalize_business_id(bid),'name':names.get('name'),'legal_form_code':form.get('type'),'legal_form_label':_desc(form),'is_active':not inactive,'registered_at':raw.get('registrationDate') or b.get('registrationDate'),'dissolved_at':raw.get('dissolutionDate'),'company_situations':active_situs,'industry_code':ind.get('type'),'industry_label':_desc(ind),'street':addr.get('street'),'city':town,'postcode':addr.get('postCode'),'country_code':addr.get('country') or 'FI','website':(raw.get('website') or {}).get('url'),'latest_update':raw.get('lastModified'),'raw':raw}
