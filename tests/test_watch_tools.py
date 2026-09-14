"""
tests/test_watch_tools.py

The five Watch MCP tools, called directly with the caller context and
store layer monkeypatched — no HTTP, no DB. Tier denial and the
not-found envelope are the contract points.
Run with: pytest tests/test_watch_tools.py -v --tb=short
"""

import asyncio
from types import SimpleNamespace

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watch.store as store
import watch.tools as wtools

KH = "k" * 64
WATCH = {
    "id": "watch_abc123", "status": "active",
    "event_types": ["company.risk_tier_changed"],
    "filters": {"orgnrs": ["5560123456"], "min_score_delta": 3},
    "callback_url": "https://platform.example.com/hook",
    "description": None, "created_at": None, "updated_at": None,
    "stats": {"events_sent": 0, "last_delivery_at": None, "consecutive_failures": 0},
}


@pytest.fixture
def standard_caller(monkeypatch):
    monkeypatch.setattr(wtools, "_caller", lambda: (KH, "standard"))
    fake_db = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(wtools, "_get_db", lambda: fake_db)  # store is patched too


def run(coro):
    return asyncio.run(coro)


class TestCaller:
    def test_free_tier_denied(self, monkeypatch):
        monkeypatch.setattr(
            wtools, "_caller",
            lambda: (_ for _ in ()).throw(
                PermissionError("Norric Watch requires a Standard or Compliance tier API key.")),
        )
        with pytest.raises(PermissionError):
            run(wtools.norric_watch_list())


class TestCreate:
    def test_create_returns_secret_with_warning(self, standard_caller, monkeypatch):
        out = dict(WATCH, signing_secret="whsec_once")
        monkeypatch.setattr(store, "create_watch", lambda db, **kw: out)
        body = run(wtools.norric_watch_create(
            event_types=["company.risk_tier_changed"],
            callback_url="https://platform.example.com/hook",
            orgnrs=["556012-3456"],
        ))
        assert body["data"]["watch"]["signing_secret"] == "whsec_once"
        assert any("shown once" in w for w in body["warnings"])
        assert body["metadata"]["tool"] == "norric_watch_create_v1"

    def test_create_over_budget_raises(self, standard_caller, monkeypatch):
        def _raise(db, **kw):
            raise store.WatchLimitError("limit")
        monkeypatch.setattr(store, "create_watch", _raise)
        with pytest.raises(ValueError, match="limit"):
            run(wtools.norric_watch_create(
                event_types=["company.score_changed"],
                callback_url="https://platform.example.com/hook",
            ))


class TestList:
    def test_list(self, standard_caller, monkeypatch):
        monkeypatch.setattr(store, "list_watches", lambda db, kh: [WATCH])
        body = run(wtools.norric_watch_list())
        assert body["data"]["count"] == 1
        assert body["data"]["watches"][0]["id"] == "watch_abc123"


class TestUpdate:
    def test_partial_filter_merge(self, standard_caller, monkeypatch):
        seen = {}
        monkeypatch.setattr(wtools, "_get_filters",
                            lambda wr, kh: {"orgnrs": ["5560123456"], "min_score_delta": 3})

        def _update(db, **kw):
            seen.update(kw)
            return WATCH
        monkeypatch.setattr(store, "update_watch", _update)
        run(wtools.norric_watch_update("watch_abc123", min_score_delta=5))
        # orgnrs preserved from current filters; delta replaced
        assert seen["patch"]["filters"] == {"orgnrs": ["5560123456"], "min_score_delta": 5}

    def test_empty_patch_rejected(self, standard_caller):
        with pytest.raises(ValueError, match="nothing to update"):
            run(wtools.norric_watch_update("watch_abc123"))

    def test_not_found_envelope(self, standard_caller, monkeypatch):
        monkeypatch.setattr(wtools, "_get_filters", lambda wr, kh: None)
        body = run(wtools.norric_watch_update("watch_nope", orgnrs=["5560123456"]))
        assert body["data"]["watch"] is None
        assert any("not found" in w for w in body["warnings"])

    def test_resume_passes_status(self, standard_caller, monkeypatch):
        seen = {}
        monkeypatch.setattr(store, "update_watch",
                            lambda db, **kw: seen.update(kw) or WATCH)
        run(wtools.norric_watch_update("watch_abc123", status="active"))
        assert seen["patch"]["status"] == "active"


class TestDelete:
    def test_delete(self, standard_caller, monkeypatch):
        monkeypatch.setattr(store, "delete_watch", lambda db, kh, wr: True)
        body = run(wtools.norric_watch_delete("watch_abc123"))
        assert body["data"]["deleted"] == "watch_abc123"

    def test_delete_not_found(self, standard_caller, monkeypatch):
        monkeypatch.setattr(store, "delete_watch", lambda db, kh, wr: False)
        body = run(wtools.norric_watch_delete("watch_nope"))
        assert body["data"]["deleted"] is None
        assert body["warnings"]


class TestEvents:
    def test_events_with_tier_window(self, standard_caller, monkeypatch):
        monkeypatch.setattr(wtools, "list_events_for_watch",
                            lambda db, kh, tier, wr, lim: [{"id": "evt_1"}])
        body = run(wtools.norric_watch_events("watch_abc123"))
        assert body["data"]["count"] == 1
        assert body["data"]["history_days"] == 7  # standard tier

    def test_events_not_found(self, standard_caller, monkeypatch):
        monkeypatch.setattr(wtools, "list_events_for_watch",
                            lambda db, kh, tier, wr, lim: None)
        body = run(wtools.norric_watch_events("watch_nope"))
        assert body["data"]["events"] is None
        assert body["warnings"]

    def test_limit_clamped(self, standard_caller, monkeypatch):
        seen = {}
        def _list(db, kh, tier, wr, lim):
            seen["lim"] = lim
            return []
        monkeypatch.setattr(wtools, "list_events_for_watch", _list)
        run(wtools.norric_watch_events("watch_abc123", limit=9999))
        assert seen["lim"] == 200
