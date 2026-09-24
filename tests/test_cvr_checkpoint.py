"""CVR events checkpoint: seeded by the bulk baseline, fail-closed poll, stale guard."""
from types import SimpleNamespace

import pytest

import ingestion.cvr.bulk_pipeline as bulk
import ingestion.cvr.events_pipeline as events
from ingestion.cvr import client


class Result(list):
    def __init__(self, rows=(), one=None, scalar=None, rowcount=1):
        super().__init__(rows)
        self._one, self._scalar, self.rowcount = one, scalar, rowcount

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self)

    def scalar(self):
        return self._scalar


class FakeDB:
    def __init__(self, state=None, stale=False):
        self.calls, self.commits = [], 0
        self.state, self.stale = state, stale

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "INSERT INTO norric_pipeline_runs" in sql:
            return Result(one=SimpleNamespace(id="run-1"))
        if "FROM norric_dk_ingest_state" in sql:
            return Result(one=self.state)
        if "< registrering_fra" in sql:
            return Result(scalar=self.stale)
        return Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass

    def sql_matching(self, needle):
        return [(s, p) for s, p in self.calls if needle in s]


# -- A: seeding -------------------------------------------------------------

def test_total_download_sequence_reads_matching_entry(monkeypatch):
    monkeypatch.setattr(client, "get_available_file_downloads", lambda: [
        {"Entity": "Navn", "Type": "Total", "RegisterImportSequenceNumber": 999},
        {"Entity": "Virksomhed", "Type": "TotalDownload", "RegisterImportSequenceNumber": "4521"},
        {"Entity": "Virksomhed", "Type": "Delta", "SequenceNumber": 9999},
    ])
    assert client.total_download_sequence("Virksomhed") == 4521


def test_total_download_sequence_none_when_absent(monkeypatch):
    monkeypatch.setattr(client, "get_available_file_downloads",
                        lambda: [{"Entity": "Virksomhed", "Type": "Total", "Size": 10}])
    assert client.total_download_sequence("Virksomhed") is None


def test_baseline_sequence_prefers_file_metadata(monkeypatch):
    monkeypatch.setattr(client, "total_download_sequence", lambda e: 4521)
    monkeypatch.setattr(client, "fetch_register_import_status",
                        lambda: pytest.fail("fallback must not be used"))
    assert bulk._baseline_sequence() == (4521, "file_download_metadata")


def test_baseline_sequence_falls_back_to_status(monkeypatch):
    def boom(e):
        raise RuntimeError("no metadata")
    monkeypatch.setattr(client, "total_download_sequence", boom)
    monkeypatch.setattr(client, "fetch_register_import_status", lambda: {"lastSequenceNumber": 700})
    assert bulk._baseline_sequence() == (700, "register_import_status_pre_download")


def test_baseline_sequence_never_raises(monkeypatch):
    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(client, "total_download_sequence", boom)
    monkeypatch.setattr(client, "fetch_register_import_status", boom)
    assert bulk._baseline_sequence() == (None, None)


def test_bulk_seeds_checkpoint_forward_only(monkeypatch, tmp_path):
    db = FakeDB()
    order = []
    monkeypatch.setattr(bulk, "Session", lambda: db)
    monkeypatch.setattr(bulk, "_baseline_sequence", lambda: order.append("seq") or (4521, "file_download_metadata"))

    def fake_download(entity, dest, **kw):
        order.append(entity)
        path = tmp_path / f"{entity}.zip"
        path.write_text("x")
        return path
    monkeypatch.setattr(bulk.client, "download_latest_total", fake_download)
    monkeypatch.setattr(bulk.client, "extract_json_rows", lambda p: [])
    out = bulk.run_bulk_pipeline()
    assert order[0] == "seq"  # read before any file download
    (sql, params), = db.sql_matching("last_bulk_filename")
    assert "GREATEST(last_sequence_number" in sql
    assert params["seq"] == 4521
    assert out["checkpoint_seed"] == 4521


# -- B: fail closed ---------------------------------------------------------

@pytest.mark.parametrize("state", [
    None,
    SimpleNamespace(last_sequence_number=0, last_event_id=0, last_bulk_at="2026-09-25"),
    SimpleNamespace(last_sequence_number=4521, last_event_id=0, last_bulk_at=None),
])
def test_events_poll_skips_unseeded_checkpoint(monkeypatch, state):
    db = FakeDB(state=state)
    monkeypatch.setattr(events, "Session", lambda: db)
    monkeypatch.setattr(events.client, "fetch_register_import_status",
                        lambda: pytest.fail("must not call Datafordeler"))
    monkeypatch.setattr(events.client, "fetch_events", lambda *a, **k: pytest.fail("must not fetch"))
    out = events.run_events_pipeline()
    assert out["skipped"] == "checkpoint_not_seeded"
    assert not db.sql_matching("UPDATE norric_dk_ingest_state")


# -- C: stale guard ---------------------------------------------------------

def _run_one_event(monkeypatch, stale):
    state = SimpleNamespace(last_sequence_number=100, last_event_id=0, last_bulk_at="2026-09-25")
    db = FakeDB(state=state, stale=stale)
    monkeypatch.setattr(events, "Session", lambda: db)
    monkeypatch.setattr(events.client, "fetch_register_import_status", lambda: {"lastSequenceNumber": 101})
    monkeypatch.setattr(events.client, "fetch_events", lambda since, batch_size=1000: [{
        "datafordelerRegisterImportSequenceNumber": 101, "eventid": 5,
        "entityname": "CVR_Virksomhed", "object_datafordelerRowId": "row-1"}])
    monkeypatch.setattr(events.client, "fetch_virksomhed_by_row_id", lambda rid: {"row": rid})
    monkeypatch.setattr(events, "map_virksomhed_row", lambda row: {
        "cvr_number": "12345678", "registrering_fra": "2020-01-01T00:00:00+00:00", "raw": {}})
    monkeypatch.setattr(events, "_diff_and_write", lambda *a, **k: 0)
    out = events.run_events_pipeline()
    return db, out


def test_stale_row_version_is_not_upserted(monkeypatch):
    db, out = _run_one_event(monkeypatch, stale=True)
    assert not db.sql_matching("INSERT INTO norric_dk_entities")
    assert out["rows_skipped"] == 1
    (sql, params), = db.sql_matching("UPDATE norric_dk_ingest_state")
    assert params["seq"] == 101  # checkpoint still advances


def test_newer_row_version_is_upserted(monkeypatch):
    db, _ = _run_one_event(monkeypatch, stale=False)
    assert len(db.sql_matching("INSERT INTO norric_dk_entities")) == 1
