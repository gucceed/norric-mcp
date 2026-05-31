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
    # T1-01b Bolagsverket konkurs — daily 03:15 (after bulk; reuses cached zip)
    "bolagsverket-konkurs-daily": {
        "task": "bolagsverket.konkurs_ingest",
        "schedule": crontab(hour=3, minute=15),
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
        "kwargs": {"orgnr_list": []},  # empty list triggers full DB rescore via worker
        "options": {"timezone": "Europe/Stockholm"},
    },
    # Daily briefing — 07:00 CET
    "kreditvakt-daily-briefing": {
        "task": "kreditvakt.tasks.send_daily_briefing",
        "schedule": crontab(hour=7, minute=0),
        "options": {"timezone": "Europe/Stockholm"},
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
    # Bolagsverket konkurs signals — daily 03:15 (after bulk; refreshes scoring inputs)
    "kreditvakt-bolagsverket-konkurs": {
        "task": "bolagsverket.konkurs_ingest",
        "schedule": crontab(hour=3, minute=15),
        "options": {"queue": "kreditvakt"},
    },
    # Portfolio rescore over the signal-bearing universe — daily 05:30
    "kreditvakt-score-portfolio": {
        "task": "kreditvakt.tasks.score_portfolio",
        "schedule": crontab(hour=5, minute=30),
        "kwargs": {"orgnr_list": []},  # empty → score_portfolio loads the signal-bearing universe
        "options": {"queue": "kreditvakt"},
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
    }
    beat_schedule = _KREDITVAKT_BEAT_SCHEDULE
else:
    beat_schedule = _FULL_BEAT_SCHEDULE
