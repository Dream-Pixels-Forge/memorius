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

## Definition of done
- [ ] `docker build -t memorius:prod .` succeeds.
- [ ] `docker run --rm memorius:prod id -u` → 10001.
- [ ] `docker run --rm memorius:prod memorius --version` works.
- [ ] No secrets baked into the image.
