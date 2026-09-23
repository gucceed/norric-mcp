import pytest
from scripts.run_ee_post_stockholm_load import _safe_target


def test_accepts_exact_expected_stockholm_host():
    assert _safe_target(
        "postgresql://postgres:secret@db.stockholm.example:5432/postgres",
        "db.stockholm.example",
    ) == "db.stockholm.example"


@pytest.mark.parametrize("url", [
    "postgresql://postgres:secret@db.us-east.example:5432/postgres",
    "",
])
def test_refuses_wrong_or_missing_database(url):
    with pytest.raises(SystemExit, match="Refusing target host"):
        _safe_target(url, "db.stockholm.example")
