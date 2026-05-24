# Anthropic MCP Connector Directory — Submission

**Connector name:** Norric Swedish Business Intelligence
**Short description:** Real-time insolvency risk, renovation likelihood, and
procurement signals from Swedish government registries — for credit,
real estate, and public sector AI workflows.
**Category:** Finance & Business Intelligence
**MCP endpoint:** https://mcp.norric.io/mcp
**Auth type:** Bearer token
**Protocol version:** 2024-11-05
**Transport:** Streamable HTTP

**Why this connector is unique:**
Norric is the only MCP server providing structured intelligence from Swedish
public registries (Bolagsverket, Skatteverket, Kronofogden, Boverket,
Lantmäteriet). No equivalent exists for Nordic market participants. Primary
use cases: bank credit AI agents, leasing underwriting, construction
contractor prospecting, public sector procurement intelligence.

**Company:** Norric AB, Malmö, Sweden
**Contact:** edgar.mutebi1@gmail.com
**Website:** norric.io

**Example tool call (for directory listing):**

```json
{
  "tool": "kreditvakt_score_company_v1",
  "description": "Returns risk_score (0–20, ascending = worse), risk_band (1–5), and risk_tier (HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL) for any Swedish aktiebolag, based on Bolagsverket konkursansökan filings, Skatteverket tax arrears, and Kronofogden payment orders. Orgnrs not yet in coverage return HTTP 404 orgnr_not_ingested — a coverage gap, not a low-risk signal.",
  "input_schema": {
    "orgnr": "Swedish organisation number, e.g. 556123-4567"
  }
}
```

**Second example — procurement signals:**

```json
{
  "tool": "signal_weekly_call_list_v1",
  "description": "Returns the ranked list of Swedish municipalities to contact this week for a procurement vertical. Sorted by composite score. Each entry includes the primary signal, suggested call window, and opening talking point.",
  "input_schema": {
    "vertikal": "One of: aldreomsorg | skola | it_digital | fastighet | hr | bygg | annat",
    "limit": "Number of results (default 10, max 50)"
  }
}
```

**Third example — BRF property intelligence:**

```json
{
  "tool": "sigvik_score_brf_v1",
  "description": "Returns financial health score and renovation risk index for a Swedish BRF (housing cooperative). Used by mortgage pre-approval agents and estate agents.",
  "input_schema": {
    "brf_id": "BRF organisation number, e.g. 716400-1234"
  }
}
```

**Response envelope (all tools):**

```json
{
  "data": { ... },
  "metadata": {
    "tool": "kreditvakt_score_company_v1",
    "confidence": 0.92,
    "cache_ttl_seconds": 3600,
    "fetched_at": "2026-04-26T10:00:00Z"
  },
  "signals": [ ... ],
  "warnings": [ ... ]
}
```

**Free tier available:** `norric_status_v1`, `norric_data_freshness_v1` — 100 calls/day, no payment required, self-serve sign-up at https://norric.io/api.

**Paid tiers (Standard / Compliance):** All other tools require a paid key. Self-serve sign-up paused pending kreditupplysningslagen (KuL) tillstånd review for the Kreditvakt offering. Paid keys issued direct via `hej@norric.io` with qualification + ToS step.

**Submission URL:** Anthropic Connectors Directory submission form — https://claude.com/docs/connectors/building/submission
(reviewed in ~2 weeks; requires tool annotations, privacy policy URL, and a test API key for reviewers).
