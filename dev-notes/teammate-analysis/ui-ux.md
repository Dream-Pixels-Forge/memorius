# UI/UX Analyst Report — memorius

**Product:** memorius v0.9.3 — self-contained memory vault for AI agents.
**Repo:** `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`
**Interfaces:** CLI (text), MCP (agent-facing JSON-RPC over stdio), REST API, 3D bookcase browser UI (loopback), agent hooks (auto-detecting lifecycle hooks).
**Cross-ref:** see `dev-notes/teammate-analysis/design.md` for visual-design findings — not duplicated here.

---

## Scope & Entry Points

- User flows: init → store → search → mine/diary → consolidate/prune → doctor/repair → export/import.
- Interactions: `input()` prompts, `--yes`/`--dry-run` non-interactive flags, EOFError handling.
- States: empty states, loading (model download), success/error messages, dry-run previews.
- Keyboard: CLI is keyboard-native; bookcase WASD/arrows, click-drag, pointer-lock, mic (Chromium only).
- Screen readers: CLI text output accessible; `--json` for tooling; bookcase 3D canvas poor SR support; librarian speech mirrored to `role="log"`.
- Errors: `Error:` messages, validation errors, "Memory not found", "Aborted."
- Onboarding: `docs/getting-started.html`, command cheat sheet in README, `memorius --version` verify.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. User flows
- [observation] First-run: `memorius init` (creates config + main vault), `memorius setup` (downloads ONNX embedding model ~80MB), then `store`/`search`.
- [observation] Core loop: `store "content"` → `search "query"` (semantic). README: "store → embed → search ... that's the whole loop."
- [observation] `mine <file>` extracts memories from a transcript into `conversations/mined/transcript`.
- [observation] `diary` writes session diary entries; `diaries` lists recent entries.
- [observation] `consolidate` merges similar memories; `prune` archives stale ones; `doctor` runs health checks; `repair` reconciles vector/meta drift.
- [observation] `export`/`import` round-trip vault (JSON/Markdown). `bookcase` opens the 3D walkable vault UI.
- [gap] No guided onboarding wizard; `init`/`setup` are manual discrete steps with no progress UI beyond console text.

### 2. Interactions
- [observation] `input()` used in 4 places: `diary` (session_id/title/summary, cli/main.py:~616-621), `profile` (session_id, ~1099), `recall` (query, ~1492), `delete` (confirmation, ~1437).
- [observation] `delete` wraps `input()` in try/except EOFError → "Aborted (no confirmation)." and returns (cli/main.py:~1444). `diary`/`profile`/`recall` do NOT catch EOFError — piped/non-interactive stdin crashes the command.
- [observation] `--yes` skips delete confirmation; `--dry-run` previews changes without mutating (prune, repair, consolidate, obsidian import/export).
- [observation] Commands reading content/query fall back to `sys.stdin.read().strip()` when the positional is absent (`store`, `search`, `mine`, `extract`, `factcheck`, `context`, `web`, `recall`, `learn`). Empty after read → "Error: … required" and return.
- [gap] No tab-completion, no REPL, no TUI — CLI is argv/stdin only.

### 3. States
- [observation] Empty states: "No vaults. Run: memorius init" (`cmd_ls`), "No memories found." (`cmd_list`), "No diary entries." (`cmd_diaries`), "No learnings found." (`cmd_learnings`).
- [observation] Loading: `setup` prints model-download progress to console; no spinner/progress bar.
- [observation] Success: "Stored: {id}" with path, "Deleted: {memory_id}", "Updated: {memory_id}".
- [observation] Dry-run previews: `[dry-run] Would delete: {memory_id}` (delete), repair/stats dry-run show what would change.
- [gap] No in-progress state for long operations (consolidate over 10k memories is O(N²) with no progress indicator).

### 4. Feedback
- [observation] Confirmations include IDs and paths: `Stored: {memory.id}` + `Path: {vault}/{shelf}/{folder}/{note}` (`cmd_store`).
- [observation] `stats`/`status` print vault/memory/embedding counts; `doctor` prints "All checks passed." or lists issues.
- [observation] `--json` output (status/stats/get/update/prune/learnings/learning-stats/repair) is deterministic, sorted-keys, single JSON object — suitable for tooling; warnings are data, exit 0.
- [observation] factcheck uses emoji verdicts (✅❌⚠️❓) with confidence %.
- [gap] No toast/notification system; CLI is fire-and-forget text; no persistent session HUD.

