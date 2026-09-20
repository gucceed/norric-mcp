"""
Tests for ingestion/cvr client + normalize - parsing and mapping only, no network.
"""

import io
import json
import zipfile

import pytest


def _zip_with_json(payload_text: str, name: str = "data.json"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload_text)
    buf.seek(0)
    return buf


class TestExtractJsonRows:
    def _extract(self, buf, tmp_path):
        from ingestion.cvr.client import extract_json_rows
        p = tmp_path / "test.zip"
        p.write_bytes(buf.read())
        return extract_json_rows(p)

    def test_bare_array(self, tmp_path):
        rows = self._extract(_zip_with_json(json.dumps([{"cvrNummer": 54562519}])), tmp_path)
        assert rows == [{"cvrNummer": 54562519}]

    def test_wrapped_features(self, tmp_path):
        payload = {"features": [{"cvrNummer": 54562519}, {"cvrNummer": 10150817}]}
        rows = self._extract(_zip_with_json(json.dumps(payload)), tmp_path)
        assert len(rows) == 2

    def test_ndjson(self, tmp_path):
        text = '{"cvrNummer": 54562519}\n{"cvrNummer": 10150817}\n'
        rows = self._extract(_zip_with_json(text), tmp_path)
        assert len(rows) == 2

    def test_utf8_danish_letters_preserved(self, tmp_path):
        rows = self._extract(_zip_with_json(
            json.dumps([{"navn": "Københavns Sølvvarefabrik ÆØÅ ApS"}])), tmp_path)
        assert rows[0]["navn"] == "Københavns Sølvvarefabrik ÆØÅ ApS"

    def test_no_json_raises(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "no data")
        buf.seek(0)
        from ingestion.cvr.client import extract_json_rows, DatafordelerError
        p = tmp_path / "bad.zip"
        p.write_bytes(buf.read())
        with pytest.raises(DatafordelerError):
            extract_json_rows(p)


class TestConfigGuard:
    def test_missing_api_key_raises_clear_error(self, monkeypatch):
        monkeypatch.delenv("DATAFORDELER_API_KEY", raising=False)
        from ingestion.cvr.client import _api_key, DatafordelerConfigError
        with pytest.raises(DatafordelerConfigError, match="DATAFORDELER_API_KEY"):
            _api_key()


class TestMapVirksomhedRow:
    def test_flat_row_maps(self):
        from ingestion.cvr.normalize import map_virksomhed_row
        row = {
            "cvrNummer": 54562519,
            "navn": "LEGO A/S",
            "virksomhedsform": {"kode": "80", "langBeskrivelse": "Aktieselskab"},
            "virksomhedsstatus": "NORMAL",
            "startDato": "1932-08-10",
            "hovedbranche": {"kode": "32.40.00",
                             "langBeskrivelse": "Fremstilling af spil og legetøj"},
            "registreringFra": "2000-01-01T00:00:00+01:00",
            "virkningFra": "1932-08-10",
        }
        rec = map_virksomhed_row(row)
        assert rec["cvr_number"] == "54562519"
        assert rec["name"] == "LEGO A/S"
        assert rec["legal_form_code"] == "80"
        assert rec["legal_form_label"] == "Aktieselskab"
        assert rec["is_active"] is True
        assert rec["industry_code"] == "32.40.00"
        assert rec["raw"] is row

    def test_unknown_fields_degrade_to_none_never_invented(self):
        from ingestion.cvr.normalize import map_virksomhed_row
        rec = map_virksomhed_row({"cvrNummer": 54562519, "someNewField": "x"})
        assert rec["cvr_number"] == "54562519"
        assert rec["name"] is None
        assert rec["legal_form_code"] is None
        assert rec["status_code"] is None
        assert rec["street"] is None

    def test_ceased_marks_inactive(self):
        from ingestion.cvr.normalize import map_virksomhed_row
        rec = map_virksomhed_row({"cvrNummer": 54562519,
                                  "ophorsDato": "2026-01-15"})
        assert rec["is_active"] is False
        assert rec["ceased_at"] == "2026-01-15"

    def test_closed_bitemporal_row_marks_inactive(self):
        from ingestion.cvr.normalize import map_virksomhed_row
        rec = map_virksomhed_row({"cvrNummer": 54562519,
                                  "registreringTil": "2026-03-01T00:00:00+01:00"})
        assert rec["is_active"] is False

    def test_no_cvr_number_returns_none(self):
        from ingestion.cvr.normalize import map_virksomhed_row
        assert map_virksomhed_row({"navn": "No Number ApS"}) is None

    def test_side_index_fills_name_address_industry(self):
        from ingestion.cvr.normalize import build_side_index, map_virksomhed_row
        sides = {}
        for cvr, values in build_side_index("Navn", [
            {"cvrNummer": 54562519, "navn": "LEGO A/S"},
        ]).items():
            sides.setdefault(cvr, {}).update(values)
        for cvr, values in build_side_index("Adressering", [
            {"cvrNummer": 54562519, "vejnavn": "Aastvej", "husnummerFra": "1",
             "postnummer": "7190", "postdistrikt": "Billund",
             "kommuneKode": "530"},
        ]).items():
            sides.setdefault(cvr, {}).update(values)
        rec = map_virksomhed_row({"cvrNummer": 54562519},
                                 side=sides.get("54562519", {}))
        assert rec["name"] == "LEGO A/S"
        assert rec["street"] == "Aastvej 1"
        assert rec["postcode"] == "7190"
        assert rec["city"] == "Billund"
        assert rec["municipality_code"] == "530"

    def test_side_index_uses_current_rows_only(self):
        from ingestion.cvr.normalize import build_side_index
        out = build_side_index("Navn", [
            {"cvrNummer": 54562519, "navn": "Gamle Navn ApS",
             "registreringTil": "2020-01-01T00:00:00+01:00"},
            {"cvrNummer": 54562519, "navn": "Nye Navn ApS"},
        ])
        assert out["54562519"]["name"] == "Nye Navn ApS"
