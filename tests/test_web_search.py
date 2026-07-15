"""Tests for the hybrid retrieval / web-fallback feature.

All web access is faked via ``MockProvider`` — no network required.
"""

import argparse
from pathlib import Path

from memorius.web_search import (
    DuckDuckGoProvider,
    MockProvider,
    WebResult,
    _parse_ddg_lite,
    get_web_provider,
    should_fallback,
    web_fallback_enabled,
)


# Sample DuckDuckGo *lite* HTML (shape only) for parser coverage.
_DDG_LITE_HTML = """
<html><body>
<table>
  <tr class="result-link-row">
    <td class="result-link">
      <a class="result-link" href="https://example.com/a">Example Article A</a>
    </td>
    <td class="result-snippet">A short snippet about topic A.</td>
  </tr>
  <tr class="result-link-row">
    <td class="result-link">
      <a class="result-link" href="https://example.com/b">Example Article B</a>
    </td>
    <td class="result-snippet">A short snippet about topic B.</td>
  </tr>
</table>
</body></html>
"""


def _cfg(**overrides):
    cfg = {
        "retrieval": {
            "web_fallback": False,
            "web_provider": "duckduckgo",
            "web_min_results": 1,
            "web_max_results": 5,
        }
    }
    for k, v in overrides.items():
        cfg["retrieval"][k] = v
    return cfg


def _args(web=False):
    return argparse.Namespace(web=web)


# ── Provider selection ────────────────────────────────────────────────────
def test_get_web_provider_default_is_duckduckgo():
    p = get_web_provider(_cfg())
    assert isinstance(p, DuckDuckGoProvider)


def test_get_web_provider_mock():
    p = get_web_provider(_cfg(), provider="mock")
    assert isinstance(p, MockProvider)


def test_get_web_provider_unknown_falls_back_to_duckduckgo(caplog):
    p = get_web_provider(_cfg(web_provider="bogus"))
    assert isinstance(p, DuckDuckGoProvider)


# ── Fallback decision ─────────────────────────────────────────────────────
def test_should_fallback_true_when_local_empty():
    assert should_fallback(0, _cfg()) is True


def test_should_fallback_false_with_any_local_result():
    # "if needed" = local found nothing; 1+ hit means no web fallback.
    assert should_fallback(1, _cfg()) is False
    assert should_fallback(5, _cfg()) is False


def test_should_fallback_false_when_local_sufficient():
    assert should_fallback(2, _cfg()) is False
    assert should_fallback(5, _cfg()) is False


def test_should_fallback_respects_min_results():
    assert should_fallback(3, _cfg(web_min_results=4)) is True
    assert should_fallback(4, _cfg(web_min_results=4)) is False


# ── Flag / config gating (local-first, opt-in) ──────────────────────────
def test_web_fallback_disabled_by_default():
    assert web_fallback_enabled(_args(web=False), _cfg()) is False


def test_web_fallback_enabled_via_flag():
    assert web_fallback_enabled(_args(web=True), _cfg()) is True


def test_web_fallback_enabled_via_config():
    assert web_fallback_enabled(_args(web=False), _cfg(web_fallback=True)) is True


# ── DuckDuckGo lite parser ──────────────────────────────────────────────
def test_parse_ddg_lite_extracts_links_and_snippets():
    provider = DuckDuckGoProvider()
    results = _parse_ddg_lite(_DDG_LITE_HTML, 5)
    assert len(results) == 2
    assert results[0].title == "Example Article A"
    assert results[0].url == "https://example.com/a"
    assert "topic A" in results[0].snippet
    assert results[1].url == "https://example.com/b"


def test_parse_ddg_lite_respects_max_results():
    provider = DuckDuckGoProvider()
    results = _parse_ddg_lite(_DDG_LITE_HTML, 1)
    assert len(results) == 1


# ── MockProvider ─────────────────────────────────────────────────────────
def test_mock_provider_returns_canned_results():
    canned = {
        "python 3.13": [
            WebResult(title="Py 3.13 notes", url="https://docs/python/3.13"),
        ]
    }
    p = MockProvider(canned)
    out = p.search("python 3.13")
    assert len(out) == 1
    assert out[0].url == "https://docs/python/3.13"


def test_mock_provider_empty_for_unknown_query():
    p = MockProvider({})
    assert p.search("anything") == []


# ── CLI integration (no real vault / no network) ───────────────────────
def test_cmd_web_uses_mock_provider(monkeypatch, capsys):
    from memorius.cli.main import cmd_web

    canned = {"python 3.13": [
        WebResult(title="Py 3.13", url="https://docs/python/3.13", snippet="New in 3.13"),
    ]}
    monkeypatch.setattr(
        "memorius.web_search.get_web_provider",
        lambda config, provider=None: MockProvider(canned),
    )

    cmd_web(None, argparse.Namespace(query="python 3.13", max=5, provider="mock"), _cfg())
    out = capsys.readouterr().out
    assert "Py 3.13" in out
    assert "https://docs/python/3.13" in out


def test_cmd_search_web_fallback_when_local_empty(monkeypatch, capsys):
    from memorius.cli.main import cmd_search

    class FakeEngine:
        def search(self, **kwargs):
            return []  # thin local recall -> triggers fallback

    canned = {"latest rust": [
        WebResult(title="Rust 1.80", url="https://rust/1.80"),
    ]}
    monkeypatch.setattr(
        "memorius.web_search.get_web_provider",
        lambda config, provider=None: MockProvider(canned),
    )

    cmd_search(
        FakeEngine(),
        argparse.Namespace(query="latest rust", n=10, vault=None, shelf=None, web=True),
        _cfg(),
    )
    out = capsys.readouterr().out
    assert "Web results (from internet):" in out
    assert "Rust 1.80" in out


def test_cmd_search_no_web_when_local_present(monkeypatch, capsys):
    from memorius.cli.main import cmd_search
    from memorius.models import Memory

    class FakeEngine:
        def search(self, **kwargs):
            return [Memory(id="m1", vault="main", shelf="default",
                        folder="default", note="default",
                        content="Rust 1.80 released June 2024")]

    # Web provider would return something, but fallback must NOT trigger
    # because local recall is sufficient.
    monkeypatch.setattr(
        "memorius.web_search.get_web_provider",
        lambda config, provider=None: MockProvider(
            {"latest rust": [WebResult(title="SHOULD NOT APPEAR", url="x")]}
        ),
    )

    cmd_search(
        FakeEngine(),
        argparse.Namespace(query="latest rust", n=10, vault=None, shelf=None, web=True),
        _cfg(),
    )
    out = capsys.readouterr().out
    assert "SHOULD NOT APPEAR" not in out
    assert "Web results" not in out
