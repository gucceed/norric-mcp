from __future__ import annotations
import re
from datetime import date
_CODE = re.compile(r'\d{8}')

def normalize_registry_code(value) -> str:
    v = str(value or '').strip()
    if not _CODE.fullmatch(v): raise ValueError(f'Invalid Estonian registry code: {value!r}. Expected 8 digits')
    return v

def _ee_date(value):
    # Source dates are DD.MM.YYYY.
    if not value: return None
    try:
        d, m, y = str(value).split('.')
        return date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError): return None

def _current(rows):
    rows = rows or []
    return [r for r in rows if not r.get('lopp_kpv')]

def map_company(raw: dict) -> dict | None:
    code = (raw or {}).get('ariregistri_kood')
    if not code: return None
    y = raw.get('yldandmed') or {}
    names = _current(y.get('arinimed'))
    name = names[-1].get('sisu') if names else raw.get('nimi')
    addrs = _current(y.get('aadressid')); addr = addrs[0] if addrs else {}
    acts = _current(y.get('teatatud_tegevusalad'))
    main = next((a for a in acts if a.get('on_pohitegevusala')), acts[0] if acts else {})
    contacts = _current(y.get('sidevahendid'))
    www = next((c.get('sisu') for c in contacts if c.get('liik') == 'WWW'), None)
    dissolved = y.get('kustutamise_kpv')
    return {
        'registry_code': normalize_registry_code(code),
        'name': name,
        'legal_form_code': y.get('oiguslik_vorm'),
        'legal_form_label': y.get('oiguslik_vorm_tekstina') or None,
        'is_active': y.get('staatus') == 'R' and not dissolved,
        'registered_at': _ee_date(y.get('esmaregistreerimise_kpv')),
        'dissolved_at': _ee_date(dissolved),
        'company_situations': _current(y.get('staatused')),
        'industry_code': main.get('emtak_kood'),
        'industry_label': main.get('emtak_tekstina'),
        'street': addr.get('tanav_maja_korter'),
        'city': addr.get('ehak_nimetus'),
        'postcode': addr.get('postiindeks'),
        'country_code': 'EE',
        'website': www,
        'latest_update': None,
        'raw': raw,
    }
