import os
from celery import Celery

app = Celery("norric")
app.config_from_object("celeryconfig")

# Auto-discover tasks in all ingestion sub-packages
app.autodiscover_tasks([
    "ingestion.tasks.bolagsverket_tasks",
    "ingestion.tasks.skatteverket_tasks",
    "ingestion.tasks.kronofogden_tasks",
    "ingestion.tasks.scb_tasks",
    "ingestion.tasks.lantmateriet_tasks",
    "ingestion.tasks.boverket_tasks",
    "ingestion.tasks.diarium_tasks",
    "kreditvakt.signal_cross",
    "kreditvakt.contagion",
])

# Kreditvakt scoring/briefing tasks live inside a register_tasks(app) factory
# (kreditvakt/tasks.py), not at module top level, so autodiscover alone won't
# bind them. Register explicitly so kreditvakt.tasks.score_portfolio et al.
# exist on the worker.
from kreditvakt.tasks import register_tasks as _register_kreditvakt_tasks  # noqa: E402

_register_kreditvakt_tasks(app)
