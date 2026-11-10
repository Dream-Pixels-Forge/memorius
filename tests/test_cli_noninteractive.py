"""Issue #59 — CLI must never crash with a raw traceback.

1. `diary`, `profile` and `recall` prompt with input() when an argument is
   missing; on piped / closed stdin (EOFError) they must abort cleanly with
   a message naming the argument to pass, instead of a traceback.
2. `main()` gets a top-level handler: an unexpected exception prints a
   one-line error plus a remediation hint and exits non-zero; `--debug`
   keeps the full traceback; Ctrl-C exits 130 with "Aborted.".
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Run the CLI in-process on an isolated store; stdin is closed (EOF)."""
    monkeypatch.setenv("MEMORIUS_STORAGE_PATH", str(tmp_path))

    def _eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    def run(argv):
        from memorius.cli.main import main

        monkeypatch.setattr(sys, "argv", ["memorius"] + argv)
        code = 0
        try:
            main()
        except SystemExit as exc:  # top-level handler exits non-zero
            code = exc.code if isinstance(exc.code, int) else 1
        return code

    return run


@pytest.mark.parametrize(
    "argv, hint",
    [
        (["diary"], "memorius diary <session_id>"),
        (["profile"], "memorius profile <session_id>"),
        (["recall"], "memorius recall <query>"),
    ],
)
def test_prompt_on_closed_stdin_aborts_cleanly(cli, capsys, argv, hint):
    code = cli(argv)
    out, err = capsys.readouterr()
    assert "Traceback" not in out + err
    assert "Aborted" in out
    assert hint in out, "abort message must say how to pass the argument"
    assert code == 0


def test_diary_optional_fields_default_to_empty_when_stdin_closed(cli, capsys):
    """Only the session id is required: with it given, a closed stdin must not
    abort the entry just because --title / --summary were not passed."""
    code = cli(["diary", "s-eof", "--content", "piped run"])
    out, err = capsys.readouterr()
    assert code == 0
    assert "Traceback" not in out + err
    assert "Aborted" not in out


def test_unexpected_error_is_one_clean_line_and_nonzero(cli, capsys, monkeypatch):
    import memorius.cli.main as cli_main

    def boom(engine, args, config):
        raise RuntimeError("index went sideways")

    monkeypatch.setattr(cli_main, "cmd_status", boom)
    code = cli(["status"])
    _, err = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in err
    assert "Error: RuntimeError: index went sideways" in err
    assert "memorius doctor" in err, "should suggest a remediation"
    assert "--debug" in err, "should say how to get the full traceback"


def test_debug_flag_keeps_the_traceback(cli, monkeypatch):
    import memorius.cli.main as cli_main

    def boom(engine, args, config):
        raise RuntimeError("index went sideways")

    monkeypatch.setattr(cli_main, "cmd_status", boom)
    with pytest.raises(RuntimeError, match="index went sideways"):
        cli(["--debug", "status"])


def test_ctrl_c_exits_130(cli, capsys, monkeypatch):
    import memorius.cli.main as cli_main

    def interrupted(engine, args, config):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "cmd_status", interrupted)
    code = cli(["status"])
    _, err = capsys.readouterr()
    assert code == 130
    assert "Aborted." in err


@pytest.mark.parametrize(
    "exc, hint",
    [
        (PermissionError("denied"), "MEMORIUS_STORAGE_PATH"),
        (FileNotFoundError("nope"), "memorius init"),
        (ModuleNotFoundError("No module named 'x'"), "pip install -U memorius"),
    ],
)
def test_remediation_hints(exc, hint):
    from memorius.cli.main import _remediation

    assert hint in (_remediation(exc) or "")


def test_validation_errors_need_no_hint():
    from memorius.cli.main import _remediation

    assert _remediation(ValueError("vault name too long")) is None
