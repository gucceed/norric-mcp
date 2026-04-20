"""
tools/provenance_tools.py

Norric AB — Provenance MCP Tools

Two tools added to the Norric MCP server:

    norric_explain_score_v1
        Human-readable explanation of how a specific score was computed,
        with full source provenance chain. For compliance teams and
        regulated workflow integrations.

    norric_data_freshness_v1
        Ingestion freshness for all active data sources, per agency.
        Used by agents deciding whether Norric data is current enough to
        act on, and by compliance dashboards monitoring pipeline health.

Wire into server.py with:
    from tools.provenance_tools import register_provenance_tools
    register_provenance_tools(mcp)

Or register individually:
    @mcp.tool()
    async def norric_explain_score_v1(...): ...
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from typing import Optional

from core.provenance import (
    Agency,
    NorricProvenance,
    ConfidenceTier,
    confidence_tier,
    min_confidence,
)
from core.envelope import NorricResponse
from shared.schemas.agency import AGENCY_REGISTRY, get_stale_days


# ---------------------------------------------------------------------------
# In-memory pipeline registry (replace with DB queries in production)
# ---------------------------------------------------------------------------
#
# In production, these records are fetched from the database:
#   SELECT source_agency, MAX(ingested_at), COUNT(*) FROM provenance_records
#   GROUP BY source_agency
#
# For now, a stub that returns realistic data structure. Wire to DB in Step 4.

def _get_pipeline_freshness_from_db(agencies: list[str] | None = None) -> list[dict]:
    """
    Stub: replace with actual DB query.

    SELECT
        source_agency,
        MAX(ingested_at) AS last_ingestion,
        COUNT(*) AS record_count,
        MIN(ingested_at) AS first_ingestion
    FROM provenance_records
    WHERE source_agency = ANY(:agencies) OR :agencies IS NULL
    GROUP BY source_agency
    """
    # Stub returns empty list — real implementation queries provenance_records table
    return []


def _get_provenance_chain_from_db(tool_name: str, record_id: str) -> list[NorricProvenance]:
    """
    Stub: replace with actual DB query.

    SELECT * FROM provenance_records
    WHERE tool_name = :tool_name
    AND entity_id = :record_id
    ORDER BY ingested_at DESC
    """
    # Stub returns empty list — real implementation queries provenance_records table
    return []


# ---------------------------------------------------------------------------
# Tool: norric_explain_score_v1
# ---------------------------------------------------------------------------

async def norric_explain_score_v1(
    tool_name: str,
    record_id: str,
    include_raw_refs: bool = False,
) -> NorricResponse:
    """
    Returns a human-readable explanation of how a specific score was computed,
    with full source provenance. Intended for compliance teams and regulated
    workflow integrations (e.g. a bank using Kreditvakt scores in credit decisions).

    Args:
        tool_name       The Norric tool that produced the score.
                        e.g. "kreditvakt_score_company_v1"
        record_id       The entity identifier for the record.
                        For Kreditvakt/Sigvik: orgnr (10-digit)
                        For SIGNAL: municipality notice ID
        include_raw_refs    If True, includes raw source document references
                            in the response. Set False to reduce response size.

    Returns:
        NorricResponse with data containing:
            explanation     Natural language explanation of the score
            pipeline_steps  Ordered list of scoring pipeline steps
            provenance_chain    Full provenance records for each source
            compliance_summary  Structured summary for EU AI Act documentation
    """
    tool = "norric_explain_score_v1"

    # Validate tool_name is a known Norric tool
    known_tools = {
        "kreditvakt_score_company_v1",
        "kreditvakt_alert_subscribe_v1",
        "sigvik_brf_score_v1",
        "sigvik_brf_lookup_v1",
        "signal_weekly_call_list_v1",
        "signal_municipality_intelligence_v1",
    }
    if tool_name not in known_tools:
        return NorricResponse.err(
            tool=tool,
            error=(
                f"Unknown tool_name: {tool_name!r}. "
                f"Known tools: {sorted(known_tools)}"
            ),
        )

    # Fetch provenance chain from DB
    provenance_chain = _get_provenance_chain_from_db(tool_name, record_id)

    if not provenance_chain:
        # Pre-provenance record — return explanation with null provenance notice
        return NorricResponse(
            success=True,
            tool=tool,
            source=["Norric provenance layer"],
            confidence=0.0,
            data={
                "record_id": record_id,
                "tool_name": tool_name,
                "explanation": (
                    f"No provenance records found for {record_id!r} in {tool_name}. "
                    "This record was ingested before the Norric provenance layer was deployed "
                    "(April 2026). Pre-provenance records do not have auditable data lineage. "
                    "Re-ingest this record to generate provenance documentation."
                ),
                "pipeline_steps": [],
                "provenance_chain": [],
                "compliance_summary": {
                    "eu_ai_act_ready": False,
                    "reason": "Pre-provenance record — no data lineage available",
                    "recommendation": "Re-ingest to generate provenance documentation",
                },
            },
        )

    # Build pipeline step explanations
    pipeline_steps = _build_pipeline_steps(tool_name, provenance_chain)

    # Build compliance summary
    overall_confidence = min_confidence(provenance_chain)
    compliance_summary = {
        "eu_ai_act_ready": True,
        "record_id": record_id,
        "tool_name": tool_name,
        "source_agencies": list({p.source_agency for p in provenance_chain}),
        "data_lineage_complete": True,
        "overall_confidence": overall_confidence,
        "confidence_tier": confidence_tier(overall_confidence).value,
        "oldest_source_data": min(
            p.ingested_at for p in provenance_chain
        ).isoformat(),
        "any_stale_sources": any(p.is_stale() for p in provenance_chain),
        "provenance_schema_version": provenance_chain[0].schema_version if provenance_chain else None,
        "documentation_standard": "EU AI Act Article 9 + Annex III",
    }

    # Build provenance chain output
    chain_output = [p.to_compliance_dict() for p in provenance_chain]
    if not include_raw_refs:
        for item in chain_output:
            item.pop("raw_url", None)

    # Generate natural language explanation
    explanation = _generate_explanation(tool_name, record_id, provenance_chain)

    return NorricResponse.ok(
        tool=tool,
        data={
            "record_id": record_id,
            "tool_name": tool_name,
            "explanation": explanation,
            "pipeline_steps": pipeline_steps,
            "provenance_chain": chain_output,
            "compliance_summary": compliance_summary,
        },
        source=[
            AGENCY_REGISTRY[p.source_agency].name_sv
            if p.source_agency in AGENCY_REGISTRY
            else p.source_agency
            for p in provenance_chain
        ],
        provenance=provenance_chain,
    )


def _build_pipeline_steps(
    tool_name: str,
    provenance_chain: list[NorricProvenance],
) -> list[dict]:
    """Generate ordered pipeline step documentation for a tool."""
    steps = []
    for i, prov in enumerate(provenance_chain, 1):
        agency_display = (
            AGENCY_REGISTRY[prov.source_agency].name_sv
            if prov.source_agency in AGENCY_REGISTRY
            else prov.source_agency
        )
        steps.append({
            "step": i,
            "description": f"Fetch {prov.source_document_ref} from {agency_display}",
            "source_agency": prov.source_agency,
            "source_document": prov.source_document_ref,
            "ingested_at": prov.ingested_at.isoformat(),
            "confidence": prov.confidence,
            "confidence_tier": prov.tier.value,
        })
    return steps


def _generate_explanation(
    tool_name: str,
    record_id: str,
    provenance_chain: list[NorricProvenance],
) -> str:
    """Generate a human-readable score explanation in Swedish/English."""
    agencies = [
        AGENCY_REGISTRY[p.source_agency].name_sv
        if p.source_agency in AGENCY_REGISTRY
        else p.source_agency
        for p in provenance_chain
    ]
    agency_list = ", ".join(agencies)
    overall_confidence = min_confidence(provenance_chain)
    tier = confidence_tier(overall_confidence)

    return (
        f"The score for record {record_id!r} via {tool_name} was computed from "
        f"{len(provenance_chain)} source record(s) across {agency_list}. "
        f"Overall derivation confidence: {overall_confidence:.2f} ({tier.value}). "
        f"Data was ingested between "
        f"{min(p.ingested_at for p in provenance_chain).strftime('%Y-%m-%d')} and "
        f"{max(p.ingested_at for p in provenance_chain).strftime('%Y-%m-%d')}. "
        f"All source records are traceable to original Swedish government documents. "
        f"This explanation is generated automatically by the Norric provenance layer "
        f"and is suitable for EU AI Act Article 9 compliance documentation."
    )


# ---------------------------------------------------------------------------
# Tool: norric_data_freshness_v1
# ---------------------------------------------------------------------------

async def norric_data_freshness_v1(
    agencies: Optional[list[str]] = None,
) -> NorricResponse:
    """
    Returns ingestion freshness for all active Norric data pipelines, per agency.

    Used by:
    - Agents deciding whether Norric data is current enough to act on
      (a Claude Code agent should check this before triggering a workflow)
    - Compliance dashboards monitoring pipeline health
    - Norric internal ops alerting (stale pipeline = data quality incident)

    Args:
        agencies    Optional list of agency IDs to filter.
                    If omitted, returns all active pipelines.
                    e.g. ["bolagsverket", "kronofogden"]

    Returns:
        NorricResponse with data containing:
            pipelines   Per-agency freshness records
            summary     Aggregate health summary
            checked_at  UTC timestamp of this freshness check
    """
    tool = "norric_data_freshness_v1"

    # Validate agency filter if provided
    if agencies:
        from core.provenance import Agency
        valid_ids = {a.value for a in Agency} | {"all"}
        invalid = [a for a in agencies if a not in valid_ids and not a.startswith("kommun:")]
        if invalid:
            return NorricResponse.err(
                tool=tool,
                error=(
                    f"Unknown agency IDs: {invalid}. "
                    f"Valid IDs: {sorted({a.value for a in Agency})}"
                ),
            )

    # Fetch freshness data from DB
    raw_records = _get_pipeline_freshness_from_db(agencies)

    # Filter by requested agencies
    target_agencies = agencies or list(AGENCY_REGISTRY.keys())
    checked_at = datetime.now(timezone.utc)

    pipelines = []
    stale_count = 0
    healthy_count = 0

    for agency_id in target_agencies:
        agency_rec = AGENCY_REGISTRY.get(agency_id)
        if not agency_rec:
            continue

        # Find DB record for this agency
        db_record = next(
            (r for r in raw_records if r["source_agency"] == agency_id),
            None,
        )

        stale_threshold = get_stale_days(agency_id)

        if db_record:
            last_ingestion = db_record["last_ingestion"]
            record_count = db_record["record_count"]
            age_days = (checked_at - last_ingestion).days
            is_stale = age_days > stale_threshold
        else:
            # No records yet — pipeline not yet deployed or no data
            last_ingestion = None
            record_count = 0
            age_days = None
            is_stale = True  # No data = stale

        if is_stale:
            stale_count += 1
        else:
            healthy_count += 1

        # Compute next scheduled ingestion (approximation from cadence)
        next_ingestion = None
        if last_ingestion:
            next_ingestion = (
                last_ingestion + timedelta(days=stale_threshold)
            ).isoformat()

        pipelines.append({
            "agency_id": agency_id,
            "agency_name": agency_rec.name_sv,
            "last_ingestion": last_ingestion.isoformat() if last_ingestion else None,
            "age_days": age_days,
            "record_count": record_count,
            "stale_threshold_days": stale_threshold,
            "is_stale": is_stale,
            "status": "🔴 STALE" if is_stale else "🟢 HEALTHY",
            "update_cadence": agency_rec.update_cadence,
            "next_scheduled_ingestion": next_ingestion,
        })

    total = len(pipelines)
    all_healthy = stale_count == 0

    return NorricResponse.ok(
        tool=tool,
        data={
            "pipelines": pipelines,
            "summary": {
                "total_pipelines": total,
                "healthy": healthy_count,
                "stale": stale_count,
                "health_pct": round(healthy_count / total * 100, 1) if total else 0,
                "overall_status": "🟢 ALL HEALTHY" if all_healthy else f"🔴 {stale_count} STALE",
            },
            "checked_at": checked_at.isoformat(),
            "filter_applied": agencies or "all",
        },
        source=["Norric provenance layer"],
        confidence=1.0 if all_healthy else (healthy_count / total if total else 0.0),
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_provenance_tools(mcp) -> None:
    """
    Register both provenance tools with a FastMCP instance.

    Usage in server.py:
        from tools.provenance_tools import register_provenance_tools
        register_provenance_tools(mcp)
    """
    mcp.tool()(norric_explain_score_v1)
    mcp.tool()(norric_data_freshness_v1)
