# Vendored Three.js

`three@0.160.0`, fetched unmodified from
`https://unpkg.com/three@0.160.0/` on 2026-11-13. MIT licensed — see
`LICENSE`.

| File | Upstream path |
|------|---------------|
| `three.module.min.js` | `build/three.module.min.js` |
| `addons/loaders/GLTFLoader.js` | `examples/jsm/loaders/GLTFLoader.js` |
| `addons/utils/BufferGeometryUtils.js` | `examples/jsm/utils/BufferGeometryUtils.js` |
| `addons/libs/meshopt_decoder.module.js` | `examples/jsm/libs/meshopt_decoder.module.js` |

## Why vendored

The bookcase used to import Three.js from unpkg through the page's import
map. That origin had to be allow-listed in the Content Security Policy, and
Subresource Integrity could not protect the graph: `GLTFLoader` dynamically
imports `../utils/BufferGeometryUtils.js`, and SRI cannot cover a module
graph resolved at runtime. It also meant the page — a loopback-only UI —
could not start without internet access.

Serving these files from the package lets the page run under
`script-src 'self'` with no third-party origin at all, and offline.

## Updating

1. Download the four files above from the new version's `build/` and
   `examples/jsm/` paths, keeping the directory layout.
2. If `GLTFLoader.js` starts importing a new addon, vendor that file too —
   the page will fail to boot otherwise.
3. Run `python -m pytest tests/test_bookcase_security.py -q`.
4. Boot the page and confirm the status pill reaches "N books".
