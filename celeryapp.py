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
])
