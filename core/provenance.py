"""
core/provenance.py

Norric AB — Provenance Layer
Trust infrastructure for all Norric data products.

Every record ingested by SIGNAL, Kreditvakt, or Sigvik carries a NorricProvenance
envelope that makes its origin, freshness, and derivation confidence machine-readable.

This is not consumer-facing. It is the accounting system of a data company.

EU AI Act Article 9 + Annex III compliance: credit scoring and BRF risk models
must maintain auditable data lineage. This module generates that documentation
automatically at the data source — it cannot be retrofitted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Agency registry
# ---------------------------------------------------------------------------

class Agency(str, Enum):
    """
    Canonical identifiers for Swedish government data sources.

    Municipality sources use the pattern `kommun:{kommunkod}` and are handled
    as freeform strings via the `KommunAgency` helper below — not enumerated
    here since there are 290 possible values.
    """

    BOLAGSVERKET = "bolagsverket"
    KRONOFOGDEN = "kronofogden"
    LANTMATERIET = "lantmateriet"
    BOVERKET = "boverket"
    SCB = "scb"
    SKATTEVERKET = "skatteverket"
    ARBETSFORMEDLINGEN = "arbetsformedlingen"
    SMHI = "smhi"
    RIKSBANKEN = "riksbanken"

    @property
    def display_name(self) -> str:
        return _AGENCY_LABELS[self]

    @property
    def data_domains(self) -> list[str]:
        return _AGENCY_DOMAINS[self]


_AGENCY_LABELS: dict[Agency, str] = {
    Agency.BOLAGSVERKET: "Bolagsverket",
    Agency.KRONOFOGDEN: "Kronofogden",
    Agency.LANTMATERIET: "Lantmäteriet",
    Agency.BOVERKET: "Boverket",
    Agency.SCB: "Statistiska centralbyrån (SCB)",
    Agency.SKATTEVERKET: "Skatteverket",
    Agency.ARBETSFORMEDLINGEN: "Arbetsförmedlingen",
    Agency.SMHI: "SMHI",
    Agency.RIKSBANKEN: "Riksbanken",
}

_AGENCY_DOMAINS: dict[Agency, list[str]] = {
    Agency.BOLAGSVERKET: ["company_registration", "arsredovisningar", "bankruptcies", "brf"],
    Agency.KRONOFOGDEN: ["payment_injunctions", "bailiff_cases", "restanslangd"],
    Agency.LANTMATERIET: ["property_ownership", "building_data", "fastighetsregister"],
    Agency.BOVERKET: ["energideklarationer", "planning_data"],
    Agency.SCB: ["statistical_series", "postcode_demographics", "economic_indicators"],
    Agency.SKATTEVERKET: ["f_skatt", "tax_tables", "vat_registration"],
    Agency.ARBETSFORMEDLINGEN: ["job_postings", "labour_market_forecasts"],
    Agency.SMHI: ["weather_data", "climate_risk", "flood_zones"],
    Agency.RIKSBANKEN: ["mortgage_rates", "financial_series"],
}


def make_kommun_source_id(kommunkod: str) -> str:
    """
    Returns the canonical source_agency string for a municipality source.
    e.g. make_kommun_source_id("1280") → "kommun:1280"
    """
    if not kommunkod.isdigit() or len(kommunkod) != 4:
        raise ValueError(f"kommunkod must be 4 digits, got: {kommunkod!r}")
    return f"kommun:{kommunkod}"


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

class ConfidenceTier(str, Enum):
    """Human-readable tier labels for confidence scores."""
    DIRECT = "direct"        # 1.0       — verbatim copy from source
    PARSED = "parsed"        # 0.8–0.99  — NLP/structured extraction
    INFERRED = "inferred"    # 0.5–0.79  — multi-field model derivation
    ESTIMATED = "estimated"  # 0.0–0.49  — statistical model, high uncertainty


def confidence_tier(score: float) -> ConfidenceTier:
    """Return the tier for a given confidence score (0.0–1.0)."""
    if score >= 1.0:
        return ConfidenceTier.DIRECT
    elif score >= 0.8:
        return ConfidenceTier.PARSED
    elif score >= 0.5:
        return ConfidenceTier.INFERRED
    else:
        return ConfidenceTier.ESTIMATED


def min_confidence(records: list["NorricProvenance"]) -> float:
    """
    Weakest-link confidence: the chain is only as trustworthy as its
    least-reliable record. Use this to set NorricResponse.confidence
    when provenance is present.
    """
    if not records:
        return 0.0
    return min(r.confidence for r in records)


# ---------------------------------------------------------------------------
# Document reference format
# ---------------------------------------------------------------------------

def make_document_ref(
    agency: Agency | str,
    entity_id: str,
    document_type: str,
    period: str | None = None,
) -> str:
    """
    Canonical document reference format:
      {agency}:{entity_id}/{document_type}/{period}

    Examples:
      make_document_ref(Agency.BOLAGSVERKET, "5565123456", "arsredovisning", "2024")
      → "bolagsverket:5565123456/arsredovisning/2024"

      make_document_ref("kronofogden", "5565123456", "restanslangd")
      → "kronofogden:5565123456/restanslangd"

      make_document_ref("kommun:1280", "2024-12345", "procurement_notice")
      → "kommun:1280:2024-12345/procurement_notice"
    """
    agency_str = agency.value if isinstance(agency, Agency) else agency
    parts = [agency_str, entity_id, document_type]
    if period:
        parts.append(period)
    # Format: agency:entity_id/doc_type[/period]
    return f"{agency_str}:{entity_id}/{document_type}" + (f"/{period}" if period else "")


# ---------------------------------------------------------------------------
# Core provenance model
# ---------------------------------------------------------------------------

class NorricProvenance(BaseModel):
    """
    Per-record lineage envelope. Attached at ingestion time, stored in DB,
    surfaced in every NorricResponse that touches this record.

    Fields:
        source_agency       Canonical agency identifier (Agency enum value or
                            "kommun:{kommunkod}" for municipality sources)
        source_document_ref Canonical document reference — see make_document_ref()
        ingested_at         UTC timestamp of ingestion (not document date)
        confidence          0.0–1.0 derivation confidence — see ConfidenceTier
        raw_url             Source URL if the record came from a web endpoint
        schema_version      Provenance schema version for forward compatibility
    """

    source_agency: str = Field(
        ...,
        description=(
            "Canonical agency identifier. One of the Agency enum values, "
            "or 'kommun:{kommunkod}' for municipality sources."
        ),
    )
    source_document_ref: str = Field(
        ...,
        description=(
            "Canonical document reference in format "
            "{agency}:{entity_id}/{document_type}[/{period}]. "
            "Use make_document_ref() to construct this."
        ),
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when this record was ingested by Norric.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Derivation confidence. 1.0=direct copy, 0.8–0.99=parsed, "
            "0.5–0.79=inferred, 0.0–0.49=estimated."
        ),
    )
    raw_url: Optional[str] = Field(
        default=None,
        description="Source URL if this record was fetched from a web endpoint.",
    )
    schema_version: str = Field(
        default="1.0",
        description="Provenance schema version. Increment when breaking changes are made.",
    )

    @field_validator("source_agency")
    @classmethod
    def validate_source_agency(cls, v: str) -> str:
        # Accept Agency enum values
        valid_agencies = {a.value for a in Agency}
        if v in valid_agencies:
            return v
        # Accept "kommun:{kommunkod}" pattern
        if v.startswith("kommun:"):
            kod = v.split(":", 1)[1]
            if kod.isdigit() and len(kod) == 4:
                return v
            raise ValueError(
                f"Municipality source must be 'kommun:{{4-digit-kommunkod}}', got: {v!r}"
            )
        raise ValueError(
            f"Unknown source_agency {v!r}. Must be a known agency identifier "
            f"or 'kommun:{{kommunkod}}'. Known agencies: {sorted(valid_agencies)}"
        )

    @field_validator("ingested_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def tier(self) -> ConfidenceTier:
        return confidence_tier(self.confidence)

    @property
    def agency_display_name(self) -> str:
        """Human-readable agency name for compliance reports."""
        if self.source_agency.startswith("kommun:"):
            kod = self.source_agency.split(":", 1)[1]
            return f"Kommun {kod}"
        try:
            return Agency(self.source_agency).display_name
        except ValueError:
            return self.source_agency

    def is_stale(self, max_age_days: int = 7) -> bool:
        """Returns True if the record is older than max_age_days."""
        now = datetime.now(timezone.utc)
        age = now - self.ingested_at
        return age.days > max_age_days

    def to_compliance_dict(self) -> dict:
        """
        Returns a structured dict suitable for compliance audit reports.
        Suitable for PDF/HTML rendering in regulated workflows.
        """
        return {
            "agency": self.agency_display_name,
            "source_agency_id": self.source_agency,
            "document_ref": self.source_document_ref,
            "ingested_at_utc": self.ingested_at.isoformat(),
            "confidence_score": self.confidence,
            "confidence_tier": self.tier.value,
            "raw_url": self.raw_url,
            "schema_version": self.schema_version,
            "is_stale": self.is_stale(),
        }

    model_config = {"frozen": True}  # Provenance is immutable after creation


# ---------------------------------------------------------------------------
# Provenance builder helpers
# ---------------------------------------------------------------------------

def bolagsverket_provenance(
    orgnr: str,
    document_type: str,
    period: str | None = None,
    confidence: float = 0.9,
    raw_url: str | None = None,
) -> NorricProvenance:
    """Convenience builder for Bolagsverket provenance records."""
    return NorricProvenance(
        source_agency=Agency.BOLAGSVERKET.value,
        source_document_ref=make_document_ref(
            Agency.BOLAGSVERKET, orgnr, document_type, period
        ),
        confidence=confidence,
        raw_url=raw_url,
    )


def kronofogden_provenance(
    orgnr: str,
    document_type: str = "restanslangd",
    confidence: float = 1.0,
    raw_url: str | None = None,
) -> NorricProvenance:
    """Convenience builder for Kronofogden provenance records."""
    return NorricProvenance(
        source_agency=Agency.KRONOFOGDEN.value,
        source_document_ref=make_document_ref(
            Agency.KRONOFOGDEN, orgnr, document_type
        ),
        confidence=confidence,
        raw_url=raw_url,
    )


def boverket_provenance(
    building_id: str,
    document_type: str = "energideklaration",
    confidence: float = 0.95,
    raw_url: str | None = None,
) -> NorricProvenance:
    """Convenience builder for Boverket provenance records."""
    return NorricProvenance(
        source_agency=Agency.BOVERKET.value,
        source_document_ref=make_document_ref(
            Agency.BOVERKET, building_id, document_type
        ),
        confidence=confidence,
        raw_url=raw_url,
    )


def signal_provenance(
    kommunkod: str,
    notice_id: str,
    confidence: float = 1.0,
    raw_url: str | None = None,
) -> NorricProvenance:
    """Convenience builder for SIGNAL (municipality procurement) provenance records."""
    source_agency = make_kommun_source_id(kommunkod)
    return NorricProvenance(
        source_agency=source_agency,
        source_document_ref=make_document_ref(
            source_agency, notice_id, "procurement_notice"
        ),
        confidence=confidence,
        raw_url=raw_url,
    )
