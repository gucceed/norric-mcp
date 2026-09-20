# Norway country three - Brønnøysund Enhetsregisteret

## Official sources and access

- API and maintenance-of-copy documentation: https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html
- Open-data terms: https://www.brreg.no/en/use-of-data-from-the-bronnoysund-register-centre/open-data/
- Complete entity download: `GET https://data.brreg.no/enhetsregisteret/api/enheter/lastned` (daily)
- Delta feed: `GET https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter?oppdateringsid=<next>&size=1000`
- Point lookup after each delta: `GET /enheter/{organisasjonsnummer}`

No account, API key or payment is required. Reuse is under NLOD 2.0 with
attribution to Brønnøysundregistrene. The official workflow is total download,
record the copy point, consume update IDs, then refetch each changed entity.
This phase excludes sub-units, roles/persons and beneficial-owner data.

## Residency and network check (2026-09-20)

`data.brreg.no` resolves directly to `195.43.63.68`, AS204027,
Registerenheten i Brønnøysund, Norway. No CDN was observed. Norway is in the
EEA rather than the EU; this upstream is the conscious country-source exception
selected by Edgar. Every Norric worker, store, index, log, backup and cache
remains in the approved EU regions (Amsterdam/Stockholm). Do not place the
Norwegian data behind global-CDN caching. Base Sepolia public RPC remains the
only separate non-EU infrastructure exception.

## Pipeline

- `brreg.bulk_ingest`: daily complete download, incremental gzip/JSON parsing,
  upsert into `norric_no_entities`, persisted field diffs.
- `brreg.updates_poll`: every 15 minutes, monotonic `oppdateringsid` checkpoint,
  idempotent event insert, official point refetch and diff/upsert.
- `brreg.reconcile_nightly`: remote/local update lag and mirror freshness.

Schema: `migrations/NO_001_brreg_core.sql`. Configuration is optional:
`BRREG_BASE_URL` exists only for tests; production must use `data.brreg.no`.

## Paid tools

- `norwegian_company_verify_v1`, lookup band ($0.002), HTTP
  `GET /x402/no/company/verify`
- `norwegian_company_changes_v1`, feed-batch band ($0.02), HTTP
  `GET /x402/no/company/changes`

No-fabrication rules apply. The change tool only emits persisted diffs. A
company's first appearance in Norric is never reported as legal registration.
