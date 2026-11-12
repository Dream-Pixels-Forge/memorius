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
3. **Copy memory** — moved to SG-10, where it lives in the centered reader
   instead of the side panel.
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
- [ ] Index lists shelves with correct counts and walks to a bay.
- [ ] Surprise opens a random book.
- [ ] Keyboard: I toggles index, X surprises, Escape closes.
- [ ] `pytest tests/test_bookcase.py -q` green.
- [ ] Headless smoke check: page boots, index renders, no console errors.
