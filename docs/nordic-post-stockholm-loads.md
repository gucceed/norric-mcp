# Nordic post-Stockholm baselines (DK -> NO -> FI)

The first load of each Nordic country into the Stockholm database runs once,
by hand, through a paced and fail-closed runner. Scheduled beats for a country
stay off (see `NORRIC_COUNTRY_BEATS` in `celeryconfig.py`) until its baseline
is done. The chain continues to EE and FR through `run_ee_/run_fr_post_stockholm_load.py`.

| Order | Runner | Confirmation string | Source |
|---|---|---|---|
| 1 | `scripts/run_dk_post_stockholm_load.py` | `STOCKHOLM_FLIP_CONFIRMED` | Datafordeler CVR Fildownload (needs the Datafordeler API key on the worker) |
| 2 | `scripts/run_no_post_stockholm_load.py` | `STOCKHOLM_FLIP_CONFIRMED_AND_DK_LOAD_FINISHED` | Brønnøysund open download (no key) |
| 3 | `scripts/run_fi_post_stockholm_load.py` | `STOCKHOLM_FLIP_CONFIRMED_AND_NO_LOAD_FINISHED` | PRH/YTJ open data (no key) |

## Guards (all fail closed)
1. `--confirm` must equal the country's string, so the order is explicit.
2. The `DATABASE_URL` host must equal `--expected-db-host` exactly. This is checked before `ingestion.db` is imported.
3. The country migration (`*_001`) is applied and its tables verified.
4. The runner refuses to start if the same pipeline has a `running` row in `norric_pipeline_runs` from the last 36 hours.
5. `--batch-size` is capped at 5000 and `--pause-seconds` must be at least 1.

## Pacing and progress
Defaults: `--batch-size 1000 --pause-seconds 30`, about 2,000 rows/min.
After every batch the runner commits and writes progress to the country's
ingest-state row (columns added idempotently on first run):

```sql
SELECT load_status, load_rows_done, load_started_at, load_progress_at
FROM norric_dk_ingest_state WHERE id = 1;
```

`load_status` is `running`, `done` or `failed`. Rows committed before a failure
stay committed. The upserts are idempotent, so a rerun picks up cleanly.

## Run (example, Denmark)
```bash
python3 scripts/run_dk_post_stockholm_load.py \
  --confirm STOCKHOLM_FLIP_CONFIRMED \
  --expected-db-host "$STOCKHOLM_DB_HOST"
```
Once it prints its result with `load_status=done`, enable the country's beats
(`NORRIC_COUNTRY_BEATS=dk`) and redeploy the worker.
