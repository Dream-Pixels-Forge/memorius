# SUBGOAL 4: Consider and execute release bump

**Status:** BLOCKED (depends on Subgoal 3)

**One-sentence objective:** Decide whether to cut a new release (0.9.4 patch or 0.10.0 minor) after PR #52 + critical fixes, and if so, execute the full release pipeline.

**Why:** PR #52 adds a user-facing `--reclaim` feature; critical fixes warrant at least a patch bump. Release must follow the project's versioning/git-tag/PyPI alignment gates.

## Deliverables (if releasing)
- `pyproject.toml` version bumped (0.9.4 or 0.10.0)
- `CHANGELOG.md` entry for the new version
- Git tag `v<version>` created and pushed
- GitHub Release created from tag
- PyPI publish triggered (via release workflow)

## Binary DoD (all must hold)
1. Decision recorded: release version + rationale (or explicit "no release yet" with reason)
2. If releasing: `git tag -l v*` contains the new tag; tag pushed to origin
3. If releasing: three-way version match (code = tag = PyPI) verified per project release gate
4. Full test suite green at release commit (Subgoal 3 must be MET first)

## Verification steps
```
# Decision
cat CHANGELOG.md | head -20
grep '^version' pyproject.toml
# If releasing:
git tag -a v0.9.4 -m "release v0.9.4"
git push origin v0.9.4
# Verify PyPI after workflow completes
curl -s https://pypi.org/pypi/memorius/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
```

## Anti-drift rules
- Never reuse a published version/tag (PyPI versions are immutable)
- Do not tag until `pnpm build`/equivalent and local artifact inspection pass
- If not releasing yet, record the decision + next review date in this file

---
