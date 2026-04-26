# Norric Intelligence MCP Server

[![MCP](https://img.shields.io/badge/MCP-Streamable_HTTP-blue)](https://norric-mcp-production.up.railway.app/mcp)

Sweden's B2B intelligence infrastructure — exposed as a single MCP server.

**Products:** Norric SIGNAL · Norric Kreditvakt · Norric Vigil · SiteLoop · Sigvik
**Framework:** FastMCP 3.2.3 · Streamable HTTP transport
**Tools:** 21 tools across 5 products

---

## Authentication

Every tool call requires an API key. The initialize handshake is open (no key needed for that step).

```bash
# Option 1 — Authorization header
Authorization: Bearer nrc_your_api_key

# Option 2 — Norric header
X-Norric-Key: nrc_your_api_key
```

**Get a key:** https://norric.io/api

---

## Pricing

| Tier | Tools | Daily limit | Price |
|------|-------|-------------|-------|
| **Free** | `norric_status_v1`, `norric_explain_score_v1`, `norric_data_freshness_v1` | 100 calls/day | Free |
| **Standard** | All 21 tools | 10,000 calls/day | 2,900 SEK/month |
| **Compliance** | All 21 tools + audit rights | Unlimited | 9,900 SEK/month |

Annual plans: Standard 29,000 SEK/year · Compliance 99,000 SEK/year

---

## Connect

### Claude Code (CLI)
```bash
claude mcp add norric https://norric-mcp-production.up.railway.app/mcp \
  --header "Authorization: Bearer nrc_your_api_key"
```

### Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp-production.up.railway.app/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer nrc_your_api_key"
      }
    }
  }
}
```

### Cursor / Windsurf (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp-production.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer nrc_your_api_key"
      }
    }
  }
}
```

### Local development
```bash
python server.py
# Server starts at http://localhost:8080/mcp
claude mcp add norric http://localhost:8080/mcp \
  --header "Authorization: Bearer nrc_your_api_key"
```

---

## Tools

### Norric SIGNAL — Municipal procurement intelligence
| Tool | Description |
|------|-------------|
| `signal_score_municipality_v1` | Score a municipality × vertical 0-100 |
| `signal_weekly_call_list_v1` | Monday call list, ranked by score |
| `signal_municipality_briefing_v1` | Full Swedish call briefing |
| `signal_contract_expiry_alerts_v1` | Expiring contracts = displacement windows |
| `signal_sweden_pulse_v1` | National procurement temperature |

### Norric Kreditvakt — Insolvency intelligence
| Tool | Description |
|------|-------------|
| `kreditvakt_score_company_v1` | 0-100 insolvency score, 9-month accuracy |
| `kreditvakt_batch_score_v1` | Portfolio scoring, max 500 orgnrs |
| `kreditvakt_debt_signals_v1` | Skatteverket restanslängd data |
| `kreditvakt_bankruptcy_status_v1` | Bolagsverket konkurs status |

### Norric Vigil — Company lifecycle detection
| Tool | Description |
|------|-------------|
| `vigil_lifecycle_stage_v1` | early / growth / scaling / distress |
| `vigil_new_companies_v1` | New F-skatt registrations by municipality |
| `vigil_ownership_velocity_v1` | Ownership change rate (distress signal) |

### SiteLoop — Website pipeline
| Tool | Description |
|------|-------------|
| `siteloop_pipeline_status_v1` | Funnel status by city |
| `siteloop_submit_lead_v1` | Inject lead into pipeline (Vigil integration point) |

### Sigvik — BRF property intelligence
| Tool | Description |
|------|-------------|
| `sigvik_score_brf_v1` | BRF financial health score |
| `sigvik_brf_avgift_v1` | Monthly fee history and trend |
| `sigvik_brf_flags_v1` | Renovation risk, energy class deadline flags |

### Cross-portfolio
| Tool | Description |
|------|-------------|
| `norric_company_profile_v1` | Unified profile: Kreditvakt + Vigil in one call |
| `norric_status_v1` | Live status of all products and data pipelines |
| `norric_explain_score_v1` | EU AI Act provenance chain for any score |
| `norric_data_freshness_v1` | Data freshness per source registry |

---

## Response envelope

Every tool returns the same structure:

```json
{
  "data": { ... },
  "metadata": {
    "response_id": "nrsp_abc123",
    "tool": "tool_name_v1",
    "source": ["skatteverket", "bolagsverket"],
    "fetched_at": "2026-04-26T10:00:00Z",
    "confidence": 0.91,
    "cache_ttl_seconds": 3600
  },
  "signals": [
    {
      "key": "skuld_published",
      "label": "Skatteskuld publicerad",
      "value": true,
      "weight": 0.45,
      "direction": "risk",
      "source": "skatteverket"
    }
  ],
  "warnings": []
}
```

`metadata.confidence` (0-1): how much to trust the data
`metadata.cache_ttl_seconds`: how long before re-fetching
`signals[]`: always present, empty list if not applicable

---

## Two-step handshake

MCP requires initializing a session before calling tools:

```bash
# Step 1: Initialize (no auth required)
SESSION=$(curl -si \
  -X POST https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

# Step 2: Call a tool (auth required)
curl -s -X POST https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer nrc_your_api_key" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"norric_status_v1","arguments":{}}}'
```

---

## Current status

Tools are live and callable. Ingestion pipelines are the next build step —
connect each product's data source to activate live scoring.

Check live status: call `norric_status_v1`.

---

## Deploy to Railway

```bash
# MCP server service (existing — daring-adaptation or similar):
# Start command: python server.py
# Env vars:
#   PORT=8080
#   NORRIC_API_KEYS=<hash:tier:label lines>
#   SUPABASE_URL=<your supabase url>
#   SUPABASE_KEY=<your supabase anon key>

# Key issuance service (separate Railway service):
# Start command: uvicorn issuance.main:app --host 0.0.0.0 --port $PORT
# Env vars: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_*,
#           SENDGRID_API_KEY, RAILWAY_API_TOKEN, RAILWAY_SERVICE_ID
```

---

## Registry

- mcp.so listing: `registry/mcpso_listing.md`
- Anthropic connector directory: `registry/anthropic_connector_submission.md`

---

## Norric AB · Malmö · 2026
