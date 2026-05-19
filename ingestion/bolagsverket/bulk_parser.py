"""
Bolagsverket bulk file parser.

Reads the semicolon-delimited UTF-8-sig file line by line.
Never loads the full file into memory.
Yields parsed entity dicts.

Column layout (0-indexed) — verified against the live bulk file 2026-05-16:
  0:  organisationsidentitet           e.g. "8888006510$ORGNR-IDORG"
  1:  namnskyddslopnummer              counter, not the name
  2:  registreringsland                e.g. "SE-LAND"
  3:  organisationsnamn                e.g. "ACME AB$FORETAGSNAMN-ORGNAM$1994-09-16"
  4:  organisationsform                e.g. "AB-ORGFO" | "S-ORGFO" | …
  5:  avregistreringsdatum             empty when active
  6:  avregistreringsorsak
  7:  pagandeAvvecklingsEllerOmstruktureringsforfarande
  8:  registreringsdatum
  9:  verksamhetsbeskrivning
  10: postadress                       sub-format: street$care_of$city$postcode$country

The earlier column comment in this file was wrong (col 1 is not name; col 3 is)
and orgnr in col 0 carries a "$ORGNR-IDORG" suffix that must be stripped before
the 10-digit length check. Both bugs are why the bulk task never inserted any
rows historically.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Iterator, TextIO

from ingestion.geo.kommunkod import resolve_kommunkod

ORGFORM_WHITELIST = {
    "BRF-ORGFO",
    "AB-ORGFO",
    "HB-ORGFO",
    "EF-ORGFO",
    "EK-ORGFO",
    "SF-ORGFO",
}


def _strip_nuls(stream: TextIO) -> Iterable[str]:
    """csv.reader chokes on NUL bytes; the Bolagsverket bulk file occasionally
    contains stray NULs. Strip them at the line layer (same pattern as
    konkurs_parser._strip_nuls)."""
    for line in stream:
        if "\x00" in line:
            yield line.replace("\x00", "")
        else:
            yield line


def parse_bulk_file(
    path: Path,
    orgform_filter: set[str] | None = None,
) -> Iterator[dict]:
    """Yields one dict per entity (active and deregistered, caller decides)."""
    filter_set = orgform_filter or ORGFORM_WHITELIST

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(_strip_nuls(f), delimiter=";", quotechar='"')
        for i, row in enumerate(reader):
            if i == 0:
                continue
            if len(row) < 11:
                continue

            orgform = row[4].strip()
            if orgform not in filter_set:
                continue

            # Bolagsverket bulk uses empty string for active, an ISO date for
            # deregistered. ~37 rows in the 2026-05 snapshot have the literal
            # 'null'/'NULL' as a sentinel — treat them as empty.
            dereg = row[5].strip()
            if dereg.lower() in ("", "null", "none"):
                dereg = ""
            is_active = not bool(dereg)

            # Col 0: "8888006510$ORGNR-IDORG" — strip the qualifier suffix.
            orgnr_raw = row[0].split("$", 1)[0].strip().replace("-", "").replace(" ", "")
            if len(orgnr_raw) != 10:
                continue
            orgnr_display = f"{orgnr_raw[:6]}-{orgnr_raw[6:]}"

            # Col 3: "ACME AB$FORETAGSNAMN-ORGNAM$1994-09-16" — first $-segment is the name.
            name = row[3].split("$", 1)[0].strip()
            if not name:
                continue

            addr_parts = row[10].strip().split("$")
            street   = addr_parts[0].strip() if len(addr_parts) > 0 else None
            city     = addr_parts[2].strip() if len(addr_parts) > 2 else None
            postcode = addr_parts[3].strip() if len(addr_parts) > 3 else None

            kommunkod, county = resolve_kommunkod(postcode or "", city or "")

            yield {
                "orgnr":           orgnr_raw,
                "orgnr_display":   orgnr_display,
                "name":            name,
                "orgform":         orgform,
                "is_active":       is_active,
                "deregistered_at": dereg or None,
                "street":          street or None,
                "city":            city or None,
                "postcode":        postcode or None,
                "kommunkod":       kommunkod or None,
                "county":          county or None,
                "raw_address":     row[10].strip() or None,
            }
