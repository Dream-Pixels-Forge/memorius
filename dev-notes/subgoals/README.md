# Memorius Subgoal Pipeline

Source: state audit of 2026-11-12 (full suite 523 passed / 7 failed; REST auth
regression; release/tag drift; bookcase CSP missing).

Execution rules: one subgoal at a time, branch-per-task, TDD (RED → GREEN),
PR with `Closes #N`, CI green, squash merge, then update this index.

| # | Subgoal | Priority | Status | Branch / PR |
|---|---------|----------|--------|-------------|
| SG-01 | Restore REST authentication (hotfix) | P0 | done | #101 merged |
| SG-02 | Make the full test suite green (3 stale tests) | P0 | done | #103 merged |
| SG-03 | Enforce full-suite CI + blocking dependency audit | P1 | done | #104 merged |
| SG-04 | Release integrity: tag 0.9.7/0.9.8 + fix release trigger | P1 | done | #105 merged, v0.9.8 shipped |
| SG-05 | Bookcase CSP/SRI hardening (vendored Three.js + header CSP) | P1 | done | #107 merged |
| SG-06 | Docs/version/PROGRESS sync + security contact | P2 | ready | — |
| SG-07 | Bookcase UX: library index, walk-to-shelf, surprise me | P2 | in-review | `feat/99-bookcase-index` |
| SG-08 | Container hardening (Dockerfile, non-root, dumb-init) | P2 | ready | — |
| SG-09 | Repo/branch/local vault hygiene | P3 | ready (ops, no PR) | — |
| SG-10 | Bookcase: bottom-left walk controls, walking hippo, centered reader | P1 | blocked by SG-07 | — |

Status legend: `ready` · `in-progress` · `in-review` · `done` · `blocked`.

## Definition of done for every code subgoal

1. Failing test written first and watched fail.
2. Minimal implementation; targeted tests pass.
3. Full local suite has no new failures.
4. Branch pushed, PR opened with `Closes #N`, CI green.
5. Squash-merged; branch deleted; this index updated.
