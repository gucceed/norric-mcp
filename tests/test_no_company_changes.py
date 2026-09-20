from types import SimpleNamespace as NS
from datetime import date,datetime,timezone
from changes.no_company import company_changes
class DB:
 def execute(self,stmt,params=None):
  if 'norric_no_field_changes' in str(stmt):return [NS(org_number='923609016',snapshot_date=date.today(),field_name='bankruptcy',old_value='False',new_value='True',change_source='brreg_updates',name='EQUINOR ASA',legal_form_code='ASA',is_active=False,last_seen_at=datetime.now(timezone.utc))]
  return [NS(pipeline='brreg_updates',last_success=datetime.now(timezone.utc),last_attempt=datetime.now(timezone.utc))]
def test_bankruptcy_change():
 d=company_changes(DB(),event_types=['bankruptcy']);assert d['data']['count']==1;assert d['data']['events'][0]['event_type']=='bankruptcy'
def test_limits():
 try:company_changes(DB(),days=31);assert False
 except ValueError:pass
