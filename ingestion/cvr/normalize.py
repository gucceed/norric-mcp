"""
CVR row normalization - Denmark country two.

Maps Datafordeler CVR entity rows onto norric_dk_entities columns.

Rules (docs/no-fabrication-contract.md applies):
- Danish codes and labels are canonical. Names, addresses and labels are
  stored exactly as issued - never translated, never re-cased.
- Danish letters stay UTF-8 (ae/oe/aa are data, not noise).
- A field whose source key is not present becomes None and the raw row is
  preserved in the `raw` column. Unknown structure degrades to nulls plus a
  warning at the pipeline level - never to an invented value.
- Candidate key lists exist because the fildownload JSON field casing is
  validated against the first real download (account/compliance spike,
  see docs/denmark-cvr.md). Every candidate comes from the official
  objekttypekatalog or the CVR GraphQL schema naming.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

_CVR_RE = re.compile(r"\d{8}")


def normalize_cvr_number(value: str) -> str:
    """Normalize a Danish CVR number to its 8-digit string form.

    CVR numbers are 8 digits and are stored as text so formatting is
    preserved. Raises ValueError on anything else.
    """
    clean = str(value or "").replace(" ", "").replace("-", "")
    if clean.isdigit() and len(clean) in (7, 8):
        clean = clean.zfill(8)
    if not _CVR_RE.fullmatch(clean):
        raise ValueError(
            f"Invalid Danish CVR number: {value!r}. Expected 8 digits, e.g. 54562519"
        )
    return clean


def _pick(row: dict, *candidates: str) -> Any:
    """First present, non-None value among candidate keys (case-tolerant)."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand in row and row[cand] is not None:
            return row[cand]
        v = lowered.get(cand.lower())
        if v is not None:
            return v
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _nested_code_label(value: Any, code_keys=("kode", "code"),
                       label_keys=("langBeskrivelse", "beskrivelse", "tekst",
                                   "kortBeskrivelse", "label")):
    """CVR code tables arrive either as scalars or as objects carrying a code
    plus a Danish description. Return (code, label)."""
    if value is None:
        return None, None
    if isinstance(value, dict):
        code = _pick(value, *code_keys)
        label = _pick(value, *label_keys)
        if code is None and label is None:
            # Single-key wrapper, e.g. {"virksomhedsformskode": "80"}
            vals = [v for v in value.values() if v is not None]
            code = vals[0] if vals else None
        return _text(code), _text(label)
    return _text(value), None


def _date(value: Any) -> Optional[str]:
    """ISO date/datetime passthrough (date part only)."""
    if not value:
        return None
    s = str(value)
    return s[:10] if len(s) >= 10 else s


def _ts(value: Any) -> Optional[str]:
    if not value:
        return None
    return str(value)


