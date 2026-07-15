"""Web search fallback for memorius.

When local recall is thin, optionally augment retrieval with live web
results. Local-first and opt-in: web fallback is OFF by default and
must be enabled via config (``retrieval.web_fallback``) or the ``--web``
flag — memorius never phones home unless you ask it to.

2026-aligned design (hybrid / grounded retrieval):
- Web results are returned as *cited* ``WebResult`` objects (title/url/snippet).
- The default provider (DuckDuckGo lite) needs no API key and uses
  only the stdlib, so it works out-of-the-box without secrets.
- A ``MockProvider`` lets the full path be tested without network.
"""

from __future__ import annotations

import html
import logging
import os
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("memorius.web")


@dataclass
class WebResult:
    """A single cited web search result."""

    title: str
    url: str
    snippet: str = ""

    def __str__(self) -> str:
        snippet = self.snippet[:160]
        return f"- {self.title}\n  {self.url}\n  {snippet}"


class WebSearchProvider(ABC):
    """Pluggable web search backend."""

    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Return cited web results for ``query``."""
        raise NotImplementedError


class DuckDuckGoProvider(WebSearchProvider):
    """Keyless DuckDuckGo *lite* scraper (stdlib only)."""

    name = "duckduckgo"
    _ENDPOINT = "https://lite.duckduckgo.com/lite/"

    def __init__(
        self,
        timeout: float = 10.0,
        user_agent: str = "memorius/0.4.2",
    ):
        self.timeout = timeout
        self.user_agent = user_agent

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(
            self._ENDPOINT,
            data=data,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception as e:  # network/timeout — never crash the CLI
            logger.warning("DuckDuckGo search failed: %s", e)
            return []
        return _parse_ddg_lite(raw, max_results)


class TavilyProvider(WebSearchProvider):
    """Tavily web search — API key required, best signal-to-noise for agents.

    Key from ``api_key`` arg, config ``retrieval.tavily_api_key``, or
    the ``TAVILY_API_KEY`` env var. Missing key -> warns + returns [].
    """

    name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0):
        self._api_key = api_key
        self.timeout = timeout

    def _resolve_key(self) -> str:
        key = self._api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RuntimeError(
                "Tavily requires an API key: set TAVILY_API_KEY or "
                "retrieval.tavily_api_key in config."
            )
        return key

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        import json
        try:
            key = self._resolve_key()
        except RuntimeError as e:
            logger.warning(str(e))
            return []
        payload = {
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # network/timeout/auth — never crash the CLI
            logger.warning("Tavily search failed: %s", e)
            return []
        out: list[WebResult] = []
        for r in body.get("results", [])[:max_results]:
            out.append(
                WebResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                )
            )
        return out


class MockProvider(WebSearchProvider):
    """Test double: returns canned results from a ``query -> [WebResult]`` map."""

    name = "mock"

    def __init__(self, results: Optional[dict[str, list[WebResult]]] = None):
        self.results = results or {}

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        return self.results.get(query, [])[:max_results]


def _parse_ddg_lite(html_text: str, max_results: int) -> list[WebResult]:
    """Extract result links + snippets from DuckDuckGo lite HTML.

    lite emits a table where each row has a ``<a class="result-link">``
    title followed by a ``<td class="result-snippet">`` cell. We pair
    link anchors with the snippet cell at the same index.
    """
    from html.parser import HTMLParser

    class _Scraper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[tuple[str, str]] = []
            self.snippets: list[str] = []
            self._in_link = False
            self._in_snippet = False
            self._cur_text: list[str] = []
            self._cur_href = ""
            self._cur_snip: list[str] = []

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            cls = d.get("class", "")
            if tag == "a" and "result-link" in cls:
                self._in_link = True
                self._cur_text = []
                self._cur_href = d.get("href", "")
            elif tag == "td" and "result-snippet" in cls:
                self._in_snippet = True
                self._cur_snip = []

        def handle_endtag(self, tag):
            if tag == "a" and self._in_link:
                self._in_link = False
                title = "".join(self._cur_text).strip()
                if title and self._cur_href:
                    self.links.append((title, self._cur_href))
                self._cur_text = []
            elif tag == "td" and self._in_snippet:
                self._in_snippet = False
                self.snippets.append("".join(self._cur_snip).strip())
                self._cur_snip = []

        def handle_data(self, data):
            if self._in_link:
                self._cur_text.append(data)
            elif self._in_snippet:
                self._cur_snip.append(data)

    parser = _Scraper()
    parser.feed(html_text)
    out: list[WebResult] = []
    for i, (title, url) in enumerate(parser.links[:max_results]):
        snippet = html.unescape(parser.snippets[i]) if i < len(parser.snippets) else ""
        out.append(
            WebResult(
                title=html.unescape(title),
                url=url,
                snippet=snippet,
            )
        )
    return out


def get_web_provider(
    config: dict, provider: Optional[str] = None
) -> Optional[WebSearchProvider]:
    """Build the configured web provider, or ``None`` if unavailable."""
    retrieval = config.get("retrieval", {}) if isinstance(config, dict) else {}
    name = (provider or retrieval.get("web_provider", "duckduckgo")).lower()
    if name == "tavily":
        retrieval = config.get("retrieval", {}) if isinstance(config, dict) else {}
        return TavilyProvider(api_key=retrieval.get("tavily_api_key"))
    if name == "mock":
        return MockProvider()
    if name == "duckduckgo":
        return DuckDuckGoProvider()
    logger.warning("Unknown web_provider %r; using duckduckgo", name)
    return DuckDuckGoProvider()


def web_fallback_enabled(args, config) -> bool:
    """True if web fallback should be considered (``--web`` flag or config)."""
    if getattr(args, "web", False):
        return True
    retrieval = config.get("retrieval", {}) if isinstance(config, dict) else {}
    return bool(retrieval.get("web_fallback", False))


def should_fallback(local_count: int, config: dict) -> bool:
    """Decide whether local recall is too thin to skip the web.

    Triggers when there are fewer local hits than ``web_min_results`` —
    i.e. "search the internet *if needed*".
    """
    retrieval = config.get("retrieval", {}) if isinstance(config, dict) else {}
    min_results = retrieval.get("web_min_results", 1)
    return local_count < min_results
