# Norric MCP — Agent Integration Guide

This file governs how AI agents (Claude Code, Cursor, etc.) should
interact with the Norric MCP server. Read this before writing any
integration code.

## Connection

MCP URL: https://mcp.norric.io/mcp
API keys: https://norric.io/api  (Free tier self-serve; Standard/Compliance via hej@norric.io)
Transport: Streamable HTTP (FastMCP 3.2.3)
Auth: Bearer token in Authorization header (or `X-Norric-Key`)

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
Filter results where risk_tier in ('HIGH','CRITICAL') (or risk_score >= 13).
For each high-risk company, call kreditvakt_score_company_v1
to get the full signal breakdown (signals[] with weights and sources).
Surface the top 5 by risk_score (descending). Note: orgnrs not yet
in norric_entities return HTTP 404 orgnr_not_ingested — surface those
separately so the user knows coverage is the gap, not the company.
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
For a list of BRF orgnrs (sourced from Hemnet, prior contractor CRM, or
manual list — Sigvik does not currently expose a batch-search tool):
1. Call sigvik_score_brf_v1 for each BRF to get the financial-health
   + renovation-likelihood score.
2. Filter to BRFs with elevated renovation likelihood (intent label
   "Starkt signal" / "Måttlig signal").
3. For shortlisted BRFs, call sigvik_brf_flags_v1 for active risk flags
   (incl. EU 2033 energy-deadline flag) and sigvik_brf_avgift_v1 for
   avgift trend.
Return a ranked list with: BRF name, score, top renovation signal,
flags surfaced.
```

## Data freshness rules

Before acting on any Norric data in a consequential workflow
(credit approval, sales outreach, procurement bid):
1. Call norric_data_freshness_v1 to check source freshness.
2. If any source is older than 7 days, note this in your output.
3. Never present Norric scores as real-time without checking freshness.

## Rate limits

- Free tier: 100 calls/day per key + 10 req/min per IP (anonymous endpoints).
- Standard tier: 10,000 calls/day per key.
- Compliance tier: unlimited per-day; IP rate limit only.
- On 429: wait 60 seconds, retry once. If second 429, stop and inform user.

## Error handling

- 401: Tell user to get API key at norric.io/api-keys
- 404: Verify orgnr is 10 digits in format XXXXXX-XXXX
- 503: Retry after 5 minutes. If persistent, check norric.io/status

## What not to do

- Never call kreditvakt_batch_score_v1 with more than 500 orgnr at once
- Never expose API keys in output, logs, or user-visible text
- Never present a risk_score / risk_tier as a definitive bankruptcy prediction —
  it is a probabilistic signal. Always surface risk_tier alongside risk_score
  and note that orgnrs returning HTTP 404 orgnr_not_ingested are coverage gaps,
  not low-risk.
- Never cache Norric responses for more than 24 hours
