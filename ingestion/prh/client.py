"""Official PRH/YTJ open-data client - Finland country four.

The daily all_companies ZIP is the baseline. The public API has no delta feed;
daily snapshots are diffed locally. No API key or account is required.
"""
from __future__ import annotations
import json, os, time, zipfile
from pathlib import Path
from typing import Iterator
import httpx
BASE_URL=os.environ.get("PRH_BASE_URL","https://avoindata.prh.fi/opendata-ytj-api/v3").rstrip("/")
TIMEOUT=httpx.Timeout(180.0,connect=20.0)
class PrhError(RuntimeError): pass

def download_companies(dest:Path)->Path:
 dest.mkdir(parents=True,exist_ok=True);out=dest/'prh-all-companies.zip';last=None
 for attempt in range(4):
  try:
   with httpx.stream('GET',f'{BASE_URL}/all_companies',timeout=TIMEOUT,follow_redirects=True,headers={'User-Agent':'Norric/1.0 (edgar@norric.io)'}) as r:
    r.raise_for_status()
    with out.open('wb') as f:
     for chunk in r.iter_bytes():f.write(chunk)
   return out
  except (httpx.HTTPError,OSError) as exc:
   last=exc
   if attempt<3:time.sleep(2**attempt)
 raise PrhError(f'PRH download failed: {type(last).__name__}: {last}')

def iter_download(path:Path)->Iterator[dict]:
 with zipfile.ZipFile(path) as z:
  names=[n for n in z.namelist() if n.lower().endswith('.json')]
  if not names:raise PrhError('PRH archive contains no JSON file')
  with z.open(names[0]) as raw:
   data=json.load(raw)
  rows=data.get('companies',data) if isinstance(data,dict) else data
  if not isinstance(rows,list):raise PrhError('Unexpected PRH bulk shape')
  yield from rows

def search_companies(**params)->dict:
 r=httpx.get(f'{BASE_URL}/companies',params=params,timeout=TIMEOUT,follow_redirects=True,headers={'User-Agent':'Norric/1.0 (edgar@norric.io)'})
 r.raise_for_status();return r.json()
