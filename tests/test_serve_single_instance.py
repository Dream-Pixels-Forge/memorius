"""Integration test: `memorius serve` single-instance guard end-to-end (issue #43).

Spawns real `python -m memorius.cli.main serve` subprocesses against a
throwaway storage dir (MEMORIUS_STORAGE_PATH). The first process acquires
the guard lock; a second process against the same storage path must exit
non-zero, fast (<5s), with a stderr diagnostic naming the incumbent PID.
After the incumbent exits, a new serve must start normally.

NOTE: the guard runs BEFORE VaultEngine construction, so the first
process's `serve.lock` appears almost immediately — no need to wait for
embedding-model load to observe the lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_for(storage_dir: Path) -> dict:
    env = dict(os.environ)
    env["MEMORIUS_STORAGE_PATH"] = str(storage_dir)
    return env


def _launch_serve(storage_dir: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "memorius.cli.main", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env_for(storage_dir),
        cwd=str(REPO_ROOT),
    )


def _wait_for_lock(storage_dir: Path, proc: subprocess.Popen, timeout: float = 60.0) -> None:
    """Wait until the running serve has acquired the guard lock. If the
    process dies first, fail with its stderr."""
    deadline = time.time() + timeout
    lock_file = storage_dir / "serve.lock"
    while time.time() < deadline:
        if lock_file.exists() and lock_file.read_text().strip() == str(proc.pid):
            return
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode(errors="replace")
            raise AssertionError(f"serve exited before acquiring lock (rc={proc.returncode}): {stderr[-2000:]}")
        time.sleep(0.2)
    raise AssertionError("timed out waiting for serve.lock")


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream:
            try:
                stream.close()
            except Exception:
                pass


def test_second_serve_refuses_while_first_runs(tmp_path):
    first = _launch_serve(tmp_path)
    try:
        _wait_for_lock(tmp_path, first)

        started = time.time()
        second = _launch_serve(tmp_path)
        rc = second.wait(timeout=30)
        elapsed = time.time() - started
        stderr = second.stderr.read().decode(errors="replace")

        assert rc == 1, f"second serve must exit non-zero, got rc={rc}: {stderr[-2000:]}"
        assert elapsed < 5.0, f"second serve must fail fast (<5s), took {elapsed:.1f}s"
        assert str(first.pid) in stderr, f"stderr must name incumbent PID {first.pid}: {stderr[-2000:]}"
    finally:
        _terminate(first)


def test_new_serve_starts_after_first_exits(tmp_path):
    first = _launch_serve(tmp_path)
    _wait_for_lock(tmp_path, first)
    _terminate(first)
    # kernel releases the flock with the process; a fresh serve must win
    second = _launch_serve(tmp_path)
    try:
        _wait_for_lock(tmp_path, second, timeout=90.0)
        assert second.poll() is None, "second serve must still be running"
    finally:
        _terminate(second)
