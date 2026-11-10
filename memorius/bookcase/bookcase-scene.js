/* bookcase-scene.js — Three.js walkable vault library: walnut bookcases in
 * rows with walkable aisles, one upright cloth-bound book per memory.
 * Spine = gilt title (note name) + folder plate; thickness ∝ content length
 * (clamped); hue = folder, brightness/gilt = recency; tops and fore-edges
 * show the page block. Search hits physically slide out of the shelf (the
 * top hit furthest, haloed in orange) and an opened book is drawn out
 * toward you. Light/air: bookcase-atmosphere.js. Lantern + crane camera:
 * bookcase-guide.js. Walk controls: bookcase-walk.js. Floor plan:
 * bookcase-layout.js. Consumes "bc:books" / "bc:layout" / "bc:search" /
 * "bc:reset-view" / "bc:open" / "bc:goto"; emits "bc:book-hover" /
 * "bc:book-click" / "bc:cinema" / "bc:locked"; exposes window.__bookcase
 * (sections / cases / auditBooks / cam / describe …) for headless checks.
 */
import * as THREE from "three";
import { WalkControls } from "./bookcase-walk.js";
import { Atmosphere } from "./bookcase-atmosphere.js";
import { Guide } from "./bookcase-guide.js";
import { CaseBuilder } from "./bookcase-cases.js";
import {
  planSections, caseHeight, EYE_Y, BOOK_H, BOOK_D, MIN_W, MAX_W, SHELF_SPACING, describePlace,
} from "./bookcase-layout.js";

const PULL_HIT = 0.05; // how far search hits slide out (m)
const PULL_TOP = 0.11;
const PULL_OPEN = 0.15;
const ACCENT = new THREE.Color("#f97316");
const FRESH = new THREE.Color("#ffb46a").multiplyScalar(0.07); // recency glow

