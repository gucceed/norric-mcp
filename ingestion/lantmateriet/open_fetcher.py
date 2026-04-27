"""
Lantmäteriet open geodata fetcher (no licence required).

Fetches property boundary centroids from the WFS service for Skåne
municipalities. Writes to norric_properties with source='lantmateriet_open'.
"""
import logging
import xml.etree.ElementTree as ET
from typing import Iterator

import httpx

from ingestion.geo.kommunkod import resolve_kommunkod

log = logging.getLogger(__name__)

WFS_BASE = "https://geodata.lantmateriet.se/topografi/v1/wfs"

# Skåne kommunkoder (33 municipalities)
SKANE_KOMMUNKODER = [
    "1230", "1231", "1233", "1256", "1257", "1260", "1261", "1262",
    "1263", "1264", "1265", "1266", "1267", "1270", "1272", "1273",
    "1275", "1276", "1277", "1278", "1280", "1281", "1282", "1283",
    "1284", "1285", "1286", "1287", "1290", "1291", "1292", "1293",
    "1315",
]


def _wfs_get_capabilities() -> dict:
    resp = httpx.get(
        WFS_BASE,
        params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
        timeout=20,
    )
    resp.raise_for_status()
    return {"status": resp.status_code, "content_type": resp.headers.get("content-type", "")}


def _fetch_features(type_name: str, bbox: str | None = None, max_features: int = 1000) -> list[dict]:
    params = {
        "service":     "WFS",
        "version":     "2.0.0",
        "request":     "GetFeature",
        "typeNames":   type_name,
        "outputFormat": "application/json",
        "count":       str(max_features),
    }
    if bbox:
        params["bbox"] = bbox

    resp = httpx.get(WFS_BASE, params=params, timeout=30)
    if resp.status_code == 401:
        log.warning("WFS requires auth for type %s — skipping", type_name)
        return []
    if resp.status_code != 200:
        log.warning("WFS returned %d for type %s", resp.status_code, type_name)
        return []

    try:
        data = resp.json()
        return data.get("features", [])
    except Exception:
        log.warning("WFS response is not JSON for type %s", type_name)
        return []


def fetch_skane_properties() -> Iterator[dict]:
    """
    Fetch property records for Skåne from open WFS.
    Yields dicts matching norric_properties columns.
    """
    caps = _wfs_get_capabilities()
    log.info("WFS capabilities status=%d type=%s", caps["status"], caps["content_type"])

    # Try common feature types — actual names depend on service
    for type_name in ["ms:Fastighetsyta", "ms:Fastighetsomrade", "lm:RegisterenhetOmrade"]:
        features = _fetch_features(type_name, max_features=500)
        if not features:
            continue

        log.info("found %d features of type %s", len(features), type_name)
        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry")

            lat = lon = None
            if geom and geom.get("type") == "Point":
                coords = geom.get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
            elif geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                # Use rough centroid from first coordinate
                coords = geom.get("coordinates", [[[]]])
                first_ring = coords[0] if geom["type"] == "Polygon" else coords[0][0]
                if first_ring:
                    lons = [c[0] for c in first_ring]
                    lats = [c[1] for c in first_ring]
                    lon = sum(lons) / len(lons)
                    lat = sum(lats) / len(lats)

            fastighet_id = props.get("objekt_id") or props.get("id") or feat.get("id")
            beteckning = props.get("beteckning") or props.get("fastighetsbeteckning", "")
            postcode = props.get("postnummer", "")
            city = props.get("postort", "")
            kommunkod, county = resolve_kommunkod(postcode, city)

            yield {
                "fastighet_id":         str(fastighet_id) if fastighet_id else None,
                "fastighetsbeteckning": beteckning or None,
                "kommunkod":            kommunkod or None,
                "county":               county or None,
                "orgnr":                None,
                "owner_name":           None,
                "building_year":        None,
                "taxeringsvarde_sek":   None,
                "area_sqm":             props.get("areal_m2"),
                "coordinates_lat":      lat,
                "coordinates_lon":      lon,
                "source":               "lantmateriet_open",
                "licence_required":     False,
            }
        return  # stop after first successful type

    log.warning(
        "No open WFS features found. Lantmäteriet may require auth for all feature types. "
        "Apply for API agreement at lantmateriet.se."
    )
