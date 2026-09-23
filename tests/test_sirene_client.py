import csv, io, zipfile
from ingestion.sirene.client import iter_siege_addresses, iter_unite_legale
from ingestion.sirene.normalize import map_company, map_siege_address, normalize_siren

ROW = {'siren': '552100554', 'statutDiffusionUniteLegale': 'O', 'dateCreationUniteLegale': '1970-01-01',
       'denominationUniteLegale': 'LIVRAISON EXPRESS SA', 'nomUniteLegale': None, 'prenom1UniteLegale': None,
       'categorieJuridiqueUniteLegale': '5710', 'activitePrincipaleUniteLegale': '52.29B',
       'etatAdministratifUniteLegale': 'A', 'dateDernierTraitementUniteLegale': '2026-08-14T09:12:00'}
SIEGE = {'siren': '552100554', 'etablissementSiege': 'true', 'numeroVoieEtablissement': '12',
         'typeVoieEtablissement': 'RUE', 'libelleVoieEtablissement': 'DE LA PAIX',
         'codePostalEtablissement': '75002', 'libelleCommuneEtablissement': 'PARIS 02'}

def test_siren_validation():
    assert normalize_siren('552100554') == '552100554'

def test_map_company_preserves_official_codes():
    out = map_company(ROW)
    assert out['siren'] == '552100554'
    assert out['name'] == 'LIVRAISON EXPRESS SA'
    assert out['legal_form_code'] == '5710'
    assert out['is_active'] is True
    assert out['industry_code'] == '52.29B'

def test_non_diffusible_never_mirrored():
    assert map_company({**ROW, 'statutDiffusionUniteLegale': 'N'}) is None
    assert map_company({**ROW, 'statutDiffusionUniteLegale': 'P'}) is None

def test_siege_address_mapping():
    out = map_siege_address(SIEGE)
    assert out['street'] == '12 RUE DE LA PAIX'
    assert out['postcode'] == '75002'

def test_iter_csv_zip(tmp_path):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(ROW)); w.writeheader(); w.writerow(ROW)
    p = tmp_path / 'stock.zip'
    with zipfile.ZipFile(p, 'w') as z: z.writestr('StockUniteLegale.csv', buf.getvalue())
    assert list(iter_unite_legale(p))[0]['siren'] == '552100554'
    buf2 = io.StringIO()
    w = csv.DictWriter(buf2, fieldnames=list(SIEGE)); w.writeheader(); w.writerow(SIEGE); w.writerow({**SIEGE, 'etablissementSiege': 'false'})
    p2 = tmp_path / 'etab.zip'
    with zipfile.ZipFile(p2, 'w') as z: z.writestr('StockEtablissement.csv', buf2.getvalue())
    assert len(list(iter_siege_addresses(p2))) == 1