export class BookcaseScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.reducedMotion = !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(52, 1, 0.05, 400);
    this.camera.position.set(0, EYE_Y, 6.4);
    this.atmosphere = new Atmosphere(this.scene, { reducedMotion: this.reducedMotion });

    this.bookGroup = new THREE.Group();
    this.furniture = new THREE.Group();
    this.scene.add(this.bookGroup, this.furniture);
    this.builder = new CaseBuilder();
    this._meshes = []; // every pickable book (shelves + new-arrivals table)
    this._halo = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({
      color: ACCENT, transparent: true, opacity: 0.0, side: THREE.BackSide,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    this._halo.visible = false;
    this.scene.add(this._halo);

    this.walk = new WalkControls(this.camera, canvas, {
      eyeY: EYE_Y, speed: 2.4, bob: !this.reducedMotion,
    });
    this.walk.sync(0, 0); // face the first row (-Z)
    this.guide = new Guide(this.scene, this.camera, this.walk, {
      reducedMotion: this.reducedMotion,
      onCinema: (on) => window.dispatchEvent(new CustomEvent("bc:cinema", { detail: { on } })),
    });

    this.byBook = new Map();
    this.books = [];
    this.layout = "shelf";
    this.marked = new Set();
    this.topId = null;
    this.openId = null;
    this._pull = new Map(); // mesh → current pull-out
    this._cases = [];
    this._audit = [];
    this._spawn = { x: 0, y: EYE_Y, z: 6.4 };
    this._plan = null;
    this._recent = new Set(); // newest books, lit when layout = "recency"
    this._built = false;
    this.onFrame = null;
    this.frameBias = new THREE.Vector3(); // shifts arrival framing (two-shot with the librarian)
    this.framePartnerY = null; // height of whoever shares the shot (his book)

    this.raycaster = new THREE.Raycaster();
    this._ndc = new THREE.Vector2();
    this._recents = { min: 0, max: 1 };
    this._events = [];
    this._hoverT = 0;

    this._onPointerDown = (e) => this._downAt(e);
    this._onPointerMove = (e) => { if (!this._locked()) this._hover(e.clientX, e.clientY); };
    this._onClick = (e) => this._click(e);
    this._onResize = () => this._resize();
    this._onLock = () => window.dispatchEvent(new CustomEvent("bc:locked", {
      detail: { locked: this._locked() },
    }));
    canvas.addEventListener("pointerdown", this._onPointerDown);
    canvas.addEventListener("pointermove", this._onPointerMove);
    canvas.addEventListener("click", this._onClick);
    window.addEventListener("resize", this._onResize);
    document.addEventListener("pointerlockchange", this._onLock);
    this._on("bc:books", (e) => this.setBooks(e.detail.books, e.detail.layout, e.detail.vaultLabel));
    this._on("bc:layout", (e) => this.relayout(e.detail.layout));
    this._on("bc:search", (e) => {
      this.markResults(e.detail.ids || [], e.detail.topId);
      if (e.detail.topId) this.flyTo(e.detail.topId);
    });
    this._on("bc:reset-view", () => this.resetView());
    this._on("bc:open", (e) => this.open(e.detail.id));
    this._on("bc:fly", (e) => this.flyTo(e.detail.id));
    this._on("bc:goto", (e) => this.goto(e.detail.x, e.detail.z));
    this._on("keydown", (e) => { if (e.code === "Escape" || e.code === "Space") this.guide.cancel(); });

    // headless-verification debug hook
    window.__bookcase = {
      sections: () => this._cases.length,
      cases: () => this._cases.map((c) => c.label),
      bays: () => (this._plan ? this._plan.bays.map((b) => b.label) : []),
      plan: () => this._plan,
      auditBooks: () => this.auditBooks(),
      collides: (x, z) => this.walk.collides(x, z),
      describe: (id) => this.describe(id),
      cinema: () => this.guide.active,
      lantern: () => this.guide.lantern.position.clone(),
      cam: () => ({ x: this.camera.position.x, y: this.camera.position.y, z: this.camera.position.z }),
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

  _locked() {
    return document.pointerLockElement === this.canvas;
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

  /* Positions are stable: switching layout never moves a book. "recency"
   * lights the newest books and leans them forward instead. */
  relayout(layout) {
    if (layout) this.layout = layout;
    this.markResults([...this.marked], this.topId);
  }

  _bookWidth(book) {
    // thickness ∝ log of content length, clamped to a hand-sized span
    return THREE.MathUtils.clamp(
      MIN_W + 0.012 * Math.log2(1 + (book.contentLen || 0) / 16), MIN_W, MAX_W);
  }

  _recencyT(book) {
    const { min, max } = this._recents;
    const t = Number(book.createdAt) || 0;
    return max === min ? 0.5 : THREE.MathUtils.clamp((t - min) / (max - min), 0, 1);
  }

  _rebuild() {
    this._clear();
    this.guide.cancel();
    const times = this.books.map((b) => Number(b.createdAt) || 0);
    this._recents = {
      min: times.length ? Math.min(...times) : 0,
      max: times.length ? Math.max(...times) : 1,
    };
    this.builder.recencyT = (b) => this._recencyT(b);
    const plan = planSections(this._groupRows(this.books));
    this._plan = plan;
    this._spawn = plan.spawn;
    this._cases = plan.cases;
    for (const c of plan.cases) {
      const { group, books } = this.builder.buildCase(c);
      this.furniture.add(group);
      for (const { mesh, book, shelf, homeZ } of books) {
        mesh.userData = {
          id: book.id, label: book.path || book.note || book.id, book, homeZ,
          level: shelf.level, caseLabel: c.label,
          bay: { label: c.bay, ordinal: c.bayOrdinal, side: c.baySide },
        };
        this.byBook.set(book.id, mesh);
        this._meshes.push(mesh);
        this._audit.push({ mesh, y: shelf.y, xMin: shelf.xMin, xMax: shelf.xMax, z: homeZ });
      }
    }
    for (const geo of plan.bays) this.furniture.add(this.builder.baySign(geo));
    const newest = this.books.slice()
      .sort((a, b) => (Number(b.createdAt) || 0) - (Number(a.createdAt) || 0));
    this._recent = new Set(newest.slice(0, Math.max(1, Math.ceil(newest.length * 0.08))).map((b) => b.id));
    const table = this.builder.arrivals(plan.table, newest.slice(0, 12));
    this.furniture.add(table.group);
    for (const m of table.meshes) {
      const book = newest[table.meshes.indexOf(m)];
      m.userData = { id: book.id, label: `new · ${book.path || book.note}`, book, arrival: true };
      this._meshes.push(m);
    }
    this.atmosphere.build(plan, caseHeight());
    this.walk.setColliders(plan.cases.map((c) => c.aabb).concat(plan.props));
    this.relayout();
    if (!this._built || this.walk.collides(this.camera.position.x, this.camera.position.z)) {
      // first build, or the rebuild left the camera inside a case → respawn
      const first = !this._built;
      this._built = true;
      this.camera.position.set(plan.spawn.x, plan.spawn.y, plan.spawn.z);
      this.walk.sync(0, 0);
      if (first && plan.cases.length) this.guide.establishing(plan.spawn, this._center());
    }
  }

  _center() {
    const b = this._plan && this._plan.bounds;
    return b ? { x: (b.minX + b.maxX) / 2, z: (b.minZ + b.maxZ) / 2 } : { x: 0, z: 0 };
  }

  _clear() {
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.byBook.clear();
    this._pull.clear();
    this.marked.clear();
    this.topId = null;
    this.openId = null;
    this._halo.visible = false;
    this._audit = [];
    this._meshes = [];
  }

  _disposeGroup(group) {
    for (const child of [...group.children]) {
      child.traverse((o) => {
        const shared = (x) => this.builder.isShared(x);
        if (o.geometry && !shared(o.geometry)) o.geometry.dispose();
        const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
        for (const m of mats) {
          if (shared(m)) continue;
          if (m.map && !shared(m.map)) m.map.dispose();
          m.dispose();
        }
      });
      group.remove(child);
    }
  }

  /* shelf → folder → books, all by name (stable, date-independent). */
  _groupRows(books) {
    const list = books.slice().sort((a, b) => (a.path || "").localeCompare(b.path || ""));
    const shelves = new Map();
    for (const book of list) {
      const sh = book.shelf || "default";
      const fo = book.folder || "default";
      if (!shelves.has(sh)) shelves.set(sh, new Map());
      const folders = shelves.get(sh);
      if (!folders.has(fo)) folders.set(fo, []);
      folders.get(fo).push({ book, w: this._bookWidth(book) });
    }
    return [...shelves].map(([shelf, folders]) => ({
      shelf, folders: [...folders].map(([folder, slots]) => ({ folder, slots })),
    }));
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
      // home slot (search hits may be temporarily slid out toward the aisle)
      const inZ = Math.abs(a.mesh.userData.homeZ - a.z) <= 0.02 && p.z - a.z <= PULL_OPEN + 0.02;
      if (!(rests && fits && inX && inZ)) misplaced += 1;
    }
    return { total: this._audit.length, misplaced, ok: !misplaced && this._audit.length > 0 };
  }

  /* ── search marks, open book, directions ───────────────────── */
  markResults(ids, topId) {
    this.marked = new Set(ids || []);
    this.topId = topId || null;
    const recency = this.layout === "recency";
    for (const [id, mesh] of this.byBook) {
      const on = this.marked.has(id);
      const fresh = recency && this._recent.has(id);
      const glow = on ? ACCENT.clone().multiplyScalar(id === topId ? 0.12 : 0.06)
        : fresh ? FRESH.clone() : new THREE.Color(0);
      mesh.material[0].emissive.copy(glow);
      mesh.material[4].emissive.copy(glow);
      if (on || fresh || this._pull.has(mesh)) this._pull.set(mesh, this._pull.get(mesh) || 0);
    }
    this._halo.visible = !!(topId && this.byBook.has(topId));
    if (!this.marked.size) this.guide.release();
  }

  _pullTarget(id) {
    if (id === this.openId) return PULL_OPEN;
    if (id === this.topId) return PULL_TOP;
    if (this.marked.has(id)) return PULL_HIT;
    return this.layout === "recency" && this._recent.has(id) ? PULL_HIT * 0.6 : 0;
  }

  open(id) {
    const prev = this.openId && this.byBook.get(this.openId);
    this.openId = id || null;
    if (prev) this._pull.set(prev, this._pull.get(prev) || 0);
    const mesh = id && this.byBook.get(id);
    if (mesh) this._pull.set(mesh, this._pull.get(mesh) || 0);
  }

  /* Spoken-direction hint relative to where the visitor stands/looks. */
  describe(id) {
    const mesh = this.byBook.get(id);
    if (!mesh) return null;
    const w = mesh.getWorldPosition(new THREE.Vector3());
    const p = this.camera.position;
    const u = mesh.userData;
    return describePlace(w.x - p.x, w.z - p.z, this.walk.yaw, u.level, u.caseLabel, u.bay);
  }

  hits() {
    return [this.topId, ...[...this.marked].filter((id) => id !== this.topId)]
      .map((id) => id && this.byBook.get(id)).filter(Boolean)
      .map((m) => m.getWorldPosition(new THREE.Vector3()));
  }

  /* World point in a book's case frame: dx along the shelf, y up, dz out
   * from the book's home slot toward the aisle. */
  caseToWorld(mesh, dx, y, dz) {
    const u = mesh.userData;
    mesh.parent.updateMatrixWorld();
    return mesh.parent.localToWorld(new THREE.Vector3(mesh.position.x + dx, y, u.homeZ + dz));
  }

  /* Where the librarian stands beside a book (side metres along the shelf). */
  besidePoint(id, side, front) {
    const mesh = this.byBook.get(id);
    return mesh ? this.caseToWorld(mesh, side, 0, BOOK_D / 2 + front) : null;
  }

  /* ── camera moves ──────────────────────────────────────────── */
  flyTo(id) {
    const mesh = this.byBook.get(id);
    if (!mesh) return;
    const c = this._center();
    const b = this.frameBias;
    const stand = this.caseToWorld(mesh, b.x, EYE_Y, 2.0);
    // two-shot: aim between the book's height and the partner's, whatever the shelf
    const y = this.framePartnerY == null ? mesh.position.y + b.y
      : mesh.position.y + (this.framePartnerY - mesh.position.y) * 0.5;
    const look = this.caseToWorld(mesh, b.x, y, 0);
    this.guide.lanternRun(look, stand, { overview: { x: c.x, z: c.z }, caseH: caseHeight() });
  }

  resetView() {
    const s = this._spawn;
    this.guide.dolly(new THREE.Vector3(s.x, EYE_Y, s.z), new THREE.Vector3(s.x, EYE_Y, s.z - 5), 0.9, { hover: false });
  }

  /* Walk to a floor-plan point (minimap click), snapping into an aisle. */
  goto(x, z) {
    let px = x;
    let pz = z;
    for (let i = 0; i < 40 && this.walk.collides(px, pz); i += 1) pz += 0.15;
    const to = new THREE.Vector3(px, EYE_Y, pz);
    const look = to.clone().add(new THREE.Vector3(0, 0, -3));
    this.guide.dolly(to, look, this.reducedMotion ? 0.3 : 1.1, { hover: false });
  }

  /* ── interaction ───────────────────────────────────────────── */
  _downAt(e) {
    [this._downX, this._downY] = [e.clientX, e.clientY];
  }

  _pick(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    if (this._locked()) this._ndc.set(0, 0);
    else this._ndc.set(((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this._ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this._meshes, false)[0];
    return hit && hit.distance < 9 ? hit.object : null;
  }

  _hover(clientX, clientY) {
    const mesh = this._pick(clientX, clientY);
    const id = mesh ? mesh.userData.id : null;
    if (id === this._hoveredId && !id) return;
    this._hoveredId = id;
    window.dispatchEvent(new CustomEvent("bc:book-hover", {
      detail: { id, x: clientX, y: clientY, label: mesh ? mesh.userData.label : "" },
    }));
  }

  _click(e) {
    // ignore clicks that were actually look-drags
    const dx = e.clientX - (this._downX ?? e.clientX);
    const dy = e.clientY - (this._downY ?? e.clientY);
    if (!this._locked() && Math.hypot(dx, dy) > 6) return;
    const mesh = this._pick(e.clientX, e.clientY);
    if (mesh) {
      window.dispatchEvent(new CustomEvent("bc:book-click", { detail: { id: mesh.userData.id } }));
    } else if (!this._locked()) {
      this.walk.requestLock(); // empty click grabs mouse-look
    }
  }

  /* ── animation loop ────────────────────────────────────────── */
  _step(t) {
    const dt = this._lastT ? Math.min(0.1, t - this._lastT) : 0.016;
    this._lastT = t;

    if (!this.guide.update(dt, t)) this.walk.update(dt);
    this.atmosphere.update(t, this.camera.position);

    // books slide out of / back into the shelf
    const k = 1 - Math.exp(-dt * (this.reducedMotion ? 30 : 7));
    for (const [mesh, cur] of this._pull) {
      const goal = this._pullTarget(mesh.userData.id);
      const next = cur + (goal - cur) * k;
      mesh.position.z = mesh.userData.homeZ + next;
      if (goal === 0 && next < 0.0005) {
        mesh.position.z = mesh.userData.homeZ;
        this._pull.delete(mesh);
      } else {
        this._pull.set(mesh, next);
      }
    }

    const top = this.topId && this.byBook.get(this.topId);
    if (top && this._halo.visible) {
      top.getWorldPosition(this._halo.position);
      top.getWorldQuaternion(this._halo.quaternion);
      this._halo.scale.set(top.scale.x + 0.025, BOOK_H * top.scale.y + 0.025, BOOK_D + 0.02);
      this._halo.material.opacity = 0.14 + (this.reducedMotion ? 0 : 0.08 * Math.sin(t * 3));
    }

    if (this._locked() && t - this._hoverT > 0.1) {
      this._hoverT = t;
      this._hover(window.innerWidth / 2, window.innerHeight / 2);
    }
    if (this.onFrame) this.onFrame(t);
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    for (const [type, fn] of this._events) window.removeEventListener(type, fn);
    this.canvas.removeEventListener("pointerdown", this._onPointerDown);
    this.canvas.removeEventListener("pointermove", this._onPointerMove);
    this.canvas.removeEventListener("click", this._onClick);
    window.removeEventListener("resize", this._onResize);
    document.removeEventListener("pointerlockchange", this._onLock);
    this._disposeGroup(this.bookGroup);
    this._disposeGroup(this.furniture);
    this.atmosphere.clear();
    this.walk.dispose();
    delete window.__bookcase;
    this.renderer.dispose();
  }
}
