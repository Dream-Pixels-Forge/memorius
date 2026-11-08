"""Regression tests for the hooks engine mine_dir action.

Covers the undefined-name bug where ``_action_mine_dir`` called
``engine.mine(text=text, vault=vault)`` while the vault name was stored in
the local variable ``vault_cfg``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memorius.hooks.engine import HookAction, HookEngine, HookEvent
from memorius.hooks.models import HookEventType


class _StubMemory:
    def __init__(self, mid: str):
        self.id = mid


class _StubVaultEngine:
    """Records mine() calls; no real storage involved."""

    def __init__(self, vault_name: str = "main"):
        self.default_vault = vault_name
        self.mine_calls: list[dict] = []

    def mine(self, text: str, vault: str = "main", **kwargs):
        self.mine_calls.append({"text": text, "vault": vault})
        return [_StubMemory(f"mem-{len(self.mine_calls)}")]


def _make_engine(tmp_path: Path, vault: _StubVaultEngine) -> HookEngine:
    engine = HookEngine()
    engine._vault = vault  # pyright: ignore[reportAttributeAccessIssue]
    engine.state_manager = type(engine.state_manager)(tmp_path / "state")
    return engine


def test_mine_dir_resolves_vault_from_action_config(tmp_path: Path):
    """A mine_dir action targeting a non-default vault must use that vault,
    not crash with NameError, and not silently fall back to the default."""
    transcript = tmp_path / "session.txt"
    transcript.write_text("user: remember this fact\nassistant: got it", encoding="utf-8")

    vault = _StubVaultEngine()
    engine = _make_engine(tmp_path, vault)

    action = HookAction(type="mine_dir", name="mine_session", config={})
    event = HookEvent(event_type=HookEventType.SESSION_STOP, session_id="s-1")
    context = {"transcript_dir": str(transcript)}

    result = engine._execute_action(action, event, context)

    assert result["status"] == "done", f"expected done, got {result!r}"
    assert result["memory_count"] == 1
    assert len(vault.mine_calls) == 1
    # Default vault resolves to "main"
    assert vault.mine_calls[0]["vault"] == "main"


def test_mine_dir_custom_vault_configured(tmp_path: Path):
    """action.config['vault'] must be forwarded to engine.mine()."""
    transcript = tmp_path / "session.txt"
    transcript.write_text("user: store me in the work vault", encoding="utf-8")

    vault = _StubVaultEngine()
    engine = _make_engine(tmp_path, vault)

    action = HookAction(
        type="mine_dir", name="mine_work", config={"vault": "work"}
    )
    event = HookEvent(event_type=HookEventType.SESSION_STOP, session_id="s-2")
    context = {"transcript_dir": str(transcript)}

    result = engine._execute_action(action, event, context)

    assert result["status"] == "done", f"expected done, got {result!r}"
    assert vault.mine_calls[0]["vault"] == "work"


def test_mine_dir_missing_path_is_skipped(tmp_path: Path):
    vault = _StubVaultEngine()
    engine = _make_engine(tmp_path, vault)

    action = HookAction(type="mine_dir", name="no_path")
    event = HookEvent(event_type=HookEventType.SESSION_STOP, session_id="s-3")
    context = {"transcript_dir": ""}

    result = engine._execute_action(action, event, context)

    assert result["status"] == "skipped"
    assert "no path" in result["reason"]
    assert vault.mine_calls == []


def test_mine_dir_nonexistent_path_is_skipped(tmp_path: Path):
    vault = _StubVaultEngine()
    engine = _make_engine(tmp_path, vault)

    action = HookAction(type="mine_dir", name="missing_path")
    event = HookEvent(event_type=HookEventType.SESSION_STOP, session_id="s-4")
    context = {"transcript_dir": str(tmp_path / "does-not-exist.txt")}

    result = engine._execute_action(action, event, context)

    assert result["status"] == "skipped"
    assert "path not found" in result["reason"]
    assert vault.mine_calls == []


def test_mine_dir_directory_mode_mines_all_transcripts(tmp_path: Path):
    """Directory mode reads .txt/.md/.json and mines the combined text."""
    dir_ = tmp_path / "transcripts"
    dir_.mkdir()
    (dir_ / "a.txt").write_text("alpha", encoding="utf-8")
    (dir_ / "b.md").write_text("beta", encoding="utf-8")
    (dir_ / "c.json").write_text("gamma", encoding="utf-8")
    (dir_ / "ignore.log").write_text("noise", encoding="utf-8")

    vault = _StubVaultEngine()
    engine = _make_engine(tmp_path, vault)

    action = HookAction(
        type="mine_dir", name="mine_dir", config={"vault": "work"}
    )
    event = HookEvent(event_type=HookEventType.SESSION_STOP, session_id="s-5")
    context = {"transcript_dir": str(dir_)}

    result = engine._execute_action(action, event, context)

    assert result["status"] == "done", f"expected done, got {result!r}"
    assert len(vault.mine_calls) == 1
    combined = vault.mine_calls[0]["text"]
    assert "alpha" in combined
    assert "beta" in combined
    assert "gamma" in combined
    assert "noise" not in combined
    assert vault.mine_calls[0]["vault"] == "work"


# ── _sanitize_template_value injection tests (issue #61, H-10) ──────────────

import re
from memorius.hooks.engine import _sanitize_template_value


class TestSanitizeTemplateValue:
    """Shell metacharacters must be stripped from template values."""

    def test_allows_normal_text(self):
        assert _sanitize_template_value("hello world") == "hello world"

    def test_allows_spaces_and_hyphens(self):
        assert _sanitize_template_value("rm -rf /") == "rm -rf /"

    def test_removes_semicolon(self):
        assert _sanitize_template_value("foo;bar") == "foobar"

    def test_removes_backtick(self):
        assert "`" not in _sanitize_template_value("foo`bar")

    def test_removes_dollar(self):
        assert "$" not in _sanitize_template_value("foo$bar")

    def test_removes_pipe(self):
        assert _sanitize_template_value("foo|bar") == "foobar"

    def test_removes_ampersand(self):
        assert _sanitize_template_value("foo&bar") == "foobar"

    def test_removes_angle_brackets(self):
        assert _sanitize_template_value("foo<bar>baz") == "foobarbaz"

    def test_removes_parens(self):
        assert _sanitize_template_value("foo(bar)baz") == "foobarbaz"

    def test_removes_null_bytes(self):
        assert "\x00" not in _sanitize_template_value("foo\x00bar")

    def test_removes_control_chars(self):
        result = _sanitize_template_value("foo\x01bar\x7fbaz")
        assert "\x01" not in result and "\x7f" not in result

    def test_removes_all_metacharacters_together(self):
        value = "foo;bar`baz$qux|quux&corge<grault>(garply)"
        result = _sanitize_template_value(value)
        for ch in ";`$&|<>()":
            assert ch not in result, f"Found {ch!r} in {result!r}"
        assert result == "foobarbazquxquuxcorgegraultgarply"
