/* bookcase-mascot.js — the Memorius hippo, the library's librarian.
 *
 * He waits by the entrance when you arrive. Ask for something and the
 * lantern (the light from his glowing book) leads the camera through the
 * stacks; by the time you land in the aisle he is already standing beside
 * the right book, and the lantern settles back into the book in his hand.
 * He gives a small hop whenever he speaks. Reset the view and he goes
 * back to the entrance.
 *
 * Rendering: an upright paper-theatre cut-out from librarian-hippo.webp
 * that turns (yaw only) to face the visitor — it never tilts into the
 * shelves when the camera looks down — mirrored when needed so his book
 * points where he is pointing, with a contact shadow.
 * Purely decorative: no collider, never intercepts book picking.
 * prefers-reduced-motion: no pop/hop/breathing, instant moves.
 */
import * as THREE from "three";
import { shadowTexture } from "./bookcase-textures.js";
import { BOOK_D } from "./bookcase-layout.js";

export const MASCOT_URL = "./librarian-hippo.webp";
const HEIGHT = 1.0; // metres — a small, friendly librarian
const ASPECT = 695 / 768; // cropped image width / height
// where his glowing book sits inside the image (fractions of the sprite)
const BOOK_U = 0.17; // from the left edge
const BOOK_V = 0.56; // from the bottom edge
const SIDE = 0.6; // how far beside the found book he stands (frame left, clear of the panel)
const FRONT = 0.3; // how far out from the shelf face (stays in the aisle)

export class Mascot {
  constructor(scene, { reducedMotion = false } = {}) {
    this.reducedMotion = reducedMotion;
    this.group = new THREE.Group();
    const loader = new THREE.TextureLoader();
    const tex = loader.load(MASCOT_URL, () => { this.ready = true; });
    tex.colorSpace = THREE.SRGBColorSpace;
    // a touch warmer/darker than white so the unlit cut-out sits in lamplight
    const geo = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0); // feet on the floor
    this.sprite = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      map: tex, transparent: true, alphaTest: 0.08, color: 0xe6d8c6, side: THREE.DoubleSide,
    }));
    this.sprite.scale.set(HEIGHT * ASPECT, HEIGHT, 1);
    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(0.9, 0.45),
      new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false })
    );
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.004;
    this.group.add(shadow, this.sprite);
    scene.add(this.group);

    this.flipped = false;
    this.at = "home";
    this._pop = 1; // 0 → hidden, 1 → fully shown
    this._pending = null; // {pos, flip, delay, at}
    this._hop = 0;
    this.home = new THREE.Vector3(-1.4, 0, 1.6);
    this.group.position.copy(this.home);
  }

  /* Entrance spot for a fresh floor plan: off to the left of the spawn,
   * in front of the first row, so the opening shot frames him. */
  setHome(spawn) {
    this.home.set(spawn.x - 1.3, 0, spawn.z - 3.4);
    this.goHome(0);
  }

  /* At the entrance he is mirrored so his book points into the room. */
  goHome(delay = 0.2) {
    this._schedule(this.home.clone(), true, delay, "home");
  }

  /* Stand beside a book (its world position + shelf-face z), holding the
   * glowing book toward it. Appears after `delay` seconds (camera flight). */
  standBeside(bookPos, shelfZ, delay = 0) {
    // left of the book, mirrored so his glowing book points at it
    const pos = new THREE.Vector3(bookPos.x - SIDE, 0, shelfZ + FRONT);
    this._schedule(pos, true, delay, "book");
  }

  _schedule(pos, flip, delay, at) {
    if (this.reducedMotion) delay = 0;
    this._pending = { pos, flip, delay, at };
  }

  /* World point of the glowing book in his hand (lantern's resting place). */
  bookPoint(out = new THREE.Vector3()) {
    const w = HEIGHT * ASPECT * (this.flipped ? -1 : 1);
    this.group.updateMatrixWorld();
    return this.group.localToWorld(out.set((BOOK_U - 0.5) * w, HEIGHT * BOOK_V, 0.04));
  }

  /* Wire him to a BookcaseScene: follow its events, return a per-frame
   * function. Scene listeners are registered first, so the case is rebuilt
   * (bc:books) and the camera flight has started (bc:search / bc:fly) by
   * the time these run. */
  attach(scene) {
    // arrival becomes a two-shot: aim between the found book and his book
    scene.frameBias.set(-SIDE * 0.5, -0.32, 0);
    const toBook = (id) => {
      const mesh = id && scene.byBook.get(id);
      if (!mesh) return;
      const f = scene.guide.flight; // arrive as the camera lands
      this.standBeside(mesh.position, mesh.userData.homeZ + BOOK_D / 2, f ? f.dur * 0.7 : 0);
    };
    window.addEventListener("bc:books", () => this.setHome(scene._spawn));
    window.addEventListener("bc:search", (e) => toBook(e.detail.topId));
    window.addEventListener("bc:fly", (e) => toBook(e.detail.id));
    window.addEventListener("bc:reset-view", () => this.goHome());
    let last = 0;
    return (t) => {
      this.update(Math.min(0.1, t - last), t, scene.camera);
      last = t;
      const g = scene.guide;
      // once he's beside the book, the lantern settles into the book he holds
      if (this.at === "book" && !this._pending && g.mode === "hover" && g.hoverAt && !g.active) {
        this.bookPoint(g.hoverAt);
      }
    };
  }

  hop() {
    if (!this.reducedMotion) this._hop = 1;
  }

  update(dt, t, camera = null) {
    if (camera) {
      // yaw-only billboard: always upright, always facing the visitor
      const g = this.group.position;
      this.group.rotation.y = Math.atan2(camera.position.x - g.x, camera.position.z - g.z);
    }
    const p = this._pending;
    if (p) {
      p.delay -= dt;
      // vanish in place (a quick shrink) while waiting, reappear at the target
      this._pop = Math.max(0, this._pop - dt * 5);
      if (p.delay <= 0 && (this._pop === 0 || this.reducedMotion)) {
        this.group.position.copy(p.pos);
        this.flipped = p.flip;
        this.at = p.at;
        this._pending = null;
        this._pop = this.reducedMotion ? 1 : 0.001;
      }
    } else if (this._pop < 1) {
      this._pop = Math.min(1, this._pop + dt * 3.2);
    }
    // ease-out-back pop so he lands with a little bounce
    const k = this._pop;
    const c = 1.9;
    const pop = k <= 0 ? 0 : 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2);
    const breathe = this.reducedMotion ? 0 : 0.012 * Math.sin(t * 2.2);
    this._hop = Math.max(0, this._hop - dt * 2.5);
    const hopY = Math.sin(this._hop * Math.PI) * 0.12;
    this.sprite.position.y = hopY;
    const flip = this.flipped ? -1 : 1;
    this.sprite.scale.set(flip * HEIGHT * ASPECT * pop * (1 - breathe * 0.5), HEIGHT * pop * (1 + breathe), 1);
    this.group.visible = pop > 0.01;
  }
}
