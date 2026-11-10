"""Tests for EOFError handling on input() prompts (issue #59).

Diary, profile, and recall commands previously crashed with a raw traceback
when stdin was closed (piped/non-interactive). They now print "Aborted." and
return gracefully, matching delete's existing behavior.
"""

import builtins
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _make_engine():
    tmp = tempfile.mkdtemp()
    os.environ["MEMORIUS_STORAGE_PATH"] = tmp
    from memorius.vault import VaultEngine
    from memorius.config import load_config
    return VaultEngine(load_config()), tmp


def _run_cli(argv):
    from memorius.cli.main import main
    sys.argv = ["memorius"] + argv
    main()


def _stdin_closed(monkeypatch):
    """Make input() raise EOFError (simulating closed / piped stdin)."""
    monkeypatch.setattr(builtins, "input", lambda *a, **k: (_ for _ in ()).throw(EOFError))


def test_cmd_diary_eof_aborts(monkeypatch, capsys):
    eng, tmp = _make_engine()
    try:
        _stdin_closed(monkeypatch)
        _run_cli(["diary", "--content", "test content"])
        out = capsys.readouterr().out
        assert "Aborted." in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_profile_eof_aborts(monkeypatch, capsys):
    eng, tmp = _make_engine()
    try:
        _stdin_closed(monkeypatch)
        _run_cli(["profile"])
        out = capsys.readouterr().out
        assert "Aborted." in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_recall_eof_aborts(monkeypatch, capsys):
    eng, tmp = _make_engine()
    try:
        _stdin_closed(monkeypatch)
        _run_cli(["recall"])
        out = capsys.readouterr().out
        assert "Aborted." in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_diary_with_args_no_input(monkeypatch, capsys):
    """When all args are provided, no input() is called — no EOFError risk."""
    eng, tmp = _make_engine()
    try:
        # Provide all required args as positionals so input() is never reached
        _run_cli(["diary", "s1", "--title", "T", "--summary", "S", "--content", "C"])
        out = capsys.readouterr().out
        # Should not contain "Aborted." or "Error:"
        assert "Aborted." not in out
        assert "Error:" not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_profile_with_args_no_input(monkeypatch, capsys):
    """When session_id is provided as positional, no input() is called."""
    eng, tmp = _make_engine()
    try:
        eng.store("a memory about zebras", vault="main")
        _run_cli(["profile", "main"])
        out = capsys.readouterr().out
        assert "Aborted." not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_recall_with_args_no_input(monkeypatch, capsys):
    """When query is provided as positional, no input() is called."""
    eng, tmp = _make_engine()
    try:
        eng.store("a memory about zebras", vault="main")
        _run_cli(["recall", "zebras"])
        out = capsys.readouterr().out
        assert "Aborted." not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
