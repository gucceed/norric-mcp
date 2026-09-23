import os
from celery.schedules import crontab

broker_url   = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

task_serializer   = "json"
result_serializer = "json"
accept_content    = ["json"]
timezone          = "Europe/Stockholm"
enable_utc        = True

_FULL_BEAT_SCHEDULE = {
    # T1-01 Bolagsverket bulk — daily 03:00
    "bolagsverket-bulk-daily": {
        "task": "bolagsverket.bulk_ingest",
        "schedule": crontab(hour=3, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-01b Bolagsverket konkurs — daily 04:15 (staggered ~75 min after the
    # 03:00 bulk INSERT so the two write bursts no longer overlap; reuses cached zip)
    "bolagsverket-konkurs-daily": {
        "task": "bolagsverket.konkurs_ingest",
        "schedule": crontab(hour=4, minute=15),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-02 Skatteverket restanslängd — Monday 04:00
    "skatteverket-restanslangd-weekly": {
        "task": "skatteverket.restanslangd_ingest",
        "schedule": crontab(day_of_week=1, hour=4, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-03 Kronofogden — Tuesday 04:00
    "kronofogden-weekly": {
        "task": "kronofogden.payment_ingest",
        "schedule": crontab(day_of_week=2, hour=4, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-04 SCB all tables — first day of quarter 05:00
    "scb-quarterly": {
        "task": "scb.ingest_all_tables",
        "schedule": crontab(month_of_year="1,4,7,10", day_of_month=1, hour=5, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-04 SCB labour market — monthly
    "scb-labour-monthly": {
        "task": "scb.ingest_table",
        "schedule": crontab(day_of_month=2, hour=5, minute=0),
        "kwargs": {"table_id": "AM/AKU/AKU01"},
    },
    # T1-05 Lantmäteriet open — Wednesday 04:00
    "lantmateriet-open-weekly": {
        "task": "lantmateriet.ingest_open",
        "schedule": crontab(day_of_week=3, hour=4, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-06 Boverket energideklarationer — weekly
    "boverket-energidekl-weekly": {
        "task": "boverket.scrape_energideklarationer",
        "schedule": crontab(day_of_week=4, hour=4, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # T1-06 Klimatklivet — monthly
    "klimatklivet-monthly": {
        "task": "boverket.ingest_klimatklivet",
        "schedule": crontab(day_of_month=3, hour=5, minute=0),
    },
    # T1-07 Diarium Skåne — nightly 02:00
    "diarium-skane-nightly": {
        "task": "diarium.crawl_all_skane",
        "schedule": crontab(hour=2, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },

    # ── T2: Kreditvakt scoring ─────────────────────────────────────────────────
    # Rescore all tracked companies nightly after T1 ingestion completes
    "kreditvakt-nightly-rescore": {
        "task": "kreditvakt.tasks.score_portfolio",
        "schedule": crontab(hour=5, minute=30),
        # incremental: score only orgnrs with new signals since the last
        # successful run, plus a 7-day staleness sweep (see score_portfolio).
        # Pass {"orgnr_list": [], "incremental": False} for a manual full rescore.
        "kwargs": {"orgnr_list": [], "incremental": True},
        "options": {"timezone": "Europe/Stockholm"},
    },
    # Daily briefing — 07:00 CET
    "kreditvakt-daily-briefing": {
        "task": "kreditvakt.tasks.send_daily_briefing",
        "schedule": crontab(hour=7, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },

    # ── T3: Norric Watch ─────────────────────────────────────────────────────
    "watch-diff-daily": {
        "task": "watch.diff_emit",
        "schedule": crontab(hour=5, minute=45),
        "options": {"timezone": "Europe/Stockholm"},
    },
    "watch-deliver-pending-1m": {
        "task": "watch.deliver_pending",
        "schedule": crontab(minute="*"),
        "options": {"expires": 50},
    },

    # ── T2: Vigil lifecycle detection ─────────────────────────────────────────
    # F-skatt registrations — nightly after Bolagsverket bulk
    "vigil-fskatt-nightly": {
        "task": "vigil.tasks.detect_fskatt_registrations",
        "schedule": crontab(hour=4, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },
    # Building permits (Malmö) — nightly
    "vigil-permits-nightly": {
        "task": "vigil.tasks.detect_building_permits",
        "schedule": crontab(hour=3, minute=30),
        "kwargs": {"days_back": 7},
        "options": {"timezone": "Europe/Stockholm"},
    },
    # Ownership change velocity — weekly (snapshots accumulate slowly)
    "vigil-ownership-weekly": {
        "task": "vigil.tasks.detect_ownership_changes",
        "schedule": crontab(day_of_week=0, hour=3, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
    },

    # ── SIGNAL: Kreditvakt cross-signal ────────────────────────────────────────
    # Score newly scraped contracts every 15 minutes
    "signal-score-unscored-15m": {
        "task": "signal.score_unscored",
        "schedule": crontab(minute="*/15"),
        "options": {"expires": 600},
    },
    # Rescore active contracts nightly (02:15 UTC ≈ 04:15 CEST Stockholm)
    "signal-rescore-active-nightly": {
        "task": "signal.rescore_active",
        "schedule": crontab(hour=2, minute=15),
        "options": {"expires": 7200},
    },
    # Refresh supply-chain contagion peers for HIGH/CRITICAL companies every 4h
    "signal-refresh-contagion-4h": {
        "task": "signal.refresh_contagion",
        "schedule": crontab(minute=30, hour="*/4"),
        "options": {"expires": 3600},
    },

    # ── DK: CVR (Datafordeler) country two ───────────────────────────────────
    # Weekly total-download baseline - generated Saturday night 03:00-06:00
    # Danish time, archived after 7 days. Saturday 08:00 Europe/Stockholm.
    "cvr-bulk-weekly": {
        "task": "cvr.bulk_ingest",
        "schedule": crontab(day_of_week=6, hour=8, minute=0),
        "options": {"timezone": "Europe/Stockholm", "expires": 7200},
    },
    # CVR_Events deltas - every 15 minutes (operational target; Datafordeler
    # publishes no numeric latency SLA for the event stream).
    "cvr-events-poll-15m": {
        "task": "cvr.events_poll",
        "schedule": crontab(minute="*/15"),
        "options": {"expires": 600},
    },
    # Nightly drift monitor: event-lag, freshness, baseline age.
    "cvr-reconcile-nightly": {
        "task": "cvr.reconcile_nightly",
        "schedule": crontab(hour=6, minute=0),
        "options": {"timezone": "Europe/Stockholm", "expires": 3600},
    },
    # NO: Brønnøysund Enhetsregisteret country three. Daily baseline plus deltas.
    "brreg-bulk-daily": {"task": "brreg.bulk_ingest", "schedule": crontab(hour=7, minute=15), "options": {"timezone": "Europe/Stockholm", "expires": 10800}},
    "brreg-updates-poll-15m": {"task": "brreg.updates_poll", "schedule": crontab(minute="7,22,37,52"), "options": {"expires": 600}},
    "brreg-reconcile-nightly": {"task": "brreg.reconcile_nightly", "schedule": crontab(hour=6, minute=30), "options": {"timezone": "Europe/Stockholm", "expires": 3600}},
    # FI: PRH/YTJ country four. Daily full snapshot; no source delta API.
    "prh-bulk-daily": {"task": "prh.bulk_ingest", "schedule": crontab(hour=7, minute=45), "options": {"timezone": "Europe/Stockholm", "expires": 10800}},
    # EE: e-Ariregister country five prep. Daily full snapshot; the keyless open-data
    # files are the baseline (real-time SOAP/XML API needs a signed RIK contract).
    "ariregister-bulk-daily": {"task": "ariregister.bulk_ingest", "schedule": crontab(hour=8, minute=15), "options": {"timezone": "Europe/Stockholm", "expires": 10800}},
    # FR: Sirene country six prep. Monthly stock files on data.gouv are the baseline
    # (Licence Ouverte 2.0, keyless); non-diffusible persons are excluded at ingest.
    "sirene-bulk-daily": {"task": "sirene.bulk_ingest", "schedule": crontab(hour=8, minute=45), "options": {"timezone": "Europe/Stockholm", "expires": 21600}},

}

# ── Role-scoped beat / queue selection ────────────────────────────────────────
# The full schedule above (T1 ingestion + vigil + signal) targets a future
# general "norric" worker that is not yet deployed. Today the only deployed
# consumer of this app is the Kreditvakt worker, which must stay isolated from
# the shared sigvik queues/Redis. When CELERY_ROLE=kreditvakt:
#   • beat fires ONLY the kreditvakt-relevant tasks,
#   • those tasks route to a dedicated `kreditvakt` queue (worker runs -Q kreditvakt),
#   • broker/result Redis uses its own DB index (REDIS_URL=.../1 set on the service).
CELERY_ROLE = os.environ.get("CELERY_ROLE", "").strip().lower()

_KREDITVAKT_BEAT_SCHEDULE = {
    # Bolagsverket entity bulk — daily 03:00 Europe/Stockholm
    "kreditvakt-bolagsverket-bulk": {
        "task": "bolagsverket.bulk_ingest",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "kreditvakt"},
    },
    # Bolagsverket konkurs signals — daily 04:15 (staggered ~75 min after the
    # 03:00 bulk INSERT; refreshes scoring inputs ahead of the 05:30 rescore)
    "kreditvakt-bolagsverket-konkurs": {
        "task": "bolagsverket.konkurs_ingest",
        "schedule": crontab(hour=4, minute=15),
        "options": {"queue": "kreditvakt"},
    },
    # Incremental portfolio rescore — daily 05:30
    "kreditvakt-score-portfolio": {
        "task": "kreditvakt.tasks.score_portfolio",
        "schedule": crontab(hour=5, minute=30),
        # empty list + incremental → only orgnrs with signals created since the
        # last successful run, plus a 7-day staleness sweep. Full rescore stays
        # available by passing {"orgnr_list": [], "incremental": False}.
        "kwargs": {"orgnr_list": [], "incremental": True},
        "options": {"queue": "kreditvakt"},
    },

    # ── T3: Norric Watch ─────────────────────────────────────────────────────
    # Diff emission — daily 05:45, after the portfolio rescore
    "watch-diff-daily": {
        "task": "watch.diff_emit",
        "schedule": crontab(hour=5, minute=45),
        "options": {"queue": "kreditvakt"},
    },
    # Signed delivery sweep — every minute (retry schedule is minute-grained)
    "watch-deliver-pending-1m": {
        "task": "watch.deliver_pending",
        "schedule": crontab(minute="*"),
        "options": {"queue": "kreditvakt", "expires": 50},
    },
}

if CELERY_ROLE == "kreditvakt":
    task_default_queue = "kreditvakt"
    task_routes = {
        "bolagsverket.bulk_ingest":             {"queue": "kreditvakt"},
        "bolagsverket.konkurs_ingest":          {"queue": "kreditvakt"},
        "kreditvakt.tasks.score_portfolio":     {"queue": "kreditvakt"},
        "kreditvakt.tasks.score_single":        {"queue": "kreditvakt"},
        "kreditvakt.tasks.send_daily_briefing": {"queue": "kreditvakt"},
        "watch.diff_emit":                    {"queue": "kreditvakt"},
        "watch.deliver_pending":              {"queue": "kreditvakt"},
    }
    beat_schedule = _KREDITVAKT_BEAT_SCHEDULE
else:
    beat_schedule = _FULL_BEAT_SCHEDULE
