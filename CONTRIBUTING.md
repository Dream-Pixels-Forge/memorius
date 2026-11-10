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

# Tests
python -m pytest

# Build
python -m build
```

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
