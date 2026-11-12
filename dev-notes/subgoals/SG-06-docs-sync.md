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

## Definition of done
- [ ] No stale `v0.9.6`/`v0.9.3` claims remain.
- [ ] SECURITY.md has a usable contact.
- [ ] PROGRESS.md matches the actual release/CI state.
