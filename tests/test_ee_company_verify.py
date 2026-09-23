from types import SimpleNamespace as NS
from verify.ee_company import verify_company
class R:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
class DB:
 def execute(self,stmt,p=None):
  q=str(stmt)
  if 'norric_ee_entities' in q:return R([NS(registry_code='12409465',name='Wise Europe SA',legal_form_code='AS',legal_form_label='Aktsiaselts',is_active=True,registered_at=None,dissolved_at=None,company_situations=[],industry_code='66190',industry_label='Other activities auxiliary to financial services',street=None,city='Tallinn',postcode='10111',country_code='EE',website='www.wise.com',latest_source_update=None,source='ariregister',first_seen_at=None,last_seen_at=None,last_updated_at=None)])
  return R([])
def test_verify_registry_code():
 r=verify_company(DB(),'12409465');assert r['data']['verified'] is True;assert r['data']['country']=='EE';assert r['data']['identity']['name']=='Wise Europe SA'
