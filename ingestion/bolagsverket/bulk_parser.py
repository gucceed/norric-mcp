"""
Bolagsverket bulk file parser.

Reads the semicolon-delimited UTF-8-sig file line by line.
Never loads the full file into memory.
Yields parsed entity dicts.

Column layout (0-indexed):
  0: orgnr  1: name  4: orgform  5: dereg_date  10: address
Address sub-format: street$care_of$city$postcode$country
"""
import csv
from pathlib import Path
from typing import Iterator

from ingestion.geo.kommunkod import resolve_kommunkod

ORGFORM_WHITELIST = {
    "BRF-ORGFO",
    "AB-ORGFO",
    "HB-ORGFO",
    "EF-ORGFO",
    "EK-ORGFO",
    "SF-ORGFO",
}


def parse_bulk_file(
    path: Path,
    orgform_filter: set[str] | None = None,
) -> Iterator[dict]:
    """Yields one dict per entity (active and deregistered, caller decides)."""
    filter_set = orgform_filter or ORGFORM_WHITELIST

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        for i, row in enumerate(reader):
            if i == 0:
                continue
            if len(row) < 11:
                continue

            orgform = row[4].strip()
            if orgform not in filter_set:
                continue

            dereg = row[5].strip()
            is_active = not bool(dereg)

            orgnr_raw = row[0].strip().replace("-", "").replace(" ", "")
            if len(orgnr_raw) != 10:
                continue
            orgnr_display = f"{orgnr_raw[:6]}-{orgnr_raw[6:]}"

            addr_parts = row[10].strip().split("$")
            street   = addr_parts[0].strip() if len(addr_parts) > 0 else None
            city     = addr_parts[2].strip() if len(addr_parts) > 2 else None
            postcode = addr_parts[3].strip() if len(addr_parts) > 3 else None

            kommunkod, county = resolve_kommunkod(postcode or "", city or "")

            yield {
                "orgnr":           orgnr_raw,
                "orgnr_display":   orgnr_display,
                "name":            row[1].strip(),
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
