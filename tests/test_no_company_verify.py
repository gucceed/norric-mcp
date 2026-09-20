from types import SimpleNamespace as NS
from datetime import datetime,timezone
from verify.no_company import verify_company
class R:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
class DB:
 def __init__(self,e=None):self.e=e
 def execute(self,stmt,params=None):
  q=str(stmt)
  if 'norric_no_entities' in q:return R([self.e] if self.e else [])
  if 'norric_no_field_changes' in q:return R([])
  if 'norric_pipeline_runs' in q:return R([NS(pipeline='brreg_bulk',last_success=datetime.now(timezone.utc),last_attempt=datetime.now(timezone.utc))])
  return R([])
def entity():return NS(org_number='923609016',name='EQUINOR ASA',legal_form_code='ASA',legal_form_label='Allmennaksjeselskap',is_active=True,registered_at='2019-10-23',founded_at='2019-05-15',bankruptcy=False,under_liquidation=False,forced_liquidation=False,industry_code='06.100',industry_label='Utvinning av råolje',street='Forusbeen 50',city='STAVANGER',postcode='4035',municipality_code='1103',country_code='NO',phone=None,email=None,website='equinor.com',source='brreg_bulk',first_seen_at=datetime.now(timezone.utc),last_seen_at=datetime.now(timezone.utc),last_updated_at=datetime.now(timezone.utc))
def test_exact_verify():
 d=verify_company(DB(entity()),'923609016');assert d['data']['verified'];assert d['data']['identity']['org_number']=='923609016';assert d['data']['evidence']['license'].startswith('NLOD')
def test_not_found_honest():
 d=verify_company(DB(),'923609016');assert d['data']['found'] is False
