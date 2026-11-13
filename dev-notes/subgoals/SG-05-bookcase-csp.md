# SG-05 — Bookcase CSP/SRI hardening (P1)

## Evidence
- Issue #66 is closed, but its fix (`51a5f41`, CSP + SRI) exists only on
  `fix/66-xss-hardening` and never reached `main`.
- The bookcase page was rewritten in #85/#86 and has no CSP/SRI.
- Blind merge would break the page: `bookcase.html` has an inline fallback
  `<script>` that `script-src 'self'` blocks.

## Scope (as planned)
- Externalize the inline boot-fallback script to `bookcase-boot.js`.
- Add a CSP: `default-src 'self'`; no objects; base/form self.
- `connect-src` must include the loopback API origin: the page is served
  from the static port (8400) while `fetch`/`POST /search` go to the REST
  port (8912, `?api=`).
- Add tests asserting the CSP exists, the inline script is gone, the page
  references the external boot script, `connect-src` allows loopback, and
  the page still boots.

## What was actually built (2026-11-13)

**Three.js is vendored, not CDN + SRI.** SRI cannot protect this page: the
import map resolves `three/addons/` to a bare specifier and `GLTFLoader`
dynamically imports `../utils/BufferGeometryUtils.js`, so no `<script
integrity>` covers the graph the browser actually executes. Keeping unpkg
also meant a loopback-only page needed internet access to boot. The four
files (`three.module.min.js` + GLTFLoader + BufferGeometryUtils +
meshopt_decoder, 848 KB, MIT) now ship inside the package under
`memorius/bookcase/vendor/`, so `script-src` allow-lists **no third-party
origin at all**.

**The policy is an HTTP header**, not a `<meta>` tag: `frame-ancestors` is
ignored in `<meta>`, and the header applies before the document body parses.
It lives in `memorius/bookcase/csp.py` and is emitted by the new
`memorius/bookcase/server.py` (also moved out of `cli/main.py`, which had the
handler inlined).

**Two directives are non-obvious and each was found by booting the page:**
- `'wasm-unsafe-eval'` — MeshoptDecoder compiles WASM to decompress the
  librarian model. It does not permit JavaScript `eval`.
- `blob:` in both `img-src` and `connect-src` — `GLTFLoader` uses
  `ImageBitmapLoader`, which `fetch`es the GLB's embedded textures as blob
  URLs. Without it the hippo loads untextured and logs errors.

**Import-map hash must be quoted.** `sha256-…` unquoted is parsed as a
host-source, silently ignored, and the page dies with `Failed to resolve
module specifier "three"`. `csp.py` holds the digest; the test recomputes it
from the served markup and prints the correct value when it drifts.

**CORS followed a hardcoded allow-list.** `rest_server.py` allowed only
`…:8912|8400`, while `memorius bookcase --port/--static-port` are documented
flags. On any other port the page booted and then failed every request with
"API unreachable". The regex is now built from `server.rest_port` /
`server.static_port` (new config key, `MEMORIUS_STATIC_PORT`) and
`cmd_bookcase` publishes the ports actually in use before the app is built.
Non-configured loopback ports are still rejected.

## Verification
- `pytest tests/test_bookcase_security.py` → 9 passed.
- `pytest tests/test_bookcase.py tests/test_feature_cors.py` → green.
- Served page returns the header:
  `script-src 'self' 'wasm-unsafe-eval' 'sha256-p88oq…='`,
  `connect-src 'self' blob: http://127.0.0.1:* http://localhost:*`.
- Booted on a random port pair in Chrome over CDP: status pill reaches
  **"6 books"**, `window.__bcBooted === true`, all four vendored modules load,
  and the console has **zero** errors (no CSP violations, no texture
  failures). Screenshot shows shelves, signs, hippo and minimap rendering.

## Definition of done
- [x] No inline executable `<script>` in `bookcase.html` (import map only,
      hash-allow-listed).
- [x] Strict CSP present, sent as a header, and tested.
- [x] `pytest tests/test_bookcase.py -q` green.
- [x] Boot check: status pill reaches "N books", no CSP violations.
- [x] Vendored files are shipped by the wheel
      (`pyproject.toml` package-data + test).

## Follow-ups found while booting
- `_bc_port_in_use` reports a port as busy while it is only in `TIME_WAIT`,
  so restarting the bookcase on the same port fails with "in use by a process
  that does not answer /health". Should probe with `SO_REUSEADDR` semantics
  or actually connect.
