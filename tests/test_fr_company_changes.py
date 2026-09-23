from types import SimpleNamespace as NS
from datetime import date,datetime,timezone
from changes.fr_company import company_changes
class DB:
 def execute(self,*a,**k):return [NS(siren='552100554',snapshot_date=date.today(),field_name='name',old_value='Old SA',new_value='New SA',change_source='sirene',name='New SA',legal_form_code='5710',is_active=True,last_seen_at=datetime.now(timezone.utc))]
def test_change_is_source_backed_rename():
 r=company_changes(DB());assert r['data']['events'][0]['event_type']=='rename';assert r['data']['events'][0]['siren']=='552100554'
