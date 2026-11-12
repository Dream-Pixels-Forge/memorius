"""CI contract — the gates that caught (or missed) real regressions.

The REST auth regression shipped because CI ran only 6 of 50 test files, and
the dependency scan was non-blocking. These tests pin both decisions.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"


def test_ci_runs_the_full_suite():
    """A dedicated job must run every test file, not a hand-picked subset."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "full-suite:" in text, "CI has no full-suite job"
    assert "pytest tests/ -q" in text or "pytest tests -q" in text, (
        "full-suite job does not run the whole tests/ directory"
    )


def test_dependency_audit_is_blocking():
    """pip-audit findings must fail the build (no `|| true` escape hatch)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pip-audit" in text, "CI has no dependency audit"
    assert "pip-audit || true" not in text, "pip-audit is non-blocking"


def test_dependency_audit_ignores_are_documented():
    """The only ignored advisories are the unreachable chromadb server CVEs."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for vuln in ("PYSEC-2026-3813", "PYSEC-2026-3814", "PYSEC-2026-3815"):
        assert vuln in text, f"{vuln} ignore is missing"
    assert "PersistentClient" in text, "ignores have no reachability note"


def test_installed_chromadb_satisfies_declared_range():
    """CI must exercise a chromadb major the project actually supports.

    The dev machine ran 1.5.9 while pyproject capped `<1.0.0`, so a green
    local run hid 35 failures on a clean 0.6.3 install.
    """
    import tomllib
    from importlib.metadata import version

    from packaging.specifiers import SpecifierSet

    pyproject = WORKFLOW.parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    req = next(
        dep for dep in data["project"]["dependencies"] if dep.startswith("chromadb")
    )
    installed = version("chromadb")
    assert installed in SpecifierSet(req[len("chromadb"):]), (
        f"installed chromadb {installed} is outside {req!r}; "
        "CI and local runs would test different majors"
    )
