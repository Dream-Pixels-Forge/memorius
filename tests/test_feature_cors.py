"""Phase 4.3 — REST CORS origin regex test."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient

    from memorius.rest_server import MemoriusAPI

    api = MemoriusAPI(engine)
    app = api.create_app()
    return TestClient(app)


class TestCORSPreflight:
    """CORS headers are present for localhost/127.0.0.1 with any port."""

    def test_preflight_localhost_rest_port(self, client):
        """CORS preflight allowed on REST port 8912."""
        response = client.options(
            "/search",
            headers={
                "Origin": "http://localhost:8912",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_preflight_127_0_0_1_bookcase_port(self, client):
        """CORS preflight allowed on bookcase port 8400."""
        response = client.options(
            "/search",
            headers={
                "Origin": "http://127.0.0.1:8400",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_preflight_unknown_port_rejected(self, client):
        """CORS preflight rejected on non-allowed localhost port (e.g. 5173)."""
        response = client.options(
            "/search",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in response.headers or response.status_code == 400

    def test_preflight_obsidian_scheme(self, client):
        response = client.options(
            "/search",
            headers={
                "Origin": "app://obsidian.md",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_preflight_unknown_origin_rejected(self, client):
        response = client.options(
            "/search",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Should not have CORS headers for unknown origins
        assert "access-control-allow-origin" not in response.headers or response.status_code == 400


class TestCORSActualRequest:
    """CORS headers appear on actual GET requests with Origin."""

    def test_get_with_origin_header(self, client):
        response = client.get(
            "/status",
            headers={"Origin": "http://localhost:8912"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


# ── Idempotency key tests (issue #65, H-02) ──────────────────────────────────

class TestIdempotency:
    """Idempotency-Key header prevents duplicate mutating requests."""

    def test_idempotent_post_returns_409_on_reuse(self, client, engine):
        """Second POST with same Idempotency-Key returns 409 Conflict."""
        os.environ["MEMORIUS_API_KEY"] = "test-key"
        try:
            # First request
            resp1 = client.post(
                "/store",
                json={"content": "idempotency test memory"},
                headers={
                    "Authorization": "Bearer test-key",
                    "Idempotency-Key": "unique-key-123",
                },
            )
            assert resp1.status_code == 200

            # Second request with same key — should return 409
            resp2 = client.post(
                "/store",
                json={"content": "different content that should be ignored"},
                headers={
                    "Authorization": "Bearer test-key",
                    "Idempotency-Key": "unique-key-123",
                },
            )
            assert resp2.status_code == 409
            assert "idempotency" in resp2.json()["detail"].lower()

            # Different key should create a new memory
            resp3 = client.post(
                "/store",
                json={"content": "different key, different memory"},
                headers={
                    "Authorization": "Bearer test-key",
                    "Idempotency-Key": "unique-key-456",
                },
            )
            assert resp3.status_code == 200
        finally:
            os.environ.pop("MEMORIUS_API_KEY", None)

    def test_idempotency_key_only_for_mutating(self, client, engine):
        """GET requests ignore Idempotency-Key header (no deduplication)."""
        os.environ["MEMORIUS_API_KEY"] = "test-key"
        try:
            resp1 = client.get(
                "/status",
                headers={
                    "Authorization": "Bearer test-key",
                    "Idempotency-Key": "some-key",
                },
            )
            assert resp1.status_code == 200

            resp2 = client.get(
                "/status",
                headers={
                    "Authorization": "Bearer test-key",
                    "Idempotency-Key": "some-key",
                },
            )
            assert resp2.status_code == 200
            # GET requests are not subject to idempotency — both succeed
        finally:
            os.environ.pop("MEMORIUS_API_KEY", None)
