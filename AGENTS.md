# Norric MCP — Agent Integration Guide

This file governs how AI agents (Claude Code, Cursor, etc.) should
interact with the Norric MCP server. Read this before writing any
integration code.

## Connection

MCP URL: https://norric-mcp-production.up.railway.app/mcp
API keys: https://norric.io/api-keys
Transport: Streamable HTTP (FastMCP 3.2.3)
Auth: Bearer token in Authorization header

## FastMCP handshake (required for direct curl calls)

All direct HTTP calls require a two-step handshake:
1. POST /mcp with method=initialize → receive mcp-session-id in response headers
2. Include mcp-session-id header in all subsequent calls

Both calls require: `Accept: application/json, text/event-stream`
Claude Code and Claude Desktop handle this automatically.

## Agent patterns

### Pattern 1 — Portfolio credit scan
```
Use kreditvakt_batch_score_v1 to score a list of orgnr.
Filter results where insolvency_score > 60.
For each high-risk company, call kreditvakt_score_company_v1
to get the full signal breakdown.
Surface the top 5 by score with verdict and onset_days.
```

### Pattern 2 — Weekly procurement briefing
```
Call signal_weekly_call_list_v1 with the user's vertical.
For the top 3 municipalities, call signal_municipality_briefing_v1.
Format as a call brief: municipality name, score, key signals,
recommended talking points, contact name if available.
```

### Pattern 3 — BRF contractor pipeline
```
Call sigvik_search_brfs_v1 with municipality and min_score=65.
For each result, call sigvik_brf_score_v1 for full signal detail.
Return a ranked list with: BRF name, score, top renovation signal,
estimated project window (onset_days).
```

## Data freshness rules

Before acting on any Norric data in a consequential workflow
(credit approval, sales outreach, procurement bid):
1. Call norric_data_freshness_v1 to check source freshness.
2. If any source is older than 7 days, note this in your output.
3. Never present Norric scores as real-time without checking freshness.

## Rate limits

- Sandbox: 100 calls/month total
- Professional: 5,000 calls/month
- On 429: wait 60 seconds, retry once. If second 429, stop and inform user.

## Error handling

- 401: Tell user to get API key at norric.io/api-keys
- 404: Verify orgnr is 10 digits in format XXXXXX-XXXX
- 503: Retry after 5 minutes. If persistent, check norric.io/status

## What not to do

- Never call kreditvakt_batch_score_v1 with more than 100 orgnr at once
- Never expose API keys in output, logs, or user-visible text
- Never present insolvency scores as a definitive bankruptcy prediction —
  always include the verdict field and note it is a probabilistic signal
- Never cache Norric responses for more than 24 hours