def map_virksomhed_row(row: dict, *, side: Optional[dict] = None) -> Optional[dict]:
    """Map one Virksomhed entity row (+ joined side-entity data) to a
    norric_dk_entities record. Returns None when the row carries no CVR
    number (unusable). `side` holds per-CVR aggregates from the Navn,
    Adressering, Branche and Virksomhedsform entities built by the bulk
    pipeline: {name, address:{...}, industry:{...}, legal_form:{...}}.
    """
    side = side or {}
    cvr = _pick(row, "cvrNummer", "cvrnummer", "CVRNummer", "cvr", "cvr_number")
    if cvr is None:
        return None
    cvr_number = normalize_cvr_number(cvr)

    form_code, form_label = _nested_code_label(
        _pick(row, "virksomhedsform", "nyesteVirksomhedsform", "virksomhedsformskode"))
    if side.get("legal_form"):
        form_code = side["legal_form"].get("code") or form_code
        form_label = side["legal_form"].get("label") or form_label

    status_code, status_label = _nested_code_label(
        _pick(row, "virksomhedsstatus", "livsforloeb", "livsforløb",
              "nyesteVirksomhedsstatus", "status"))

    ind_code, ind_label = _nested_code_label(
        _pick(row, "hovedbranche", "nyesteHovedbranche", "branche", "branchekode"))
    if side.get("industry"):
        ind_code = side["industry"].get("code") or ind_code
        ind_label = side["industry"].get("label") or ind_label

    name = _text(_pick(row, "navn", "nyesteNavn", "virksomhedsnavn"))
    if side.get("name"):
        name = side["name"]

    address = side.get("address") or {}
    street = address.get("street")
    city = address.get("city")
    postcode = address.get("postcode")
    municipality = address.get("municipality_code")
    country = address.get("country_code")
    raw_address = address.get("raw")

    ceased = _date(_pick(row, "ophorsDato", "ophørsDato", "ophoersdato",
                         "ophoersDato", "ceasedAt"))
    started = _date(_pick(row, "startDato", "startdato", "stiftelsesDato",
                        "virksomhedStartDato"))

    registrering_til = _ts(_pick(row, "registreringTil", "registreringtil"))
    is_active = not ceased and not registrering_til
    if status_code and str(status_code).strip().lower() in {
        "ophørt", "ophort", "ophoert", "opløst", "oploest", "ceased", "dissolved",
    }:
        is_active = False

    return {
        "cvr_number": cvr_number,
        "name": name,
        "legal_form_code": form_code,
        "legal_form_label": form_label,
        "status_code": status_code,
        "status_label": status_label,
        "is_active": is_active,
        "started_at": started,
        "ceased_at": ceased,
        "industry_code": ind_code,
        "industry_label": ind_label,
        "street": street,
        "city": city,
        "postcode": postcode,
        "municipality_code": municipality,
        "country_code": country,
        "raw_address": raw_address,
        "phone": _text(_pick(row, "telefonnummer", "phone")),
        "email": _text(_pick(row, "email", "e_mailadresse", "emailadresse")),
        "website": _text(_pick(row, "hjemmeside", "website")),
        "registrering_fra": _ts(_pick(row, "registreringFra", "registreringfra")),
        "registrering_til": registrering_til,
        "virkning_fra": _ts(_pick(row, "virkningFra", "virkningfra")),
        "virkning_til": _ts(_pick(row, "virkningTil", "virkningtil")),
        "datafordeler_row_id": _text(_pick(row, "datafordelerRowId", "rowId")),
        "raw": row,
    }


# ── Side-entity aggregation (bulk pipeline) ──────────────────────────────────

def build_side_index(entity: str, rows: list[dict]) -> dict[str, Any]:
    """Aggregate one side entity's rows into per-CVR values.

    Only 'current' rows are used (registreringTil empty/null) when bitemporal
    fields are present; otherwise the last row per CVR wins.
    """
    def cvr_of(r):
        v = _pick(r, "cvrNummer", "cvrnummer", "CVRNummer", "virksomhedCVRNummer", "cvr")
        if v is None:
            return None
        try:
            return normalize_cvr_number(v)
        except ValueError:
            return None

    def current(rows_):
        open_rows = [r for r in rows_ if not _pick(r, "registreringTil", "registreringtil")]
        return open_rows or rows_

    out: dict[str, Any] = {}
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        c = cvr_of(r)
        if c:
            grouped.setdefault(c, []).append(r)

    for cvr, group in grouped.items():
        rows_now = current(group)
        latest = rows_now[-1]
        if entity == "Navn":
            navn = _text(_pick(latest, "navn", "Navn", "tekst", "vaerdi", "værdi"))
            if navn:
                out.setdefault(cvr, {})["name"] = navn
        elif entity == "Virksomhedsform":
            code, label = _nested_code_label(
                _pick(latest, "virksomhedsform", "virksomhedsformskode",
                      "form", "kode") or latest)
            if code or label:
                out.setdefault(cvr, {})["legal_form"] = {"code": code, "label": label}
        elif entity == "Branche":
            code, label = _nested_code_label(
                _pick(latest, "branchekode", "branche", "kode") or latest)
            if code or label:
                out.setdefault(cvr, {})["industry"] = {"code": code, "label": label}
        elif entity == "Adressering":
            street_parts = [
                _text(_pick(latest, "vejnavn", "gade")),
                _text(_pick(latest, "husnummerFra", "husnummer", "nr")),
                _text(_pick(latest, "etage")),
                _text(_pick(latest, "sidedoer", "sidedør", "doer", "dør")),
            ]
            street = " ".join(p for p in street_parts if p) or None
            postcode = _text(_pick(latest, "postnummer", "postnr"))
            city = _text(_pick(latest, "postdistrikt", "bynavn", "city"))
            municipality = _text(_pick(latest, "kommuneKode", "kommunekode",
                                       "kommune", "municipalityCode"))
            country = _text(_pick(latest, "landekode", "countryCode"))
            if any((street, postcode, city)):
                out.setdefault(cvr, {})["address"] = {
                    "street": street,
                    "postcode": postcode,
                    "city": city,
                    "municipality_code": municipality,
                    "country_code": country,
                    "raw": latest,
                }
    return out
