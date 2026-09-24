import importlib

ALL_COUNTRY_BEATS = {
    "dk": {"cvr-bulk-weekly", "cvr-events-poll-15m", "cvr-reconcile-nightly"},
    "no": {"brreg-bulk-daily", "brreg-updates-poll-15m", "brreg-reconcile-nightly"},
    "fi": {"prh-bulk-daily"},
    "ee": {"ariregister-bulk-daily"},
    "fr": {"sirene-bulk-daily"},
}


def _load(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("NORRIC_COUNTRY_BEATS", raising=False)
    else:
        monkeypatch.setenv("NORRIC_COUNTRY_BEATS", value)
    monkeypatch.delenv("CELERY_ROLE", raising=False)
    import celeryconfig
    return importlib.reload(celeryconfig)


def test_all_country_beats_off_by_default(monkeypatch):
    names = set(_load(monkeypatch, None).beat_schedule)
    for beats in ALL_COUNTRY_BEATS.values():
        assert not (beats & names)
    # Swedish and other beats are untouched.
    assert {"bolagsverket-bulk-daily", "kreditvakt-nightly-rescore", "watch-diff-daily"} <= names


def test_enable_one_country_at_a_time(monkeypatch):
    names = set(_load(monkeypatch, " DK ").beat_schedule)
    assert ALL_COUNTRY_BEATS["dk"] <= names
    for cc in ("no", "fi", "ee", "fr"):
        assert not (ALL_COUNTRY_BEATS[cc] & names)


def test_enable_several(monkeypatch):
    names = set(_load(monkeypatch, "dk,no,fi").beat_schedule)
    assert ALL_COUNTRY_BEATS["dk"] | ALL_COUNTRY_BEATS["no"] | ALL_COUNTRY_BEATS["fi"] <= names
    assert not ((ALL_COUNTRY_BEATS["ee"] | ALL_COUNTRY_BEATS["fr"]) & names)
    _load(monkeypatch, None)


def test_every_gated_name_exists_in_full_schedule():
    import celeryconfig
    gated = {n for names in celeryconfig._GATED_COUNTRY_BEATS.values() for n in names}
    assert gated == set().union(*ALL_COUNTRY_BEATS.values())
