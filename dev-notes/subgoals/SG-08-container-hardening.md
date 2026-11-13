# SG-08 — Container hardening (P2)

## Evidence
GOAL.md item 4.4 is open; there is no `Dockerfile` in the repo.

## Scope
- Multi-stage `Dockerfile` (python:3.12-slim):
  - build stage installs the package,
  - runtime runs as non-root UID 10001,
  - `dumb-init` as PID 1,
  - no shell/debug tools in the runtime image beyond what the base needs,
  - healthcheck against `/health/live` for the REST server.
- `.dockerignore` (git, tests, docs, caches).
- `compose.yml` for local runs with a mounted vault volume.
- Document build/run in README or `docs/getting-started.html`.

## What was built

- `Dockerfile` — `python:3.12-slim` multi-stage. The build stage installs the
  package into `/opt/venv`; the runtime stage copies that venv, adds only
  `dumb-init` (no curl, git, compilers), runs as `USER 10001:10001`, keeps the
  vault at `/data` (`VOLUME`), exposes 8912, and healthchecks
  `GET /health/live` with a stdlib `urllib` probe. `ENTRYPOINT ["dumb-init",
  "--"]` with `CMD memorius serve-rest --host 0.0.0.0 --port 8912 --insecure`.
- `.dockerignore` — excludes VCS/CI, tests, docs, dev-notes, caches, build
  output, `memorius.yaml` and `.env*`; README/LICENSE stay because the wheel
  metadata needs them.
- `compose.yml` — builds `memorius:prod`, publishes `127.0.0.1:8912` only,
  mounts the `memorius-data` volume at `/data`, passes an optional
  `MEMORIUS_API_KEY`, and reuses the liveness healthcheck.
- `tests/test_container_contract.py` — 14 static checks for the build stages,
  UID, dumb-init, healthcheck, volume, secrets, ignore rules, compose ports
  and README instructions.
- README "Run in a container" section documents build, plain `docker run`,
  Compose, the read-only-by-default API, and the TLS caveat.

## Verification

Built on 2026-11-13: `memorius:prod` = `dadf6d1758fd`, 2.53 GB (CPU torch).

| Check | Result |
|-------|--------|
| `docker build -t memorius:prod .` | exit 0 |
| `docker run --rm memorius:prod id -u` | `10001` |
| `docker run --rm memorius:prod id -un` | `memorius` |
| `docker run --rm memorius:prod memorius --version` | `memorius v0.9.8` |
| `docker image inspect .Config.Env` | no `*_KEY` / `*_TOKEN` / `*_SECRET` |
| `docker exec … stat -c %u:%g /data` | `10001:10001` |
| `docker exec … command -v curl/git` | absent |
| `GET /health/live` | 200 `{"status":"alive"}` |
| `GET /health/ready` | 200 `{"status":"ready",…}` |
| `POST /search` (no key) | 200 (read-only allowed) |
| `POST /store` (no key) | 401 `API key required` |
| `docker inspect … .State.Health.Status` | `healthy` |

The first boot downloads the embedding model (~83 MB) before uvicorn binds,
so the container reports `starting` for a few minutes on a cold volume.

## Definition of done
- [x] `docker build -t memorius:prod .` succeeds.
- [x] `docker run --rm memorius:prod id -u` → 10001.
- [x] `docker run --rm memorius:prod memorius --version` works.
- [x] No secrets baked into the image.
