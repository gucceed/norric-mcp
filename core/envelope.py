"""
core/envelope.py

Norric AB — Universal Response Envelope
All MCP tool responses are wrapped in NorricResponse.

v2: Added `provenance` field — per-record data lineage for EU AI Act compliance.

Confidence derivation rule (when provenance is present):
    response.confidence = min(p.confidence for p in provenance)
    (weakest-link: the chain is only as trustworthy as its least-reliable record)

Backward compatibility: `provenance` is Optional. Tools that have not yet been
wired to the provenance layer return `provenance: null`. Do not treat null as an
error — treat it as "pre-provenance record." New ingestion pipelines must populate
provenance from their first run. Do not backfill.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, model_validator

from core.provenance import NorricProvenance, min_confidence


class NorricResponse(BaseModel):
    """
    Universal response envelope for all Norric MCP tools.

    Every tool — Kreditvakt, Sigvik, SIGNAL, Vigil, LeadFlow — returns
    this shape. Agents and compliance systems can rely on a consistent
    structure regardless of which product generated the response.

    Fields:
        success         True if the tool executed without error
        tool            The tool name that generated this response
        source          Human-readable list of data agencies (for display)
        confidence      Overall confidence score 0.0–1.0
                        When provenance is present, derived as min(provenance.confidence)
        data            Tool-specific payload (dict or list)
        error           Error message if success=False, else None
        cached          True if response was served from cache
        ts              UTC timestamp of response generation
        provenance      Per-record lineage (None for pre-provenance records)
    """

    success: bool
    tool: str
    source: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    data: Optional[Union[dict, list]] = None
    error: Optional[str] = None
    cached: bool = False
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # v2: provenance layer
    provenance: Optional[list[NorricProvenance]] = Field(
        default=None,
        description=(
            "Per-record data lineage. Present for SIGNAL, Kreditvakt, and Sigvik "
            "records ingested after provenance layer deployment. "
            "Null for pre-provenance records — do not treat as error."
        ),
    )

    @model_validator(mode="after")
    def derive_confidence_from_provenance(self) -> "NorricResponse":
        """
        When provenance records are present, confidence is derived as the
        weakest-link minimum across all provenance records. This ensures
        that a high-level tool confidence cannot mask low-confidence source data.

        If provenance is absent (pre-provenance records), confidence is
        left as-is (set by the tool).
        """
        if self.provenance:
            derived = min_confidence(self.provenance)
            object.__setattr__(self, "confidence", derived)
        return self

    @classmethod
    def ok(
        cls,
        tool: str,
        data: Union[dict, list],
        source: list[str] | None = None,
        confidence: float = 1.0,
        cached: bool = False,
        provenance: list[NorricProvenance] | None = None,
    ) -> "NorricResponse":
        """
        Convenience constructor for successful responses.

        Usage:
            return NorricResponse.ok(
                tool="kreditvakt_score_company_v1",
                data={"insolvency_score": 72, ...},
                source=["Bolagsverket", "Kronofogden"],
                provenance=[bolagsverket_prov, kronofogden_prov],
            )
        """
        return cls(
            success=True,
            tool=tool,
            source=source or [],
            confidence=confidence,
            data=data,
            cached=cached,
            provenance=provenance,
        )

    @classmethod
    def err(
        cls,
        tool: str,
        error: str,
        source: list[str] | None = None,
    ) -> "NorricResponse":
        """
        Convenience constructor for error responses.

        Usage:
            return NorricResponse.err(
                tool="kreditvakt_score_company_v1",
                error="Bolagsverket rate limit exceeded",
            )
        """
        return cls(
            success=False,
            tool=tool,
            source=source or [],
            confidence=0.0,
            data=None,
            error=error,
        )

    @property
    def has_provenance(self) -> bool:
        return self.provenance is not None and len(self.provenance) > 0

    @property
    def is_stale(self) -> bool:
        """True if any provenance record is stale (>7 days)."""
        if not self.provenance:
            return False
        return any(p.is_stale() for p in self.provenance)

    def provenance_summary(self) -> dict | None:
        """
        Returns a compact provenance summary for agent reasoning.
        Agents (e.g. Claude Code) use this to decide whether data is
        fresh enough to act on before triggering a workflow.
        """
        if not self.provenance:
            return None
        return {
            "record_count": len(self.provenance),
            "agencies": list({p.source_agency for p in self.provenance}),
            "oldest_ingestion": min(
                p.ingested_at for p in self.provenance
            ).isoformat(),
            "newest_ingestion": max(
                p.ingested_at for p in self.provenance
            ).isoformat(),
            "min_confidence": min_confidence(self.provenance),
            "any_stale": self.is_stale,
        }

    model_config = {"arbitrary_types_allowed": True}
