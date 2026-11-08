# SUBGOAL 5: Triage the 50 high-severity findings into GitHub issues

**Status:** BLOCKED (depends on Subgoal 3)

**One-sentence objective:** Convert all 50 high-severity findings from the teammate analysis into tracked GitHub issues with labels, priorities, and owners.

**Why:** High-severity findings are not "fix immediately" (that's Subgoal 2) but must not be lost — they need triage into the issue queue for scheduled work.

## Source data
- `dev-notes/teammate-analysis/INDEX.md` — 50 high-severity findings across all 10 domains
- Domain reports with exact findings, file paths, line numbers

## Deliverables
- 50 GitHub issues created (or existing issues linked) for each high-severity finding
- Each issue labeled `bug` or `enhancement` + `status:new` + `high`
- Issue body includes: domain, file:line reference, description, suggested fix, severity

## Binary DoD (all must hold)
1. All 50 high-severity findings enumerated from INDEX.md + domain reports
2. Each finding has a corresponding GitHub issue (number recorded)
3. Issues labeled consistently (`bug`/`enhancement`, `status:new`, `high`)
4. A summary index created at `dev-notes/subgoals/high-severity-index.md` mapping finding → issue number

## Verification steps
```
gh issue list --label "high" --limit 60 --json number,title,labels
# Count should be 50 (or however many are new vs pre-existing)
cat dev-notes/subgoals/high-severity-index.md  # exists and maps all 50
```

## Anti-drift rules
- Do not fix high-severity issues in this subgoal — only triage/create issues
- Fixing happens in subsequent sprint work, not here
- If a high-severity finding is already addressed by Subgoal 2's critical fixes, mark it "resolved-by-critical" in the index instead of duplicating

---
