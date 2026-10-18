"""Bookcase goal — 3D vault bookcase + librarian voice.

TDD RED→GREEN per dev-notes/GOAL-bookcase-3d-librarian.md:
  1. test_bookcase_assets     — page assets ship in the package, well-formed,
     required element ids, JS references the 5 REST endpoints, ≤500 lines/file.
  2. test_bookcase_api_shapes — the REST contract the page depends on
     (GET /vaults, GET /vault, GET /memories, POST /search, GET /memory/{id}).
  3. test_bookcase_serve      — CLI `bookcase` end-to-end over loopback:
     static page 200, REST /health 200, ports released after terminate.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ELEMENT_IDS = [
    "bc-scene", "bc-search", "bc-detail", "bc-librarian",
    "bc-mic", "bc-voice", "bc-vault", "bc-layout", "bc-status",
]
REQUIRED_JS_ENDPOINT_REFS = ["/vault", "/memories", "/search", "/memory/"]
REQUIRED_ASSETS = ["bookcase.html", "bookcase.css", "bookcase.js"]
MAX_LINES_PER_FILE = 500

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}


class _TagChecker(HTMLParser):
    """Tag-balance checker (non-void tags must open/close in order)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(
                f"mismatched </{tag}> (open tail: {self.stack[-3:]})"
            )
        else:
            self.stack.pop()


def _assert_well_formed_html(html: str) -> None:
    checker = _TagChecker()
    checker.feed(html)
    checker.close()
    assert not checker.errors, f"malformed tags: {checker.errors[:5]}"
    assert not checker.stack, f"unclosed tags: {checker.stack[-5:]}"


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


class TestBookcaseAssets:
    """Assets ship with the package and are well-formed (Verification 1)."""

    def test_bookcase_assets(self):
        import memorius.bookcase as bookcase_pkg  # noqa: F401  (package must exist)

        root = Path(bookcase_pkg.__file__).parent
        for name in REQUIRED_ASSETS:
            path = root / name
            assert path.is_file(), f"missing asset {name!r}"

        html = (root / "bookcase.html").read_text(encoding="utf-8")
        _assert_well_formed_html(html)
        for element_id in REQUIRED_ELEMENT_IDS:
            assert f'id="{element_id}"' in html, f"missing #{element_id}"

        js_text = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(root.glob("*.js"))
        )
        for ref in REQUIRED_JS_ENDPOINT_REFS:
            assert ref in js_text, f"JS does not reference {ref}"

        for path in (
            list(root.glob("*.js"))
            + list(root.glob("*.html"))
            + list(root.glob("*.css"))
        ):
            lines = path.read_text(encoding="utf-8").splitlines()
            assert len(lines) <= MAX_LINES_PER_FILE, (
                f"{path.name} is {len(lines)} lines (>{MAX_LINES_PER_FILE} "
                "without a split)"
            )


class TestBookcaseApiShapes:
    """REST contract the bookcase page depends on (Verification 2)."""

    def test_bookcase_api_shapes(self, client, engine):
        engine.store(
            "pytest timeout regression notes",
            vault="main",
            shelf="tools",
            folder="qa",
        )

        # GET /vaults → {vaults: [{name, memories}]} including "main"
        response = client.get("/vaults")
        assert response.status_code == 200
        body = response.json()
        assert "vaults" in body
        entries = {v["name"]: v for v in body["vaults"]}
        assert "main" in entries
        for entry in body["vaults"]:
            assert "name" in entry and "memories" in entry

        # GET /vault?vault=main → hierarchy dict containing the shelves keys
        response = client.get("/vault", params={"vault": "main"})
        assert response.status_code == 200
        tree = response.json()
        assert isinstance(tree, dict)
        assert "shelves" in tree
        assert any(s["name"] == "tools" for s in tree["shelves"])

        # GET /memories?limit=5 → {count, next_cursor, memories} with ≤5 items
        response = client.get("/memories", params={"limit": 5})
        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {"count", "next_cursor", "memories"}
        assert len(body["memories"]) <= 5
        first_id = body["memories"][0]["id"]

        # POST /search → 200 with a results list
        response = client.post("/search", json={"query": "pytest"})
        assert response.status_code == 200
        assert isinstance(response.json()["results"], list)

        # GET /memory/{id} → record with content
        response = client.get(f"/memory/{first_id}")
        assert response.status_code == 200
        assert "content" in response.json()


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _port_released(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = socket.socket()
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            probe.close()
            return True
        except OSError:
            probe.close()
            time.sleep(0.2)
    return False


class TestBookcaseServe:
    """CLI end-to-end: static page + REST health over loopback (Verification 3)."""

    def test_bookcase_serve(self, engine):
        storage = Path(tempfile.mkdtemp())
        rest_port = _free_port()
        static_port = _free_port()
        env = dict(os.environ)
        env["MEMORIUS_STORAGE_PATH"] = str(storage)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [
            sys.executable, "-m", "memorius.cli.main", "bookcase",
            "--no-browser",
            "--port", str(rest_port),
            "--static-port", str(static_port),
        ]
        proc = subprocess.Popen(
            cmd, env=env, cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = ""
        try:
            page_text = ""
            health_ok = False
            deadline = time.time() + 90
            while time.time() < deadline:
                if proc.poll() is not None:
                    assert proc.stdout is not None
                    output = proc.stdout.read().decode()
                    pytest.fail(f"bookcase process exited early: {output}")
                if not page_text:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{static_port}/bookcase.html",
                            timeout=2,
                        ) as resp:
                            assert resp.status == 200
                            page_text = resp.read().decode("utf-8")
                    except Exception:
                        pass
                if not health_ok:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{rest_port}/health",
                            timeout=2,
                        ) as resp:
                            health_ok = resp.status == 200
                    except Exception:
                        pass
                if page_text and health_ok:
                    break
                time.sleep(0.5)
            assert page_text, f"static page never served on {static_port}"
            assert "bc-scene" in page_text, "page served without #bc-scene"
            assert health_ok, f"REST /health never ready on {rest_port}"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            output = proc.stdout.read().decode() if proc.stdout else output

        assert _port_released(static_port), f"static port {static_port} still held"
        assert _port_released(rest_port), f"REST port {rest_port} still held: {output}"

