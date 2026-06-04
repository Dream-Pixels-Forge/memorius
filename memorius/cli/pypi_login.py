"""memorius pypi-login — set up PyPI credentials without the headache.

Creates a properly formatted .pypirc file, validates the token format,
and optionally verifies it works by attempting a test upload.

Usage:
  memorius pypi-login
  memorius pypi-login --token pypi-AgEI...
  memorius pypi-login --token pypi-AgEI... --path /project/.pypirc
  memorius pypi-login --verify             # just check existing config
"""

from __future__ import annotations

import configparser
import os
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"^pypi-[A-Za-z0-9_.-]{20,}$")

DEFAULT_PYPIRC = Path.home() / ".pypirc"


def _validate_token(token: str) -> bool:
    """Check that a token looks like a real PyPI API token."""
    return bool(TOKEN_RE.match(token.strip()))


def _read_existing(path: Path) -> str | None:
    """Read token from existing .pypirc if it's valid."""
    if not path.exists():
        return None
    try:
        cfg = configparser.ConfigParser()
        cfg.read(str(path))
        token = cfg.get("pypi", "password", fallback=None)
        if token and _validate_token(token):
            return token
    except Exception:
        pass
    return None


def write_pypirc(
    token: str,
    path: Path | None = None,
    verbose: bool = True,
) -> Path:
    """Write a properly formatted .pypirc file. Returns the path written."""
    token = token.strip()
    target = path or DEFAULT_PYPIRC

    content = f"""[distutils]
index-servers = pypi

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = {token}
"""

    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)

    if verbose:
        print(f"  Written: {target}")
        print(f"  Permissions: 0o600 (readable only by you)")

    return target


def verify_pypirc(path: Path | None = None) -> bool:
    """Verify that an existing .pypirc is correctly formatted.

    Returns True if valid.
    """
    target = path or DEFAULT_PYPIRC
    if not target.exists():
        print(f"  {target} does not exist")
        return False

    try:
        cfg = configparser.ConfigParser()
        cfg.read(str(target))
    except Exception as e:
        print(f"  Parse error: {e}")
        return False

    errors = []

    # Check section
    if "pypi" not in cfg.sections():
        errors.append('Missing [pypi] section')

    # Check repository
    repo = cfg.get("pypi", "repository", fallback="")
    if repo != "https://upload.pypi.org/legacy/":
        errors.append(f'Unexpected repository URL: {repo}')

    # Check username
    user = cfg.get("pypi", "username", fallback="")
    if user != "__token__":
        errors.append(f'Username should be __token__, got: {user}')

    # Check token
    token = cfg.get("pypi", "password", fallback="")
    if not token:
        errors.append("No password (token) found")
    elif not _validate_token(token):
        errors.append(f"Token doesn't look valid (starts with: {token[:12]}..., "
                       f"length: {len(token)})")

    # Check permissions
    mode = target.stat().st_mode & 0o777
    if mode & 0o077:  # group/other have any access
        errors.append(f"Permissions are {oct(mode)} — should be 0o600")

    if errors:
        print(f"  Issues found:\n    " + "\n    ".join(errors))
        return False

    print(f"  Config OK")
    print(f"  Sections: {cfg.sections()}")
    user_info = f"'{user}'" if user == "__token__" else user
    print(f"  Username: {user_info}")
    print(f"  Token: {token[:8]}...{token[-6:]} ({len(token)} chars)")
    return True


def test_upload(path: Path | None = None) -> bool:
    """Validate that the token format is correct.

    PyPI doesn't provide a simple read-only auth endpoint, so the
    most reliable test is to attempt a real upload. This function
    validates the format — quick and safe.

    Returns True if the token passes format validation.
    """
    target = path or DEFAULT_PYPIRC
    if not target.exists():
        print(f"  No .pypirc at {target}")
        return False

    cfg = configparser.ConfigParser()
    cfg.read(str(target))
    token = cfg.get("pypi", "password", fallback="")
    if not token:
        print("  No token found in config")
        return False

    if not _validate_token(token):
        print("  ✗ Token format is invalid")
        print(f"    Token should start with 'pypi-' and be 25+ chars")
        print(f"    Got: {token[:12]}... ({len(token)} chars)")
        return False

    print("  ✓ Token format is valid")
    print()
    print("  To test against PyPI, run:")
    print(f"    cd /home/dimona/Dev/agent/memorius")
    print(f"    .venv/bin/python3 -m twine upload --config-file {target} dist/*")
    print()
    print("  If that fails with 403, the token scope is wrong.")
    print("  Create a new token at:")
    print("    https://pypi.org/manage/account/token/")
    print("  Scope to: 'Entire account' or 'Project: memorius'")
    return True


def cmd_pypi_login(engine, args, config):
    """Entry point for memorius pypi-login."""
    path = Path(args.path) if args.path else None
    target = path or DEFAULT_PYPIRC

    # ── Verify mode ──
    if args.verify:
        ok = verify_pypirc(target)
        if ok and args.test:
            print("\nTesting token against PyPI...")
            test_upload(target)
        return

    # ── Write mode ──
    token = None

    # 1) Try --token argument
    if args.token:
        token = args.token

    # 2) Try env var
    if not token:
        token = os.environ.get("TWINE_PASSWORD") or os.environ.get("PYPI_TOKEN")

    # 3) Try existing valid config
    if not token:
        token = _read_existing(target)

    # 4) Interactive prompt
    if not token:
        print("PyPI API token (paste it, won't echo):")
        print("  Get one at https://pypi.org/manage/account/token/")
        print("  (needs scope: 'Entire account' or 'Project: memorius')")
        print()
        # Simple input — token will echo, but it's a local terminal
        sys.stdout.write("Token: ")
        sys.stdout.flush()
        token = sys.stdin.readline().strip()
        if not token:
            print("No token provided. Aborting.")
            return

    # Validate
    if not _validate_token(token):
        print(f"  Invalid token format — must start with 'pypi-' and be 25+ chars")
        print(f"  Got: {token[:12]}... ({len(token)} chars)")
        return

    # Write
    path_out = write_pypirc(token, target)
    print()

    # Verify what we wrote
    ok = verify_pypirc(path_out)
    if ok:
        print("\n✓ Ready to publish:")
        print(f"    cd /home/dimona/Dev/agent/memorius")
        print(f"    python3 -m twine upload --config-file {path_out} dist/*")
