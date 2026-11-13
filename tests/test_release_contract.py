"""Release contract — a published artifact must match the tag that shipped it.

0.9.7 reached PyPI without a tag or GitHub release because the workflow
published on any `pyproject.toml` push and `skip-existing` hid the duplicate.
These tests pin the repaired pipeline.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> dict:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))


def test_publishing_is_triggered_by_a_published_release():
    """No `push` trigger: a version bump alone must never publish."""
    workflow = _workflow()
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "push" not in triggers, "release.yml still publishes on push"
    assert triggers["release"]["types"] == ["published"]
    assert "workflow_dispatch" in triggers, "no manual recovery path"


def test_publish_checks_out_the_release_tag():
    """`release: published` checks out the default branch by default.

    Without an explicit ref, main's tip gets published under the release's
    version whenever main has moved on since the tag was cut.
    """
    text = RELEASE.read_text(encoding="utf-8")
    assert "ref: ${{ github.event.release.tag_name" in text, (
        "publish job does not check out the release tag"
    )


def test_publish_verifies_tag_matches_version():
    """The tag and pyproject version must be proven equal before uploading."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "tomllib" in text and "pyproject.toml" in text, (
        "no version read from pyproject.toml before publishing"
    )
    assert "does not match" in text, "no tag/version mismatch assertion"


def test_duplicate_publish_is_not_silenced():
    """skip-existing hides version drift; a reused version must fail loudly."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "skip-existing: true" not in text, (
        "skip-existing: true hides an already-published version"
    )
