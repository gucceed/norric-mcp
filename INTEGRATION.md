# Norric Provenance Layer — Integration Guide

**Status:** Ready to wire into `norric-mcp`  
**Tests:** 59/59 passing  
**Build order:** Steps 1–3 complete (provenance.py, envelope.py, agency.py). Steps 4–9 below.

---

## Files produced

```
core/
  provenance.py        NorricProvenance model, Agency enum, confidence helpers
  envelope.py          NorricResponse v2 — add provenance field here
shared/schemas/
  agency.py            Agency registry, 9 agencies, staleness thresholds, API docs
tools/
  provenance_tools.py  norric_explain_score_v1 + norric_data_freshness_v1
tests/
  test_provenance.py   59 tests, 100% coverage on core/provenance.py
```

---

## Step 4 — Wire into your existing server.py

In your `norric-mcp/server.py`, the current envelope import is:

```python
from app.schemas import NorricResponse  # or wherever it lives
```

Replace with the v2 envelope:

```python
from core.envelope import NorricResponse
from core.provenance import (
    bolagsverket_provenance,
    kronofogden_provenance,
    boverket_provenance,
    signal_provenance,
)
```

Register the two new tools:

```python
from tools.provenance_tools import register_provenance_tools
register_provenance_tools(mcp)
```

That's it. The existing 19 tools are backward compatible — `provenance: null` is valid.

---

## Step 5 — Wire SIGNAL ingestion pipeline

In your SIGNAL ingestion worker, after fetching a procurement notice:

```python
from core.provenance import signal_provenance

# After fetching notice from municipality DMS:
prov = signal_provenance(
    kommunkod=notice.kommunkod,
    notice_id=notice.id,
    confidence=1.0,        # direct extraction from source document
    raw_url=notice.source_url,
)

# Store prov alongside the record in Supabase:
await db.execute("""
    INSERT INTO provenance_records
        (entity_id, tool_name, source_agency, source_document_ref,
         ingested_at, confidence, raw_url, schema_version)
    VALUES (:entity_id, :tool_name, :source_agency, :source_document_ref,
            :ingested_at, :confidence, :raw_url, :schema_version)
""", prov.model_dump() | {"entity_id": notice.id, "tool_name": "signal_municipality_intelligence_v1"})
```

---

## Step 6 — Wire Kreditvakt ingestion

Two provenance records per company (Bolagsverket + Kronofogden):

```python
from core.provenance import bolagsverket_provenance, kronofogden_provenance

provenance = [
    bolagsverket_provenance(
        orgnr=company.orgnr,
        document_type="arsredovisning",
        period=str(company.fiscal_year),
        confidence=0.9,   # NLP parsed
    ),
    kronofogden_provenance(
        orgnr=company.orgnr,
        confidence=1.0,   # direct extraction
        raw_url=f"https://www.kronofogden.se/restanslangd/{company.orgnr}",
    ),
]

# Return in MCP tool response:
return NorricResponse.ok(
    tool="kreditvakt_score_company_v1",
    data=score_payload,
    source=["Bolagsverket", "Kronofogden"],
    provenance=provenance,  # confidence auto-derived as min(0.9, 1.0) = 0.9
)
```

---

## Step 7 — Wire Sigvik ingestion

Two provenance records per BRF (Bolagsverket BRF + Boverket):

```python
from core.provenance import bolagsverket_provenance, boverket_provenance

provenance = [
    bolagsverket_provenance(
        orgnr=brf.orgnr,
        document_type="brf_arsredovisning",
        period=str(brf.fiscal_year),
        confidence=0.85,  # two-stage NLP parser (rule-based + Haiku fallback)
    ),
    boverket_provenance(
        building_id=brf.building_id,
        confidence=0.95,  # structured API response
        raw_url=f"https://api.boverket.se/energideklarationer/{brf.building_id}",
    ),
]
```

---

## Step 8 — Database migration (Supabase / PostgreSQL)

```sql
CREATE TABLE provenance_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       TEXT NOT NULL,           -- orgnr, notice_id, building_id
    tool_name       TEXT NOT NULL,
    source_agency   TEXT NOT NULL,
    source_document_ref TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence      NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    raw_url         TEXT,
    schema_version  TEXT NOT NULL DEFAULT '1.0',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_provenance_entity_tool ON provenance_records(entity_id, tool_name);
CREATE INDEX idx_provenance_agency ON provenance_records(source_agency);
CREATE INDEX idx_provenance_ingested_at ON provenance_records(ingested_at);
```

---

## Step 9 — Wire DB stubs in provenance_tools.py

Replace the two stub functions with real Supabase queries:

```python
# In tools/provenance_tools.py:

async def _get_pipeline_freshness_from_db(agencies):
    result = await supabase.rpc("get_pipeline_freshness", {"agency_ids": agencies})
    return result.data

async def _get_provenance_chain_from_db(tool_name, record_id):
    result = await supabase.table("provenance_records") \
        .select("*") \
        .eq("tool_name", tool_name) \
        .eq("entity_id", record_id) \
        .order("ingested_at", desc=True) \
        .execute()
    return [NorricProvenance(**r) for r in result.data]
```

---

## Acceptance criteria checklist

- [x] `NorricProvenance` model — immutable, validated, UTC-enforced
- [x] `agency_display_name` property for compliance reports
- [x] `is_stale()` with configurable threshold
- [x] `to_compliance_dict()` for EU AI Act documentation
- [x] `make_document_ref()` canonical format enforced
- [x] `make_kommun_source_id()` validated 4-digit format
- [x] Confidence helpers: `confidence_tier()`, `min_confidence()`
- [x] Convenience builders: bolagsverket, kronofogden, boverket, signal
- [x] `NorricResponse` v2: `provenance` field added
- [x] Weakest-link confidence derivation in `model_validator`
- [x] `has_provenance`, `is_stale`, `provenance_summary()` on response
- [x] `NorricResponse.ok()` and `.err()` constructors updated
- [x] Agency registry: 9 agencies, staleness thresholds, docs URLs
- [x] `norric_explain_score_v1` tool — compliance chain explanation
- [x] `norric_data_freshness_v1` tool — pipeline health monitoring
- [x] 59 tests, all passing
- [ ] Wire SIGNAL ingestion (Step 5)
- [ ] Wire Kreditvakt ingestion (Step 6)  
- [ ] Wire Sigvik ingestion (Step 7)
- [ ] Supabase migration (Step 8)
- [ ] Replace DB stubs (Step 9)
- [ ] Railway redeploy + confirm provenance survives restart
