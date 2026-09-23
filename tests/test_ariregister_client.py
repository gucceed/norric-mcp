import json, zipfile
from ingestion.ariregister.client import iter_download
from ingestion.ariregister.normalize import normalize_registry_code, map_company

SAMPLE = {'ariregistri_kood': 16752073, 'nimi': '007 Agent & Partners OÜ', 'yldandmed': {
    'esmaregistreerimise_kpv': '05.06.2023', 'kustutamise_kpv': None, 'staatus': 'R',
    'oiguslik_vorm': 'OÜ', 'oiguslik_vorm_tekstina': 'Osaühing',
    'staatused': [{'staatus': 'R', 'staatus_tekstina': 'Registrisse kantud', 'algus_kpv': '05.06.2023'}],
    'arinimed': [{'sisu': '007 Agent & Partners OÜ', 'algus_kpv': '05.06.2023', 'lopp_kpv': None}],
    'aadressid': [{'riik': 'EST', 'ehak_nimetus': 'Pirita linnaosa, Tallinn, Harju maakond',
                   'tanav_maja_korter': 'Regati pst 12', 'postiindeks': '11911', 'lopp_kpv': None}],
    'teatatud_tegevusalad': [{'emtak_kood': '73111', 'emtak_tekstina': 'Reklaamiagentuuride tegevus',
                              'on_pohitegevusala': True, 'lopp_kpv': None}],
    'sidevahendid': [{'liik': 'WWW', 'sisu': 'https://007agentandpartners.com/', 'lopp_kpv': None}]}}

def test_registry_code_validation():
    assert normalize_registry_code('16752073') == '16752073'
    assert normalize_registry_code(16752073) == '16752073'

def test_map_company_preserves_official_codes():
    out = map_company(SAMPLE)
    assert out['registry_code'] == '16752073'
    assert out['name'] == '007 Agent & Partners OÜ'
    assert out['legal_form_code'] == 'OÜ'
    assert out['is_active'] is True
    assert out['registered_at'] == '2023-06-05'
    assert out['industry_code'] == '73111'
    assert out['postcode'] == '11911'
    assert out['website'] == 'https://007agentandpartners.com/'

def test_iter_zip(tmp_path):
    p = tmp_path / 'all.zip'
    with zipfile.ZipFile(p, 'w') as z: z.writestr('yldandmed.json', json.dumps([SAMPLE]))
    assert list(iter_download(p))[0]['ariregistri_kood'] == 16752073
