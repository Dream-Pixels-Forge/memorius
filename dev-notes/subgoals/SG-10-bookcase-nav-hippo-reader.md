# SG-10 — Bookcase: walk controls, walking hippo, centered reader (P1)

Requested 2026-11-13. Depends on SG-05 (CSP externalization) and SG-07
(library index) because all three edit the same bookcase files; land them in
that order to avoid conflicts.

## Why

The bookcase is a walkable library, but the only way to move is the keyboard
(WASD), the hippo teleports between spots instead of walking, and a clicked
book opens in a narrow right-hand side panel that is cramped for reading.
This subgoal makes the room usable with a mouse/touch, makes the librarian
feel alive, and turns reading a memory into a proper centered reader.

## 1. Bottom-left navigation cluster

Add a persistent movement cluster, bottom-left, above the librarian log:

```
        [ ▲ ]
[ ◀ ]  [ ▼ ]  [ ▶ ]      [ ⌂ ]
```

- Markup: `<nav id="bc-nav" class="bc-nav" aria-label="Walk controls">`
  with `#bc-nav-forward`, `#bc-nav-left`, `#bc-nav-back`,
  `#bc-nav-right`, `#bc-nav-home`.
- Each movement button: `type="button"`, `aria-label` ("Walk forward",
  "Strafe left", …), `data-key="KeyW|KeyA|KeyS|KeyD"`, visible glyph +
  visually-hidden label.
- Hold-to-walk: `pointerdown` presses the mapped key, `pointerup` /
  `pointercancel` / `pointerleave` releases it. Expose
  `WalkControls.press(code)` / `release(code)` instead of synthesising
  keyboard events, so focus and modifiers stay untouched.
- Home (`#bc-nav-home`) dispatches `bc:reset-view`; `R` keeps working.
- Touch: `touch-action: none` on the cluster; buttons ≥44×44 px; no 300 ms
  delay.
- Keyboard: buttons are real `<button>`s and work with Enter/Space (a tap
  = a short step; holding Space repeats via keydown).
- Layout: `position: fixed; left: 14px; bottom: 14px; z-index: 12`. Move
  `#bc-guidance` up (`bottom: 112px`) so the two never overlap. On
  `max-width: 720px`, shrink to 40 px buttons and keep the map top-right.
- Hide the cluster during cinematic flights (`body.bc-cinema`) to avoid
  accidental walking mid-crane; restore afterwards.

## 2. The hippo walks

Replace the pop-in/teleport in `bookcase-mascot.js` with actual locomotion.

- `Mascot.walkTo(target, { delay = 0, flip = true })`:
  - route from the current position to the target through walkable space:
    nearest nave point (`x = 0`) → along the nave to the target's `z` →
    into the target bay's opening → target,
  - never cross a case AABB (reuse the layout plan / `scene._plan.bays`,
    which already knows openings and the nave),
  - walk speed `1.25 m/s` (constant `WALK_SPEED`), turn toward each
    waypoint with yaw damping, arrive facing the visitor,
  - walk cycle: vertical bob (±3 cm), slight roll (±2°), and a lean into
    the direction of travel; the cut-out and the GLB share the same rig,
  - hop once on arrival (reuse `hop()`).
- `standAt` becomes `walkTo`; `goHome` walks back to the desk.
- While the camera flight is running, start walking immediately so he
  arrives as the camera lands (`delay` only for the establishing shot).
- `prefers-reduced-motion`: keep today's instant placement (no bob, no
  lean) — do not animate a long glide.
- Expose `isWalking`, `path` (waypoints) and `position` on the mascot for
  the debug hook (`window.__bookcase`) and headless checks.

## 3. Click to open a book

- Single click on a book still emits `bc:book-click`; the main module opens
  the reader for that id.
- Guard against look-drags (existing `_downAt` threshold stays) and against
  double-fetches: keep a request token so a slow response for book A cannot
  overwrite book B.
- `openBook(id)`:
  - fetches `GET /memory/{id}`,
  - dispatches `bc:open` so the book is drawn from the shelf,
  - renders the centered reader (below), not `#bc-detail`,
  - on failure shows the status pill error and leaves the reader closed.
- `#bc-detail` remains the search-results panel only. Result rows still
  open the reader.
- Clicking the backdrop or pressing `Esc` closes the reader and dispatches
  `bc:open {id:null}` so the book returns to the shelf.

## 4. Centered reader modal

Replace the side-panel book view with a dialog that is comfortable to read.

Markup (in `bookcase.html`):

```html
<div id="bc-reader" class="bc-reader" hidden>
  <div class="bc-reader-backdrop" data-close="reader"></div>
  <section class="bc-reader-panel" role="dialog" aria-modal="true"
           aria-labelledby="bc-reader-title">
    <header class="bc-reader-head">
      <div id="bc-reader-crumb" class="bc-crumb"></div>
      <h2 id="bc-reader-title"></h2>
      <div id="bc-reader-meta" class="bc-meta"></div>
      <div id="bc-reader-tags" class="bc-tags"></div>
      <button id="bc-reader-close" aria-label="Close reader">×</button>
    </header>
    <div id="bc-reader-actions" class="bc-actions"></div>
    <article id="bc-reader-body" class="bc-reader-body"></article>
    <footer id="bc-reader-foot" class="bc-reader-foot"></footer>
  </section>
</div>
```

Visual/UX contract:

- Panel centered with `position: fixed; inset: 0; display: grid;
  place-items: center`; width `min(720px, calc(100vw - 32px))`, max-height
  `min(82vh, 900px)`; panel scrolls internally, page does not.
