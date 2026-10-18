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
