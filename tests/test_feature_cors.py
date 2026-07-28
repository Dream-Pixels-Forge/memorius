"""Phase 4.3 — REST CORS origin regex test."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

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

    def test_preflight_localhost_5173(self, client):
        response = client.options(
            "/search",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_preflight_127_0_0_1_8080(self, client):
        response = client.options(
            "/search",
            headers={
                "Origin": "http://127.0.0.1:8080",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_preflight_no_port(self, client):
        response = client.options(
            "/search",
            headers={
                "Origin": "http://localhost",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

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
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
