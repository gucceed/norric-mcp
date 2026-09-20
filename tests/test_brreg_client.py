import gzip,json
from ingestion.brreg.normalize import normalize_org_number,map_entity
from ingestion.brreg.client import iter_download

def test_org_number_validation():
 assert normalize_org_number('923 609 016')=='923609016'
 for bad in ('','123','9236090160'):
  try:normalize_org_number(bad);assert False
  except ValueError:pass

def test_map_live_shape_utf8():
 rec=map_entity({'organisasjonsnummer':'923609016','navn':'EQUINOR ASA','organisasjonsform':{'kode':'ASA','beskrivelse':'Allmennaksjeselskap'},'forretningsadresse':{'adresse':['Forusbeen 50'],'postnummer':'4035','poststed':'STAVANGER','kommunenummer':'1103','landkode':'NO'},'naeringskode1':{'kode':'06.100','beskrivelse':'Utvinning av råolje'},'konkurs':False,'underAvvikling':False,'underTvangsavviklingEllerTvangsopplosning':False})
 assert rec['org_number']=='923609016';assert rec['legal_form_code']=='ASA';assert rec['industry_label']=='Utvinning av råolje';assert rec['is_active']

def test_incremental_bulk_parser(tmp_path):
 p=tmp_path/'x.gz';rows=[{'organisasjonsnummer':'923609016'},{'organisasjonsnummer':'971032081'}]
 with gzip.open(p,'wt',encoding='utf-8') as f:json.dump(rows,f)
 assert list(iter_download(p))==rows
