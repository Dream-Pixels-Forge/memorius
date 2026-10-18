"""Single-instance guard for `memorius serve` (stdio MCP server) — issue #43.

Multiple long-lived `memorius serve` processes sharing one storage dir
hold the SQLite (WAL) and HNSW index files open simultaneously; stale
readers block WAL checkpointing and writes in the stuck clients hang
indefinitely (observed >60s MCP store timeouts while a fresh process
wrote in ~1.25s).

Mechanism
---------
Exclusive non-blocking ``flock`` on ``<storage.path>/serve.lock``
holding the incumbent PID:

- live holder      → ``ServeAlreadyRunningError`` (carries the PID)
- dead/absent PID  → kernel already released the flock → steal the lock
- no ``fcntl`` (Windows) → documented no-op (guard disabled, warning)

The lock is released automatically by the kernel when the holder exits
(SIGTERM/SIGKILL included), so no manual cleanup is ever required.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # Windows — no flock in stdlib
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger("memorius")

LOCK_NAME = "serve.lock"
# Attempts before giving up on a contested lock (handles the
# read-PID / retry race between two losing processes)
_MAX_ACQUIRE_ATTEMPTS = 3


class ServeAlreadyRunningError(RuntimeError):
    """Raised when another live `memorius serve` holds the guard lock."""

    def __init__(self, pid: int, lock_path: Path) -> None:
        self.pid = pid
        self.lock_path = Path(lock_path)
        super().__init__(
            f"another 'memorius serve' is already running (PID {pid}) "
            f"— lock: {lock_path}"
        )


class ServeLock:
    """Handle for the guard lock. Hold it for the lifetime of the process;
    the kernel releases the flock on exit. ``release()`` for tests/cleanup.
    """

    def __init__(self, lock_path: Path, fd: Optional[int] = None) -> None:
        self.lock_path = lock_path
        self._fd = fd

    @property
    def locked(self) -> bool:
        """True when an exclusive flock is actually held."""
        return self._fd is not None

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except (OSError, AttributeError):
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None


def resolve_lock_path(config: dict[str, Any]) -> Path:
    """`<storage.path>/serve.lock`, expanded and parent-dir ensured."""
    raw = (config or {}).get("storage", {}).get("path") or "~/.memorius/data"
    return Path(raw).expanduser() / LOCK_NAME


def _read_lock_pid(lock_path: Path) -> Optional[int]:
    try:
        content = lock_path.read_text().strip()
        return int(content) if content.isdigit() else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    except OSError:
        return False
    return True


def acquire_serve_lock(config: dict[str, Any]) -> ServeLock:
    """Acquire the single-instance guard lock for the configured storage dir.

    Raises ``ServeAlreadyRunningError`` when a live incumbent holds it.
    On platforms without ``fcntl`` returns an unlocked no-op handle after
    logging a warning (the guard is unavailable, but serve still works).
    """
    lock_path = resolve_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        logger.warning(
            "single-instance guard unavailable on this platform "
            "(no fcntl); 'memorius serve' continuing without a lock"
        )
        return ServeLock(lock_path, fd=None)

    last_pid: Optional[int] = None
    for _ in range(_MAX_ACQUIRE_ATTEMPTS):
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            last_pid = _read_lock_pid(lock_path)
            # A dead holder's flock was already released by the kernel:
            # retry and steal. A live holder: fail with its PID.
            if last_pid is not None and _pid_alive(last_pid):
                raise ServeAlreadyRunningError(last_pid, lock_path) from None
            continue
        except OSError:
            os.close(fd)
            raise

        # Won the lock: stamp our PID (replace any stale content).
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
        return ServeLock(lock_path, fd=fd)

    # Three consecutive contested attempts: report the best-known holder.
    raise ServeAlreadyRunningError(
        last_pid if last_pid is not None else os.getpid(), lock_path
    )
