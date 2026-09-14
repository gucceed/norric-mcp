"""
tests/test_watch_api.py

Watch REST API over FastAPI TestClient. The outer auth middleware is
simulated by a scope-injection wrapper (production stamps norric_tier /
norric_key_hash the same way); store functions are monkeypatched — no DB.
Run with: pytest tests/test_watch_api.py -v --tb=short
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watch.api as watch_api
import watch.store as store


class _ScopeStub:
    """Stamps tier/key_hash the way server.py's _NorricAuthMiddleware does."""

    def __init__(self, app, tier, key_hash):
        self.app, self.tier, self.key_hash = app, tier, key_hash

    async def __call__(self, scope, receive, send):
        scope["norric_tier"] = self.tier
        if self.key_hash:
            scope["norric_key_hash"] = self.key_hash
        await self.app(scope, receive, send)


def _client(tier="standard", key_hash="k" * 64):
    return TestClient(_ScopeStub(watch_api.app, tier, key_hash))


WATCH = {
    "id": "watch_abc123",
    "status": "active",
    "event_types": ["company.risk_tier_changed"],
    "filters": {"orgnrs": ["5560123456"], "min_score_delta": 3},
    "callback_url": "https://platform.example.com/hook",
    "description": None,
    "created_at": "2026-09-14T15:00:00+00:00",
    "updated_at": "2026-09-14T15:00:00+00:00",
    "stats": {"events_sent": 0, "last_delivery_at": None, "consecutive_failures": 0},
}

CREATE_BODY = {
    "event_types": ["company.risk_tier_changed"],
    "filters": {"orgnrs": ["5560123456"]},
    "callback_url": "https://platform.example.com/hook",
    "description": "credit portfolio Q4",
}


class TestTierGating:
    def test_free_tier_403(self):
        assert _client(tier="free").get("/api/v1/watches").status_code == 403

    def test_master_key_without_db_identity_403(self):
        # tier "all" may watch, but has no api_keys row to own watches
        assert _client(tier="all", key_hash="").get("/api/v1/watches").status_code == 403

    def test_compliance_allowed(self, monkeypatch):
        monkeypatch.setattr(store, "list_watches", lambda db, kh: [])
        assert _client(tier="compliance").get("/api/v1/watches").status_code == 200


class TestCreate:
    def test_success_returns_secret_once(self, monkeypatch):
        out = dict(WATCH, signing_secret="whsec_shown_once")
        monkeypatch.setattr(store, "create_watch", lambda db, **kw: out)
        r = _client().post("/api/v1/watches", json=CREATE_BODY)
        assert r.status_code == 201
        assert r.json()["signing_secret"] == "whsec_shown_once"

    def test_invalid_event_type_400(self, monkeypatch):
        def _raise(db, **kw):
            raise ValueError("unknown event type 'company.vibes_changed'")
        monkeypatch.setattr(store, "create_watch", _raise)
        r = _client().post("/api/v1/watches", json=CREATE_BODY)
        assert r.status_code == 400
        assert "vibes_changed" in r.json()["detail"]

    def test_over_budget_403(self, monkeypatch):
        def _raise(db, **kw):
            raise store.WatchLimitError("watched-entity limit for tier 'standard' is 500")
        monkeypatch.setattr(store, "create_watch", _raise)
        assert _client().post("/api/v1/watches", json=CREATE_BODY).status_code == 403


class TestReadUpdateDelete:
    def test_list(self, monkeypatch):
        monkeypatch.setattr(store, "list_watches", lambda db, kh: [WATCH])
        body = _client().get("/api/v1/watches").json()
        assert body["watches"][0]["id"] == "watch_abc123"
        assert "signing_secret" not in body["watches"][0]

    def test_get_404(self, monkeypatch):
        monkeypatch.setattr(store, "get_watch", lambda db, kh, wr: None)
        assert _client().get("/api/v1/watches/watch_nope").status_code == 404

    def test_patch_ok(self, monkeypatch):
        monkeypatch.setattr(store, "update_watch", lambda db, **kw: WATCH)
        r = _client().patch("/api/v1/watches/watch_abc123", json={"status": "paused"})
        assert r.status_code == 200

    def test_patch_unknown_field_400(self, monkeypatch):
        def _raise(db, **kw):
            raise ValueError("unknown watch fields: signing_secret")
        monkeypatch.setattr(store, "update_watch", _raise)
        r = _client().patch("/api/v1/watches/watch_abc123",
                            json={"description": "x", "status": "paused"})
        assert r.status_code == 400

    def test_delete(self, monkeypatch):
        monkeypatch.setattr(store, "delete_watch", lambda db, kh, wr: True)
        r = _client().delete("/api/v1/watches/watch_abc123")
        assert r.status_code == 200 and r.json()["deleted"] == "watch_abc123"

    def test_delete_404(self, monkeypatch):
        monkeypatch.setattr(store, "delete_watch", lambda db, kh, wr: False)
        assert _client().delete("/api/v1/watches/watch_nope").status_code == 404


class TestTestEvent:
    ROW = SimpleNamespace(
        watch_ref="watch_abc123",
        callback_url="https://platform.example.com/hook",
        signing_secret="whsec_secret",
        status="active",
    )

    def test_delivered(self, monkeypatch):
        monkeypatch.setattr(store, "get_watch_row", lambda db, kh, wr: self.ROW)
        monkeypatch.setattr(watch_api, "post_signed", lambda *a, **kw: (200, None))
        recorded = {}
        monkeypatch.setattr(store, "record_delivery",
                            lambda db, wr, ok: recorded.setdefault("ok", ok) or {})
        r = _client().post("/api/v1/watches/watch_abc123/test")
        body = r.json()
        assert r.status_code == 200
        assert body["delivered"] is True and body["http_status"] == 200
        assert recorded["ok"] is True

    def test_endpoint_down(self, monkeypatch):
        monkeypatch.setattr(store, "get_watch_row", lambda db, kh, wr: self.ROW)
        monkeypatch.setattr(watch_api, "post_signed",
                            lambda *a, **kw: (None, "ConnectError: refused"))
        monkeypatch.setattr(store, "record_delivery", lambda db, wr, ok: {})
        body = _client().post("/api/v1/watches/watch_abc123/test").json()
        assert body["delivered"] is False
        assert body["http_status"] is None
        assert "refused" in body["error"]

    def test_test_event_404(self, monkeypatch):
        monkeypatch.setattr(store, "get_watch_row", lambda db, kh, wr: None)
        assert _client().post("/api/v1/watches/watch_nope/test").status_code == 404


class TestRotateSecret:
    def test_rotate_returns_new_secret(self, monkeypatch):
        monkeypatch.setattr(store, "rotate_secret", lambda db, kh, wr: "whsec_new")
        body = _client().post("/api/v1/watches/watch_abc123/rotate-secret").json()
        assert body["signing_secret"] == "whsec_new"

    def test_rotate_404(self, monkeypatch):
        monkeypatch.setattr(store, "rotate_secret", lambda db, kh, wr: None)
        assert _client().post("/api/v1/watches/watch_nope/rotate-secret").status_code == 404
