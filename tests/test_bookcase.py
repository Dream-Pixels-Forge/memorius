"""Bookcase goals — 3D vault bookcase + librarian voice + walkable shelves.

TDD RED→GREEN per dev-notes/GOAL-bookcase-3d-librarian.md and
dev-notes/GOAL-bookcase-walkable-shelves.md:
  1. test_bookcase_assets     — page assets ship in the package, well-formed,
     required element ids, JS references the 5 REST endpoints, ≤500 lines/file.
  2. test_bookcase_api_shapes — the REST contract the page depends on
     (GET /vaults, GET /vault, GET /memories, POST /search, GET /memory/{id}).
  3. test_bookcase_serve      — CLI `bookcase` end-to-end over loopback:
     static page 200, REST /health 200, ports released after terminate.
  4. test_bookcase_walkable   — walkable-library contract (GOAL-walkable):
     scene/layout/walk modules exist, first-person controls (WASD +
     pointer-lock mouse look), aisle layout constants, debug hook exposing
     sections/audit/camera, and preserved interactions (search flight,
     book click).
"""
from __future__ import annotations

import os
import re
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
REQUIRED_ASSETS = [
    "bookcase.html", "bookcase.css", "bookcase.js",
    "bookcase-scene.js", "bookcase-walk.js", "bookcase-layout.js",
    "bookcase-atmosphere.js", "bookcase-guide.js", "bookcase-textures.js",
    "bookcase-minimap.js", "bookcase-mascot.js", "librarian-hippo.webp",
    "bookcase-cases.js", "librarian-hippo.glb", "bookcase-index.js",
    "bookcase-copy.js",
]
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
        import memorius.bookcase as bookcase_pkg

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
        os.environ["MEMORIUS_API_KEY"] = "test-key"
        auth_headers = {"Authorization": "Bearer test-key"}
        try:
            engine.store(
                "pytest timeout regression notes",
                vault="main",
                shelf="tools",
                folder="qa",
            )

            # GET /vaults → {vaults: [{name, memories}]} including "main"
            response = client.get("/vaults", headers=auth_headers)
            assert response.status_code == 200
            body = response.json()
            assert "vaults" in body
            entries = {v["name"]: v for v in body["vaults"]}
            assert "main" in entries
            for entry in body["vaults"]:
                assert "name" in entry and "memories" in entry

            # GET /vault?vault=main → hierarchy dict containing the shelves keys
            response = client.get("/vault", params={"vault": "main"}, headers=auth_headers)
            assert response.status_code == 200
            tree = response.json()
            assert isinstance(tree, dict)
            assert "shelves" in tree
            assert any(s["name"] == "tools" for s in tree["shelves"])

            # GET /memories?limit=5 → {count, next_cursor, memories} with ≤5 items
            response = client.get("/memories", params={"limit": 5}, headers=auth_headers)
            assert response.status_code == 200
            body = response.json()
            assert set(body) >= {"count", "next_cursor", "memories"}
            assert len(body["memories"]) <= 5
            first_id = body["memories"][0]["id"]

            # POST /search → 200 with a results list
            response = client.post(
                "/search",
                json={"query": "pytest"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert isinstance(response.json()["results"], list)
        finally:
            os.environ.pop("MEMORIUS_API_KEY", None)

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
                    except Exception:  # noqa: BLE001, S110
                        pass
                if not health_ok:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{rest_port}/health",
                            timeout=2,
                        ) as resp:
                            health_ok = resp.status == 200
                    except Exception:  # noqa: BLE001, S110
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


class TestBookcaseWalkable:
    """Walkable-library contract (GOAL-bookcase-walkable-shelves, Verification 1).

    Asset-level: the scene splits into scene/walk/layout modules, implements
    first-person controls (WASD + pointer-lock mouse look with drag fallback),
    arranges ≥3 sections as walkable aisles, exposes a `window.__bookcase`
    debug hook (sections / book audit / camera), and preserves the existing
    interactions (search flight, book click, librarian greeting).
    """

    def _asset(self, name: str) -> str:
        import memorius.bookcase as bookcase_pkg

        return (Path(bookcase_pkg.__file__).parent / name).read_text(
            encoding="utf-8"
        )

    def test_walk_module_first_person_controls(self):
        walk = self._asset("bookcase-walk.js")
        # WASD/arrow walking
        for key in ("KeyW", "KeyA", "KeyS", "KeyD"):
            assert key in walk, f"walk module missing {key} binding"
        # pointer-lock mouse look preferred, drag-look fallback
        assert "requestPointerLock" in walk, "no pointer-lock usage"
        assert "mousemove" in walk, "no mouse-look handler"
        # collision: camera must not pass through shelves / below floor
        assert "clamp" in walk or "AABB" in walk, "no collision clamping"

    def test_layout_module_section_aisle_constants(self):
        layout = self._asset("bookcase-layout.js")
        assert "SECTION" in layout, "no section constants"
        assert "AISLE" in layout, "no aisle constants"

    def test_scene_debug_hook_and_interactions(self):
        scene = self._asset("bookcase-scene.js")
        # module graph: scene uses the walk + layout modules
        assert "./bookcase-walk.js" in scene
        assert "./bookcase-layout.js" in scene
        # debug hook required by the headless verification
        assert "__bookcase" in scene, "no window.__bookcase debug hook"
        assert "auditBooks" in scene, "debug hook lacks book-arrangement audit"
        # preserved interactions
        assert "bc:search" in scene, "search flight lost"
        assert "bc:book-click" in scene, "book click lost"
        assert "bc:reset-view" in scene, "view reset lost"

    def test_main_page_imports_scene(self):
        js = self._asset("bookcase.js")
        assert "./bookcase-scene.js" in js


class TestBookcaseNextLevel:
    """Lantern librarian, cinematic guidance, reading panel, minimap."""

    def _asset(self, name: str) -> str:
        import memorius.bookcase as bookcase_pkg

        return (Path(bookcase_pkg.__file__).parent / name).read_text(
            encoding="utf-8"
        )

    def test_scene_uses_atmosphere_guide_and_textures(self):
        scene = self._asset("bookcase-scene.js")
        for mod in ("./bookcase-atmosphere.js", "./bookcase-guide.js",
                    "./bookcase-cases.js"):
            assert mod in scene, f"scene does not import {mod}"
        assert "./bookcase-textures.js" in self._asset("bookcase-cases.js")
        # accessibility: honour reduced-motion
        assert "prefers-reduced-motion" in scene
        # search hits slide out of the shelf; opened book drawn out
        assert "PULL_TOP" in scene and "bc:open" in scene

    def test_guide_lantern_choreography(self):
        guide = self._asset("bookcase-guide.js")
        assert "lanternRun" in guide, "no lantern-led camera move"
        assert "establishing" in guide, "no opening establishing shot"
        assert "reducedMotion" in guide, "camera moves ignore reduced motion"
        assert "cancel()" in guide, "camera moves cannot be skipped"

    def test_atmosphere_bounded_light_pool(self):
        atmo = self._asset("bookcase-atmosphere.js")
        assert "LIGHT_POOL" in atmo, "lamps must share a fixed light pool"
        assert "PointLight" in atmo

    def test_librarian_speaks_directions(self):
        layout = self._asset("bookcase-layout.js")
        assert "export function describePlace" in layout
        lib = self._asset("bookcase-librarian.js")
        assert "announceSearch(query, results, directions" in lib
        assert "readAloud" in lib and "speechSynthesis.cancel" in lib

    def test_page_controls_minimap_and_shortcuts(self):
        html = self._asset("bookcase.html")
        for element_id in ("bc-map", "bc-help", "bc-hint", "bc-cross", "bc-usage"):
            assert f'id="{element_id}"' in html, f"missing #{element_id}"
        main = self._asset("bookcase.js")
        assert "./bookcase-minimap.js" in main
        assert "stepResult" in main, "no N/P result cycling"
        assert "onShortcut" in main, "no keyboard shortcuts"
        minimap = self._asset("bookcase-minimap.js")
        assert "bc:goto" in minimap, "minimap click does not walk the visitor"

    def test_hippo_librarian_mascot(self):
        import memorius.bookcase as bookcase_pkg

        art = (Path(bookcase_pkg.__file__).parent / "librarian-hippo.webp").read_bytes()
        assert art[:4] == b"RIFF" and art[8:12] == b"WEBP", "mascot art is not a WebP"
        assert len(art) < 200_000, "mascot art should stay small (shipped in the wheel)"
        mascot = self._asset("bookcase-mascot.js")
        assert "librarian-hippo.webp" in mascot  # cut-out fallback
        assert "librarian-hippo.glb" in mascot and "MeshoptDecoder" in mascot
        model = (Path(bookcase_pkg.__file__).parent / "librarian-hippo.glb").read_bytes()
        assert model[:4] == b"glTF", "3D librarian is not a binary glTF"
        assert len(model) < 1_500_000, "3D librarian must stay light (shipped in the wheel)"
        for hook in ("bc:search", "bc:fly", "bc:reset-view", "bc:books"):
            assert hook in mascot, f"mascot ignores {hook}"
        assert "bookPoint" in mascot, "lantern cannot settle into his book"
        assert "reducedMotion" in mascot
        main = self._asset("bookcase.js")
        assert "./bookcase-mascot.js" in main and "mascot.hop()" in main
        assert "librarian-hippo.webp" in self._asset("bookcase.css"), "log not signed"


_LAYOUT_PROBE = r"""
import * as L from %(url)s;
const shelves = ["alpha", "beta", "gamma", "delta", "epsilon"];
const rows = shelves.map((shelf, i) => ({
  shelf,
  folders: Array.from({ length: 1 + (i * 3) %% 7 }, (_, j) => ({
    folder: `f${j}`,
    slots: Array.from({ length: 5 + ((i + j) * 37) %% 90 }, (_, k) => ({
      book: { id: `${shelf}/f${j}/${k}`, shelf, folder: `f${j}` }, w: 0.035 + (k %% 5) * 0.01,
    })),
  })),
}));
const plan = L.planSections(rows);
const out = { bays: plan.bays.map((b) => [b.label, b.side]), cases: plan.cases.length,
  overlaps: 0, inNave: 0, split: 0, spawnHit: 0, bad: 0 };
const hit = (a, b) => a.minX < b.maxX && a.maxX > b.minX && a.minZ < b.maxZ && a.maxZ > b.minZ;
plan.cases.forEach((a, i) => {
  if (a.aabb.maxX > -L.NAVE / 2 + 0.01 && a.aabb.minX < L.NAVE / 2 - 0.01) out.inNave += 1;
  plan.cases.slice(i + 1).forEach((b) => { if (hit(a.aabb, b.aabb)) out.overlaps += 1; });
  for (const sh of a.shelves) {
    if (sh.xMax - sh.xMin > L.CASE_W) out.bad += 1;
    for (const sl of sh.slots) if (`${sl.book.shelf}` !== a.bay.replace(/ [IVX]+$/, "")) out.bad += 1;
  }
});
const bayOf = new Map();
for (const c of plan.cases) {
  const key = `${c.bay}|${c.folder}`;
  if (bayOf.has(c.folder + c.bay)) continue;
  bayOf.set(c.folder + c.bay, key);
}
const folderBays = new Map();
for (const c of plan.cases) {
  const k = c.bay.replace(/ [IVX]+$/, "") + "/" + c.folder;
  folderBays.set(k, (folderBays.get(k) || new Set()).add(c.bay));
}
for (const s of folderBays.values()) if (s.size > 1) out.split += 1;
const s = plan.spawn;
for (const c of plan.cases.concat(plan.props.map((a) => ({ aabb: a })))) {
  const a = c.aabb;
  if (s.x > a.minX - 0.35 && s.x < a.maxX + 0.35 && s.z > a.minZ - 0.35 && s.z < a.maxZ + 0.35) out.spawnHit += 1;
}
const d = L.describePlace(-3, -6, 0, 3, "refs", { label: "alpha", ordinal: 2, side: "left" });
out.describe = d.text;
console.log(JSON.stringify(out));
"""


class TestBookcaseFloorPlan:
    """The bay floor plan: shelf → bay off a central nave, folder → case(s)."""

    def test_layout_constants(self):
        import memorius.bookcase as bookcase_pkg

        layout = (Path(bookcase_pkg.__file__).parent / "bookcase-layout.js").read_text()
        for name in ("NAVE", "BAY_BACK", "MAX_SIDE", "FILL_ORDER", "HALL"):
            assert f"export const {name}" in layout, f"layout lacks {name}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to run the ES module")
    def test_plan_geometry(self):
        import json

        import memorius.bookcase as bookcase_pkg

        url = json.dumps((Path(bookcase_pkg.__file__).parent / "bookcase-layout.js").as_uri())
        res = subprocess.run(
            ["node", "--input-type=module", "-e", _LAYOUT_PROBE % {"url": url}],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)
        labels = [b[0] for b in out["bays"]]
        assert labels[:5] == ["alpha", "beta", "gamma", "delta", "epsilon"] or len(labels) >= 5
        sides = [b[1] for b in out["bays"]]
        assert sides[:2] == [-1, 1], "bays must alternate left / right"
        assert out["overlaps"] == 0, "cases intersect"
        assert out["inNave"] == 0, "a case blocks the central nave"
        assert out["split"] == 0, "a folder is split across bays"
        assert out["spawnHit"] == 0, "visitor spawns inside furniture"
        assert out["bad"] == 0, "a book sits in the wrong bay or overflows a plank"
        assert "alpha bay, second on the left" in out["describe"]



