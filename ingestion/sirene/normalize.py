from __future__ import annotations
import re
_SIREN = re.compile(r'\d{9}')

def normalize_siren(value) -> str:
    v = str(value or '').strip()
    if not _SIREN.fullmatch(v): raise ValueError(f'Invalid SIREN: {value!r}. Expected 9 digits')
    return v

def map_company(row: dict) -> dict | None:
    siren = (row or {}).get('siren')
    if not siren: return None
    # Art. A123-96 code de commerce: natural persons may opt out of commercial
    # redistribution. Non-diffusible units never enter the mirror.
    if (row.get('statutDiffusionUniteLegale') or 'O') != 'O': return None
    name = (row.get('denominationUniteLegale') or '').strip()
    if not name:
        name = ' '.join(x for x in [row.get('nomUniteLegale'), row.get('prenom1UniteLegale')] if x) or None
    return {
        'siren': normalize_siren(siren),
        'name': name,
        'legal_form_code': row.get('categorieJuridiqueUniteLegale') or None,
        'legal_form_label': None,
        'is_active': row.get('etatAdministratifUniteLegale') == 'A',
        'registered_at': row.get('dateCreationUniteLegale') or None,
        'dissolved_at': None,
        'company_situations': [],
        'industry_code': row.get('activitePrincipaleUniteLegale') or None,
        'industry_label': None,
        'street': None,
        'city': None,
        'postcode': None,
        'country_code': 'FR',
        'website': None,
        'latest_update': row.get('dateDernierTraitementUniteLegale') or None,
        'raw': dict(row),
    }

def map_siege_address(row: dict) -> dict | None:
    siren = (row or {}).get('siren')
    if not siren: return None
    street = ' '.join(x for x in [
        row.get('numeroVoieEtablissement'), row.get('typeVoieEtablissement'), row.get('libelleVoieEtablissement'),
    ] if x) or None
    return {
        'siren': normalize_siren(siren),
        'street': street,
        'city': row.get('libelleCommuneEtablissement') or None,
        'postcode': row.get('codePostalEtablissement') or None,
    }
