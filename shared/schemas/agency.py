"""
shared/schemas/agency.py

Norric AB — Agency Registry
Canonical registry of Swedish government data sources used by Norric products.

This module is the single source of truth for:
  - Agency identifier strings (matches Agency enum in core/provenance.py)
  - Human-readable display names (Swedish and English)
  - Data domains served by each agency
  - Staleness thresholds (how often the agency publishes updates)
  - Links to developer documentation / API endpoints

Import this module in ingestion pipelines to register sources and in
norric_explain_score_v1 to generate human-readable compliance reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AgencyRecord:
    """
    Complete metadata for a Swedish government data source.

    Fields:
        id              Canonical identifier string (matches Agency enum)
        name_sv         Swedish display name
        name_en         English display name
        domains         Data domains this agency covers
        update_cadence  How often the agency publishes updates (human-readable)
        stale_days      Number of days before a record from this agency is stale
        api_base        Base URL for the agency's public API (if available)
        docs_url        Developer documentation URL
        notes           Any important caveats for data consumers
    """

    id: str
    name_sv: str
    name_en: str
    domains: list[str]
    update_cadence: str
    stale_days: int
    api_base: Optional[str] = None
    docs_url: Optional[str] = None
    notes: Optional[str] = None


AGENCY_REGISTRY: dict[str, AgencyRecord] = {

    "bolagsverket": AgencyRecord(
        id="bolagsverket",
        name_sv="Bolagsverket",
        name_en="Swedish Companies Registration Office",
        domains=[
            "company_registration",
            "arsredovisningar",
            "bankruptcies",
            "brf",
            "board_members",
        ],
        update_cadence="Daily (registration changes), Annual (årsredovisningar)",
        stale_days=7,
        api_base="https://api.bolagsverket.se",
        docs_url="https://developer.bolagsverket.se",
        notes="Free API since February 2025. OAuth2 client credentials. "
              "Årsredovisningar lag 30–90 days after fiscal year end.",
    ),

    "kronofogden": AgencyRecord(
        id="kronofogden",
        name_sv="Kronofogdemyndigheten",
        name_en="Swedish Enforcement Authority",
        domains=[
            "payment_injunctions",
            "bailiff_cases",
            "restanslangd",
            "betalningsforelagganden",
        ],
        update_cadence="Weekly (restanslängd), Near-real-time (injunctions)",
        stale_days=7,
        api_base=None,
        docs_url="https://www.kronofogden.se/foretag/",
        notes="Restanslängd published weekly. "
              "Scraper-based ingestion — no public API. "
              "Betalningsförelägganden available via court records.",
    ),

    "lantmateriet": AgencyRecord(
        id="lantmateriet",
        name_sv="Lantmäteriet",
        name_en="Swedish Mapping, Cadastral and Land Registration Authority",
        domains=[
            "property_ownership",
            "building_data",
            "fastighetsregister",
            "coordinate_systems",
        ],
        update_cadence="Continuous (ownership changes registered same-day)",
        stale_days=30,
        api_base="https://api.lantmateriet.se",
        docs_url="https://www.lantmateriet.se/sv/geodata/vara-produkter/",
        notes="Commercial licence required for Fastighetsregister data. "
              "Partner licence application via partner@lm.se. "
              "Norric Fastighetsdata licence application pending.",
    ),

    "boverket": AgencyRecord(
        id="boverket",
        name_sv="Boverket",
        name_en="Swedish National Board of Housing, Building and Planning",
        domains=[
            "energideklarationer",
            "planning_data",
            "building_permits",
        ],
        update_cadence="Continuous (new deklarationer as buildings are certified)",
        stale_days=180,
        api_base="https://api.boverket.se",
        docs_url="https://www.boverket.se/sv/energideklaration/",
        notes="Energideklarationer are property-level, not company-level. "
              "Sigvik uses these for BRF building energy risk scoring.",
    ),

    "scb": AgencyRecord(
        id="scb",
        name_sv="Statistiska centralbyrån",
        name_en="Statistics Sweden",
        domains=[
            "statistical_series",
            "postcode_demographics",
            "economic_indicators",
            "population_data",
        ],
        update_cadence="Monthly (most series), Quarterly (national accounts)",
        stale_days=45,
        api_base="https://api.scb.se",
        docs_url="https://www.scb.se/vara-tjanster/oppna-data/",
        notes="JSON-stat format. Free, no authentication required. "
              "Postcode demographic tables used in Kreditvakt regional risk scoring.",
    ),

    "skatteverket": AgencyRecord(
        id="skatteverket",
        name_sv="Skatteverket",
        name_en="Swedish Tax Agency",
        domains=[
            "f_skatt",
            "tax_tables",
            "vat_registration",
            "restanslangd",
        ],
        update_cadence="Daily (F-skatt status), Weekly (restanslängd)",
        stale_days=7,
        api_base=None,
        docs_url="https://www.skatteverket.se/foretagochorganisationer/",
        notes="Restanslängd (tax debt register) is a key Kreditvakt signal. "
              "F-skatt status available via Bolagsverket API (reseller). "
              "No public REST API — scraper-based ingestion.",
    ),

    "arbetsformedlingen": AgencyRecord(
        id="arbetsformedlingen",
        name_sv="Arbetsförmedlingen",
        name_en="Swedish Public Employment Service",
        domains=[
            "job_postings",
            "labour_market_forecasts",
        ],
        update_cadence="Daily (job postings)",
        stale_days=3,
        api_base="https://jobsearch.api.jobtechdev.se",
        docs_url="https://jobtechdev.se/docs",
        notes="JobTech Dev open API. No authentication required. "
              "Hiring signals used in Norric Vigil lifecycle detection.",
    ),

    "smhi": AgencyRecord(
        id="smhi",
        name_sv="Sveriges meteorologiska och hydrologiska institut",
        name_en="Swedish Meteorological and Hydrological Institute",
        domains=[
            "weather_data",
            "climate_risk",
            "flood_zones",
        ],
        update_cadence="Hourly (weather), Periodic (climate risk assessments)",
        stale_days=1,
        api_base="https://opendata-download-metfcst.smhi.se",
        docs_url="https://opendata.smhi.se/apidocs/",
        notes="Open data, no authentication. "
              "Flood zone data relevant to Sigvik property risk.",
    ),

    "riksbanken": AgencyRecord(
        id="riksbanken",
        name_sv="Sveriges Riksbank",
        name_en="Swedish Central Bank",
        domains=[
            "mortgage_rates",
            "financial_series",
            "policy_rate",
            "exchange_rates",
        ],
        update_cadence="Daily (rates), Quarterly (financial stability reports)",
        stale_days=3,
        api_base="https://api.riksbank.se",
        docs_url="https://www.riksbank.se/sv/statistik/",
        notes="Open API, no authentication. "
              "Policy rate and STIBOR used in Kreditvakt macroeconomic risk layer.",
    ),
}


def get_agency(agency_id: str) -> AgencyRecord | None:
    """
    Look up an agency by its canonical identifier.
    Returns None for unknown agencies (including 'kommun:{kod}' variants).
    """
    return AGENCY_REGISTRY.get(agency_id)


def get_stale_days(agency_id: str) -> int:
    """
    Returns the staleness threshold in days for an agency.
    Falls back to 7 days for unknown agencies (incl. municipality sources).
    """
    record = AGENCY_REGISTRY.get(agency_id)
    return record.stale_days if record else 7


def all_agency_ids() -> list[str]:
    """Returns all known agency identifier strings."""
    return list(AGENCY_REGISTRY.keys())


def agencies_for_domain(domain: str) -> list[AgencyRecord]:
    """Returns all agencies that serve a given data domain."""
    return [
        rec for rec in AGENCY_REGISTRY.values()
        if domain in rec.domains
    ]
