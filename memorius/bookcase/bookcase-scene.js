/* bookcase-scene.js — Three.js 3D bookcase: one row per shelf, one book
 * per memory. Spine label = truncated shelf/folder/note path; thickness ∝
 * content length (clamped); colour = recency (deep amber → accent orange).
 * Consumes "bc:books" / "bc:layout" / "bc:search" / "bc:reset-view" events,
 * emits "bc:book-hover" / "bc:book-click" on window.
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const ROW_GAP = 2.4;
const BOOK_H = 1.5;
const BOOK_D = 1.1;
const MIN_W = 0.16;
const MAX_W = 0.62;
const GAP = 0.05;
const OLD_COLOR = new THREE.Color("#5b3a1c");
const NEW_COLOR = new THREE.Color("#f97316");
const HOME_POS = new THREE.Vector3(0, 4, 26);
const HOME_TGT = new THREE.Vector3(0, 2, 0);

export class BookcaseScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#0d0b09");
    this.scene.fog = new THREE.Fog("#0d0b09", 40, 120);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 400);
    this.camera.position.copy(HOME_POS);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.target.copy(HOME_TGT);
    this.controls.minDistance = 3;
    this.controls.maxDistance = 90;

    this.scene.add(new THREE.AmbientLight(0x8a7a66, 0.9));
    const warm = new THREE.PointLight(0xffd9a0, 60, 0, 2);
    warm.position.set(10, 14, 16);
    this.scene.add(warm);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.MeshLambertMaterial({ color: 0x14100c })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.2;
    this.scene.add(floor);

    this.bookGroup = new THREE.Group();
    this.scene.add(this.bookGroup);
    this.furniture = new THREE.Group();
    this.scene.add(this.furniture);

    this.byBook = new Map();
    this.books = [];
    this.layout = "shelf";
    this.marked = new Set();
    this.topId = null;
    this._flight = null;
    this._hovered = null;

    this.raycaster = new THREE.Raycaster();
    this._ndc = new THREE.Vector2();
    this._recents = { min: 0, max: 1 };
    this._events = [];

    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("click", (e) => this._onClick(e));
    window.addEventListener("resize", () => this._resize());
    this._on("bc:books", (e) => this.setBooks(e.detail.books, e.detail.layout, e.detail.vaultLabel));
    this._on("bc:layout", (e) => this.relayout(e.detail.layout));
    this._on("bc:search", (e) => {
      this.markResults(e.detail.ids || [], e.detail.topId);
      if (e.detail.topId) this.flyTo(e.detail.topId);
    });
    this._on("bc:reset-view", () => this.resetView());

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
    // thickness ∝ log of content length, clamped (spec)
    return THREE.MathUtils.clamp(
      MIN_W + 0.05 * Math.log2(1 + (book.contentLen || 0) / 16),
      MIN_W, MAX_W
    );
  }

  _recencyT(book) {
    const { min, max } = this._recents;
    const t = Number(book.createdAt) || 0;
    return max === min ? 0.5 : (t - min) / (max - min);
  }

  _rebuild() {
    this._clear();
    const times = this.books.map((b) => Number(b.createdAt) || 0);
    this._recents = {
      min: times.length ? Math.min(...times) : 0,
      max: times.length ? Math.max(...times) : 1,
    };
    const rows = this._groupRows(this._sortForLayout(this.books));
    rows.forEach((row, i) => this._buildRow(row, i * ROW_GAP));
    this._frameCase(rows);
  }

  _clear() {
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.byBook.clear();
    this.marked.clear();
    this.topId = null;
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
      // newest on the left within each row
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
    return Array.from(byShelf.entries()).map(([shelf, booksInRow]) => ({
      shelf,
      slots: booksInRow.map((book) => ({ book, w: this._bookWidth(book) })),
    }));
  }

  _buildRow(row, rowY) {
    const rowWidth = row.slots.reduce((a, s) => a + s.w + GAP, 0);
    this._addPlank(rowWidth, rowY, row.shelf);
    let x = -rowWidth / 2;
    for (const slot of row.slots) {
      const book = slot.book;
      const y = rowY + BOOK_H / 2 + 0.06;
      const mesh = this._makeBookMesh(book, slot.w);
      mesh.position.set(x + slot.w / 2, y, 0);
      mesh.userData = {
        id: book.id,
        label: book.path || book.note || book.id,
        book,
      };
      this.bookGroup.add(mesh);
      this.byBook.set(book.id, mesh);
      x += slot.w + GAP;
    }
  }

  _addPlank(width, rowY, shelfName) {
    const plank = new THREE.Mesh(
      new THREE.BoxGeometry(width + 0.8, 0.08, BOOK_D + 0.4),
      new THREE.MeshLambertMaterial({ color: 0x3a2a18 })
    );
    plank.position.set(0, rowY - 0.04, 0);
    this.furniture.add(plank);
    const plate = this._textPlate(shelfName);
    plate.position.set(-(width / 2 + 1.4), rowY + 0.5, 0.4);
    this.furniture.add(plate);
  }

  _frameCase(rows) {
    if (!rows.length) return;
    const topY = (rows.length - 1) * ROW_GAP;
    this.flyToDefaults(topY);
  }

  _makeBookMesh(book, w) {
    const t = Math.max(0, Math.min(1, this._recencyT(book)));
    const color = OLD_COLOR.clone().lerp(NEW_COLOR, 0.25 + 0.75 * t);
    const side = new THREE.MeshLambertMaterial({ color });
    const front = new THREE.MeshLambertMaterial({
      map: this._makeSpineTexture(book, color),
    });
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

  _textPlate(text) {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 64;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "rgba(249,115,22,0.9)";
    ctx.font = "bold 26px ui-monospace, monospace";
    ctx.fillText(String(text).slice(0, 12), 12, 42);
    const tex = new THREE.CanvasTexture(c);
    return new THREE.Mesh(
      new THREE.PlaneGeometry(1.8, 0.45),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true })
    );
  }

  /* ── search marks + camera flight ──────────────────────────── */
  markResults(ids, topId) {
    for (const mesh of this.bookGroup.children) {
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats) m.emissive = m.emissive || new THREE.Color(0x000000);
    }
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

  flyTo(id) {
    const mesh = this.byBook.get(id);
    if (!mesh) return;
    const target = mesh.position.clone();
    this._startFlight(
      target.clone().add(new THREE.Vector3(0, 0.25, 3.6)), target, 0.9
    );
  }

  resetView() {
    this._startFlight(HOME_POS.clone(), HOME_TGT.clone(), 0.9);
  }

  flyToDefaults(topY) {
    const tgt = new THREE.Vector3(0, topY / 2, 0);
    const dist = Math.max(14, 10 + topY * 0.9);
    this._startFlight(new THREE.Vector3(0, tgt.y + 2, dist), tgt, 1.1);
  }

  _startFlight(toPos, toTgt, dur) {
    this._flight = {
      t: 0,
      dur,
      fromPos: this.camera.position.clone(),
      toPos,
      fromTgt: this.controls.target.clone(),
      toTgt: toTgt,
    };
  }

  /* ── interaction ───────────────────────────────────────────── */
  _onPointerDown(e) {
    this._downX = e.clientX;
    this._downY = e.clientY;
  }

  _onPointerMove(e) {
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

  _onClick(e) {
    // ignore clicks that were actually orbit drags
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
      this.controls.target.lerpVectors(f.fromTgt, f.toTgt, e);
      if (k >= 1) this._flight = null;
    }

    if (this.topId && this.byBook.has(this.topId)) {
      const mesh = this.byBook.get(this.topId);
      const s = 1 + 0.14 * Math.abs(Math.sin(t * 3));
      mesh.scale.x = s;
      mesh.scale.z = s;
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    for (const [type, fn] of this._events) window.removeEventListener(type, fn);
    this.canvas.removeEventListener("pointermove", this._onPointerMove);
    this.canvas.removeEventListener("click", this._onClick);
    window.removeEventListener("resize", this._resize);
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.controls.dispose();
    this.renderer.dispose();
  }
}



