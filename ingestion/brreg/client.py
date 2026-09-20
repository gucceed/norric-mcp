"""Official Brønnøysund Enhetsregisteret client - Norway country three.

No account or API key is required. The daily complete download seeds the local
copy; /oppdateringer/enheter plus point lookups maintain it. All called hosts
are data.brreg.no (195.43.63.68, AS204027, Brønnøysundregistrene, Norway),
verified 2026-09-20, with no global CDN.
"""
from __future__ import annotations
import gzip, json, os, time
from pathlib import Path
from typing import Iterator
import httpx

BASE_URL=os.environ.get("BRREG_BASE_URL","https://data.brreg.no/enhetsregisteret/api").rstrip("/")
TIMEOUT=httpx.Timeout(120.0,connect=20.0)
class BrregError(RuntimeError): pass

def _get(path, *, params=None, stream=False):
    url=f"{BASE_URL}/{path.lstrip('/')}"
    last=None
    for attempt in range(4):
        try:
            c=httpx.Client(timeout=TIMEOUT,follow_redirects=True,headers={"User-Agent":"Norric/1.0 (edgar@norric.io)"})
            if stream: return c.stream("GET",url,params=params)
            r=c.get(url,params=params); r.raise_for_status(); c.close(); return r
        except (httpx.HTTPError,OSError) as exc:
            last=exc
            if attempt==3: break
            time.sleep(2**attempt)
    raise BrregError(f"Brreg request failed: {type(last).__name__}: {last}")

def download_entities(dest: Path) -> Path:
    dest.mkdir(parents=True,exist_ok=True); out=dest/'brreg-enheter.json.gz'
    with httpx.stream("GET",f"{BASE_URL}/enheter/lastned",timeout=TIMEOUT,follow_redirects=True,
                      headers={"User-Agent":"Norric/1.0 (edgar@norric.io)"}) as r:
        r.raise_for_status()
        with out.open('wb') as f:
            for chunk in r.iter_bytes(): f.write(chunk)
    return out

def iter_download(path: Path) -> Iterator[dict]:
    with gzip.open(path,'rt',encoding='utf-8') as f:
        first=f.read(1)
        if first!='[': raise BrregError('Expected JSON array in Brreg bulk download')
        # Incremental decoder avoids loading the complete registry into RAM.
        dec=json.JSONDecoder(); buf=''; eof=False
        while True:
            while not eof and len(buf)<131072:
                chunk=f.read(131072)
                if chunk: buf+=chunk
                else: eof=True; break
            buf=buf.lstrip(' \r\n\t,')
            if buf.startswith(']'): break
            try: obj,end=dec.raw_decode(buf)
            except json.JSONDecodeError:
                if eof: raise
                continue
            yield obj; buf=buf[end:]

def fetch_updates(since_id:int, size:int=1000)->dict:
    return _get('oppdateringer/enheter',params={'oppdateringsid':since_id+1,'size':min(size,1000)}).json()

def fetch_entity(orgnr:str)->dict|None:
    r=httpx.get(f"{BASE_URL}/enheter/{orgnr}",timeout=TIMEOUT,follow_redirects=True,
                headers={"User-Agent":"Norric/1.0 (edgar@norric.io)"})
    if r.status_code==404:return None
    r.raise_for_status(); return r.json()

def latest_update_id()->int:
    first=_get('oppdateringer/enheter',params={'size':1}).json()
    total=int(first.get('page',{}).get('totalElements') or 0)
    if not total:return 0
    last=_get('oppdateringer/enheter',params={'oppdateringsid':max(total-10,1),'size':10}).json()
    rows=last.get('_embedded',{}).get('oppdaterteEnheter',[])
    return max((int(x.get('oppdateringsid') or 0) for x in rows),default=0)
