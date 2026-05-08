# Kreditvakt Operations Runbook

**Service:** Norric MCP / Kreditvakt scoring API  
**Host:** Railway (`https://norric-mcp-production.up.railway.app`)  
**Frontend:** Vercel (`https://kreditvakt.com`)  
**DB:** Supabase PostgreSQL (Frankfurt → `aws-1-us-east-1.pooler.supabase.com`)  
**Upstash Redis:** Frankfurt (rate limiting — `kreditvakt:rl` prefix)

---

## Table of Contents

1. [Reading structured logs](#1-reading-structured-logs)
2. [Error code reference](#2-error-code-reference)
3. [Circuit breaker state](#3-circuit-breaker-state)
4. [DB schema health check](#4-db-schema-health-check)
5. [Rollback procedure](#5-rollback-procedure)
6. [Key revocation](#6-key-revocation)
7. [Taking the site offline](#7-taking-the-site-offline)
8. [Incident log](#8-incident-log)

---

## 1. Reading structured logs

Every `/api/score/{orgnr}` request emits one JSON line:

```json
{
  "requestId":    "uuid",
  "timestamp":    "2026-05-08T14:23:01.123Z",
  "route":        "/api/score/{orgnr}",
  "tier":         "free",
  "orgnr":        "a3f9c1...",
  "latencyMs":    142.3,
  "statusCode":   200,
  "errorCode":    null,
  "errorMessage": null,
  "stackTrace":   null,
  "deploySha":    "abc1234",
  "region":       "us-east-1"
}
```

**orgnr is a partial SHA-256 hash — never the raw value (GDPR).**  
**stackTrace is populated on server errors — never sent to client.**

### Common jq queries

```bash
# All errors in last N lines of Railway log
railway logs | grep '"statusCode":[^2]' | jq .

# Latency histogram
railway logs | jq -r 'select(.latencyMs) | .latencyMs' | sort -n | uniq -c

# Error code breakdown
railway logs | jq -r 'select(.errorCode) | .errorCode' | sort | uniq -c | sort -rn

# Circuit breaker transitions
railway logs | grep '"circuit'

# All 500s with stack traces
railway logs | jq 'select(.statusCode == 500 and .stackTrace != null)'
```

---

## 2. Error code reference

| Code | HTTP | Meaning | Common cause | Action |
|------|------|---------|--------------|--------|
| `VALIDATION_FAILED` | 400 | Bad orgnr format | Client sent non-numeric or wrong length | None — client fix |
| `AUTH_REQUIRED` | 401 | Missing/invalid API key | Key revoked, typo, copied partial key | Check `api_keys` table; re-issue if needed |
| `SEARCH_LIMIT_REACHED` | 402 | Free tier cap (10 searches) | User exhausted quota | Upsell to Silver; admin can reset: `UPDATE api_keys SET searches_used=0 WHERE email=:e` |
| `TIER_INSUFFICIENT` | 403 | Feature requires paid tier | User on wrong tier | Upsell |
| `UPSTREAM_TIMEOUT` | 504 | DB/scoring timed out | DB overloaded, slow query | Check Supabase dashboard; check `company_scores` table size |
| `UPSTREAM_RATE_LIMIT` | 429 | IP rate limit exceeded | >10 req/min from same IP | Automatic — user waits 1 minute |
| `UPSTREAM_DEGRADED` | 503 | Circuit breaker OPEN | 5 consecutive scoring failures | See §3 below |
| `SCHEMA_MISSING` | 500 | DB table absent | Migrations not run | See §4 below — run missing migrations |
| `CONFIG_MISSING` | 500 | Env var absent | `DATABASE_URL` or `NORRIC_API_KEYS` not set | Check Railway env vars |
| `SCORING_ERROR` | 500 | Unexpected scoring failure | Bug or data corruption | Check stack trace in logs |

---

## 3. Circuit breaker state

The circuit breaker is in-memory per Railway instance. It trips after **5 consecutive scoring failures** and stays OPEN for **30 seconds**.

**Check current state:**
```
GET https://norric-mcp-production.up.railway.app/health
```

Response includes:
```json
{
  "checks": {
    "circuit_breaker": "closed"   // closed | open | half_open
  }
}
```

**Manual reset:** Restart the Railway service (triggers process restart → circuit resets to CLOSED).

```bash
railway up --detach  # redeploy
# OR
railway service restart
```

**Half-open:** One trial request is allowed. If it succeeds, circuit closes. If it fails, circuit re-opens for 30s.

---

## 4. DB schema health check

**Check which tables exist:**
```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

**Required tables for scoring to work:**
- `api_keys` — key validation + quota
- `company_scores` — scoring output
- `company_score_history` — band change alerting
- `norric_tax_signals` — T1 Skatteverket signals (can be empty → falls back to mock)
- `norric_payment_signals` — T1 Kronofogden signals (can be empty → falls back to mock)

**Run missing migrations:**
```bash
cd /tmp/norric-mcp-repo
python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.autocommit = True
cur = conn.cursor()
for f in ['migrations/T1_000_pipeline_runs.sql', 'migrations/T1_001_norric_entities.sql',
          'migrations/T1_002_tax_signals.sql', 'migrations/T1_003_payment_signals.sql']:
    cur.execute(open(f).read())
    print(f'OK: {f}')
"
```

All migrations use `CREATE TABLE IF NOT EXISTS` — safe to re-run.

---

## 5. Rollback procedure

**Kreditvakt frontend (Vercel):**
```bash
# List recent deployments
vercel ls

# Rollback to previous production deployment (~10 seconds)
vercel rollback
```

**Norric MCP backend (Railway):**
```bash
# Railway auto-deploys from main branch.
# To rollback: revert the commit and push.
git revert HEAD
git push origin main
```

Railway redeploys automatically on push. ETA: ~2 minutes.

---

## 6. Key revocation

**Revoke a single key:**
```sql
UPDATE api_keys SET status = 'revoked' WHERE email = 'user@example.com';
```

**Revoke all keys for an org:**
```sql
UPDATE api_keys SET status = 'revoked' WHERE org_nr = '556123-4567';
```

**Invalidate Redis cache immediately (if Redis is configured):**
```bash
# Connect to Upstash Redis and delete cached key
# Key format: api_key:{sha256_of_raw_key}
redis-cli -u $REDIS_URL DEL "api_key:$(echo -n 'nrk_...' | sha256sum | cut -d' ' -f1)"
```

Without Redis cache invalidation, revocation propagates within 60 seconds (cache TTL for revoked keys).

---

## 7. Taking the site offline

**Frontend — maintenance page:**
```bash
# Deploy a static maintenance page via Vercel
# OR set VITE_MAINTENANCE_MODE=true and redeploy
```

**Backend — block all scoring requests:**
```bash
# Emergency: set NORRIC_SCORING_DISABLED=1 in Railway env vars
# kreditvakt/api.py checks this env var and returns 503 immediately
```

**Complete takedown:**
```bash
# Vercel
vercel rollback --to=<safe-deployment-id>

# Railway — stop service
railway service down
```

---

## 8. Incident log

### INC-001 — Free tier search returning 500 (2026-05-08)

**Severity:** P0 — 100% of free tier searches failing  
**Duration:** Unknown start — resolved 2026-05-08  
**Blast radius:** All Free tier users on kreditvakt.com/lookup  

**Proximate cause:** `scoring/kreditvakt.py:score_from_db()` executed `SELECT ... FROM norric_tax_signals` which failed with `ProgrammingError: relation "norric_tax_signals" does not exist`. Exception propagated to `kreditvakt/api.py:get_score()` catch block → HTTP 500. Frontend `else` branch showed generic "Kreditvakt är tillfälligt otillgänglig."

**Underlying cause:** T1 ingestion table migrations (`T1_000`–`T1_003`) were never applied to the Supabase production database. The `score_from_db()` function had a "no rows" fallback but not a "no table" fallback.

**Systemic cause:** No migration runner in Railway deployment; no startup schema validation; no structured error taxonomy to distinguish infrastructure missing from data missing from computation error.

**Five whys:**
1. User sees generic error → frontend catch-all maps all 5xx to one string
2. Endpoint returns 500 → `ProgrammingError` from missing table propagates unhandled
3. Table missing → T1 migrations never run against production DB
4. Migrations not run → no automated migration runner; manual step omitted during initial setup
5. No detection → no health check verified schema; no deployment gate checked migration state

**Resolution:**
1. Ran T1_000–T1_003 migrations against Supabase production (2026-05-08)
2. Added try/except in `score_from_db()` for missing T1 tables → falls back to mock
3. Added structured error taxonomy with specific customer-facing messages
4. Added circuit breaker to fail fast on consecutive DB failures
5. Added structured JSON logging with error codes and stack traces
6. Made API key optional for free tier (IP-based rate limiting)
7. Updated frontend error handling to surface server error messages

**Action items:**
- [ ] Add migration runner to Railway startup command (`python -m migrations.run_all`) — **DRI: Edgar, due: 2026-05-15**
- [ ] Add `/api/health` to uptime monitoring (UptimeRobot free tier) — **DRI: Edgar, due: 2026-05-10**
- [ ] Write integration test: `GET /api/score/{orgnr}` with no key returns 200 — **DRI: Edgar, due: 2026-05-15**
- [ ] Add `SCHEMA_MISSING` alert to Railway monitoring — **DRI: Edgar, due: 2026-05-15**
