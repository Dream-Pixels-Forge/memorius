# Design Analyst Report — memorius

**Product:** memorius v0.9.3 — self-contained memory vault for AI agents.
**Repo:** `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`
**Design artifacts:** `dev-notes/SPEC.md`, `dev-notes/IMPLEMENTATION_PLAN.md`, `dev-notes/DISCOVERY.md`, `dev-notes/AUDIT.md`, `dev-notes/GOAL.md`; docs site (`docs/architecture.html`, `index.html`, `cli-reference.html`, `mcp-server.html`, `rest-api.html`, `consolidation.html`, `agents.html`); brand assets (`assets/logo-1.svg`, `assets/logo-2.png`, `assets/banner.png`); 3D bookcase UI (`memorius/bookcase/`).
**Cross-ref:** see `dev-notes/teammate-analysis/ui-ux.md` for interaction/flow findings — not duplicated here.

---

## Scope & Entry Points

- Visual identity: logo/banner assets; no formal DESIGN.md or design-token file found.
- UI surface: bookcase 3D scene (Three.js), CLI terminal output, docs pages.
- Component patterns: bookcase shelves/books/detail-panel/librarian/search/camera-reset/layout-toggle; CLI tables/lists/JSON.
- Motion: Three.js camera fly-to/reset, pointer-lock look, librarian Web-Speech utterances.
- Handoff: docs site vs implementation; spec drift; asset licensing.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. Design system / tokens
- [gap] No design-token file, no DESIGN.md, no documented color/scale/spacing/typography tokens. Visual identity lives only in `assets/` (logo-1.svg, logo-2.png, banner.png) and inline bookcase CSS (`bookcase.css` dark/cinematic with orange accent).
- [observation] bookcase.css is self-contained (~<500 lines, enforced by `tests/test_bookcase.py`), dark theme, orange accent color, no CSS variables/design-token system.
- [gap] No dark/light mode toggle; no `prefers-color-scheme` handling.

### 2. Components
- [observation] Bookcase components: 3D shelves (AABB collision, camera cannot pass through), book instances, book detail panel (content + librarian speech), librarian on/off toggle, search bar (Enter submits), camera-reset button, layout toggle ("by shelf" / "by recency"), hold-to-talk mic button (Chromium only).
- [observation] CLI "components": text tables, bullet lists, JSON `--json` output (sorted keys, deterministic), emoji factcheck verdicts (✅❌⚠️❓).
- [gap] No shared component library between CLI/MCP/REST/bookcase — each renders independently.
- [gap] No loading/skeleton states in CLI or bookcase; model-download progress is console text only (`setup` command).

