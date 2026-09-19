from datetime import datetime, timezone

import pytest

from core.event_contract import EntityEvent, evidence_hash, idempotency_key
from scripts.estimate_event_storage import sample_bytes

NOW = datetime(2026, 9, 19, 3, 10, tzinfo=timezone.utc)


def _event(**changes):
    values = dict(
        entity_key="5561234567",
        entity_type="company",
        event_type="entity.address.changed",
        source="bolagsverket_bulk",
        source_observed_at=NOW,
        detected_at=NOW,
        before={"address": "A"},
        after={"address": "B"},
        changed_fields=("address",),
        evidence={"source_record": "fixture-1"},
        detector_version="stage0.v1",
    )
    values.update(changes)
    return EntityEvent(**values)


def test_replay_produces_same_idempotency_key():
    first = _event().hashes()[1]
    replay = _event(detected_at=datetime(2026, 9, 19, 3, 30, tzinfo=timezone.utc)).hashes()[1]
    assert first == replay


def test_changed_mutation_produces_different_key():
    first = _event().hashes()[1]
    changed = _event(after={"address": "C"}).hashes()[1]
    assert first != changed


def test_hashes_ignore_mapping_key_order():
    assert evidence_hash({"a": 1, "b": 2}) == evidence_hash({"b": 2, "a": 1})


def test_contract_rejects_unknown_type_and_naive_time():
    with pytest.raises(ValueError, match="unsupported event_type"):
        _event(event_type="entity.magic.changed").validate()
    with pytest.raises(ValueError, match="timezone-aware"):
        _event(source_observed_at=datetime(2026, 9, 19)).validate()


def test_representative_sample_is_bounded_and_nonempty():
    sizes = sample_bytes()
    assert len(sizes) == 4
    assert all(300 <= value <= 900 for value in sizes)

from datetime import date
from core.varsel_contract import VarselMatch


def test_varsel_exact_orgnr_can_auto_score():
    match = VarselMatch("varsel-1", date(2026, 9, 1), "5561234567", "exact_orgnr", 1.0, 10, 15)
    assert match.can_auto_score is True


def test_varsel_name_only_never_auto_scores():
    match = VarselMatch("varsel-2", date(2026, 9, 1), "5561234567", "normalised_name", 0.95)
    assert match.can_auto_score is False
