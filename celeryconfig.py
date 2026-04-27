import os
from celery.schedules import crontab

broker_url   = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

task_serializer   = "json"
result_serializer = "json"
accept_content    = ["json"]
timezone          = "Europe/Stockholm"
enable_utc        = True

beat_schedule = {
    # T1-01 Bolagsverket bulk — daily 03:00
    "bolagsverket-bulk-daily": {
        "task": "bolagsverket.bulk_ingest",
        "schedule": crontab(hour=3, minute=0),
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
}
