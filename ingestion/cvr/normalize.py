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
  checked against the official CVR GraphQL schema. Validate against actual
  Fildownload rows before a production metadata backfill.
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
    number (unusable). `side` holds per-Virksomhed.id aggregates from the Navn,
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

    ceased = _date(_pick(row, "ophorsDato", "ophørsDato", "ophoersdato", "virksomhedOphoersdato",
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

def _entity_id(row: dict) -> Optional[str]:
    """Datafordeler side entities link to Virksomhed.id, not CVRNummer."""
    value = _pick(row, "CVREnhedsId")
    return str(value) if value is not None and str(value).strip() else None


def _latest_current(rows: list[dict], *, address: bool = False) -> Optional[dict]:
    """Select a currently valid version; never resurrect a closed version."""
    current = [r for r in rows
               if not _pick(r, "registreringTil") and not _pick(r, "virkningTil")]
    if address:
        current = [r for r in current if str(_pick(r, "AdresseringAnvendelse") or "").lower()
                   == "beliggenhedsadresse"]
    if not current:
        return None
    return max(current, key=lambda r: (
        str(_pick(r, "virkningFra") or ""),
        str(_pick(r, "registreringFra") or ""),
        int(_pick(r, "sekvens") or 0),
    ))


def build_side_index(entity: str, rows: list[dict]) -> dict[str, Any]:
    """Aggregate current side entities keyed by Virksomhed.id/CVREnhedsId.

    Field names follow the published CVR GraphQL schema, not synthetic flat
    CVR-number fixtures. Unmatched rows are never fabricated into metadata.
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        entity_id = _entity_id(row)
        if entity_id:
            grouped.setdefault(entity_id, []).append(row)

    out: dict[str, Any] = {}
    for entity_id, group in grouped.items():
        latest = _latest_current(group, address=(entity == "Adressering"))
        if latest is None:
            continue
        if entity == "Navn":
            name = _text(_pick(latest, "vaerdi"))
            if name:
                out[entity_id] = {"name": name}
        elif entity == "Branche":
            code, label = _text(_pick(latest, "vaerdi")), _text(_pick(latest, "vaerdiTekst"))
            if code or label:
                out[entity_id] = {"industry": {"code": code, "label": label}}
        elif entity == "Virksomhedsform":
            code, label = _text(_pick(latest, "vaerdi")), _text(_pick(latest, "vaerdiTekst"))
            if code or label:
                out[entity_id] = {"legal_form": {"code": code, "label": label}}
        elif entity == "Adressering":
            street = " ".join(str(v) for v in (
                _pick(latest, "CVRAdresse_vejnavn"),
                _pick(latest, "CVRAdresse_husnummerFra"),
                _pick(latest, "CVRAdresse_etagebetegnelse"),
                _pick(latest, "CVRAdresse_doerbetegnelse"),
            ) if v is not None and str(v).strip()) or None
            postcode = _text(_pick(latest, "CVRAdresse_postnummer"))
            city = _text(_pick(latest, "CVRAdresse_postdistrikt"))
            if any((street, postcode, city)):
                out[entity_id] = {"address": {
                    "street": street, "postcode": postcode, "city": city,
                    "municipality_code": _text(_pick(latest, "CVRAdresse_kommunekode")),
                    "country_code": _text(_pick(latest, "CVRAdresse_landekode")),
                    "raw": latest,
                }}
    return out
