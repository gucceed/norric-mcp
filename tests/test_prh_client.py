import json,zipfile
from ingestion.prh.client import iter_download
from ingestion.prh.normalize import normalize_business_id,map_company

def test_business_id_validation():
 assert normalize_business_id('0112038-9')=='0112038-9'

def test_map_company_preserves_official_codes():
 row={'businessId':{'value':'0112038-9','registrationDate':'1978-03-15'},'names':[{'name':'Nokia Oyj','version':1}],'companyForms':[{'type':'17','version':1,'descriptions':[{'languageCode':'3','description':'Public limited company'}]}],'mainBusinessLine':{'type':'70100','descriptions':[{'languageCode':'3','description':'Activities of head offices'}]},'companySituations':[],'addresses':[{'type':'1','street':'Karakaari 7','postCode':'02610','postOffice':'Espoo'}],'website':{'url':'www.nokia.com'}}
 out=map_company(row);assert out['business_id']=='0112038-9';assert out['name']=='Nokia Oyj';assert out['legal_form_code']=='17';assert out['is_active'] is True

def test_iter_zip(tmp_path):
 p=tmp_path/'all.zip'
 with zipfile.ZipFile(p,'w') as z:z.writestr('companies.json',json.dumps({'companies':[{'businessId':{'value':'0112038-9'}}]}))
 assert list(iter_download(p))[0]['businessId']['value']=='0112038-9'
