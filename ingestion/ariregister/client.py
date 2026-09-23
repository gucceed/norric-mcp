"""Official e-Ariregister open-data client - Estonia country five prep.

The daily general-data JSON archive is the baseline. The real-time interface is
the legacy contract SOAP/XML service (ariregxmlv6.rik.ee), which needs a signed
RIK contract and is out of scope for the post-Stockholm baseline. The open-data
files need no key or account; downloading accepts the CC BY 4.0 licence.
"""
from __future__ import annotations
import io, json, os, time, zipfile
from pathlib import Path
from typing import Iterator
import httpx
GENERAL_URL = os.environ.get(
    'ARIREGISTER_GENERAL_URL',
    'https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/ettevotja_rekvisiidid__yldandmed.json.zip',
)
TIMEOUT = httpx.Timeout(300.0, connect=20.0)
HEADERS = {'User-Agent': 'Norric/1.0 (edgar@norric.io)'}
class AriregisterError(RuntimeError): pass

def download_companies(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / 'ariregister-yldandmed.json.zip'
    last = None
    for attempt in range(4):
        try:
            with httpx.stream('GET', GENERAL_URL, timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as r:
                r.raise_for_status()
                with out.open('wb') as f:
                    for chunk in r.iter_bytes(): f.write(chunk)
            return out
        except (httpx.HTTPError, OSError) as exc:
            last = exc
            if attempt < 3: time.sleep(2 ** attempt)
    raise AriregisterError(f'Ariregister download failed: {type(last).__name__}: {last}')

def iter_download(path: Path) -> Iterator[dict]:
    # The archive holds one pretty-printed JSON array (~215 MB compressed).
    # Stream it so a worker never holds the full Estonian register in memory.
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.json')]
        if not names: raise AriregisterError('Ariregister archive contains no JSON file')
        with z.open(names[0]) as raw:
            f = io.TextIOWrapper(raw, encoding='utf-8')
            first = f.read(1)
            if first != '[': raise AriregisterError('Expected a JSON array in Ariregister bulk archive')
            dec = json.JSONDecoder(); buf = ''; eof = False
            while True:
                while not eof and len(buf) < 131072:
                    chunk = f.read(131072)
                    if chunk: buf += chunk
                    else: eof = True; break
                buf = buf.lstrip(' \r\n\t,')
                if buf.startswith(']') or not buf: break
                try: obj, end = dec.raw_decode(buf)
                except json.JSONDecodeError:
                    if eof: raise
                    continue
                yield obj; buf = buf[end:]
