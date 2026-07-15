"""Regression tests for the factcheck emoji / Windows console crash.

`cmd_factcheck` prints verdict glyphs (✅ ❌ ⚠️ ❓). On Windows the
console defaults to the cp1252 encoding, which cannot represent those
code points, so `print()` raised ``UnicodeEncodeError`` and factcheck
died before emitting a verdict. The CLI now forces UTF-8 on stdout/stderr
in ``main()`` via ``_ensure_utf8_streams()``.

These tests reproduce the cp1252 condition with a fake console and assert
factcheck (a) used to crash and (b) no longer crashes after the fix.
"""

import argparse
import io
import sys

from memorius.cli.main import _ensure_utf8_streams, cmd_factcheck
from memorius.factcheck import FactCheckResult


class Cp1252Console:
    """Minimal stand-in for a Windows cp1252 console.

    Mirrors the real ``TextIOWrapper`` contract that the fix depends on:
    it encodes written text with its current ``encoding`` and exposes a
    ``reconfigure(encoding=..., errors=...)`` method. With
    ``encoding="cp1252"`` + ``errors="strict"`` (the Windows default),
    writing an emoji raises ``UnicodeEncodeError`` — exactly the bug.
    """

    def __init__(self, encoding="cp1252", errors="strict"):
        self.encoding = encoding
        self.errors = errors
        self._buf = io.BytesIO()

    def reconfigure(self, *, encoding=None, errors=None):
        if encoding is not None:
            self.encoding = encoding
        if errors is not None:
            self.errors = errors

    def write(self, text):
        data = text.encode(self.encoding, self.errors)
        self._buf.write(data)
        return len(text)

    def flush(self):
        self._buf.flush()

    def getvalue(self):
        return self._buf.getvalue()


class _StubEngine:
    """Returns a fixed verdict so cmd_factcheck can be exercised in isolation."""

    def __init__(self, verdict="verified", confidence=0.9):
        self._verdict = verdict
        self._confidence = confidence

    def check_fact(self, statement, vault=None):
        return FactCheckResult(
            statement=statement,
            verdict=self._verdict,
            confidence=self._confidence,
            explanation="matches a stored memory",
        )


def test_cp1252_console_raises_on_emoji_without_fix():
    """Documents the original bug: emoji print crashes on cp1252 (strict)."""
    console = Cp1252Console(encoding="cp1252", errors="strict")
    saved = sys.stdout
    sys.stdout = console
    try:
        raised = False
        try:
            print("✅ VERIFIED")
        except UnicodeEncodeError:
            raised = True
        assert raised, "expected cp1252 + strict to reject emoji (pre-fix behavior)"
    finally:
        sys.stdout = saved


def test_factcheck_emoji_no_crash_after_utf8_fix():
    """The fix: forcing UTF-8 lets factcheck print emoji verdicts on a
    cp1252-style console without raising."""
    console = Cp1252Console(encoding="cp1252", errors="strict")
    saved = sys.stdout
    sys.stdout = console
    try:
        _ensure_utf8_streams()  # the fix, as called at the top of main()
        cmd_factcheck(
            _StubEngine(verdict="verified"),
            argparse.Namespace(statement="User prefers dark mode", vault="main"),
            {},
        )
        sys.stdout.flush()
    finally:
        sys.stdout = saved

    decoded = console.getvalue().decode("utf-8")
    assert "✅ VERIFIED" in decoded
    assert "User prefers dark mode" in decoded


def test_factcheck_all_verdict_glyphs_render_after_fix():
    """Every verdict glyph (verified/contradicted/uncertain/no_match) survives."""
    expected = {
        "verified": "✅ VERIFIED",
        "contradicted": "❌ CONTRADICTED",
        "uncertain": "⚠️ UNCERTAIN",
        "no_match": "❓ NO_MATCH",
    }
    decoded_parts = []
    console = Cp1252Console(encoding="cp1252", errors="strict")
    saved = sys.stdout
    sys.stdout = console
    try:
        _ensure_utf8_streams()
        for verdict in expected:
            cmd_factcheck(
                _StubEngine(verdict=verdict),
                argparse.Namespace(statement=f"stmt-{verdict}", vault="main"),
                {},
            )
        sys.stdout.flush()
        decoded_parts.append(console.getvalue().decode("utf-8"))
    finally:
        sys.stdout = saved

    decoded = "".join(decoded_parts)
    for glyph_line in expected.values():
        assert glyph_line in decoded
