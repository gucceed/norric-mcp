"""
Generic SCB PX-Web API fetcher.

Handles JSON-stat dataset response format, missing values (..), and
both quarterly (YYYY K1) and monthly (YYYY M01) period formats.
"""
import logging
import re
from itertools import product as itertools_product
from typing import Any

import httpx

log = logging.getLogger(__name__)

SCB_BASE = "https://api.scb.se/OV0104/v1/doris/sv/ssd/"


def _parse_period(raw: str) -> str:
    """Normalise SCB period strings to consistent format."""
    raw = raw.strip()
    # Quarterly: '2026K1' → '2026Q1'
    m = re.match(r"(\d{4})K(\d)", raw)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    # Monthly: '2026M01' → '2026M01' (already normalised)
    if re.match(r"\d{4}M\d{2}", raw):
        return raw
    # Annual: '2026' → '2026A'
    if re.match(r"^\d{4}$", raw):
        return f"{raw}A"
    return raw


def _map_region(scb_region: str) -> str:
    """Map SCB region codes to Norric kommunkod format (strip trailing zeros etc)."""
    # SCB uses 4-digit codes for municipalities, same as Norric
    clean = scb_region.strip().lstrip("0")
    return scb_region.strip()  # return as-is; already 4-digit in most cases


class ScbFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30)

    def fetch_table(self, table_id: str, query_spec: dict) -> list[dict]:
        """
        POST a query to SCB and return flat list of observation dicts.
        Each dict: {period, region_kod, dimension_key, dimension_val, value, unit}
        """
        url = f"{SCB_BASE}{table_id}"

        resp = self._client.post(url, json=query_spec)
        resp.raise_for_status()
        dataset = resp.json()

        return self._parse_dataset(dataset, table_id)

    def _parse_dataset(self, dataset: dict, table_id: str) -> list[dict]:
        # JSON-stat structure: dataset.value[], dataset.id[], dataset.size[], dataset.dimension{}
        if "dataset" in dataset:
            ds = dataset["dataset"]
        else:
            ds = dataset

        ids = ds.get("id", [])
        sizes = ds.get("size", [])
        dims = ds.get("dimension", {})
        values = ds.get("value", [])
        unit = ds.get("unit", {})

        # Build category label lists for each dimension
        cat_labels: list[list[tuple[str, str]]] = []
        for dim_id in ids:
            dim_data = dims.get(dim_id, {})
            cats = dim_data.get("category", {})
            label_map = cats.get("label", {})
            index_map = cats.get("index", {})
            ordered = sorted(index_map.items(), key=lambda x: x[1])
            cat_labels.append([(k, label_map.get(k, k)) for k, _ in ordered])

        results = []
        for idx, combo in enumerate(itertools_product(*cat_labels)):
            if idx >= len(values):
                break

            raw_val = values[idx]
            if raw_val == ".." or raw_val is None:
                numeric_val = None
            else:
                try:
                    numeric_val = float(raw_val)
                except (ValueError, TypeError):
                    numeric_val = None

            row: dict[str, Any] = {"table_id": table_id}
            region_kod = None

            for dim_id, (cat_key, cat_label) in zip(ids, combo):
                if dim_id.lower() in ("region", "lan", "kommun", "regionkod"):
                    region_kod = _map_region(cat_key)
                    row["region_kod"] = region_kod
                elif dim_id.lower() in ("tid", "ar", "period"):
                    row["period"] = _parse_period(cat_key)
                else:
                    row["dimension_key"] = dim_id
                    row["dimension_val"] = cat_label

            row["value"] = numeric_val
            row.setdefault("region_kod", None)
            row.setdefault("period", "")
            row.setdefault("dimension_key", ids[-1] if ids else "value")
            row.setdefault("dimension_val", "")

            # Get unit for this dimension
            unit_key = row.get("dimension_key", "")
            row["unit"] = unit.get(unit_key, {}).get("base", None) if isinstance(unit, dict) else None

            results.append(row)

        log.info("parsed %d observations from %s", len(results), table_id)
        return results

    def get_table_metadata(self, table_id: str) -> dict:
        url = f"{SCB_BASE}{table_id}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()