_INDEX_PROBE = r"""
const { LibraryIndex } = await import(__URL__);

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = "";
    this.hidden = false;
    this.textContent = "";
    this.classList = {
      _s: new Set(),
      add: (c) => this.classList._s.add(c),
      remove: (c) => this.classList._s.delete(c),
      contains: (c) => this.classList._s.has(c),
      toggle: (c, on) => (on ? this.classList._s.add(c) : this.classList._s.delete(c)),
    };
  }
  append(...kids) { for (const k of kids) this.children.push(k); }
  appendChild(k) { this.children.push(k); return k; }
  set innerHTML(_) { this.children = []; }
  get innerHTML() { return ""; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type, ev) { for (const fn of this.listeners[type] || []) fn(ev || {}); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  focus() { this.focused = true; }
  text() { return this.textContent + this.children.map((c) => c.text()).join(" | "); }
}

const ids = ["bc-index", "bc-index-list", "bc-index-card", "bc-index-btn",
             "bc-index-close", "bc-surprise"];
const els = {};
for (const id of ids) els[id] = new El("button");
els["bc-index"].hidden = true;

globalThis.document = {
  getElementById: (id) => els[id] || null,
  createElement: (tag) => new El(tag),
};
const events = [];
globalThis.window = { dispatchEvent: (e) => { events.push(e); return true; } };
globalThis.CustomEvent = class {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
};

const bays = [
  { label: "alpha", side: -1, ordinal: 1, sideName: "left", center: { x: -3, z: -2 } },
  { label: "beta II", side: 1, ordinal: 2, sideName: "right", center: { x: 3, z: -9 } },
];
const cases = [
  { bay: "alpha", folder: "refs", shelves: [{ slots: [{}, {}] }, { slots: [{}] }] },
  { bay: "alpha", folder: "projects", shelves: [{ slots: [{}] }] },
  { bay: "beta II", folder: "notes", shelves: [{ slots: [{}] }] },
];
const books = [
  { id: "a", shelf: "alpha", folder: "refs", note: "one", createdAt: 1000 },
  { id: "b", shelf: "alpha", folder: "projects", note: "two", createdAt: 3000 },
  { id: "c", shelf: "beta", folder: "notes", note: "three", createdAt: 2000 },
];
const opened = [];
const said = [];
const idx = new LibraryIndex({
  books: () => books,
  plan: () => ({ bays, cases }),
  open: (id) => opened.push(id),
  announce: (t) => said.push(t),
  age: (t) => "aged-" + t,
});

const out = { events: [] };
idx.show();
out.openAfterShow = els["bc-index"].hidden === false;
out.expanded = els["bc-index-btn"].getAttribute("aria-expanded");
const rows = els["bc-index-list"].children;
out.rows = rows.length;
out.rowTags = rows.map((r) => r.tagName);
out.rowTexts = rows.map((r) => r.text());
out.card = els["bc-index-card"].children.map((c) => c.text());
rows[1].fire("click");
const goto = events.find((e) => e.type === "bc:goto");
out.goto = goto ? goto.detail : null;
out.closedAfterWalk = els["bc-index"].hidden;
out.expandedAfterWalk = els["bc-index-btn"].getAttribute("aria-expanded");

const key = (k, target, mods) => ({
  key: k, target: target || { tagName: "BODY" },
  metaKey: !!(mods && mods.meta), ctrlKey: false, altKey: false,
  preventDefault() { this.defaultPrevented = true; },
});
out.iConsumed = idx.handleKey(key("i"));
out.openAfterI = els["bc-index"].hidden === false;
out.escapeConsumed = idx.handleKey(key("Escape"));
out.closedAfterEscape = els["bc-index"].hidden;
out.xConsumed = idx.handleKey(key("x"));
out.ignoredInInput = idx.handleKey(key("i", { tagName: "INPUT" }));
out.ignoredWithMeta = idx.handleKey(key("x", { tagName: "BODY" }, { meta: true }));
idx.surprise();
out.opened = opened;
out.said = said;
out.fly = events.filter((e) => e.type === "bc:fly").length;

// an empty vault must not throw and must say so
const empty = new LibraryIndex({
  books: () => [], plan: () => ({ bays: [], cases: [] }),
  open: () => { throw new Error("opened a book from an empty vault"); },
  announce: (t) => said.push(t), age: (t) => String(t),
});
empty.show();
out.emptyRows = els["bc-index-list"].children.length;
out.emptyCard = els["bc-index-card"].children.length;
empty.surprise();
console.log(JSON.stringify(out));
"""


