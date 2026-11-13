# syntax=docker/dockerfile:1
#
# Memorius production image — multi-stage, non-root, dumb-init as PID 1.
#
#   docker build -t memorius:prod .
#   docker run --rm -p 127.0.0.1:8912:8912 -v memorius-data:/data memorius:prod
#
# The REST API is served in plaintext (--insecure); terminate TLS in front of
# the container or mount a certificate and override CMD. Without
# MEMORIUS_API_KEY the API is read-only for non-loopback clients.

# ── build: resolve dependencies and install the package into a venv ──────
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY memorius ./memorius
# CPU-only torch keeps the runtime image small and avoids pulling the CUDA
# stack; sentence-transformers is satisfied by it.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && /opt/venv/bin/pip install .

# ── runtime: slim, non-root UID 10001, dumb-init as PID 1 ───────────────
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEMORIUS_STORAGE_PATH=/data

# dumb-init forwards signals to the server; nothing else is installed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends dumb-init \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 memorius \
 && useradd --uid 10001 --gid 10001 --no-create-home \
      --home-dir /data --shell /usr/sbin/nologin memorius \
 && mkdir -p /data \
 && chown 10001:10001 /data

COPY --from=build /opt/venv /opt/venv

USER 10001:10001
WORKDIR /data
EXPOSE 8912
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8912/health/live', timeout=3)"]

ENTRYPOINT ["dumb-init", "--"]
CMD ["memorius", "serve-rest", "--host", "0.0.0.0", "--port", "8912", "--insecure"]
