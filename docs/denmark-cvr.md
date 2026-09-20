# Denmark country two - CVR via Datafordeler

Norric's second country. Mirrors the Swedish pipeline shape (bulk baseline +
event deltas + nightly reconciliation + paid verify/changes tools) onto
Denmark's Central Business Register (CVR), served by Datafordeleren.

## Sources (all official, all EU)

| Interface | Endpoint | Use | Access | License |
|---|---|---|---|---|
| CVR Fildownload | `https://api.datafordeler.dk/FileDownloads/v1.0/GetFile` | Weekly total-download baseline (Sat night 03:00-06:00 generation, 7-day archive) | API key | CC BY 4.0 |
| CVR GraphQL | `https://graphql.datafordeler.dk/CVR/v1` | Point lookup, `CVR_Events` deltas, `DAF_RegisterImportStatus` | API key (OAuth for restricted entities) | CC BY 4.0 |

Docs:
- https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/
- https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/cvr-fildownload/
- https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/cvr-graphql/
- https://confluence.kds.dk/pages/viewpage.action?pageId=219514028 (entity-based events)
- Terms: https://datafordeler.dk/vejledning/brugervilkaar/det-centrale-virksomhedsregister-cvr/

The legacy `services.datafordeler.dk` Haendelser service is deprecated
(ultimo 2026 / 2027-01-15) and is not used. Non-person CVR entities need no
access request; `CVRPerson` is confidential and is not ingested. Beneficial
owners (reelle ejere) have been restricted since 2025-09-01 and are not
ingested or exposed anywhere in this pipeline.

## EU residency verification (2026-09-20)

- `api.datafordeler.dk`, `graphql.datafordeler.dk`, `services.datafordeler.dk`
  all resolve to 87.60.242.40, AS3292 (TDC Holding A/S, Denmark). No global
  CDN in the path.
- `regnskaber.virk.dk` (later filings phase) resolves to AWS S3 eu-west-1
  (Ireland) - EU.
- `datacvr.virk.dk` is Cloudflare-fronted (104.20.x/172.66.x, global CDN).
  It is never called by this pipeline; per the EU-only bar, no Danish data
  may be fetched through or cached by a global CDN. Evidence links in tool
  responses point at datafordeler.dk only.
- Ingestion workers, raw landing, Postgres, Redis, queues, logs and backups
  stay in the existing Amsterdam/Stockholm stack (Railway norric-production,
  Supabase). The only approved non-EU exception remains the public Base
  Sepolia RPC (testnet metadata).

## Configuration

| Env var | Purpose |
|---|---|
| `DATAFORDELER_API_KEY` | API key for Fildownload + GraphQL (zone-0 entities) |
| `DATAFORDELER_FILEDOWNLOAD_BASE` | Override fildownload base URL (default `https://api.datafordeler.dk/FileDownloads/v1.0`) |
| `DATAFORDELER_GRAPHQL_URL` | Override GraphQL URL (default `https://graphql.datafordeler.dk/CVR/v1`) |

Account setup (build-order step 1): create a Datafordeler user on the
Administration site, register Norric as an IT system, issue an API key.
Accept the CVR brugervilkaar. No access request is needed for non-person
entities. Confirm operational quotas at setup; no numeric quota is published,
so the client runs bounded retries with 429/5xx backoff.

## Pipeline

- `cvr.bulk_ingest` - weekly Saturday 08:00 (Europe/Stockholm). Downloads the
  latest current total downloads for `Virksomhed`, `Navn`, `Adressering`,
  `Branche`, `Virksomhedsform` (+ `Produktionsenhed` reserved), upserts
  `norric_dk_entities`, diffs tracked fields into `norric_dk_field_changes`.
- `cvr.events_poll` - every 15 min. Reads `CVR_Events` above the checkpoint,
  processes only packages at or below `DAF_RegisterImportStatus.lastSequenceNumber`,
  refetches changed virksomhed rows by `object_datafordelerRowId`, upserts +
  diffs, advances the checkpoint idempotently (`norric_dk_events.event_id`).
- `cvr.reconcile_nightly` - 06:00. Drift monitor: event lag vs register
  import status, mirror freshness, baseline age. No company-data mutation.

Cadence honesty: Datafordeler publishes no numeric latency SLA for
`CVR_Events`. Freshness claims come from `norric_pipeline_runs` and the
reconcile report - never marketed as real-time until measured.

## Tools (x402, Base Sepolia testnet, same bands as Sweden)

- `danish_company_verify_v1` - lookup band ($0.002). CVR number or name in,
  cited identity/status/changes out. HTTP: `GET /x402/dk/company/verify`.
- `danish_company_changes_v1` - feed_batch band ($0.02). 1-30 day window of
  source-backed changes (new_registration, closure, rename, address_change,
  merger). HTTP: `GET /x402/dk/company/changes`.

Data rules: Danish codes/labels are canonical and never translated; names and
addresses verbatim UTF-8; untracked fields return `not_tracked`/null - never
fabricated; no first-seen-as-registration inference; no merger inference
without fusion evidence in the source.

## Field-mapping validation checklist (first real download)

The normalizer (`ingestion/cvr/normalize.py`) maps from official
objekttypekatalog field names with documented candidate keys. On the first
run with real credentials:

1. Diff mapped vs raw for a sample of 50 virksomhed rows; every populated
   source field should land in a column or remain visible in `raw`.
2. Confirm the fildownload JSON envelope (array vs wrapped vs NDJSON) and the
   bitemporal `registreringFra/Til`, `virkningFra/Til` casing.
3. Confirm `CVR_Events` accepts the sequence filter and page through a batch.
4. Measure event latency (event `datafordelerOpdateringstid` vs ingest time)
   before any freshness claim.
5. Record quotas observed (429s) and tune the backoff budget.
