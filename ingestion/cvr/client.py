"""
Datafordeler CVR client - Denmark country two.

Two first-party interfaces, both official Erhvervsstyrelsen/Datafordeleren
services (ground data, CC BY 4.0, attribution required):

1. Fildownload REST API - weekly total downloads per entity, JSON or CSV.
   Generated Saturday night 03:00-06:00, archived 7 days.
   https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/cvr-fildownload/
   Versioned endpoint: https://api.datafordeler.dk/FileDownloads/v1.0/GetFile

2. Entity-based GraphQL - point lookups plus the CVR_Events change entity
   and DAF_RegisterImportStatus package-completeness marker.
   https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/cvr-graphql/
   https://confluence.kds.dk/pages/viewpage.action?pageId=219514028
   Endpoint shape: https://graphql.datafordeler.dk/<Register>/<version>

The legacy "Hændelser (CVR)" services on services.datafordeler.dk are being
phased out (ultimo 2026 / 15 January 2027 per KDS docs) and are NOT used here.

EU residency: api.datafordeler.dk and graphql.datafordeler.dk both resolve to
87.60.242.40, AS3292 (TDC, Denmark) - verified 2026-09-20. No global CDN is
involved on these endpoints. datacvr.virk.dk is Cloudflare-fronted and is
never called by this client.

Credentials come from the environment; nothing is hardcoded:
  DATAFORDELER_API_KEY   - API key for Fildownload + GraphQL (zone 0 entities)
No numeric rate quota is published by Datafordeleren, so every call runs with
bounded retries, 429/5xx backoff and a per-run request budget.
"""
from __future__ import annotations

import json
import logging
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

FILEDOWNLOAD_BASE = os.environ.get(
    "DATAFORDELER_FILEDOWNLOAD_BASE",
    "https://api.datafordeler.dk/FileDownloads/v1.0",
)
GRAPHQL_URL = os.environ.get(
    "DATAFORDELER_GRAPHQL_URL",
    "https://graphql.datafordeler.dk/CVR/v1",
)
REGISTER = "CVR"

# Entities Norric ingests for the company spine. CVRPerson is access-restricted
# and deliberately excluded. Beneficial owners (reelle ejere) are restricted
# since 2025-09-01 and deliberately excluded.
BULK_ENTITIES = (
    "Virksomhed",
    "Navn",
    "Adressering",
    "Branche",
    "Virksomhedsform",
    "Produktionsenhed",
)

_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 2.0
_REQUEST_TIMEOUT = 120.0
_STREAM_CHUNK = 65536


class DatafordelerError(RuntimeError):
    pass


class DatafordelerConfigError(DatafordelerError):
    pass


def _api_key() -> str:
    key = os.environ.get("DATAFORDELER_API_KEY", "").strip()
    if not key:
        raise DatafordelerConfigError(
            "DATAFORDELER_API_KEY is not set - create a Datafordeler user, "
            "register an IT system and issue an API key (see docs/denmark-cvr.md)."
        )
    return key


