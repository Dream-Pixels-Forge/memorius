/* bookcase-scene.js — Three.js walkable vault library: bookcase rows with
 * walkable aisles, one upright book per memory. First-person controls come
 * from bookcase-walk.js; the floor plan (cases, shelves, spawn) from
 * bookcase-layout.js. Spine label = truncated shelf/folder/note path;
 * thickness ∝ content length (clamped); colour = recency (deep amber →
 * accent orange). Consumes "bc:books" / "bc:layout" / "bc:search" /
 * "bc:reset-view" events, emits "bc:book-hover" / "bc:book-click", and
 * exposes window.__bookcase (sections / cases / auditBooks / cam) for
 * headless verification.
 */
import * as THREE from "three";
import { WalkControls } from "./bookcase-walk.js";
import {
  planSections, caseHeight, EYE_Y, FLOOR_Y, BOOK_H, BOOK_D, MIN_W, MAX_W,
  SHELF_T, SHELF_SPACING, CASE_W, CASE_D,
} from "./bookcase-layout.js";

const OLD_COLOR = new THREE.Color("#5b3a1c");
const NEW_COLOR = new THREE.Color("#f97316");
const WOOD_DARK = 0x3a2a18;

export class BookcaseScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#0d0b09");
    this.scene.fog = new THREE.Fog("#0d0b09", 8, 60);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.05, 400);
    this.camera.position.set(0, EYE_Y, 3.2);

    this.scene.add(new THREE.AmbientLight(0x8a7a66, 0.85));

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400),
      new THREE.MeshLambertMaterial({ color: 0x1c140c })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = FLOOR_Y;
    this.scene.add(floor);

    this.bookGroup = new THREE.Group();
    this.scene.add(this.bookGroup);
    this.furniture = new THREE.Group();
    this.scene.add(this.furniture);

    this.walk = new WalkControls(this.camera, canvas, { eyeY: EYE_Y, speed: 2.4 });
    this.walk.sync(0, 0); // face the first row (-Z)

    this.byBook = new Map();
    this.books = [];
    this.layout = "shelf";
    this.marked = new Set();
    this.topId = null;
    this._flight = null;
    this._hovered = null;
    this._cases = [];
    this._audit = [];
    this._spawn = { x: 0, y: EYE_Y, z: 3.2 };
    this._built = false;

    this.raycaster = new THREE.Raycaster();
    this._ndc = new THREE.Vector2();
    this._recents = { min: 0, max: 1 };
    this._events = [];

    this._onPointerDown = (e) => this._downAt(e);
    this._onPointerMove = (e) => this._hover(e);
    this._onClick = (e) => this._click(e);
    this._onResize = () => this._resize();
    canvas.addEventListener("pointerdown", this._onPointerDown);
    canvas.addEventListener("pointermove", this._onPointerMove);
    canvas.addEventListener("click", this._onClick);
    window.addEventListener("resize", this._onResize);
    this._on("bc:books", (e) => this.setBooks(e.detail.books, e.detail.layout, e.detail.vaultLabel));
    this._on("bc:layout", (e) => this.relayout(e.detail.layout));
    this._on("bc:search", (e) => {
      this.markResults(e.detail.ids || [], e.detail.topId);
      if (e.detail.topId) this.flyTo(e.detail.topId);
    });
    this._on("bc:reset-view", () => this.resetView());

    // headless-verification debug hook
    window.__bookcase = {
      sections: () => this._cases.length,
      cases: () => this._cases.map((c) => c.label),
      auditBooks: () => this.auditBooks(),
      collides: (x, z) => this.walk.collides(x, z),
      cam: () => ({
        x: this.camera.position.x,
        y: this.camera.position.y,
        z: this.camera.position.z,
      }),
    };

    this._resize();
    const clock = new THREE.Clock();
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      this._step(clock.getElapsedTime());
    };
    loop();
  }

  _on(type, fn) {
    window.addEventListener(type, fn);
    this._events.push([type, fn]);
  }

  _resize() {
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  /* ── build ─────────────────────────────────────────────────── */
  setBooks(books, layout, vaultLabel) {
    this.books = books || [];
    this.layout = layout || "shelf";
    this.vaultLabel = vaultLabel || "";
    this._rebuild();
  }

  relayout(layout) {
    if (layout) this.layout = layout;
    this._rebuild();
  }

  _bookWidth(book) {
    // thickness ∝ log of content length, clamped to a hand-sized span
    return THREE.MathUtils.clamp(
      MIN_W + 0.012 * Math.log2(1 + (book.contentLen || 0) / 16), MIN_W, MAX_W);
  }

  _recencyT(book) {
    const { min, max } = this._recents;
    const t = Number(book.createdAt) || 0;
    return max === min ? 0.5 : (t - min) / (max - min);
  }

  _rebuild() {
    this._clear();
    this._flight = null;
    this.walk.enabled = true;
    const times = this.books.map((b) => Number(b.createdAt) || 0);
    this._recents = {
      min: times.length ? Math.min(...times) : 0,
      max: times.length ? Math.max(...times) : 1,
    };
    const rows = this._groupRows(this._sortForLayout(this.books));
    const plan = planSections(rows);
    this._spawn = plan.spawn;
    this._cases = plan.cases;
    plan.cases.forEach((c) => this._buildCase(c));
    this._lightRows();
    const colliders = plan.cases.map((c) => c.aabb);
    this.walk.setColliders(colliders);
    if (!this._built || this.walk.collides(this.camera.position.x, this.camera.position.z)) {
      // first build, or the rebuild left the camera inside a case → respawn
      this._built = true;
      this.camera.position.set(plan.spawn.x, plan.spawn.y, plan.spawn.z);
      this.walk.sync(0, 0);
    }
  }

  _clear() {
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.byBook.clear();
    this.marked.clear();
    this.topId = null;
    this._audit = [];
  }

  _disposeGroup(group) {
    for (const child of group.children) {
      child.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of mats) {
            if (m.map) m.map.dispose();
            m.dispose();
          }
        }
      });
      group.remove(child);
    }
  }

  _sortForLayout(books) {
    const list = books.slice();
    if (this.layout === "recency") {
      // newest first within each shelf
      list.sort((a, b) => (Number(b.createdAt) || 0) - (Number(a.createdAt) || 0));
    } else {
      list.sort((a, b) => (a.path || "").localeCompare(b.path || ""));
    }
    return list;
  }

  _groupRows(books) {
    const byShelf = new Map();
    for (const book of books) {
      const key = book.shelf || "default";
      if (!byShelf.has(key)) byShelf.set(key, []);
      byShelf.get(key).push(book);
    }
    return [...byShelf].map(([shelf, list]) => ({
      shelf,
      slots: list.map((book) => ({ book, w: this._bookWidth(book) })),
    }));
  }

  /* One bookcase unit: plinth, sides, top, backboard, planks, books, label. */
  _buildCase(c) {
    const caseH = caseHeight();
    const wood = new THREE.MeshLambertMaterial({ color: WOOD_DARK });
    const add = (geo, mat, x, y, z) => {
      const m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      this.furniture.add(m);
      return m;
    };
    // plinth + sides + top + backboard
    add(new THREE.BoxGeometry(CASE_W + 0.1, 0.15, CASE_D), wood,
      c.x, 0.075, c.z);
    add(new THREE.BoxGeometry(0.05, caseH, CASE_D), wood,
      c.x - (CASE_W / 2 + 0.025), caseH / 2, c.z);
    add(new THREE.BoxGeometry(0.05, caseH, CASE_D), wood,
      c.x + (CASE_W / 2 + 0.025), caseH / 2, c.z);
    add(new THREE.BoxGeometry(CASE_W + 0.1, 0.05, CASE_D), wood,
      c.x, caseH + 0.025, c.z);
    add(new THREE.BoxGeometry(CASE_W + 0.1, caseH, 0.02), wood,
      c.x, caseH / 2, c.z - CASE_D / 2 + 0.01);

    // aisle-side warm light every other row is added by _lightRows()
    for (const shelf of c.shelves) {
      add(new THREE.BoxGeometry(CASE_W, SHELF_T, CASE_D - 0.04), wood,
        c.x, shelf.y - SHELF_T / 2, c.z);
      for (const slot of shelf.slots) {
        const book = slot.book;
        const mesh = this._makeBookMesh(book, slot.w);
        const bz = c.z + CASE_D / 2 - BOOK_D / 2 - 0.02;
        const by = shelf.y + (BOOK_H * mesh.scale.y) / 2;
        mesh.position.set(c.x + slot.dx + slot.w / 2, by, bz);
        mesh.userData = {
          id: book.id,
          label: book.path || book.note || book.id,
          book,
        };
        this.bookGroup.add(mesh);
        this.byBook.set(book.id, mesh);
        this._audit.push({ mesh, y: shelf.y, xMin: shelf.xMin, xMax: shelf.xMax, z: bz });
      }
    }

    this.furniture.add(this._makeLabelSprite(c.label, c.x, caseH + 0.4, c.z));
  }

  /* Warm point lights over the first rows so distant aisles stay lit. */
  _lightRows() {
    const seen = new Set();
    let added = 0;
    for (const c of this._cases) {
      if (added >= 6 || seen.has(c.z)) continue;
      seen.add(c.z);
      const light = new THREE.PointLight(0xffd9a0, 14, 0, 2);
      light.position.set(0, 2.6, c.z + 1.1);
      this.furniture.add(light);
      added += 1;
    }
  }

  _makeBookMesh(book, w) {
    const t = Math.max(0, Math.min(1, this._recencyT(book)));
    const color = OLD_COLOR.clone().lerp(NEW_COLOR, 0.25 + 0.75 * t);
    const side = new THREE.MeshLambertMaterial({ color });
    const front = new THREE.MeshLambertMaterial({ map: this._makeSpineTexture(book, color) });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, BOOK_H, BOOK_D),
      [side, side, side, side, front, side]);
    // deterministic tiny height jitter so rows look organic
    const idStr = String(book.id || "");
    mesh.scale.y = 1 + 0.05 * ((idStr.length * 31) % 7) / 7;
    return mesh;
  }

  _makeSpineTexture(book, color) {
    const c = document.createElement("canvas");
    c.width = 64;
    c.height = 160;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#" + color.getHexString();
    ctx.fillRect(0, 0, 64, 160);
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(0, 0, 64, 6);
    ctx.fillRect(0, 154, 64, 6);
    ctx.fillStyle = "#f5efe6";
    ctx.font = "11px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.translate(32, 80);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText((book.path || book.note || book.id || "").slice(0, 18), 0, 4);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  _makeLabelSprite(text, x, y, z) {
    const c = document.createElement("canvas");
    c.width = 512;
    c.height = 128;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "rgba(13,11,9,0.78)";
    ctx.fillRect(0, 0, 512, 128);
    ctx.strokeStyle = "rgba(249,115,22,0.85)";
    ctx.lineWidth = 6;
    ctx.strokeRect(3, 3, 506, 122);
    ctx.fillStyle = "#f5efe6";
    ctx.font = "bold 56px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(text).slice(0, 22), 256, 68);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
    sprite.scale.set(2.2, 0.55, 1);
    sprite.position.set(x, y, z);
    return sprite;
  }

  /* ── book-arrangement audit (headless verification) ────────── */
  auditBooks() {
    let misplaced = 0;
    for (const a of this._audit) {
      const p = a.mesh.position;
      const half = (BOOK_H * a.mesh.scale.y) / 2;
      const bottom = p.y - half;
      const top = p.y + half;
      const rests = Math.abs(bottom - a.y) <= 0.02;
      const fits = top <= a.y + SHELF_SPACING - 0.01;
      const inX = p.x >= a.xMin - 0.01 && p.x <= a.xMax + 0.01;
      const inZ = Math.abs(p.z - a.z) <= 0.02;
      if (!(rests && fits && inX && inZ)) misplaced += 1;
    }
    return { total: this._audit.length, misplaced, ok: !misplaced && this._audit.length > 0 };
  }

  /* ── search marks + camera flight ──────────────────────────── */
  markResults(ids, topId) {
    this.marked = new Set(ids || []);
    this.topId = topId || null;
    for (const [id, mesh] of this.byBook) {
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      const c = this.marked.has(id) ? new THREE.Color("#3d1d08") : new THREE.Color(0x000000);
      for (const m of mats) if (m.emissive) m.emissive = c.clone();
    }
  }

  clearMarks() {
    this.markResults([], null);
  }

  /* Stand in the aisle in front of the book and look at it. */
  flyTo(id) {
    const mesh = this.byBook.get(id);
    if (!mesh) return;
    // stand in the aisle directly in front: straight-on view, slight tilt down
    const p = mesh.position;
    this._startFlight(
      new THREE.Vector3(p.x, EYE_Y, p.z + 0.9),
      0, // dir = (0, dy, -0.9) → facing -Z
      Math.atan2(p.y - EYE_Y, 0.9),
      0.9
    );
  }

  resetView() {
    this._startFlight(new THREE.Vector3(this._spawn.x, EYE_Y, this._spawn.z), 0, 0, 0.9);
  }

  _startFlight(toPos, toYaw, toPitch, dur) {
    const fromYaw = this.walk.yaw;
    let d = (toYaw - fromYaw) % (2 * Math.PI);
    if (d > Math.PI) d -= 2 * Math.PI;
    if (d < -Math.PI) d += 2 * Math.PI;
    this._flight = {
      t: 0,
      dur,
      fromPos: this.camera.position.clone(),
      toPos,
      fromYaw,
      toYaw: fromYaw + d,
      fromPitch: this.walk.pitch,
      toPitch,
    };
    this.walk.enabled = false;
  }

  /* ── interaction ───────────────────────────────────────────── */
  _downAt(e) {
    this._downX = e.clientX;
    this._downY = e.clientY;
  }

  _hover(e) {
    const rect = this.canvas.getBoundingClientRect();
    this._ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this._ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this._ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.bookGroup.children, false)[0];
    const id = hit ? hit.object.userData.id : null;
    const mesh = id ? this.byBook.get(id) : null;
    this._hovered = id;
    window.dispatchEvent(new CustomEvent("bc:book-hover", {
      detail: {
        id,
        x: e.clientX,
        y: e.clientY,
        label: mesh ? mesh.userData.label : "",
      },
    }));
  }

  _click(e) {
    // ignore clicks that were actually look-drags
    const dx = e.clientX - (this._downX ?? e.clientX);
    const dy = e.clientY - (this._downY ?? e.clientY);
    if (Math.hypot(dx, dy) > 6) return;
    const rect = this.canvas.getBoundingClientRect();
    this._ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this._ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this._ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.bookGroup.children, false)[0];
    if (hit) {
      window.dispatchEvent(new CustomEvent("bc:book-click", {
        detail: { id: hit.object.userData.id },
      }));
    } else {
      this.walk.requestLock(); // empty click grabs mouse-look
    }
  }

  /* ── animation loop ────────────────────────────────────────── */
  _step(t) {
    const dt = this._lastT ? Math.min(0.1, t - this._lastT) : 0.016;
    this._lastT = t;

    const f = this._flight;
    if (f) {
      f.t += dt;
      const k = Math.min(1, f.t / f.dur);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      this.camera.position.lerpVectors(f.fromPos, f.toPos, e);
      this.walk.yaw = f.fromYaw + (f.toYaw - f.fromYaw) * e;
      this.walk.pitch = f.fromPitch + (f.toPitch - f.fromPitch) * e;
      this.walk._apply();
      if (k >= 1) {
        this._flight = null;
        this.walk.enabled = true;
        this.walk.sync(f.toYaw, f.toPitch);
      }
    } else {
      this.walk.update(dt);
    }

    if (this.topId && this.byBook.has(this.topId)) {
      const mesh = this.byBook.get(this.topId);
      const s = 1 + 0.14 * Math.abs(Math.sin(t * 3));
      mesh.scale.x = s;
      mesh.scale.z = s;
    }

    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    for (const [type, fn] of this._events) window.removeEventListener(type, fn);
    this.canvas.removeEventListener("pointerdown", this._onPointerDown);
    this.canvas.removeEventListener("pointermove", this._onPointerMove);
    this.canvas.removeEventListener("click", this._onClick);
    window.removeEventListener("resize", this._onResize);
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.walk.dispose();
    delete window.__bookcase;
    this.renderer.dispose();
  }
}
