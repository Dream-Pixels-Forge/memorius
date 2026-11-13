"""Bookcase security contract — strict CSP, vendored Three.js, no inline script.

The bookcase is a loopback-only page with no authentication in front of it by
default, so the page is the security boundary: a compromised CDN script could
call the local REST API. The rules pinned here:

* `script-src 'self'` — no third-party origin is allow-listed at all.
* Three.js and its two addons are **vendored** into the package instead of
  loaded from unpkg. SRI on a `modulepreload` cannot cover a dynamically
  imported module graph, and the CDN made the page useless offline.
* The only inline script left is the required import map (import maps must be
  inline), which is allow-listed by its SHA-256 and checked here.
* CSS is external, the favicon is a data URI (`img-src 'self' data:`).
* The static server sends the policy as a header (a meta tag cannot express
  `frame-ancestors`).
"""

from __future__ import annotations

import re
import threading
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

VENDOR_FILES = [
    "vendor/three.module.min.js",
    "vendor/LICENSE",
    "vendor/addons/loaders/GLTFLoader.js",
    "vendor/addons/utils/BufferGeometryUtils.js",
    "vendor/addons/libs/meshopt_decoder.module.js",
]


def _root() -> Path:
    import memorius.bookcase as bookcase_pkg

    return Path(bookcase_pkg.__file__).parent


def _html() -> str:
    return (_root() / "bookcase.html").read_text(encoding="utf-8")


def _importmap_text(html: str) -> str:
    match = re.search(r'<script\s+type="importmap"\s*>(.*?)</script>', html, re.DOTALL)
    assert match, "no inline import map found"
    return match.group(1)


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        self.scripts.append({key: value for key, value in attrs})


def test_no_executable_inline_script():
    """Every <script> must have a src, except the import map."""
    collector = _ScriptCollector()
    collector.feed(_html())
    inline = [
        attrs
        for attrs in collector.scripts
        if not attrs.get("src") and attrs.get("type") != "importmap"
    ]
    assert not inline, f"inline executable script(s) in bookcase.html: {inline}"


def test_boot_fallback_is_external():
    """The CDN-failure fallback moved into bookcase-boot.js."""
    html = _html()
    assert '<script src="./bookcase-boot.js"></script>' in html or (
        'src="./bookcase-boot.js"' in html
    ), "page does not load bookcase-boot.js"
    boot = _root() / "bookcase-boot.js"
    assert boot.is_file(), "bookcase-boot.js is missing"
    text = boot.read_text(encoding="utf-8")
    assert "__bcBooted" in text, "boot fallback no longer waits for __bcBooted"
    assert "bc-status" in text, "boot fallback does not report into the status pill"


def test_three_is_vendored_not_fetched_from_a_cdn():
    """No third-party origin may appear in the page or be needed at runtime."""
    html = _html()
    assert "unpkg.com" not in html, "page still points at unpkg"
    import json

    mapping = json.loads(_importmap_text(html))["imports"]
    assert mapping["three"] == "./vendor/three.module.min.js", mapping["three"]
    assert mapping["three/addons/"] == "./vendor/addons/", mapping["three/addons/"]
    assert not any(
        value.startswith(("http:", "https:", "//")) for value in mapping.values()
    ), f"import map points off-origin: {mapping}"

    for name in VENDOR_FILES:
        path = _root() / name
        assert path.is_file(), f"vendored asset missing: {name}"
        assert path.stat().st_size > 1024, f"vendored asset is a stub: {name}"

    three = (_root() / VENDOR_FILES[0]).read_text(encoding="utf-8", errors="replace")
    assert "Three.js Authors" in three, "vendored build lost its license header"


def test_csp_blocks_third_party_scripts():
    from memorius.bookcase.csp import CONTENT_SECURITY_POLICY as csp

    directives = {
        part.strip().split(" ")[0]: part.strip()
        for part in csp.split(";")
        if part.strip()
    }
    script_src = directives["script-src"]
    assert "'self'" in script_src
    # WASM is needed by MeshoptDecoder for the compressed hippo model.
    assert "'wasm-unsafe-eval'" in script_src
    assert "'unsafe-eval'" not in script_src, "JS eval must stay blocked"
    assert "'unsafe-inline'" not in script_src, "inline script must stay blocked"
    assert "http" not in script_src, f"script-src allow-lists an origin: {script_src}"

    assert directives["default-src"] == "default-src 'self'"
    assert directives["object-src"] == "object-src 'none'"
    assert directives["base-uri"] == "base-uri 'self'"
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"
    assert "data:" in directives["img-src"], "favicon is a data URI"
    # GLTFLoader materialises the hippo's embedded textures as blob: URLs;
    # without it the model loads untextured and logs errors.
    assert "blob:" in directives["img-src"], "GLB textures need blob: in img-src"
    assert "unsafe-inline" not in directives["style-src"], "no inline styles allowed"


def test_csp_allows_the_loopback_rest_api():
    """The page is served on 8400 and calls the API on 8912 (?api=)."""
    from memorius.bookcase.csp import CONTENT_SECURITY_POLICY as csp

    connect = next(
        part.strip()
        for part in csp.split(";")
        if part.strip().startswith("connect-src")
    )
    assert "http://127.0.0.1:*" in connect, connect
    assert "http://localhost:*" in connect, connect
    assert "'self'" in connect
    # ImageBitmapLoader fetches the GLB's embedded textures as blob: URLs.
    assert "blob:" in connect, "GLB textures are fetched through connect-src"


def test_importmap_hash_matches_the_policy():
    """An inline import map needs its own hash; a reformat silently breaks it."""
    import base64
    import hashlib

    from memorius.bookcase.csp import CONTENT_SECURITY_POLICY as csp
    from memorius.bookcase.csp import IMPORTMAP_SHA256

    digest = base64.b64encode(
        hashlib.sha256(_importmap_text(_html()).encode("utf-8")).digest()
    ).decode()
    assert IMPORTMAP_SHA256 == f"sha256-{digest}", (
        "IMPORTMAP_SHA256 is stale — update memorius/bookcase/csp.py to "
        f"sha256-{digest}"
    )
    # Hash sources must be quoted or the browser treats them as host sources
    # and blocks the import map.
    assert f"'{IMPORTMAP_SHA256}'" in csp, (
        "the import map hash must be single-quoted in script-src"
    )


def test_package_data_ships_the_vendored_files():
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["memorius"]
    joined = " ".join(patterns)
    assert "bookcase/vendor/" in joined, (
        f"package-data does not ship bookcase/vendor: {patterns}"
    )


def test_static_server_sends_the_security_headers(tmp_path):
    """The policy must arrive as a response header, not only in the markup."""
    from memorius.bookcase.csp import SECURITY_HEADERS
    from memorius.bookcase.server import serve

    (tmp_path / "bookcase.html").write_text("<html>probe</html>", encoding="utf-8")
    server = serve(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/bookcase.html"
        with urllib.request.urlopen(url, timeout=5) as response:
            headers = response.headers
            body = response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "probe" in body
    csp = headers.get("Content-Security-Policy")
    assert csp == SECURITY_HEADERS["Content-Security-Policy"]
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "no-referrer"


def test_static_server_refuses_directory_listing(tmp_path):
    from memorius.bookcase.server import serve

    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    server = serve(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(url, timeout=5)
        assert excinfo.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
