"""Content-Security-Policy for the bookcase page.

The page is served on loopback with no authentication in front of it by
default, so a third-party script running in it could read the vault through
the local REST API. Everything is therefore served from the package:

* Three.js and its addons are vendored (``vendor/``), so ``script-src`` needs
  no external origin — not unpkg, not anything.
* The one inline script the platform requires is the import map (import maps
  cannot be external), allow-listed by its SHA-256.
* ``'wasm-unsafe-eval'`` is required because MeshoptDecoder compiles WASM to
  decompress the librarian model. It does not permit JavaScript ``eval``.
* ``connect-src`` must include the REST origin: the page is served on the
  static port (8400) and fetches the API on another loopback port (8912,
  ``?api=``). ``'self'`` alone would block every request.

The policy is sent as an HTTP header by ``memorius.bookcase.server`` because
``frame-ancestors`` is ignored in a ``<meta>`` element.
"""

from __future__ import annotations

# SHA-256 of the exact text content of the import map in bookcase.html.
# tests/test_bookcase_security.py recomputes it and prints the correct value.
IMPORTMAP_SHA256 = "sha256-p88oqFV+VvqgWHhxGwTi45SAQOmulL1/9gmQyjN/44Q="

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # A hash source MUST be single-quoted. Unquoted, the browser reads it
        # as a host-source, ignores it, and blocks the import map — the page
        # then dies with "Failed to resolve module specifier 'three'".
        f"script-src 'self' 'wasm-unsafe-eval' '{IMPORTMAP_SHA256}'",
        "style-src 'self'",
        # data: is the inline favicon; blob: is required by GLTFLoader, which
        # turns the hippo model's embedded textures into blob URLs.
        "img-src 'self' data: blob:",
        "font-src 'self'",
        # REST API lives on a different loopback port than the static page.
        # blob: is GLTFLoader's ImageBitmapLoader fetching the hippo's
        # embedded textures out of the GLB.
        "connect-src 'self' blob: http://127.0.0.1:* http://localhost:*",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
