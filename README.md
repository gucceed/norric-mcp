# Norric Intelligence MCP Server

Sweden's B2B intelligence infrastructure — exposed as a single MCP server.

**Products:** Norric SIGNAL · Norric Kreditvakt · Norric Vigil · SiteLoop · Sigvik  
**Framework:** FastMCP 3.2.3 · Streamable HTTP transport  
**Tools:** 19 tools across 5 products + 2 cross-portfolio tools

---

## Connect

### Claude Code (CLI)
```bash
claude mcp add norric https://norric-mcp.up.railway.app/mcp
```

### Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp.up.railway.app/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### Cursor / Windsurf (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp.up.railway.app/mcp"
    }
  }
}
```

### Local development
```bash
python server.py
# Server starts at http://localhost:8000/mcp
claude mcp add norric http://localhost:8000/mcp
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
    "fetched_at": "2026-04-13T10:00:00Z",
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

## Current status

Tools are live and callable. Ingestion pipelines are the next build step —
connect each product's data source to activate live scoring.

Check live status: call `norric_status_v1` with no arguments.

---

## Deploy to Railway

```bash
# Push to GitHub, connect repo in Railway
# Set environment variables:
PORT=8000
HOST=0.0.0.0

# Railway auto-detects requirements.txt and runs:
# python server.py
```

## Norric AB · Malmö · 2026