### 3. Patterns
- [observation] Vault hierarchy pattern: Vault > Shelf > Folder > Note, with `validate_name` restricting names to `^[a-zA-Z0-9_\-]+$`.
- [observation] Core loop pattern: store → embed → search (the README's "whole loop").
- [observation] Session pattern: diary write/list, `SessionProfile` + `inherit_from_previous_session()` for session inheritance.
- [observation] Learning pattern: `learn`/`recall`/`learnings`/`apply_learning` with category enum (bug_fix, strategy, pattern, self_improvement, tool_usage, code_snippet, workflow).
- [gap] No documented pattern library; patterns are implicit in code, not in a design-system doc.

### 4. Screens
- [observation] Bookcase 3D scene: walkable vault at eye height (EYE_Y=1.65), WASD/arrow walking, mouse look (pointer-lock + click-drag fallback), camera fly-to on search hit, view reset to spawn.
- [observation] CLI screens: command help, status/store/search output, `--json` machine output, interactive prompts (session_id/title/summary/delete-confirmation).
- [observation] Docs screens: getting-started, CLI reference, MCP server, REST API, architecture, consolidation, agents — static HTML in `docs/`.
- [gap] No responsive breakpoint system for bookcase; no mobile layout considered (desktop-first 3D).

### 5. a11y
- [observation] `#bc-guidance` uses `role="log" aria-live="polite"`; every librarian utterance is also written as text (voice off still readable). `#bc-mic` has `aria-label="Hold to talk"`. `#bc-status` uses `role="status"`. `escapeHtml()`/`textContent` for all dynamic markup (no innerHTML on user content).
- [observation] `WalkControls` ignores keydown when focus is inside INPUT/TEXTAREA/SELECT/contenteditable so typing in search doesn't walk the camera.
- [gap] No `prefers-reduced-motion` handling (camera fly-to animations always on). No focus traps, no skip links. Canvas/WebGL 3D scene has no ARIA alternative — keyboard-only navigation of the bookcase scene is limited (search/controls work, movement through scene is pointer-driven). No screen-reader testing evident.

### 6. Responsive
- [observation] Bookcase is a fixed 3D canvas; no CSS media-query breakpoints found in `bookcase.css`. Works at the browser's default viewport; no explicit mobile adaptation.
- [observation] CLI adapts to terminal width implicitly (plain text wrapping); no hard terminal-width assumptions found.
- [gap] No responsive bookcase layout; no touch controls for the 3D scene.

### 7. Motion
- [observation] Three.js camera: `flyTo()` on search hit (camera flies to matching book), `resetView()` to spawn position. Pointer-lock mouse look. WASD walking with axis-separated AABB collision.
- [observation] Librarian: Web-Speech `speechSynthesis.speak` utterances when enabled; mirrored to `#bc-guidance` log as text. Voice choice persisted in `localStorage` (`bc-voice`).
- [gap] No reduced-motion alternative; no animation-duration config; no pause/resume for camera flights.

### 8. Handoff / spec-to-code alignment
- [gap] No explicit design-to-code handoff doc; SPEC.md/IMPLEMENTATION_PLAN.md describe features but not visual design. Risk of spec drift between docs site (`docs/*.html`) and implementation (e.g. REST endpoint tables vs actual routes).
- [observation] `tests/test_bookcase.py` asserts bookcase JS references specific REST contract substrings (`/vaults`, `/vault?vault=`, `/memories?limit=100&cursor=`, `/search`, `/memory/{id}`) — a lightweight contract test between UI and API.
- [gap] Asset licensing not documented for logo/banner; no attribution file.

---

## Highlights (3-5 short)

1. No design-token system or DESIGN.md — visual identity is inline bookcase CSS + assets/ only.
2. Bookcase is a self-contained Three.js scene with WASD/pointer-lock, librarian TTS mirrored to an accessible `role="log"` region, but no reduced-motion, no focus traps, no canvas ARIA alternative.
3. CLI renders text tables/lists + deterministic `--json`; no shared component library with bookcase.
4. Core UX patterns (vault hierarchy, store→embed→search, session diary, learn/recall) are implicit in code, not documented as a pattern library.
5. Handoff risk: docs site vs implementation may drift; no contract between SPEC.md and visual design; asset licensing undocumented.

---

## Domain summary

memorius has no formal design system: no DESIGN.md, no design tokens, no color/scale/spacing/typography documentation. Visual identity is carried by `assets/` (logo-1.svg, logo-2.png, banner.png) and inline `bookcase.css` (dark/cinematic, orange accent). The bookcase 3D scene is the richest UI — Three.js shelves/books/detail-panel with WASD/pointer-lock navigation, librarian Web-Speech TTS mirrored to an accessible `role="log"` aria-live region, search bar, camera reset, and layout toggle — but it lacks reduced-motion handling, focus traps, skip links, and any canvas ARIA alternative. CLI output is plain text tables/lists plus deterministic `--json`; no shared component library exists between CLI and bookcase. UX patterns (vault hierarchy, store→embed→search, session diary, learn/recall) are implicit in code rather than documented. Handoff risk stems from docs-site/implementation drift and undocumented asset licensing. Suggested canonical home: `dev-notes/teammate-analysis/design.md` (this file).
