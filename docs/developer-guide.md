# Norric Intelligence API — Developer Guide

**MCP Server:** https://norric-mcp-production.up.railway.app/mcp
**API Keys:** https://norric.io/api-keys
**Support:** edgar.mutebi1@gmail.com

---

## Quick start (60 seconds)

### 1. Get an API key
Visit https://norric.io/api-keys and request access.
Free sandbox keys are available immediately.

### 2. Connect via Claude Code
```bash
claude mcp add norric https://norric-mcp-production.up.railway.app/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

### 3. Connect via Claude Desktop
Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp-production.up.railway.app/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### 4. Connect via Cursor / Windsurf
Edit `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "norric": {
      "url": "https://norric-mcp-production.up.railway.app/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

### 5. Direct API call (curl)
```bash
# Step 1: Initialize session
SESSION=$(curl -si https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}' \
  | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

# Step 2: Call a tool
curl -s https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kreditvakt_score_company_v1","arguments":{"orgnr":"556012-3456"}}}'
```

---

## Tools reference

### Norric Kreditvakt — Insolvency scoring

| Tool | Description | Key params |
|------|-------------|------------|
| `kreditvakt_score_company_v1` | Insolvency score 0-100 for a Swedish company | `orgnr` |
| `kreditvakt_batch_score_v1` | Score up to 100 companies in one call | `orgnr_list` |
| `kreditvakt_monitor_portfolio_v1` | Add companies to monitored watchlist | `orgnr_list`, `webhook_url` |
| `kreditvakt_get_alerts_v1` | Get recent threshold crossings | `threshold`, `limit` |

**Example — score a company:**
```python
result = await client.call_tool("kreditvakt_score_company_v1", {"orgnr": "556012-3456"})
# Returns: insolvency_score, risk_tier, signal_breakdown, verdict, onset_days
```

### Norric SIGNAL — Municipal procurement intelligence

| Tool | Description | Key params |
|------|-------------|------------|
| `signal_score_municipality_v1` | Score municipality × vertical 0-100 | `municipality_kod`, `vertikal` |
| `signal_weekly_call_list_v1` | Monday call list ranked by score | `vertikal`, `limit` |
| `signal_municipality_briefing_v1` | Full political + budget briefing | `municipality_kod`, `vertikal` |
| `signal_contract_expiry_v1` | Upcoming contract renewals | `vertikal`, `months_ahead` |

### Sigvik — BRF intelligence

| Tool | Description | Key params |
|------|-------------|------------|
| `sigvik_brf_score_v1` | Renovation intent score for a BRF | `orgnr` |
| `sigvik_brf_lookup_v1` | Full BRF profile + signals | `orgnr` |
| `sigvik_search_brfs_v1` | Search BRFs by municipality/score | `municipality`, `min_score` |

### Norric Vigil — B2B lifecycle signals

| Tool | Description | Key params |
|------|-------------|------------|
| `vigil_new_companies_v1` | F-skatt registrations this week | `region`, `limit` |
| `vigil_building_permits_v1` | Expansion signals from permits | `municipality`, `days_back` |
| `vigil_ownership_changes_v1` | Ownership transition signals | `region`, `limit` |

### Infrastructure tools

| Tool | Description |
|------|-------------|
| `norric_explain_score_v1` | Human-readable explanation of any score |
| `norric_data_freshness_v1` | Check when each data source was last updated |

---

## NorricResponse envelope

Every tool returns a standard envelope:
```json
{
  "success": true,
  "tool": "kreditvakt_score_company_v1",
  "source": ["skatteverket", "kronofogden", "bolagsverket"],
  "confidence": 0.87,
  "data": { ... },
  "error": null,
  "cached": false,
  "ts": "2026-04-26T18:00:00Z",
  "provenance": [
    {
      "source_agency": "skatteverket",
      "source_document_ref": "orgnr:556012-3456/restanslangd/2026-04",
      "ingested_at": "2026-04-26T06:00:00Z",
      "confidence": 1.0
    }
  ]
}
```

## Error codes

| Code | Meaning | Agent action |
|------|---------|--------------|
| 401 | Invalid or missing API key | Get key at norric.io/api-keys |
| 404 | Company/entity not found in registry | Verify orgnr format (XXXXXX-XXXX) |
| 429 | Rate limit exceeded | Wait 60s, retry with exponential backoff |
| 503 | Data source temporarily unavailable | Retry after 5 minutes |

## Pricing

| Plan | Price | Calls/month | Features |
|------|-------|-------------|----------|
| Sandbox | Free | 100 | All tools, test data |
| Professional | 299 kr/mo | 5,000 | Live data, all products |
| Konsult | 499 kr/mo | 20,000 | Live data, webhooks, priority support |
| Enterprise | Custom | Unlimited | SLA, dedicated ingestion, EU data residency |

Get your key: **norric.io/api-keys**