def _request_with_backoff(method: str, url: str, **kwargs) -> httpx.Response:
    delay = _BACKOFF_BASE_SECONDS
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.request(method, url, timeout=_REQUEST_TIMEOUT,
                                 follow_redirects=True, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                log.warning("datafordeler %s -> HTTP %s (attempt %d)",
                            url.split("?")[0], resp.status_code, attempt + 1)
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            log.warning("datafordeler %s -> %s (attempt %d)",
                        url.split("?")[0], type(exc).__name__, attempt + 1)
            time.sleep(delay)
            delay *= 2
    raise DatafordelerError(
        f"datafordeler request failed after {_MAX_RETRIES} attempts: "
        f"{url.split('?')[0]} ({last_exc or 'HTTP error'})"
    )


def get_available_file_downloads() -> list[dict[str, Any]]:
    """List available CVR file downloads (metadata incl. extraction numbers
    and, per Datafordeler docs, register-import sequence metadata)."""
    resp = _request_with_backoff(
        "GET",
        f"{FILEDOWNLOAD_BASE}/GetAvailableFileDownloads",
        params={"Register": REGISTER, "apiKey": _api_key()},
    )
    data = resp.json()
    if isinstance(data, dict):
        for key in ("FileDownloads", "files", "value", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data if isinstance(data, list) else []


def download_latest_total(entity: str, dest_dir: Path,
                          temporal_type: str = "current",
                          fmt: str = "JSON") -> Path:
    """Download the latest total download zip for one CVR entity."""
    resp = _request_with_backoff(
        "GET",
        f"{FILEDOWNLOAD_BASE}/GetFile",
        params={
            "Register": REGISTER,
            "LatestTotalForEntity": entity,
            "type": temporal_type,
            "format": fmt,
            "apiKey": _api_key(),
        },
    )
    zip_path = dest_dir / f"CVR_{entity}_TotalDownload_{temporal_type}.{fmt.lower()}.zip"
    zip_path.write_bytes(resp.content)
    return zip_path


def extract_json_rows(zip_path: Path) -> list[dict[str, Any]]:
    """Extract entity rows from a total-download zip.

    The zip contains one JSON file. Defensive about the envelope: a bare
    array, an object wrapping the array, or newline-delimited JSON. Rows are
    returned as-is; normalization happens in normalize.py and unmapped fields
    are preserved in the entity's raw column - never dropped silently, never
    invented.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not names:
            raise DatafordelerError(f"no JSON file inside {zip_path.name}")
        text = zf.read(names[0]).decode("utf-8-sig")

    stripped = text.lstrip()
    if not stripped:
        return []
    payload = None
    if stripped.startswith(("[", "{")):
        try:
            doc = json.loads(stripped)
            if isinstance(doc, list):
                payload = doc
            else:
                for key in ("features", "items", "value", "data"):
                    if isinstance(doc.get(key), list):
                        payload = doc[key]
                        break
                else:
                    payload = [doc]
        except json.JSONDecodeError:
            payload = None  # newline-delimited JSON
    if payload is None:
        payload = [json.loads(line) for line in stripped.splitlines() if line.strip()]

    rows = []
    for i, item in enumerate(payload):
        if isinstance(item, dict):
            rows.append(item)
        else:
            log.warning("skipping non-object row %d in %s", i, zip_path.name)
    return rows


def graphql(query: str, variables: Optional[dict] = None) -> dict[str, Any]:
    """Run a GraphQL query against the CVR service."""
    resp = _request_with_backoff(
        "POST",
        GRAPHQL_URL,
        params={"apiKey": _api_key()},
        json={"query": query, "variables": variables or {}},
    )
    payload = resp.json()
    if payload.get("errors"):
        raise DatafordelerError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data") or {}


# CVR_Events node fields, per the official entity-based events documentation
# (confluence.kds.dk pageId 219514028, adapted from the BBR example to CVR).
_EVENT_NODE_FIELDS = """
    eventid
    entityname
    eventaction
    datafordelerRegisterImportSequenceNumber
    datafordelerOpdateringstid
    object_id
    object_datafordelerRowId
    object_registreringfra
    object_registreringtil
    object_status
    object_virkningfra
    object_virkningtil
"""


def fetch_events(since_sequence: int, batch_size: int = 1000) -> list[dict[str, Any]]:
    """Fetch CVR_Events nodes newer than a sequence number.

    Query-shape note: the public docs show `where: {entityname: {eq: ...}}`
    filtering on the events entity. Sequence filtering uses the documented
    sequence field; if the service rejects the filter, that surfaces as a
    DatafordelerError during the account/compliance spike - it is never
    silently swallowed.
    """
    query = """
    query ($since: BigInt!, $batch: Int!) {
        CVR_Events(
            where: { datafordelerRegisterImportSequenceNumber: { gt: $since } }
            first: $batch
        ) {
            nodes { %s }
        }
    }
    """ % _EVENT_NODE_FIELDS
    data = graphql(query, {"since": since_sequence, "batch": batch_size})
    events = (data.get("CVR_Events") or {}).get("nodes") or []
    events.sort(key=lambda e: (
        e.get("datafordelerRegisterImportSequenceNumber") or 0,
        e.get("eventid") or 0,
    ))
    return events


def fetch_register_import_status() -> dict[str, Any]:
    """DAF_RegisterImportStatus - completeness marker for event packages.

    Only events at or below lastSequenceNumber belong to fully imported
    packages and are safe to process (per the official docs)."""
    query = """
    query {
        DAF_RegisterImportStatus {
            lastSequenceNumber
            lastEventId
            lastUpdated
        }
    }
    """
    data = graphql(query)
    return data.get("DAF_RegisterImportStatus") or {}


def fetch_virksomhed_by_row_id(row_id: str) -> Optional[dict[str, Any]]:
    """Refetch the current virksomhed row behind an event, per the official
    pattern: on a CVR_Virksomhed event, fetch the actual company data via
    GraphQL using object_datafordelerRowId from the event."""
    query = """
    query ($rowId: ID!) {
        CVR_Virksomhed(where: { datafordelerRowId: { eq: $rowId } }) {
            nodes
        }
    }
    """
    data = graphql(query, {"rowId": row_id})
    nodes = (data.get("CVR_Virksomhed") or {}).get("nodes")
    if isinstance(nodes, list) and nodes:
        return nodes[0]
    return None
