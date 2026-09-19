# Compounding core Stage 0

Status: design contract only. This branch changes no beat, server tool, worker schedule, deployed service or live database.

## Scope

Stage 0 fixes the contract before Norric starts accumulating irreversible event history:

- canonical event taxonomy and deterministic hashing, including `entity.layoff_notice.changed`;
- review-only forward and rollback migrations;
- local cost instrumentation;
- synthetic fixtures, varsel join-confidence rules, held-out backtest design and tests;
- an EU-only dependency inventory;
- a representative storage-estimation method.

Later stages require separate approval. Do not merge, apply a migration, deploy, backfill or expose an MCP tool from this PR alone.

## Event taxonomy

| Event type | First source | Trigger in a later stage |
|---|---|---|
| `entity.address.changed` | `bolagsverket_bulk` | Registered address differs from the previous observed snapshot |
| `entity.officer.added` | `bolagsverket_bulk` | Stable person/role pair appears |
| `entity.officer.removed` | `bolagsverket_bulk` | Stable person/role pair disappears |
| `entity.capital.changed` | `bolagsverket_bulk` | Registered capital differs |
| `entity.filing.added` | `bolagsverket_bulk` | Filing identity appears for the first time |
| `entity.bankruptcy.changed` | `bolagsverket_konkurs` | Bankruptcy status/case changes |
| `entity.score.changed` | `kreditvakt_scoring` | Risk band or approved score field changes |
| `entity.layoff_notice.changed` | `arbetsformedlingen_varsel` | Exact-orgnr matched notice appears or materially changes |

All timestamps are timezone-aware. `source_observed_at` is the source's fact time; `detected_at` is Norric's detection time. `idempotency_key` excludes `detected_at`, so replaying the same observed mutation cannot create a second logical event.

## Schema and transaction plan

`migrations/T5_001_entity_events.sql` introduces `entity_events` plus a daily metrics table. Stage 1 beat adapters must write the source state, its event and the beat checkpoint in one Postgres transaction. A failed event write must roll back the checkpoint.

Varsel matching and the held-out validation plan are defined in `varsel-backtest.md`; name-only matches never auto-score. The initial schema is not partitioned. Partitioning millions of existing entities would optimise the wrong variable: row count depends on observed mutations after launch, not the current entity count. Add monthly partitions only after query plans or measured growth justify them.

Rollback is in `T5_001_entity_events.down.sql`. It is destructive by definition. Before any approved rollback: disable writers, export and count event rows, verify the export hash, then apply the down migration in Stockholm. Nothing in Stage 0 performs those steps.

## Evidence and privacy

- `before_json` and `after_json` contain only changed values, not duplicate full entities.
- `evidence_json` contains the minimum source references needed to reproduce the claim.
- `evidence_hash` is SHA-256 over canonical evidence JSON.
- Officer events use a stable internal person key. Raw personal identifiers must not be copied into webhook payloads unless the customer's permitted source package requires them.
- Corrections append a correcting event in a later stage. Do not rewrite observed history.

## EU-only dependency inventory

| Layer | Approved v0 location | Stage 0 decision |
|---|---|---|
| Postgres, metrics, event history, backups | Supabase Stockholm | Keep all event state and metrics here |
| API, beat adapters, worker, temporary processing | Railway Amsterdam | Use current services; add no service in Stage 0 |
| Queue/result state | Current Railway-attached Redis in Amsterdam | Reuse only; no external relay |
| Webhook delivery | Direct from Railway Amsterdam | No webhook relay or delivery SaaS |
| Runtime logs | Existing EU-hosted runtime only | No third-party log or error service |
| Builds/artifacts | Existing controlled repo/CI path, subject to residency audit before Stage 1 | Do not add a vendor in this PR |
| CDN/analytics | None for the core | No CDN, analytics SDK or tracking pixel |
| Secrets | Existing service secret store | Never place signing secrets in events or logs |

The current `requirements.txt` contains non-EU vendors/SDKs used by other repo surfaces (for example Anthropic, Stripe and Google Generative AI). Stage 0 adds **zero dependencies** and the core event path must not import or call them. Before Stage 1 deploy approval, confirm no shared middleware sends event data, request bodies or logs to those services.

## Cost instrumentation and stop-gate

The approved additional run-rate for all three products is no more than USD 30/month. `entity_event_daily_metrics` records rows, payload bytes, beat runtime and queued deliveries without a new vendor.

Stage 1 approval needs a Stockholm rehearsal against a representative diff sample. Record:

```sql
SELECT
  count(*) AS rows,
  pg_size_pretty(pg_total_relation_size('entity_events')) AS total_size,
  pg_size_pretty(pg_relation_size('entity_events')) AS heap_size,
  pg_size_pretty(pg_indexes_size('entity_events')) AS index_size,
  avg(pg_column_size(e)) AS avg_row_bytes
FROM entity_events e;
```

Also record WAL growth, backup growth, beat runtime, delivery volume and current Supabase/Railway billed deltas. Stop if forecast total additional cost exceeds $30/month or Stage 1 alone exceeds its $20/month ceiling.

### Synthetic payload estimate

`scripts/estimate_event_storage.py` measures compact JSON payloads for four representative events. At the time of this PR the mean is **about 445 bytes**, or **about 0.436 GiB per million events** for payload JSON alone. It deliberately excludes Postgres row overhead, indexes, WAL and backups. It is a lower bound, not a production capacity estimate.

## Acceptance for Stage 0

- Taxonomy covers the approved v0 mutation classes and rejects unknown values.
- Canonical hashing is stable across map ordering.
- Replaying the same source observation yields the same idempotency key.
- Changing before/after values changes the idempotency key.
- Naive timestamps are rejected.
- Forward and rollback SQL are reviewable but unapplied.
- Cost metrics stay inside Supabase Stockholm and require no new service.
- Dependency count remains unchanged.
- Existing test suite stays green.

## Next approval boundary

After review, Stage 1 is a separate branch and PR for beat adapters, transactional writes, cursor feed, evidence lookup and freshness status. It requires a Stockholm rehearsal and explicit approval before merge or deployment.
