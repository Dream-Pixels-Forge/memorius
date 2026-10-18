"""Unit tests for the single-instance guard on `memorius serve` (issue #43).

Mechanism under test: exclusive non-blocking flock on
`<storage.path>/serve.lock` holding the incumbent PID. A second, live
holder blocks the new acquire (raises ServeAlreadyRunningError); a dead
holder is transparently stolen (the kernel releases flock on process
death). On platforms without fcntl the guard degrades to a documented
no-op.
"""

from __future__ import annotations

import os

import pytest

from memorius.single_instance import (
    ServeAlreadyRunningError,
    acquire_serve_lock,
)


def _config(storage_dir: str) -> dict:
    return {"storage": {"path": storage_dir}}


def test_acquire_creates_lock_with_own_pid(tmp_path):
    handle = acquire_serve_lock(_config(str(tmp_path)))
    try:
        assert handle.locked
        lock_file = tmp_path / "serve.lock"
        assert lock_file.exists()
        assert lock_file.read_text().strip() == str(os.getpid())
    finally:
        handle.release()


def test_second_acquire_raises_with_incumbent_pid(tmp_path):
    first = acquire_serve_lock(_config(str(tmp_path)))
    try:
        with pytest.raises(ServeAlreadyRunningError) as excinfo:
            acquire_serve_lock(_config(str(tmp_path)))
        exc = excinfo.value
        assert exc.pid == os.getpid()
        assert str(exc.lock_path) == str(tmp_path / "serve.lock")
    finally:
        first.release()


def test_release_allows_reacquire(tmp_path):
    first = acquire_serve_lock(_config(str(tmp_path)))
    first.release()
    second = acquire_serve_lock(_config(str(tmp_path)))
    try:
        assert second.locked
        assert (tmp_path / "serve.lock").read_text().strip() == str(os.getpid())
    finally:
        second.release()


def test_dead_holder_lock_is_stolen(tmp_path):
    """A lock file left behind by a dead process (no live flock) must be
    stolen automatically — no manual cleanup required."""
    lock_file = tmp_path / "serve.lock"
    # PID that is (with overwhelming probability) not alive on this host
    lock_file.write_text("999999999\n")
    handle = acquire_serve_lock(_config(str(tmp_path)))
    try:
        assert handle.locked
        assert lock_file.read_text().strip() == str(os.getpid())
    finally:
        handle.release()


def test_no_fcntl_platform_is_noop(monkeypatch, tmp_path):
    """Without fcntl (Windows) the guard degrades to a no-op handle —
    acquire must not raise and the second acquire must succeed too."""
    import memorius.single_instance as si

    monkeypatch.setattr(si, "fcntl", None)
    first = acquire_serve_lock(_config(str(tmp_path)))
    assert not first.locked
    second = acquire_serve_lock(_config(str(tmp_path)))
    assert not second.locked
    first.release()
    second.release()


def test_missing_storage_path_expanded(tmp_path, monkeypatch):
    """config may carry a relative or ~ path; the lock must land in the
    resolved storage dir, and the dir must be created if missing."""
    target = tmp_path / "nested" / "data"
    handle = acquire_serve_lock({"storage": {"path": str(target)}})
    try:
        assert handle.locked
        assert (target / "serve.lock").exists()
    finally:
        handle.release()
