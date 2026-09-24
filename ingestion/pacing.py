"""Slow-and-safe pacing for one-shot country baselines.

Scheduled beats call the bulk pipelines without a pacer and keep their
existing behaviour. The post-Stockholm runners pass a Pacer so a first load
commits in small batches, sleeps between batches, and writes progress to the
country's ingest-state row after every batch.
"""
from __future__ import annotations

import time
from typing import Callable

from sqlalchemy import text

_ALLOWED_STATE_TABLES = frozenset({
    "norric_dk_ingest_state",
    "norric_no_ingest_state",
    "norric_fi_ingest_state",
})

PROGRESS_COLUMNS_SQL = """
ALTER TABLE {table}
    ADD COLUMN IF NOT EXISTS load_rows_done bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS load_status text,
    ADD COLUMN IF NOT EXISTS load_started_at timestamptz,
    ADD COLUMN IF NOT EXISTS load_progress_at timestamptz
"""


def _check_table(table: str) -> str:
    if table not in _ALLOWED_STATE_TABLES:
        raise ValueError(f"unknown ingest-state table {table!r}")
    return table


class Pacer:
    def __init__(self, state_table: str, batch_size: int = 1000,
                 pause_seconds: float = 30.0,
                 sleep: Callable[[float], None] = time.sleep):
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if pause_seconds < 0:
            raise ValueError("pause_seconds must be >= 0")
        self.db = None
        self.table = _check_table(state_table)
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds
        self._sleep = sleep
        self.rows_done = 0
        self._pending = 0

    def bind(self, db) -> "Pacer":
        """Attach the pipeline's own session so batch commits cover its writes."""
        self.db = db
        return self

    def start(self) -> None:
        self.db.execute(text(
            f"UPDATE {self.table} SET load_rows_done=0, load_status='running', "
            "load_started_at=now(), load_progress_at=now(), updated_at=now() WHERE id=1"))
        self.db.commit()

    def _write_progress(self, status: str) -> None:
        self.db.execute(text(
            f"UPDATE {self.table} SET load_rows_done=:n, load_status=:s, "
            "load_progress_at=now(), updated_at=now() WHERE id=1"),
            {"n": self.rows_done, "s": status})

    def tick(self, n: int = 1) -> None:
        self.rows_done += n
        self._pending += n
        if self._pending >= self.batch_size:
            self._write_progress("running")
            self.db.commit()
            self._pending = 0
            if self.pause_seconds:
                self._sleep(self.pause_seconds)

    def finish(self, status: str = "done") -> None:
        self._write_progress(status)
        self.db.commit()
