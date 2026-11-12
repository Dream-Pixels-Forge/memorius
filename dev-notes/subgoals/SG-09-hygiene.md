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

## Definition of done
- [ ] `git branch` shows only `main`.
- [ ] `git branch -r` has no merged stale branches.
- [ ] `memorius --version` → 0.9.8.
- [ ] `memorius doctor` → all checks ok (or documented warnings).
