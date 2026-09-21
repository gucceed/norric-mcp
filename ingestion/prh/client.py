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
 # The compressed archive is ~100 MB but expands past 1.4 GB. Stream the JSON
 # array so a worker never holds the complete Finnish registry in memory.
 with zipfile.ZipFile(path) as z:
  names=[n for n in z.namelist() if n.lower().endswith('.json')]
  if not names:raise PrhError('PRH archive contains no JSON file')
  with z.open(names[0]) as raw:
   import io
   f=io.TextIOWrapper(raw,encoding='utf-8');first=f.read(1)
   if first!='[':raise PrhError('Expected a JSON array in PRH bulk archive')
   dec=json.JSONDecoder();buf='';eof=False
   while True:
    while not eof and len(buf)<131072:
     chunk=f.read(131072)
     if chunk:buf+=chunk
     else:eof=True;break
    buf=buf.lstrip(' \r\n\t,')
    if buf.startswith(']'):break
    try:obj,end=dec.raw_decode(buf)
    except json.JSONDecodeError:
     if eof:raise
     continue
    yield obj;buf=buf[end:]

def search_companies(**params)->dict:
 r=httpx.get(f'{BASE_URL}/companies',params=params,timeout=TIMEOUT,follow_redirects=True,headers={'User-Agent':'Norric/1.0 (edgar@norric.io)'})
 r.raise_for_status();return r.json()