- Backdrop `rgba(5,4,3,0.72)` + `backdrop-filter: blur(6px)`.
- Reading column: `max-width: 68ch; margin: 0 auto; font-family:
  var(--bc-serif); font-size: 17px; line-height: 1.75;
  white-space: pre-wrap; overflow-wrap: anywhere;` so paragraphs, lists
  and long ids all stay readable.
- Title uses the existing serif style, sentence-cased note name; crumb
  shows `shelf › folder`; meta shows relative date and tags; footer shows
  `id …` in mono.
- Actions: **Copy**, **Read aloud**, **Walk me there**, **Close**.
  - Copy uses `navigator.clipboard.writeText` with a hidden-textarea
    fallback; button label flips to "Copied" for 1.5 s.
- Accessibility:
  - focus moves to the close button on open; Tab is trapped inside the
    panel; focus returns to the previously focused element on close;
  - `Esc` closes; backdrop click closes;
  - `aria-modal="true"`, labelled by the title;
  - `body.bc-reader-open` prevents background scroll.
- Mobile (`max-width: 720px`): panel fills the viewport with safe-area
  padding, actions wrap, close stays top-right.
- Reduced motion: no backdrop fade/scale transition.

## 5. File-size budget (tests enforce ≤500 lines/file)

`bookcase.js` is already 492 lines. Split before adding:

- `bookcase-reader.js` — reader markup fill, copy, focus trap, open/close,
  `openBook` fetch. Export `createReader({api, librarian, setStatus, books})`.
- `bookcase-nav.js` — nav cluster wiring + `WalkControls.press/release`.
- `bookcase.js` — bootstrap, data loading, search, shortcuts; imports the
  two modules.
- `bookcase-mascot.js` — walking logic may push it near 300 lines; keep
  path math in `bookcase-layout.js` (`routeBetween(from, to, plan)`) so it
  stays testable and the mascot stays presentational.

## Tests (write first, watch fail)

Add to `tests/test_bookcase.py`:

1. `test_bookcase_nav_contract` — `#bc-nav` and the five buttons exist,
   each movement button has `data-key` + `aria-label`, CSS places the
   cluster bottom-left and moves `#bc-guidance` clear of it.
2. `test_bookcase_mascot_walks` — mascot module exports `WALK_SPEED`,
   `walkTo`, `isWalking`; scene calls `walkTo` (not a teleport-only path);
   reduced-motion branch present; layout exports `routeBetween`.
3. `test_bookcase_reader_contract` — dialog role/`aria-modal`, required
   ids, `white-space: pre-wrap`, reading measure, close/backdrop handlers,
   focus-restore and Esc handling, copy action, and that `openBook` writes
   to `#bc-reader-body` (not `#bc-detail-body`).
4. Extend `test_bookcase_assets` with the new ids and the
   `bookcase-reader.js` / `bookcase-nav.js` modules; keep the ≤500-line
   assertion.

## What was built

**Nav pad** — `bookcase-nav.js` builds the wiring: `pointerdown` calls
`WalkControls.press("KeyW")`, and `pointerup` / `pointercancel` /
`pointerleave` / `lostpointercapture` call `release`. No synthetic
keyboard events, so focus and modifiers are untouched. Home dispatches
`bc:reset-view`; the pad hides on `bc:cinema` and returns after the
flight. Buttons are 44 px (40 px under 720 px), and `bookcase-nav.css`
moves `#bc-guidance` to `bottom: 112px`.

**Walking hippo** — `routeBetween(from, to, plan)` in
`bookcase-layout.js` builds bay-centre → nave → target-bay-centre →
target. `Mascot.walkTo()` follows those waypoints at `WALK_SPEED`
(1.25 m/s), damps yaw at corners, bobs/rolls/leans during the walk, and
hops on arrival. Reduced motion places him instantly. `standAt` is kept
as an alias. `window.__bookcase.mascot()` reports `at`, `walking`, `path`
and `position` for headless checks. He sets off immediately during a
camera flight instead of waiting for its duration.

**Centered reader** — `bookcase-reader.js` owns the dialog: fetch with a
last-request-wins token, `bc:open` on open and close, focus moved to the
close button, Tab trapped, focus restored on close, Esc / × / backdrop,
`body.bc-reader-open` scroll lock, Copy / Read aloud / Walk me there, and
neighbours from the same shelf+folder. `#bc-detail` is now only the
search-results panel; result rows and book clicks both open the reader.

**File budget** — `bookcase.js` 468 lines, `bookcase.css` 451 split into
`bookcase-nav.css` (60) and `bookcase-reader.css` (146); mascot 280,
reader 180. Both new stylesheets are linked from `bookcase.html`.

## Definition of done

- [x] Holding a nav button walks continuously; releasing stops; touch and
      mouse both work; `R`/Home resets the view.
- [x] Nav cluster sits bottom-left and never overlaps the librarian log or
      the minimap at 1280×720 and 390×844.
- [x] The hippo visibly walks to a searched book and back home, routes
      around cases, and arrives facing the visitor.
- [x] Clicking a book opens the centered reader with readable typography;
      `Esc`, the close button, and the backdrop all close it; focus returns
      to where it was.
- [x] Copy and Read aloud work from the reader.
- [x] `prefers-reduced-motion` keeps instant placement and no fades.
- [x] `pytest tests/test_bookcase.py -q` green; full suite green.
- [x] Headless smoke: page boots to "N books", nav moves the camera, reader
      opens on a book click, zero console errors.
