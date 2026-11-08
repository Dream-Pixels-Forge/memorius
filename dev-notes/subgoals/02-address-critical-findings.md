# SUBGOAL 2: Address the 11 critical findings from teammate analysis

**Status:** BLOCKED (depends on Subgoal 1)

**One-sentence objective:** Fix all 11 critical-severity findings flagged by the 10-domain teammate analysis audit (dev-notes/teammate-analysis/).

**Why:** Critical findings are tagged "Fix Immediately" — they represent real security, correctness, and reliability risks that must not ship in a release.

## Source data
- `dev-notes/teammate-analysis/INDEX.md` — 11 critical findings across 6 domains
- Domain reports: `security.md` (2), `api.md` (1), `db.md` (1), `dependencies.md` (1), `testing.md` (3), `ui-ux.md` (3)

## Deliverables
- Each critical finding either fixed, documented as accepted-risk, or converted to a GitHub issue with `bug` + `status:triaged` labels
- No critical finding left unfixed and un-tracked

## Binary DoD (all must hold)
1. Read all 6 domain reports and extract the exact critical findings (file paths, line numbers, severity)
2. For each finding: fix code OR file a GitHub issue with reproduction steps
3. `grep -rn` confirm no obvious instances of the flagged anti-patterns remain in unfixed findings
4. Full test suite green after fixes (`pytest tests/ -q`)

## Verification steps
```
# Read each domain report
cat dev-notes/teammate-analysis/security.md
cat dev-notes/teammate-analysis/api.md
cat dev-notes/teammate-analysis/db.md
cat dev-notes/teammate-analysis/dependencies.md
cat dev-notes/teammate-analysis/testing.md
cat dev-notes/teammate-analysis/ui-ux.md
# Then fix or issue-file each critical finding
pytest tests/ -q
```

## Anti-drift rules
- Do not fix non-critical (high/medium/low) findings in this subgoal — they belong to Subgoal 5 (triage)
- Each fix must have a test or regression coverage where applicable
- Document accepted-risk findings in `dev-notes/AUDIT.md`

---
