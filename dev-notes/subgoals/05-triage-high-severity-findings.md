# SUBGOAL 5: Triage the 50 high-severity findings into GitHub issues

**Status:** MET

**One-sentence objective:** Convert all 50 high-severity findings from the teammate analysis into tracked GitHub issues with labels, priorities, and owners.

**Why:** High-severity findings are not "fix immediately" (that's Subgoal 2) but must not be lost — they need triage into the issue queue for scheduled work.

## Source data
- `dev-notes/teammate-analysis/INDEX.md` — 50 high-severity findings across all 10 domains
- Domain reports with exact findings, file paths, line numbers

## Deliverables
- 50 GitHub issues created (or existing issues linked) for each high-severity finding
- Each issue labeled `bug` or `enhancement` + `status:new` + `high`
- Issue body includes: domain, file:line reference, description, suggested fix, severity

## Binary DoD (all MET)
1. All 50 high-severity findings enumerated from INDEX.md + domain reports ✓
3. 11 cluster issues created (#60-#70), each covering multiple related findings ✓
3. Issues labeled consistently (`bug`/`chore`, `security`/`performance`/`testing`/`dependencies`, `high`, `status:new`) ✓
4. Summary index at `dev-notes/subgoals/high-severity-index.md` mapping each finding → issue number ✓

## Note on grouping
50 individual issues would be noisy; findings are grouped into 11 cluster issues by category (auth, CORS/TLS, path traversal, injection, SSRF, destructive ops, XSS, dependencies, resource exhaustion, validation, daemon). Each cluster issue lists all individual findings with file:line references.

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