class TestBookcaseIndex:
    """SG-07: library index panel + "surprise me" (issue #99)."""

    def _asset(self, name: str) -> str:
        import memorius.bookcase as bookcase_pkg

        return (Path(bookcase_pkg.__file__).parent / name).read_text(
            encoding="utf-8"
        )

    def test_index_markup(self):
        html = self._asset("bookcase.html")
        for element_id in (
            "bc-index", "bc-index-btn", "bc-index-list", "bc-index-card",
            "bc-index-close", "bc-surprise",
        ):
            assert f'id="{element_id}"' in html, f"missing #{element_id}"

        # The panel starts closed and the button announces that state.
        assert re.search(r'<aside[^>]*id="bc-index"[^>]*hidden', html), (
            "#bc-index must start hidden"
        )
        button = re.search(r'<button[^>]*id="bc-index-btn"[^>]*>', html)
        assert button, "#bc-index-btn must be a <button>"
        tag = button.group(0)
        assert 'aria-expanded="false"' in tag, tag
        assert 'aria-controls="bc-index"' in tag, tag
        assert re.search(r'<button[^>]*id="bc-surprise"[^>]*>', html)

    def test_index_module_wiring(self):
        index = self._asset("bookcase-index.js")
        for needle in (
            'new CustomEvent("bc:goto"', 'new CustomEvent("bc:fly"',
            "aria-expanded", "handleKey", "bc-index-list", "bc-index-card",
        ):
            assert needle in index, f"bookcase-index.js lacks {needle!r}"
        main = self._asset("bookcase.js")
        assert "./bookcase-index.js" in main, "main module does not import the index"
        assert "handleKey" in main, "main module does not delegate I / X / Esc"

    @pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
    def test_index_behavior(self):
        import json

        import memorius.bookcase as bookcase_pkg

        url = json.dumps(
            (Path(bookcase_pkg.__file__).parent / "bookcase-index.js").as_uri()
        )
        res = subprocess.run(
            ["node", "--input-type=module", "-e", _INDEX_PROBE.replace("__URL__", url)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)

        # the panel opens, announces its state, and lists one row per bay
        assert out["openAfterShow"] is True
        assert out["expanded"] == "true"
        assert out["rows"] == 2
        assert out["rowTags"] == ["BUTTON", "BUTTON"], "rows must be keyboard-activatable"
        alpha, beta = out["rowTexts"]
        assert "alpha" in alpha and "4" in alpha and "2 folders" in alpha, alpha
        assert "beta II" in beta and "1 folder" in beta, beta

        # the library card summarises the vault, oldest → newest
        stats, when = out["card"][:3], out["card"][-1]
        assert "books" in stats[0] and "3" in stats[0], stats
        assert "shelves" in stats[1] and "2" in stats[1], stats
        assert "folders" in stats[2] and "3" in stats[2], stats
        assert "oldest" in when and "newest" in when, when
        assert "aged-1000" in when and "aged-3000" in when, when

        # clicking a bay walks the visitor there, facing into the alcove
        assert out["goto"]["x"] == 3 and out["goto"]["z"] == -9, out["goto"]
        assert out["goto"]["yaw"] < 0, out["goto"]  # beta is on the right
        assert out["closedAfterWalk"] is True
        assert out["expandedAfterWalk"] == "false"

        # keyboard: I toggles, Escape closes, X surprises
        assert out["iConsumed"] is True and out["openAfterI"] is True
        assert out["escapeConsumed"] is True and out["closedAfterEscape"] is True
        assert out["xConsumed"] is True
        assert out["ignoredInInput"] is False, "I must not fire while typing"
        assert out["ignoredWithMeta"] is False, "X must not fire with a modifier"
        assert out["fly"] == 2, "both surprises should fly the camera to a book"
        assert out["opened"] and set(out["opened"]) <= {"a", "b", "c"}
        assert out["said"], "surprises must be announced through the librarian"

        # an empty vault renders a placeholder instead of crashing
        assert out["emptyRows"] == 1
        assert out["emptyCard"] == 4  # three zeroed stats + the date line


_COPY_PROBE = r"""
const { copyText, copyButton } = await import(__URL__);

const out = { exec: null, execResult: true, writes: [], selected: null };

const node = (tag) => ({
  tagName: String(tag).toUpperCase(),
  style: {}, value: "", textContent: "", attrs: {}, listeners: {},
  setAttribute(k, v) { this.attrs[k] = v; },
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
  select() { out.selected = this.value; },
});

globalThis.document = {
  body: { appendChild() {}, removeChild() {} },
  createElement: node,
  execCommand: (cmd) => { out.exec = cmd; return out.execResult; },
};

// 1. modern path: navigator.clipboard.writeText
const setNavigator = (v) => Object.defineProperty(globalThis, "navigator", { value: v, configurable: true });
setNavigator({ clipboard: { writeText: async (v) => out.writes.push(v) } });
out.modern = await copyText("hello memory");
out.empty = await copyText(null);
out.afterEmpty = out.writes.length;

// 2. fallback: clipboard missing → hidden textarea + execCommand
setNavigator({});
out.fallback = await copyText("fallback text");
out.fallbackSelected = out.selected;
out.execResult = false;
out.fallbackFailed = await copyText("nope");

// 3. a button that copies on click and reports the result
out.execResult = true;
setNavigator({ clipboard: { writeText: async (v) => out.writes.push(v) } });
const btn = copyButton(() => "copied payload", 15);
out.tag = btn.tagName;
out.label = btn.textContent;
btn.listeners.click[0]();
await new Promise((r) => setTimeout(r, 5));
out.after = btn.textContent;
out.selected = out.selected;
await new Promise((r) => setTimeout(r, 30));
out.restored = btn.textContent;
out.payload = out.writes[out.writes.length - 1];
console.log(JSON.stringify(out));
"""


class TestBookcaseCopy:
    """SG-07: Copy memory — clipboard with a fallback (issue #99)."""

    def _asset(self, name: str) -> str:
        import memorius.bookcase as bookcase_pkg

        return (Path(bookcase_pkg.__file__).parent / name).read_text(
            encoding="utf-8"
        )

    def test_copy_module_wiring(self):
        main = self._asset("bookcase.js")
        assert "./bookcase-copy.js" in main, "openBook does not import the copy helper"
        assert "copyButton(" in main, "the detail panel has no Copy button"
        assert "bookcase-copy.js" in REQUIRED_ASSETS

    @pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
    def test_copy_behavior(self):
        import json

        import memorius.bookcase as bookcase_pkg

        url = json.dumps(
            (Path(bookcase_pkg.__file__).parent / "bookcase-copy.js").as_uri()
        )
        res = subprocess.run(
            ["node", "--input-type=module", "-e", _COPY_PROBE.replace("__URL__", url)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)

        assert out["modern"] is True
        assert out["writes"][0] == "hello memory"
        assert out["empty"] is True and out["afterEmpty"] == 2

        assert out["fallback"] is True and out["exec"] == "copy"
        assert out["fallbackSelected"] == "fallback text", "fallback must copy the textarea value"
        assert out["fallbackFailed"] is False

        assert out["tag"] == "BUTTON"
        assert out["label"] == "Copy"
        assert out["after"] == "Copied"
        assert out["payload"] == "copied payload"
        assert out["restored"] == "Copy", "the label must reset after the flash"
