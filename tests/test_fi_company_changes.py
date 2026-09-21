from types import SimpleNamespace as NS
from datetime import date,datetime,timezone
from changes.fi_company import company_changes
class DB:
 def execute(self,*a,**k):return [NS(business_id='0112038-9',snapshot_date=date.today(),field_name='name',old_value='Old Oy',new_value='New Oy',change_source='prh_ytj',name='New Oy',legal_form_code='16',is_active=True,last_seen_at=datetime.now(timezone.utc))]
def test_change_is_source_backed_rename():
 r=company_changes(DB());assert r['data']['events'][0]['event_type']=='rename';assert r['data']['events'][0]['business_id']=='0112038-9'
