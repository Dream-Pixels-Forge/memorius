# GOAL: Issue #43 — single-instance guard for `memorius serve`

**One-sentence objective:** a second `memorius serve` against the same storage path fails fast (<2s, exit ≠0) with a diagnostic naming the incumbent PID, instead of silently joining a cross-process WAL lock-contention pool.

## Deliverables (paths that exist after)
- `memorius/single_instance.py` — `acquire_serve_lock(config)` + `ServeAlreadyRunningError`; fcntl flock on `<storage.path>/serve.lock` holding the PID; stale locks (dead PID) are stolen; no-op warning on platforms without fcntl (Windows)
- `memorius/cli/main.py` — `main()` guard hook: for `command == "serve"`, acquire the lock **before** `VaultEngine(config)` (loser exits non-zero, stderr diagnostic, no vault files opened by the loser)
- `tests/test_single_instance.py` — unit tests (lock created w/ PID; second acquire raises with incumbent pid; release → reacquire; dead holder stolen; no-fcntl platform is no-op)
- `tests/test_serve_single_instance.py` — subprocess integration: live `memorius serve` (tmp storage via `MEMORIUS_STORAGE_PATH`) holds lock; second `memorius serve` with same path exits non-zero within 5s, stderr contains incumbent PID; after first terminates, second can start

## Binary DoD (all must hold — 100% or NOT-MET)
1. `acquire_serve_lock` writes own PID into `<storage.path>/serve.lock` and holds an exclusive non-blocking flock
2. Concurrent second acquire on the same path raises `ServeAlreadyRunningError` carrying `pid` (incumbent) and `lock_path`; does NOT block/hang
3. After `release()`, a new acquire on the same path succeeds
4. A lock file containing a dead PID is stolen (acquire succeeds, PID overwritten) — no manual cleanup needed
5. `memorius serve` while another `memorius serve` holds the lock: exits with code 1 in <5s, stderr contains the incumbent PID; the loser process opens no vault files (guard runs before `VaultEngine`)
6. After the incumbent exits, a new `memorius serve` starts normally (lock is freed by kernel)
7. On a platform without `fcntl`, `acquire_serve_lock` is a documented no-op (logs warning, returns a releasing handle) — no crash
8. Full pre-existing test suite still green (no test deleted/skipped/weakened — negative space)
9. No new third-party dependency (fcntl = stdlib)

## Verification steps (goal-met re-runs these from scratch)
```
pytest tests/test_single_instance.py -v
pytest tests/test_serve_single_instance.py -v
pytest tests/ -q                      # full suite
# live check (throwaway storage dir):
MEMORIUS_STORAGE_PATH=/tmp/s1 serve1=(python -m memorius.cli.main serve) &  # holds lock
MEMORIUS_STORAGE_PATH=/tmp/s1 python -m memorius.cli.main serve </dev/null # -> rc=1, stderr names PID
kill serve1; MEMORIUS_STORAGE_PATH=/tmp/s1 serve2=(python -m memorius.cli.main serve) # -> starts normally
grep -n "acquire_serve_lock" memorius/cli/main.py    # hook present, before VaultEngine
grep -rn "flock\|fcntl" memorius/single_instance.py  # mechanism present
```

## Anti-drift rules
- No changes to `VaultEngine`, `mcp_server.py`, or REST/`serve-rest` (issue scope = stdio `serve` only)
- No new dependencies
- The lock lives in `storage.path` (issue text: `~/.memorius/data/serve.lock`), NOT the config dir
- Do not make `serve-rest` use the same lock (REST already has its own `--pid-file` daemon machinery)
