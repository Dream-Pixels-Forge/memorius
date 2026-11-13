# SG-07 — Bookcase UX improvements + new features (P2)

## Improvement
The bookcase has search, walk, minimap, layouts and a librarian, but no way to
see the library as a directory or jump to a shelf without walking/searching.

## New features
1. **Library index panel** (`#bc-index`, button "Index", shortcut `I`):
   - lists every shelf/bay with book and folder counts,
   - clicking a shelf walks the visitor to that bay (`bc:goto` with the bay
     centre from the layout plan),
   - shows a "library card" summary: books, shelves, folders, oldest/newest.
2. **Surprise me** (`#bc-surprise`, shortcut `X`):
   - picks a random book from the current vault, flies to it and opens it,
   - announces the pick through the librarian log.
3. **Copy memory** — a Copy button in the detail panel, using the
   clipboard with a textarea fallback (the page can be opened over plain
   http). SG-10 keeps it when the reader moves to the centre of the
   screen; the logic already lives in `bookcase-copy.js`.
4. **Index accessibility**: `aria-expanded` on the button, Escape closes the
   panel, rows are keyboard-activatable.

## Scope
- `bookcase.html`: index panel markup + button + surprise button.
- `bookcase.js`: build index from `state.books` + `scene._plan.bays`,
  handlers, shortcuts, copy action.
- `bookcase.css`: panel/rows/badge styling, mobile-safe.
- `tests/test_bookcase.py`: asset/contract tests for the new ids, events,
  and shortcuts; keep every JS file ≤500 lines (split index logic into
  `bookcase-index.js` if needed).

## Definition of done
- [x] Index lists shelves with correct counts and walks to a bay.
- [x] Surprise opens a random book.
- [x] Keyboard: I toggles index, X surprises, Escape closes.
- [x] `pytest tests/test_bookcase.py -q` green.
- [x] Headless smoke check: page boots, index renders, no console errors.

## What was built (2026-11-13)

- **`bookcase-index.js`** (new, 176 lines) — `LibraryIndex` renders the panel
  from the floor plan (`plan.bays` + `plan.cases`), so counts and the
  "first on the left" wording match the actual shelves. Rows are real
  `<button>`s (keyboard-activatable, hover/focus states). The library card
  summarises books / shelves / folders and the oldest → newest dates.
  Reads `books()` and `plan()` lazily, so switching vaults keeps it fresh.
- **`bc:goto` gained an optional `yaw`** (`bookcase-scene.js`): the index
  passes the bay's inward yaw, so the visitor arrives looking into the
  alcove instead of at the back of the last case. The minimap still sends
  only `{x, z}` and keeps its old behaviour.
- **Markup/CSS**: `#bc-index-btn` (with `aria-expanded` / `aria-controls`),
  `#bc-surprise`, `#bc-index` panel, `#bc-index-list`, `#bc-index-card`,
  `#bc-index-close`; panel styling follows the site's dark/orange language
  and collapses to a full-width sheet on mobile. Help text and the first
  visit hint mention `I` / `X`.
- **`bookcase-copy.js`** (new) — `copyText` uses `navigator.clipboard`
  and falls back to a hidden textarea + `execCommand("copy")` for
  non-secure origins; `copyButton()` is the "Copy" action in the detail
  panel (flashes "Copied" / "Copy failed", then resets).
- **`Cache-Control: no-store` on the static server** (found while
  verifying): the page is served straight from the package directory and
  upgraded in place, so without it an upgrade leaves the browser running
  the previous `bookcase.js` against the new markup — new buttons appear
  and do nothing. Pinned in `test_bookcase_security.py`.
- **Tests**: `TestBookcaseIndex` (markup, module wiring, and a Node probe
  that drives show/click/keyboard/surprise against a DOM stub),
  `TestBookcaseCopy` (clipboard + fallback + button flash) and the
  no-store header assertion. `tests/test_bookcase.py` and
  `tests/test_bookcase_security.py`: 29 passed; `ruff check` clean.
- **Browser verification** (CDP, fresh ports): page boots "6 books";
  `bookcase-index.js` loads; `I` opens the panel with 4 bay rows and the
  card "6 books / 4 shelves / 5 folders"; clicking the ops row moves the
  camera 7 m to the bay centre, closes the panel and announces the walk;
  `X` flies the lantern to a random book and opens it. No console errors
  from the serving origin. Copy is covered by the Node probe (clipboard +
  fallback); the live tab reports "Copy failed" only because the CDP
  window is unfocused (`document.hasFocus()` false), where Chrome denies
  clipboard writes by policy.
- **Index layout**: verified at a 780×493 viewport — panel clears the
  top bars (top 104 px) and the guidance log (bottom 132 px), the card
  stays pinned while the bay list scrolls, and counts read
  "1 book" / "2 books" instead of the old static "books".
