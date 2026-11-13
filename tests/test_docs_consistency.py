"""The docs must agree with the release they describe (issue #98).

Version strings drift silently: a badge keeps saying the previous release
while the package has moved on, and PROGRESS still calls an old version the
current state. These checks read the single source of truth
(``pyproject.toml``) and fail until every published surface agrees with it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    assert match, "pyproject.toml has no static version"
    return match.group(1)


class TestDocsConsistency:
    """The README, docs site and PROGRESS name the released version."""

    def test_readme_changelog_badge_matches_version(self):
        version = _version()
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        badge = re.search(r"changelog-v([0-9]+\.[0-9]+\.[0-9]+)-green", readme)
        assert badge, "README changelog badge lost its version"
        assert badge.group(1) == version, (
            f"README badge says v{badge.group(1)}, package is v{version}"
        )

    def test_docs_badges_match_version(self):
        version = _version()
        docs = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        claims = re.findall(
            r'<span class="accent">v([0-9]+\.[0-9]+\.[0-9]+)</span>', docs
        )
        assert claims, "docs/index.html has no version badge"
        assert set(claims) == {version}, (
            f"docs/index.html says {sorted(set(claims))}, package is v{version}"
        )

    def test_progress_reports_current_version(self):
        version = _version()
        progress = (ROOT / "dev-notes" / "PROGRESS.md").read_text(encoding="utf-8")
        line = re.search(
            r"^- Version: ([0-9]+\.[0-9]+\.[0-9]+)", progress, re.MULTILINE
        )
        assert line, "PROGRESS.md has no Version line"
        assert line.group(1) == version, (
            f"PROGRESS.md says {line.group(1)}, package is {version}"
        )

    def test_security_has_a_usable_contact(self):
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        email = re.search(r'email = "([^"]+)"', pyproject)
        assert email, "pyproject.toml has no author email"
        assert email.group(1) in security, (
            "SECURITY.md does not name the maintainer email from pyproject.toml"
        )

    def test_subgoal_index_is_linked_from_dev_notes(self):
        index = ROOT / "dev-notes" / "README.md"
        assert index.is_file(), "dev-notes/README.md is missing"
        text = index.read_text(encoding="utf-8")
        assert "subgoals/README.md" in text, (
            "dev-notes/README.md does not link the subgoal index"
        )
