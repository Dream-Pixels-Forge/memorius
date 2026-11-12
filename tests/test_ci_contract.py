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
    # The distribution is `pip-audit`; the module is `pip_audit`. Invoking
    # `python -m pip-audit` fails with "No module named pip-audit".
    assert "python -m pip_audit" in text, (
        "audit must be invoked as `python -m pip_audit` (underscore)"
    )
    assert "python -m pip-audit " not in text, (
        "`python -m pip-audit` is not a valid module path"
    )


def test_dependency_audit_ignores_are_documented():
    """The only ignored advisories are the unreachable chromadb server CVEs."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for vuln in (
        "PYSEC-2026-311",
        "PYSEC-2026-3813",
        "PYSEC-2026-3814",
        "PYSEC-2026-3815",
    ):
        assert vuln in text, f"{vuln} ignore is missing"
    assert "PersistentClient" in text, "ignores have no reachability note"


def test_no_chroma_http_server_surface():
    """The audit ignores stay valid only while chromadb is embedded, not served.

    All ignored advisories target the multi-tenant Chroma HTTP API
    (/api/v2/tenants/...). If Memorius ever starts a Chroma server or sets
    trust_remote_code, the exceptions become real vulnerabilities.
    """
    package = WORKFLOW.parents[2] / "memorius"
    offenders = [
        f"{path.relative_to(package.parent)}:{lineno}"
        for path in sorted(package.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "trust_remote_code" in line or "chromadb.HttpClient" in line
    ]
    assert not offenders, (
        "memorius now touches the Chroma server surface; the pip-audit ignores "
        "must be re-evaluated: " + ", ".join(offenders)
    )


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
    assert installed in SpecifierSet(req[len("chromadb") :]), (
        f"installed chromadb {installed} is outside {req!r}; "
        "CI and local runs would test different majors"
    )


def test_tests_do_not_hardcode_a_developer_path():
    """Tests must derive paths from __file__, never from /home/<someone>.

    `test_cli_repair_subparser_is_registered` passed on the dev machine and
    failed the first `full-suite` CI run for exactly this reason.
    """
    import re
    import tokenize

    tests_dir = WORKFLOW.parents[2] / "tests"
    # An absolute path that names a real user segment, e.g. /home/dimona/...
    pattern = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/|[A-Za-z]:\\\\Users\\\\")
    offenders: list[str] = []
    for path in sorted(tests_dir.glob("*.py")):
        with path.open("rb") as handle:
            for tok in tokenize.tokenize(handle.readline):
                if tok.type != tokenize.STRING:
                    continue
                if pattern.search(tok.string):
                    offenders.append(f"{path.name}:{tok.start[0]}")
    assert not offenders, (
        "tests hardcode a developer path (use Path(__file__).resolve().parents[1]): "
        + ", ".join(offenders)
    )
