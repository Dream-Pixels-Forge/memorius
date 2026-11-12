# SG-05 — Bookcase CSP/SRI hardening (P1)

## Evidence
- Issue #66 is closed, but its fix (`51a5f41`, CSP + SRI) exists only on
  `fix/66-xss-hardening` and never reached `main`.
- The bookcase page was rewritten in #85/#86 and has no CSP/SRI.
- Blind merge would break the page: `bookcase.html` has an inline fallback
  `<script>` that `script-src 'self'` blocks.

## Scope
- Externalize the inline boot-fallback script to `bookcase-boot.js`.
- Add a CSP meta tag: `default-src 'self'`; scripts self + `unpkg.com`;
  styles self + inline; images self + data; no objects; base/form self.
- **`connect-src` must include the loopback API origin**: the page is served
  from the static port (8400) while `fetch`/`POST /search` go to the REST
  port (8912, `?api=`). `connect-src 'self'` alone would break every call.
  Use `connect-src 'self' http://127.0.0.1:* http://localhost:*`.
- Add SRI (`modulepreload` + `integrity`) for the Three.js module. Document
  that `three/addons/*` are covered by the CSP origin allowlist because SRI
  cannot cover a dynamically imported module graph.
- Add tests asserting the CSP exists, the inline script is gone, the page
  references the external boot script, and `connect-src` allows loopback.
- Re-check the page boots with the CSP in headless Chrome (or at minimum the
  asset/HTML contract tests plus a static server fetch).
- Cover the splash/loading canvas and GLB/texture fetches: both are
  same-origin, so `default-src 'self'` plus `img-src 'self' data:` suffice.

## Definition of done
- [ ] No inline `<script>` in `bookcase.html`.
- [ ] CSP + SRI present and tested.
- [ ] `pytest tests/test_bookcase.py -q` green.
- [ ] Manual/headless boot check: status pill reaches "N books", no CSP
      violations in the console.
