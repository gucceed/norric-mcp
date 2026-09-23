"""Official Sirene open-data client - France country six prep.

The baseline is the monthly-refreshed StockUniteLegale CSV published on
data.gouv.fr (Licence Ouverte 2.0), with siege-establishment addresses from
StockEtablissement. No key or account is needed. The keyless
recherche-entreprises.api.gouv.fr search API (7 req/s per IP) is the point
lookup fallback; the account-gated INSEE API Sirene (30 calls/min) is not
required for the baseline.
"""
from __future__ import annotations
import csv, io, os, time, zipfile
from pathlib import Path
from typing import Iterator
import httpx
DATASET_API = os.environ.get(
    'SIRENE_DATASET_API',
    'https://www.data.gouv.fr/api/1/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/',
)
SEARCH_API = 'https://recherche-entreprises.api.gouv.fr/search'
TIMEOUT = httpx.Timeout(600.0, connect=20.0)
HEADERS = {'User-Agent': 'Norric/1.0 (edgar@norric.io)'}
class SireneError(RuntimeError): pass

def latest_resource_url(kind: str = 'StockUniteLegale') -> str:
    # Resource URLs carry a sortable date directory (…/20260901-083236/…).
    r = httpx.get(DATASET_API, timeout=httpx.Timeout(30.0), follow_redirects=True, headers=HEADERS)
    r.raise_for_status()
    urls = [
        res['url'] for res in r.json().get('resources', [])
        if f'Fichier {kind}' in (res.get('title') or '')
        and 'parquet' not in (res.get('title') or '').lower()
        and (res.get('url') or '').endswith('.zip')
    ]
    if not urls: raise SireneError(f'No {kind} CSV resource found on data.gouv.fr')
    return sorted(urls)[-1]

def download_stock(dest: Path, kind: str = 'StockUniteLegale', url: str | None = None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f'sirene-{kind.lower()}.csv.zip'
    src = url or latest_resource_url(kind)
    last = None
    for attempt in range(4):
        try:
            with httpx.stream('GET', src, timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as r:
                r.raise_for_status()
                with out.open('wb') as f:
                    for chunk in r.iter_bytes(): f.write(chunk)
            return out
        except (httpx.HTTPError, OSError) as exc:
            last = exc
            if attempt < 3: time.sleep(2 ** attempt)
    raise SireneError(f'Sirene download failed: {type(last).__name__}: {last}')

def _iter_csv(path: Path) -> Iterator[dict]:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if not names: raise SireneError('Sirene archive contains no CSV file')
        with z.open(names[0]) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8'))

def iter_unite_legale(path: Path) -> Iterator[dict]:
    yield from _iter_csv(path)

def iter_siege_addresses(path: Path) -> Iterator[dict]:
    # StockEtablissement is tens of millions of rows; only siege rows carry the
    # headquarters address onto the legal unit.
    for row in _iter_csv(path):
        if (row.get('etablissementSiege') or '').lower() == 'true':
            yield row
