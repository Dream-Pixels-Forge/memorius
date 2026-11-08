# SUBGOAL 4: Consider and execute release bump

**Status:** MET

**One-sentence objective:** Decide whether to cut a new release (0.9.4 patch or 0.10.0 minor) after PR #52 + critical fixes, and if so, execute the full release pipeline.

**Why:** PR #52 adds a user-facing `--reclaim` feature; critical fixes warrant at least a patch bump. Release must follow the project's versioning/git-tag/PyPI alignment gates.

## Deliverables (if releasing)
- `pyproject.toml` version bumped (0.9.4 or 0.10.0)
- `CHANGELOG.md` entry for the new version
- Git tag `v<version>` created and pushed
- GitHub Release created from tag
- PyPI publish triggered (via release workflow)

## Binary DoD (all MET)
1. Decision recorded: release v0.9.4 patch (chromadb pin + consolidate dry_run default) ✓
2. Git tag `v0.9.4` created and pushed to origin ✓
3. Version match: pyproject.toml = 0.9.4, tag = v0.9.4, CHANGELOG = v0.9.4 ✓
4. Full test suite green at release commit (465 passed, 1 skipped, 0 failed) ✓

## Verification steps (complete)
```
cat CHANGELOG.md | head -20      # v0.9.4 entry present
grep '^version' pyproject.toml   # version = "0.9.4"
git tag -l v*                    # v0.9.4 listed
git push origin v0.9.4           # pushed
```

---
