/* bookcase-mascot.js — the Memorius hippo, the library's librarian.
 *
 * He waits by the entrance when you arrive. Ask for something and the
 * lantern (the light from his book) leads the camera through the stacks;
 * by the time you land he is already standing beside the right book,
 * holding his book toward it, and the lantern settles back into it. He
 * hops whenever he speaks and turns to face you as you move. Reset the
 * view and he goes back to his spot by the doors.
 *
 * Rendering: the 3D model librarian-hippo.glb (meshopt + WebP, ~0.6 MB),
 * shown as soon as it loads; until then — or if it cannot load — an
 * upright paper cut-out (librarian-hippo.webp) stands in. Both are
 * mirrored so the book is in the hand nearest the shelf he points at.
 * Purely decorative: no collider, never intercepts book picking.
 * prefers-reduced-motion: no pop/hop/breathing, instant moves.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { shadowTexture } from "./bookcase-textures.js";

export const MASCOT_URL = "./librarian-hippo.webp";
export const MASCOT_MODEL_URL = "./librarian-hippo.glb";
const HEIGHT = 1.05; // metres — a small, friendly librarian
const ASPECT = 695 / 768; // cut-out image width / height
const CUTOUT_BOOK = [0.17 - 0.5, 0.56]; // book in the image (u from centre, v from feet)
const MODEL_H = 1.9; // model's native height (bbox y -0.95 … 0.95), facing +Z
const MODEL_BOOK = [-0.62, 0.05, 0.25]; // book in model space (his right hand)
const SIDE = 0.6; // how far beside the found book he stands (frame left)
const FRONT = 0.3; // how far out from the shelf face (stays in the aisle)

export class Mascot {
  constructor(scene, { reducedMotion = false } = {}) {
    this.reducedMotion = reducedMotion;
    this.group = new THREE.Group(); // position + yaw
    this.figure = new THREE.Group(); // pop / breathe / hop / mirror
    this.anchor = new THREE.Object3D(); // where his book is
    this.group.add(this.figure);

    // paper cut-out first (instant), replaced by the 3D model when ready
    const tex = new THREE.TextureLoader().load(MASCOT_URL);
    tex.colorSpace = THREE.SRGBColorSpace;
    const geo = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0); // feet on the floor
    this.cutout = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      map: tex, transparent: true, alphaTest: 0.08, color: 0xe6d8c6, side: THREE.DoubleSide,
    }));
    this.cutout.scale.set(HEIGHT * ASPECT, HEIGHT, 1);
    this.figure.add(this.cutout);
    this.anchor.position.set(CUTOUT_BOOK[0] * HEIGHT * ASPECT, CUTOUT_BOOK[1] * HEIGHT, 0.05);
    this.figure.add(this.anchor);
    this.model = null;
    this._loadModel();

    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(0.9, 0.55),
      new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false })
    );
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.004;
    this.group.add(shadow);
    scene.add(this.group);

    this.flipped = true;
    this.at = "home";
    this._pop = 1; // 0 → hidden, 1 → fully shown
    this._pending = null; // {pos, flip, delay, at}
    this._hop = 0;
    this._yaw = 0;
    this.home = new THREE.Vector3(-1.3, 0, 3.0);
    this.group.position.copy(this.home);
  }

  _loadModel() {
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(MASCOT_MODEL_URL, (gltf) => {
      const model = gltf.scene;
      const s = HEIGHT / MODEL_H;
      model.scale.setScalar(s);
      model.position.y = (MODEL_H / 2) * s; // feet on the floor
      model.traverse((o) => {
        if (!o.isMesh) return;
        const m = o.material;
        m.metalness = 0; // no env map in the hall: metal would read black
        // a little self-light so he stays readable in the dim reading room
        m.emissive = new THREE.Color(0x2a221c);
        m.emissiveMap = m.map;
      });
      this.figure.remove(this.cutout);
      this.figure.add(model);
      this.anchor.position.set(MODEL_BOOK[0] * s, MODEL_BOOK[1] * s + (MODEL_H / 2) * s,
        MODEL_BOOK[2] * s);
      this.model = model;
    }, undefined, () => {
      /* stay a paper cut-out — the page keeps working */
    });
  }

  /* His spot by the doors (from the floor plan), facing into the hall. */
  setHome(desk) {
    this.home.set(desk.x, 0, desk.z);
    this.goHome(0);
  }

  goHome(delay = 0.2) {
    this._schedule(this.home.clone(), true, delay, "home");
  }

  /* Stand at a world point beside a book; appears after `delay` seconds. */
  standAt(pos, delay = 0) {
    this._schedule(pos.clone().setY(0), true, delay, "book");
  }

  _schedule(pos, flip, delay, at) {
    if (this.reducedMotion) delay = 0;
    this._pending = { pos, flip, delay, at };
  }

  /* World point of the book in his hand (the lantern's resting place). */
  bookPoint(out = new THREE.Vector3()) {
    this.group.updateMatrixWorld(true);
    return this.anchor.getWorldPosition(out);
  }

  hop() {
    if (!this.reducedMotion) this._hop = 1;
  }

  /* Wire him to a BookcaseScene: follow its events, return a per-frame
   * function. Scene listeners are registered first, so the hall is rebuilt
   * (bc:books) and the camera flight has started (bc:search / bc:fly) by
   * the time these run. */
  attach(scene) {
    // arrival becomes a two-shot: aim between the found book and his book
    scene.frameBias.set(-SIDE * 0.5, 0, 0);
    scene.framePartnerY = this.anchor.position.y + 0.1;
    const toBook = (id) => {
      const pos = id && scene.besidePoint(id, -SIDE, FRONT);
      if (!pos) return;
      const f = scene.guide.flight; // arrive as the camera lands
      this.standAt(pos, f ? f.dur * 0.7 : 0);
    };
    window.addEventListener("bc:books", () => scene._plan && this.setHome(scene._plan.desk));
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

  update(dt, t, camera = null) {
    if (camera) {
      // turn (yaw only) to face the visitor, with a little lag like a person
      const g = this.group.position;
      const want = Math.atan2(camera.position.x - g.x, camera.position.z - g.z);
      let d = want - this._yaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      this._yaw += this.reducedMotion ? d : d * Math.min(1, dt * 4);
      this.group.rotation.y = this._yaw;
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
        if (camera) {
          this._yaw = Math.atan2(camera.position.x - p.pos.x, camera.position.z - p.pos.z);
        }
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
    this.figure.position.y = Math.sin(this._hop * Math.PI) * 0.12;
    const mirror = this.flipped ? -1 : 1;
    this.figure.scale.set(mirror * pop * (1 - breathe * 0.5), pop * (1 + breathe), pop);
    this.group.visible = pop > 0.01;
  }
}
