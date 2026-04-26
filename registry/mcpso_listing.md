# Norric — Swedish Business Intelligence MCP

**Category:** Business & Finance
**Region:** Sweden / Nordic
**Language:** Swedish public data, responses in English
**Transport:** Streamable HTTP (2024-11-05 protocol)
**Auth:** Bearer token (API key)

## What it does

Norric provides real-time intelligence on Swedish companies and associations
drawn from five Swedish government registries: Bolagsverket, Skatteverket,
Kronofogden, Boverket, and Lantmäteriet.

## Tools (21 total)

| Tool | Description |
|------|-------------|
| `kreditvakt_score_company_v1` | 12-month insolvency probability for any Swedish aktiebolag |
| `kreditvakt_batch_score_v1` | Score up to 500 companies in one call |
| `kreditvakt_debt_signals_v1` | Skatteverket tax debt and F-skatt status |
| `kreditvakt_bankruptcy_status_v1` | Bolagsverket konkurs filing status |
| `sigvik_score_brf_v1` | Renovation likelihood index for Swedish BRFs |
| `sigvik_brf_avgift_v1` | Monthly avgift history, trend, YoY delta |
| `sigvik_brf_flags_v1` | Active risk flags incl. EU 2033 energy deadline |
| `signal_score_municipality_v1` | Procurement readiness score for any municipality × vertical |
| `signal_weekly_call_list_v1` | Ranked Monday call list for sales and SDR agents |
| `signal_municipality_briefing_v1` | Full Swedish call briefing with talking points |
| `signal_contract_expiry_alerts_v1` | Expiring contracts = displacement windows |
| `signal_sweden_pulse_v1` | National procurement activity index (0-100) |
| `vigil_lifecycle_stage_v1` | Company lifecycle: early / growth / scaling / distress |
| `vigil_new_companies_v1` | Newly registered companies via Skatteverket F-skatt |
| `vigil_ownership_velocity_v1` | Ownership change rate — acquisition / distress signal |
| `siteloop_pipeline_status_v1` | Autonomous website pipeline health by city |
| `siteloop_submit_lead_v1` | Submit a lead into the SiteLoop pipeline |
| `norric_company_profile_v1` | Unified cross-product profile for any Swedish company |
| `norric_status_v1` | Live pipeline health across all products |
| `norric_explain_score_v1` | EU AI Act-compliant provenance chain for any score |
| `norric_data_freshness_v1` | Data freshness per source registry |

## Pricing

| Tier | Tools | Daily limit | Price |
|------|-------|-------------|-------|
| **Free** | Status + explain tools | 100 calls/day | Free |
| **Standard** | All 21 tools | 10,000 calls/day | 2,900 SEK/month |
| **Compliance** | All 21 tools + audit rights | Unlimited | 9,900 SEK/month |

## Get access

https://norric.io/api

## Endpoint

```
https://norric-mcp-production.up.railway.app/mcp
```

## Authentication

```
Authorization: Bearer nrc_your_api_key
# or
X-Norric-Key: nrc_your_api_key
```

## Quick start

```bash
# Step 1: Initialize session (no auth required for this step)
SESSION=$(curl -si \
  -X POST https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

# Step 2: Call a tool with your API key
curl -s -X POST https://norric-mcp-production.up.railway.app/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer nrc_your_api_key" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"norric_status_v1","arguments":{}}}'
```

## Add to Claude Code

```bash
claude mcp add norric https://norric-mcp-production.up.railway.app/mcp \
  --header "Authorization: Bearer nrc_your_api_key"
```

## Company

Norric AB · Malmö, Sweden · norric.io
