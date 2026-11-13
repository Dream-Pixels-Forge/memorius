# SG-06 — Docs/version/PROGRESS sync (P2)

## Evidence
- README changelog badge and `docs/index.html` say `v0.9.6`; current is 0.9.8.
- `dev-notes/PROGRESS.md` still says `v0.9.3`.
- Bookcase goal checklists are unchecked although #40/#50/#85/#86 shipped.
- `SECURITY.md` says "email us" without an address.

## Scope
- Update README + docs badges to `v0.9.8` (or make them link to PyPI).
- Rewrite the PROGRESS current-state block; mark bookcase goals done.
- Add a contact address to SECURITY.md (use the repo owner's published
  email from `pyproject.toml`).
- Add the SG index to `dev-notes/` links.

## What was built

- `tests/test_docs_consistency.py` reads `pyproject.toml` as the source of
  truth and fails when the README changelog badge, the two `docs/index.html`
  hero badges, the PROGRESS version line, or the security contact drift.
- README and both docs badges now say **v0.9.8**.
- `dev-notes/PROGRESS.md` current state rewritten: version 0.9.8, CI matrix
  3.11/3.12/3.13 + full suite (570 tests), SG-01–SG-05/SG-07/SG-10 merged,
  the two open subgoals named, bookcase milestones logged, Phase 3 marked
  complete, and a Planning section linking the subgoal index.
- `dev-notes/README.md` added as the notes hub (PROGRESS, subgoal index,
  goal/spec/audit/plan documents, per-feature plans).
- Both bookcase goal files have every deliverable and DoD box ticked — they
  shipped in v0.9.0–v0.9.8.
- `SECURITY.md` names the maintainer address from `pyproject.toml` and adds
  GitHub's private-advisory link.

## Definition of done
- [x] No stale `v0.9.6`/`v0.9.3` claims remain.
- [x] SECURITY.md has a usable contact.
- [x] PROGRESS.md matches the actual release/CI state.
