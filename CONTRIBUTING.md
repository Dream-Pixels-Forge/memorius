# Contributing to Memorius

Thanks for contributing! Memorius is a universal memory vault for AI agents, and we welcome
bug fixes, features, docs, and integrations.

## How to contribute

1. **Fork the repo** and create a branch: `git checkout -b feat/your-feature`
2. **Make your changes** — keep them focused and atomic
3. **Run the checks** (see below)
4. **Open a PR** — describe what changed and why
5. **Respond to review** — we'll look at it and merge or request changes

## Development setup

```bash
# Clone
git clone https://github.com/Dream-Pixels-Forge/memorius.git
cd memorius

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with all deps
pip install -e "."

# Install dev deps
pip install ruff pyright pytest pytest-asyncio pip-audit
```

## Checks

Run these before opening a PR:

```bash
# Type checking
python -m pyright

# Linting + formatting
ruff check .
ruff format --check .

# Tests (the full suite — CI runs exactly this)
python -m pytest tests/ -q

# Dependency audit (blocking in CI)
python -m pip_audit --skip-editable

# Build
python -m build
```

### Required CI checks

Every PR must be green on:

| Check | What it runs |
|-------|--------------|
| `test (3.11)`, `test (3.12)`, `test (3.13)` | Fast unit + integration subset |
| `full-suite` | Every file under `tests/` on Python 3.12, then `pip-audit` |

`pip-audit` is **blocking**. If a finding is genuinely unreachable, add a
documented ignore with a link to the advisory in
`.github/workflows/test.yml`; do not silence the step with `|| true`.

## Releasing

Publishing is driven by a GitHub release, never by pushing to `main`:

1. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry; merge it.
2. Wait for `full-suite` to pass on `main`.
3. Tag the release commit and push the tag:
   `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`
4. Publish a GitHub release for that tag. `release.yml` then checks out the
   **tagged commit** (not `main`), asserts the tag equals the `pyproject.toml`
   version, builds, and uploads to PyPI via trusted publishing.
5. Verify all three agree before calling it shipped:

   ```bash
   CODE=$(grep '^version' pyproject.toml | cut -d'"' -f2)
   TAG=$(git ls-remote --tags origin | awk -F'refs/tags/' '{print $2}' | sort -V | tail -1)
   REL=$(gh release list --limit 1 --json tagName --jq '.[0].tagName')
   PYPI=$(curl -s https://pypi.org/pypi/memorius/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])")
   [ "v$CODE" = "$TAG" ] && [ "$TAG" = "$REL" ] && [ "$CODE" = "$PYPI" ] \
     && echo "OK $CODE" || echo "MISMATCH code=$CODE tag=$TAG rel=$REL pypi=$PYPI"
   ```

PyPI versions are immutable. Never reuse a published version or move a
published tag — bump the version instead. `release.yml` deliberately has no
`skip-existing`, so a duplicate publish fails the job instead of silently
reusing the old artifact.

## Code style

- Python 3.11+ with type hints
- Ruff for linting + formatting
- Docstrings on public functions
- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`

## Reporting bugs

Open an issue using the bug report template. Include:
- Steps to reproduce
- Expected vs actual behavior
- `memorius doctor` output
- Python and memorius versions

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

By contributing, you agree your contributions are licensed under the [MIT License](LICENSE).
