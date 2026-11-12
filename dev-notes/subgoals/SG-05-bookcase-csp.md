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
- Add SRI for the Three.js module and document that `three/addons/*` modules
  are covered by the CSP origin allowlist (SRI cannot cover the whole graph).
- Add a test asserting the CSP exists, the inline script is gone, and the
  page references the external boot script.
- Re-check the page boots with the CSP in headless Chrome (or at minimum the
  asset/HTML contract tests plus a static server fetch).

## Definition of done
- [ ] No inline `<script>` in `bookcase.html`.
- [ ] CSP + SRI present and tested.
- [ ] `pytest tests/test_bookcase.py -q` green.
- [ ] Manual/headless boot check: status pill reaches "N books", no CSP
      violations in the console.
