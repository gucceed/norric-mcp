from types import SimpleNamespace as NS
from verify.fr_company import verify_company
class R:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def __iter__(self):return iter(self.rows)
class DB:
 def execute(self,stmt,p=None):
  q=str(stmt)
  if 'norric_fr_entities' in q:return R([NS(siren='552100554',name='SOCIETE GENERALE',legal_form_code='5710',legal_form_label='Societe anonyme',is_active=True,registered_at=None,dissolved_at=None,company_situations=[],industry_code='64.19Z',industry_label='Autres intermidiations monetaires',street=None,city='PARIS 9',postcode='75009',country_code='FR',website=None,latest_source_update=None,source='sirene',first_seen_at=None,last_seen_at=None,last_updated_at=None)])
  return R([])
def test_verify_siren():
 r=verify_company(DB(),'552100554');assert r['data']['verified'] is True;assert r['data']['country']=='FR';assert r['data']['identity']['name']=='SOCIETE GENERALE'
