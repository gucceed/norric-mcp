from __future__ import annotations
import re
_ORG=re.compile(r"\d{9}")
def normalize_org_number(value)->str:
    clean=str(value or '').replace(' ','').replace('-','')
    if not _ORG.fullmatch(clean): raise ValueError(f"Invalid Norwegian organisation number: {value!r}. Expected 9 digits")
    return clean

def _address(a):
    a=a or {}; lines=a.get('adresse') or []
    return {'street':', '.join(str(x) for x in lines) or None,'city':a.get('poststed'),'postcode':a.get('postnummer'),
            'municipality_code':a.get('kommunenummer'),'country_code':a.get('landkode'),'raw_address':a}

def map_entity(row:dict)->dict|None:
    raw=row or {}; n=raw.get('organisasjonsnummer')
    if not n:return None
    org=normalize_org_number(n); addr=_address(raw.get('forretningsadresse') or raw.get('postadresse'))
    form=raw.get('organisasjonsform') or {}; ind=raw.get('naeringskode1') or {}
    inactive=bool(raw.get('konkurs') or raw.get('underAvvikling') or raw.get('underTvangsavviklingEllerTvangsopplosning'))
    return {'org_number':org,'name':raw.get('navn'),'legal_form_code':form.get('kode'),'legal_form_label':form.get('beskrivelse'),
      'is_active':not inactive,'registered_at':raw.get('registreringsdatoEnhetsregisteret'),'founded_at':raw.get('stiftelsesdato'),
      'bankruptcy':bool(raw.get('konkurs')),'under_liquidation':bool(raw.get('underAvvikling')),
      'forced_liquidation':bool(raw.get('underTvangsavviklingEllerTvangsopplosning')),
      'industry_code':ind.get('kode'),'industry_label':ind.get('beskrivelse'),**addr,
      'phone':raw.get('telefon') or raw.get('mobil'),'email':raw.get('epostadresse'),'website':raw.get('hjemmeside'),'raw':raw}
