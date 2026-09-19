from celery import Celery

from ingestion.bolagsverket.download_url import (
    DEFAULT_DIRECT_DOWNLOAD_URL,
    direct_download_url,
)
from kreditvakt import tasks


def test_direct_download_url_defaults_to_public_bulk_file(monkeypatch):
    monkeypatch.delenv("BOLAGSVERKET_DIRECT_URL", raising=False)
    assert direct_download_url() == DEFAULT_DIRECT_DOWNLOAD_URL


def test_direct_download_url_accepts_https_override(monkeypatch):
    url = "https://example.test/bulk.zip"
    monkeypatch.setenv("BOLAGSVERKET_DIRECT_URL", url)
    assert direct_download_url() == url


def test_direct_download_url_rejects_swapped_database_url(monkeypatch, caplog):
    monkeypatch.setenv("BOLAGSVERKET_DIRECT_URL", "postgresql://db.example/norric")
    assert direct_download_url() == DEFAULT_DIRECT_DOWNLOAD_URL
    assert "expected an HTTP(S) URL" in caplog.text


def test_score_portfolio_task_accepts_incremental_kwargs(monkeypatch):
    app = Celery("test", broker="memory://", backend="cache+memory://")
    app.conf.task_always_eager = True
    _, score_task, _ = tasks.register_tasks(app)

    seen = {}

    def fake_score_portfolio(orgnr_list, incremental=False, stale_days=7):
        seen.update(
            orgnr_list=orgnr_list,
            incremental=incremental,
            stale_days=stale_days,
        )
        return {"ok": True}

    monkeypatch.setattr(tasks, "score_portfolio", fake_score_portfolio)
    result = score_task.apply(
        kwargs={"orgnr_list": [], "incremental": True, "stale_days": 5}
    ).get()

    assert result == {"ok": True}
    assert seen == {"orgnr_list": [], "incremental": True, "stale_days": 5}
