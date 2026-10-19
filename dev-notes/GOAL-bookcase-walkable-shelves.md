# Goal: Bookcase — Walkable Realistic Sections with Well-Arranged Shelves

## Objective
Rearrange the 3D vault bookcase (v0.9.0, `memorius/bookcase/`) into a realistic,
walkable library: the user can walk on foot between distinct sections/aisles and
sees books arranged upright and orderly on the shelves.

## Context
The current scene (`memorius/bookcase/bookcase-scene.js`, Three.js r160 via CDN,
414 lines) uses `OrbitControls` orbiting a single fixed target — the user spins
around a static wall of books instead of walking through a library. The user
viewed it live via `memorius bookcase` (static server 127.0.0.1:8400 + REST
health-check 127.0.0.1:8912) and wants it to feel like a real bookcase: multiple
sections you physically walk between, and books that sit properly on the shelves.

Existing behavior that must survive untouched: book click → detail + librarian
speech, search → camera flight to the book, "N books" pill, librarian text
greeting, `GET /vaults`-driven sections, all served by `memorius bookcase` with
zero REST/MCP/CLI changes.

## Deliverables
- [ ] Reworked scene layout in `memorius/bookcase/bookcase-scene.js` (may add a
      sibling module, e.g. `bookcase-walk.js`): ≥3 distinct vault sections laid
      out as aisles/walls a person can walk between (not one orbit target)
- [ ] First-person navigation: WASD/arrow-key walking at eye height plus mouse
      look (pointer-lock preferred, drag-look fallback); camera cannot pass
      through shelves and cannot go below the floor
- [ ] Realistic shelf dressing: books stand upright, aligned in orderly rows
      with plausible varied heights/widths/colors, resting on shelf planks —
      no floating, no intersecting, no books lying flat or scattered
- [ ] Per-section labels/markers readable while walking (section/vault names)
- [ ] All pre-existing interactions still work: book click → info + librarian
      speech; search → fly-to-book; books pill; librarian greeting
- [ ] Tests updated in `tests/test_bookcase.py` (existing 3 still pass; asset
      presence for any new file)
- [ ] CHANGELOG entry + docs page section describing the walkable bookcase
- [ ] Repo conventions held: all `memorius/bookcase/*` files ≤500 lines, TDD
      (RED → GREEN), branch-per-task → PR → CI 3.11+3.12 green → squash merge

## Definition of Done
- [ ] Scene graph contains ≥3 distinct sections, each with its own shelves,
      positioned apart so aisles exist between them
- [ ] Headless-Chrome live check: page boots via `memorius bookcase`, renders
      with zero JS console errors
- [ ] Walkability proven headlessly: a scripted synthetic keydown (W) held ~1s
      moves the camera forward by ≥1 world unit; after a scripted walk sequence
      the camera remains above the floor and outside shelf bounds
- [ ] Book arrangement proven: every book mesh's position sits within its
      shelf's vertical band and inside the shelf's horizontal extent
      (verifiable via a scene dump or debug hook, e.g. `window.__bookcase`
      or equivalent observable)
- [ ] Librarian greeting still renders as text on load (existing behavior)
- [ ] Full suite green: `python3 -m pytest -q` → all tests pass
- [ ] `memorius bookcase --help` exits 0
- [ ] `wc -l memorius/bookcase/*` → every file ≤500 lines
- [ ] CHANGELOG has the walkable-bookcase entry; docs page updated

## Verification Steps
1. `python3 -m pytest -q` — full suite passes (existing 3 bookcase tests +
   any new ones)
2. `memorius bookcase` → serve both static (8400) and REST (8912); `curl -s -o
   /dev/null -w "%{http_code}" http://127.0.0.1:8400/bookcase.html` → 200
3. Headless Chrome against `http://127.0.0.1:8400/bookcase.html?api=http://127.0.0.1:8912`:
   - zero JS console errors in the captured log
   - scripted WASD keydown moves camera ≥1 unit; camera stays in bounds
   - book-position audit passes (every book within its shelf band/extent)
   - librarian greeting text present in DOM
4. `memorius bookcase --help` → exit 0
5. `wc -l memorius/bookcase/*.js memorius/bookcase/*.html memorius/bookcase/*.css`
   → all ≤500
6. `grep -A5 "0.9.2" CHANGELOG.md` (or next version) → walkable-bookcase entry
   present; docs page shows the new section

## Anti-Drift Rules
- Scene/navigation/appearance changes only. No REST API, MCP, hooks, or other
  CLI behavior changes. `memorius bookcase` CLI contract stays as-is.
- No librarian voice/behavior changes beyond keeping existing interactions
  working.
- Keep Three.js r160 CDN + importmap approach; no bundler introduction.
- New ideas (texture packs, minimap, VR, mobile joystick) → separate goal.
- Do not claim completion without running every Verification Step; report
  blockers instead of working around them.

## Estimated Effort
Medium-large: one focused session (~1 day) — scene rework + walk controls +
collision + headless verification. Hardest part: scripted walkability check in
headless Chrome (use CDP/`--remote-debugging-port` with Node 24 built-in
WebSocket, or an in-page debug hook evaluated via `--headless --run-all-compositor-stages-before-draw`).
