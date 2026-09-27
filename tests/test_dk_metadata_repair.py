"""Regression tests for official Datafordeler entity links and event safety."""
from ingestion.cvr.normalize import build_side_index, map_virksomhed_row
from ingestion.cvr.events_pipeline import _EVENT_UPSERT_SQL, _EVENT_DIFF_FIELDS
from ingestion.cvr.bulk_pipeline import _UPSERT_SQL


def test_official_entity_id_and_fields_not_cvr_number():
    entity_id = "1234567890"
    sides = {}
    for entity, rows in (
        ("Navn", [{"CVREnhedsId": entity_id, "vaerdi": "Ærø Øko ApS", "sekvens": 1,
                    "registreringFra": "2020-01-01", "virkningFra": "2020-01-01"}]),
        ("Branche", [{"CVREnhedsId": entity_id, "vaerdi": "123456", "vaerdiTekst": "Landbrug"}]),
        ("Virksomhedsform", [{"CVREnhedsId": entity_id, "vaerdi": "80",
                             "vaerdiTekst": "Aktieselskab"}]),
        ("Adressering", [{"CVREnhedsId": entity_id,
                          "AdresseringAnvendelse": "beliggenhedsadresse",
                          "CVRAdresse_vejnavn": "Købmagergade", "CVRAdresse_husnummerFra": "2",
                          "CVRAdresse_postnummer": "1150", "CVRAdresse_postdistrikt": "København K",
                          "CVRAdresse_kommunekode": "0101"}]),
    ):
        for k, value in build_side_index(entity, rows).items():
            sides.setdefault(k, {}).update(value)
    assert "54562519" not in sides
    rec = map_virksomhed_row({"id": entity_id, "CVRNummer": 54562519}, side=sides[entity_id])
    assert (rec["name"], rec["industry_code"], rec["legal_form_code"],
            rec["street"], rec["city"]) == (
        "Ærø Øko ApS", "123456", "80", "Købmagergade 2", "København K")


def test_closed_or_non_location_versions_not_resurrected():
    assert build_side_index("Navn", [{"CVREnhedsId": "1", "vaerdi": "Old",
                                     "registreringTil": "2022-01-01"}]) == {}
    assert build_side_index("Adressering", [{"CVREnhedsId": "1",
        "AdresseringAnvendelse": "postadresse", "CVRAdresse_postnummer": "1000"}]) == {}


def test_event_upsert_cannot_erase_side_fields():
    updates = _EVENT_UPSERT_SQL.split("ON CONFLICT (cvr_number) DO UPDATE SET", 1)[1]
    for field in ("name", "legal_form_code", "industry_code", "street", "city",
                  "postcode", "raw_address"):
        assert f"{field}=" not in updates and f"{field} =" not in updates
        assert field not in _EVENT_DIFF_FIELDS
    assert "name = EXCLUDED.name" in _UPSERT_SQL


def test_validator_is_read_only_by_default():
    import inspect
    from scripts.validate_or_backfill_dk_metadata import main
    src = inspect.getsource(main)
    assert 'if args.apply:' in src
    assert 'DK_METADATA_BACKFILL_APPROVED' in src
    assert 'backfill(' in src


def test_structural_validation_refuses_empty_join(monkeypatch, tmp_path):
    import pytest
    from pathlib import Path
    from scripts import validate_or_backfill_dk_metadata as check
    monkeypatch.setattr(check.client, "download_latest_total", lambda entity, dest:
                        (dest / (entity + ".zip")))
    monkeypatch.setattr(Path, "stat", lambda self: type("stat", (), {"st_size": 100})())
    def fake_rows(path):
        if path.stem == "Virksomhed":
            return [{"id": "different", "CVRNummer": 54562519}]
        return [{"CVREnhedsId": "1", "vaerdi": "Test", "vaerdiTekst": "Test",
                 "AdresseringAnvendelse": "beliggenhedsadresse",
                 "CVRAdresse_postnummer": "1000"}]
    monkeypatch.setattr(check.client, "extract_json_rows", fake_rows)
    with pytest.raises(RuntimeError, match="names match fewer"):
        check.inspect_files(tmp_path)


def test_bulk_refuses_unmatched_names_before_upsert(monkeypatch, tmp_path):
    import pytest
    from ingestion.cvr import bulk_pipeline as bulk
    from ingestion.cvr.client import DatafordelerError
    from tests.test_cvr_checkpoint import FakeDB
    db = FakeDB()
    monkeypatch.setattr(bulk, "Session", lambda: db)
    monkeypatch.setattr(bulk, "_baseline_sequence", lambda: (1, "test"))
    def download(entity, dest):
        path = tmp_path / (entity + ".zip")
        path.write_text("fixture")
        return path
    monkeypatch.setattr(bulk.client, "download_latest_total", download)
    monkeypatch.setattr(bulk.client, "extract_json_rows", lambda p:
                        [{"id": "2", "CVRNummer": 54562519}] if p.stem == "Virksomhed" else
                        [{"CVREnhedsId": "1", "vaerdi": "Wrong ID"}] if p.stem == "Navn" else [])
    with pytest.raises(DatafordelerError, match="matched a current Navn"):
        bulk.run_bulk_pipeline()
    assert not db.sql_matching("INSERT INTO norric_dk_entities")
