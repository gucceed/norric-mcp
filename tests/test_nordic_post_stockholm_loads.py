import pytest

from ingestion.pacing import Pacer
from scripts import _nordic_post_stockholm as runner
from scripts.run_dk_post_stockholm_load import CONFIRMATION as DK_CONFIRM
from scripts.run_fi_post_stockholm_load import CONFIRMATION as FI_CONFIRM
from scripts.run_no_post_stockholm_load import CONFIRMATION as NO_CONFIRM


def test_chain_order_is_encoded_in_confirmations():
    assert DK_CONFIRM == "STOCKHOLM_FLIP_CONFIRMED"
    assert NO_CONFIRM.endswith("_AND_DK_LOAD_FINISHED")
    assert FI_CONFIRM.endswith("_AND_NO_LOAD_FINISHED")


def test_accepts_exact_expected_stockholm_host():
    assert runner._safe_target(
        "postgresql+psycopg2://postgres:secret@db.stockholm.example:5432/postgres",
        "db.stockholm.example",
    ) == "db.stockholm.example"


@pytest.mark.parametrize("url", ["postgresql://postgres:s@db.us-east.example:5432/postgres", ""])
def test_refuses_wrong_or_missing_database(url):
    with pytest.raises(SystemExit, match="Refusing target host"):
        runner._safe_target(url, "db.stockholm.example")


@pytest.mark.parametrize("country", [runner.DK, runner.NO, runner.FI])
def test_wrong_confirmation_refuses(country):
    with pytest.raises(SystemExit, match="--confirm must equal"):
        runner.parse_args(country, ["--confirm", "yes", "--expected-db-host", "h"])


@pytest.mark.parametrize("argv,msg", [
    (["--batch-size", "0"], "batch-size"),
    (["--batch-size", "20000"], "batch-size"),
    (["--pause-seconds", "0"], "pause-seconds"),
])
def test_pacing_limits_refuse(argv, msg):
    base = ["--confirm", runner.DK.confirmation, "--expected-db-host", "h"]
    with pytest.raises(SystemExit, match=msg):
        runner.parse_args(runner.DK, base + argv)


def test_run_refuses_before_touching_db_on_wrong_host(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@aws-1-us-east-1.pooler.supabase.com:5432/postgres")
    with pytest.raises(SystemExit, match="Refusing target host"):
        runner.run(runner.DK, ["--confirm", runner.DK.confirmation,
                               "--expected-db-host", "db.fbqwmkfqskojrirlhjtp.supabase.co"])


class FakeDB:
    def __init__(self):
        self.executed, self.commits = [], 0

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))

    def commit(self):
        self.commits += 1


def test_pacer_commits_pauses_and_records_progress():
    sleeps = []
    db = FakeDB()
    pacer = Pacer("norric_dk_ingest_state", batch_size=3, pause_seconds=30, sleep=sleeps.append).bind(db)
    pacer.start()
    for _ in range(7):
        pacer.tick()
    pacer.finish()
    assert sleeps == [30, 30]
    assert db.commits == 1 + 2 + 1
    progress = [p for s, p in db.executed if p]
    assert progress[-1] == {"n": 7, "s": "done"}


def test_pacer_rejects_unknown_state_table():
    with pytest.raises(ValueError):
        Pacer("norric_entities")