### 5. Keyboard
- [observation] CLI is fully keyboard-native (argv + stdin).
- [observation] Bookcase: WASD/arrow-key walking at eye height (EYE_Y=1.65), mouse look via `requestPointerLock()` + click-drag drag-look fallback, `Escape` to release pointer lock, search submits on Enter.
- [observation] `WalkControls` ignores keydown when focus is inside INPUT/TEXTAREA/SELECT/contenteditable (bookcase-walk.js:~75-79) — typing in search doesn't walk the camera.
- [observation] Hold-to-talk mic (`#bc-mic`, Chromium `SpeechRecognition`/`webkitSpeechRecognition`); disabled gracefully on non-Chromium.
- [gap] No keyboard navigation through the 3D scene itself (movement is pointer/mouse-driven). No focus traps, no skip links, no arrow-key menu navigation in bookcase UI.

### 6. Screen readers
- [observation] CLI plain-text output is screen-reader friendly; `--json` gives stable parseable output for tooling.
- [observation] `#bc-guidance` uses `role="log" aria-live="polite"`; every librarian utterance is also written as text (voice off still readable). `#bc-mic` has `aria-label="Hold to talk"`. `#bc-status` uses `role="status"`.
- [observation] `escapeHtml()`/`textContent` for all dynamic markup (no innerHTML on user content).
- [gap] Bookcase 3D canvas/WebGL has no ARIA alternative; canvas is pointer-driven. No `prefers-reduced-motion`. No screen-reader testing evident.

### 7. Errors
- [observation] Validation errors via `memorius.validation` (`validate_name`/`validate_memory_id`/`validate_session_id`/`validate_content`) → clear `ValueError` messages.
- [observation] "Error: content required (pass as argument or pipe to stdin)" for missing input; "Memory not found: {id}"; "Aborted." / "Aborted (no confirmation)."
- [observation] MCP returns `{"error": "..."}` text blobs in success responses — callers must parse text to detect errors (inconsistent with JSON-RPC error objects).
- [gap] CLI `main()` has no top-level exception handler — unhandled handler exceptions become raw tracebacks.
- [gap] Error messages don't suggest remediation (e.g. "run memorius repair" for drift — only in doctor, not inline).

### 8. Onboarding
- [observation] `docs/getting-started.html` covers install, init, first memory, vault hierarchy, agent skill.
- [observation] README command cheat sheet lists all subcommands; verify step `memorius --version`.
- [observation] `memorius setup --skip-model` and `--force` options for model download control.
- [gap] No `memorius --help`-guided first-run; no "welcome" flow; no example memories pre-seeded.

---

## Highlights (3-5 short)

1. Core flow (init→setup→store→search) is clear but unguided — no onboarding wizard or welcome flow.
2. `input()` prompts exist in 4 places; only `delete` handles EOFError — `diary`/`profile`/`recall` crash on piped stdin.
3. `--json` output is deterministic and sorted (status/stats/get/update/prune/learnings/learning-stats/repair) — good for tooling.
4. Bookcase is keyboard-usable for search/controls but the 3D scene itself is pointer-only; no reduced-motion, no ARIA canvas alternative.
5. Librarian TTS is mirrored to an accessible `role="log"` region — voice off still usable.

---

## Domain summary

memorius presents four user-facing interfaces: a text CLI (argv/stdin, `--json` machine output, `input()` prompts), an agent-facing MCP server over stdio, a FastAPI REST API, and a loopback-only Three.js bookcase. The core user flow (init → setup → store → search) is documented but unguided — no onboarding wizard. Interaction gaps: `input()` prompts in 4 places with EOFError handled only on `delete`; `--yes`/`--dry-run` flags exist for non-interactive use. Empty states and success/error confirmations are present (IDs+paths). Keyboard support is strong for CLI and bookcase controls, but the bookcase 3D scene is pointer-only with no reduced-motion or ARIA canvas alternative. Screen-reader support is adequate for CLI/text (`--json`, `role="log"` librarian mirroring) but weak for the 3D canvas. Error handling is clear but inconsistent (MCP `{"error":...}` text blobs vs REST HTTP+JSON vs CLI plain text), and `main()` lacks a top-level exception handler. Suggested canonical home: `dev-notes/teammate-analysis/ui-ux.md` (this file).
