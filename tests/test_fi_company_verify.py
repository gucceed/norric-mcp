from types import SimpleNamespace as NS
from verify.fi_company import verify_company
class R:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
class DB:
 def execute(self,stmt,p=None):
  q=str(stmt)
  if 'norric_fi_entities' in q:return R([NS(business_id='0112038-9',name='Nokia Oyj',legal_form_code='17',legal_form_label='Public limited company',is_active=True,registered_at=None,dissolved_at=None,company_situations=[],industry_code='70100',industry_label='Activities of head offices',street=None,city='Espoo',postcode='02610',country_code='FI',website='www.nokia.com',latest_source_update=None,source='prh_ytj',first_seen_at=None,last_seen_at=None,last_updated_at=None)])
  return R([])
def test_verify_business_id():
 r=verify_company(DB(),'0112038-9');assert r['data']['verified'] is True;assert r['data']['country']=='FI';assert r['data']['identity']['name']=='Nokia Oyj'
