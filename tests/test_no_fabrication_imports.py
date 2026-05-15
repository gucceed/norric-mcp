"""Production scoring code must not import fabrication helpers. If this test
fails, you are about to ship mock data to a paying customer.

The exact directory set is locked by docs/no-fabrication-contract.md.
"""

import ast
import pathlib

FORBIDDEN_NAMES = {
    # Generators
    "faker", "Faker", "fabricate", "mock_company", "fake_name",
    # The in-repo fabricator deleted by the kill-mock PR
    "tools.kreditvakt_engine", "kreditvakt_engine",
    "score_company",
}

# Production surface protected by this guardrail. After the kill-mock PR
# every Kreditvakt-facing module is covered: the scoring layer, the HTTP
# API, the MCP tool surface in server.py, and the tools/ helper package
# (where the fabricator used to live — deleted by this PR).
PROD_DIRS = ["scoring", "kreditvakt", "mcp_tools", "tools"]
PROD_FILES = ["server.py"]


def _iter_prod_py(repo_root: pathlib.Path):
    for d in PROD_DIRS:
        prod_dir = repo_root / d
        if not prod_dir.exists():
            continue
        for py in prod_dir.rglob("*.py"):
            yield py
    for f in PROD_FILES:
        path = repo_root / f
        if path.exists():
            yield path


def test_no_fabrication_imports() -> None:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for py in _iter_prod_py(repo_root):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_NAMES or any(
                        alias.name.startswith(f"{f}.") for f in FORBIDDEN_NAMES
                    ):
                        offenders.append(f"{py.relative_to(repo_root)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                forbidden_root = mod in FORBIDDEN_NAMES or any(
                    mod.startswith(f"{f}.") for f in FORBIDDEN_NAMES
                )
                forbidden_name = any(alias.name in FORBIDDEN_NAMES for alias in node.names)
                if forbidden_root or forbidden_name:
                    offenders.append(
                        f"{py.relative_to(repo_root)}:{node.lineno} from {mod} import {[a.name for a in node.names]}"
                    )
    assert not offenders, f"fabrication imports in production code: {offenders}"


def test_score_source_mock_not_in_production() -> None:
    """The literal string 'mock' must not appear as a score_source value anywhere
    in production scoring code paths. (Documentation/comments allowed; runtime
    assignments forbidden.)"""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for py in _iter_prod_py(repo_root):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Match assignments and dict-key forms only, not comments.
            if ('"score_source": "mock"' in line
                    or "'score_source': 'mock'" in line
                    or 'score_source = "mock"' in line
                    or "score_source = 'mock'" in line):
                offenders.append(f"{py.relative_to(repo_root)}:{n} {stripped}")
    assert not offenders, f"score_source='mock' assignments still in production: {offenders}"


def test_fabricator_file_deleted() -> None:
    """tools/kreditvakt_engine.py was deleted by the kill-mock PR. If this
    test fails, the fabricator has been re-introduced."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    assert not (repo_root / "tools" / "kreditvakt_engine.py").exists(), (
        "tools/kreditvakt_engine.py has reappeared. Re-add this file ONLY in "
        "tests/fixtures/ and never under tools/, scoring/, kreditvakt/, or server.py."
    )
