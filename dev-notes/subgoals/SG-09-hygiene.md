# SG-09 — Repo/branch/local vault hygiene (P3, ops)

## Evidence
- 8 local branches appear unmerged (squash-merge artifacts); only
  `fix/66-xss-hardening` has content not in `main` (handled by SG-05).
- 17 stale remote branches (dependabot, old chore/fix branches).
- Installed CLI is `0.9.5`; repo is `0.9.8`.
- Local vault drift: `meta=903, vectors=9`; `repair --dry-run` reports
  894 missing vectors, 0 orphans.

## Scope
- After SG-01..SG-08 merge: delete merged local branches; prune remote
  branches whose PRs are merged.
- Upgrade the local install (`pip install -e .` or pipx) to `0.9.8`.
- Run `memorius repair` (not dry-run) to re-embed the 894 missing vectors.
- Re-run `memorius doctor`; expect all checks ok.

## What was built

- **Branches** — every local branch whose PR was squash-merged is deleted;
  `git branch` now lists only `main`. `fix/66-xss-hardening` was the one
  branch with content not in `main` (a `<meta>` CSP plus an unpkg SRI
  preload); SG-05 superseded it with a vendored Three.js and an HTTP-header
  CSP, so it was deleted rather than merged. All 18 stale remote branches
  (dependabot, `claude/*`, `fix/*`) are gone after `git push origin
  --delete` and `git fetch --prune`; `git branch -r` lists only
  `origin/main`.
- **Local install** — `/home/dimona/.memorius-venv` upgraded from 0.9.5 to
  0.9.8 with `pip install --upgrade memorius==0.9.8` from PyPI;
  `memorius --version` → `memorius v0.9.8`.
- **Vault** — `memorius repair --reindex` re-embedded the 894 metadata rows
  whose vectors were missing (903 meta / 9 vectors before). `memorius
  doctor` now reports every check ok.

## Definition of done
- [x] `git branch` shows only `main`.
- [x] `git branch -r` has no merged stale branches.
- [x] `memorius --version` → 0.9.8.
- [x] `memorius doctor` → all checks ok (or documented warnings).
