/* bookcase-mascot.js — the Memorius hippo, the library's librarian.
 *
 * He waits by the entrance when you arrive. Ask for something and he walks
 * to the right book — through the nave and into the bay, never through a
 * case — while the lantern (the light from his book) leads the camera
 * there; when he arrives he holds his book toward it and the lantern
 * settles back into it. He hops whenever he speaks and turns to face you
 * as you move. Reset the view and he walks back to his spot by the doors.
 *
 * Rendering: the 3D model librarian-hippo.glb (meshopt + WebP, ~0.6 MB),
 * shown as soon as it loads; until then — or if it cannot load — an
 * upright paper cut-out (librarian-hippo.webp) stands in. Both are
 * mirrored so the book is in the hand nearest the shelf he points at.
 * Purely decorative: no collider, never intercepts book picking.
 * prefers-reduced-motion: no pop/hop/breathing or walk cycle; he is
 * placed instantly instead of gliding.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { shadowTexture } from "./bookcase-textures.js";
import { routeBetween } from "./bookcase-layout.js";

export const MASCOT_URL = "./librarian-hippo.webp";
export const MASCOT_MODEL_URL = "./librarian-hippo.glb";
const HEIGHT = 1.05; // metres — a small, friendly librarian
const ASPECT = 695 / 768; // cut-out image width / height
const CUTOUT_BOOK = [0.17 - 0.5, 0.56]; // book in the image (u from centre, v from feet)
const MODEL_H = 1.9; // model's native height (bbox y -0.95 … 0.95), facing +Z
const MODEL_BOOK = [-0.62, 0.05, 0.25]; // book in model space (his right hand)
const SIDE = 0.6; // how far beside the found book he stands (frame left)
const FRONT = 0.3; // how far out from the shelf face (stays in the aisle)
export const WALK_SPEED = 1.25; // m/s — a librarian's unhurried pace
const TURN_RATE = 6; // yaw damping while following the route
const BOB = 0.03; // ±3 cm walk bob
const ROLL = 0.035; // ±2° side-to-side sway
const LEAN = 0.07; // leans into the direction of travel

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
    this._hop = 0;
    this._yaw = 0;
    this._plan = null; // floor plan (bays + openings), set on bc:books
    this._path = []; // remaining waypoints, on the floor
    this._target = null; // {pos, flip, at} for the walk in progress
    this._delay = 0; // seconds to stand still before setting off
    this._stride = 0; // walk-cycle phase
    this._lean = 0; // 0 idle → 1 walking
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
  setHome(desk, plan = null) {
    if (plan) this._plan = plan;
    this.home.set(desk.x, 0, desk.z);
    this.goHome(0);
  }

  goHome(delay = 0.2) {
    this.walkTo(this.home, { delay, at: "home" });
  }

  /* Walk to a world point beside a book, then hop and face the visitor.
   * `delay` is for the establishing shot; while a camera flight is running
   * callers pass 0 so he sets off at once and arrives as the camera lands. */
  walkTo(target, { delay = 0, flip = true, at = "book" } = {}) {
    const pos = new THREE.Vector3(target.x, 0, target.z);
    this._target = { pos, flip, at };
    if (this.reducedMotion) {
      this._place(pos, flip, at);
      return;
    }
    this._delay = Math.max(0, delay);
    const route = routeBetween(this.group.position, pos, this._plan || { bays: [] });
    this._path = route.slice(1).map((p) => new THREE.Vector3(p.x, 0, p.z));
    if (!this._path.length) this._arrive();
  }

  /* Kept for callers from before he walked: same as walkTo. */
  standAt(pos, delay = 0) {
    this.walkTo(pos, { delay, at: "book" });
  }

  get isWalking() {
    return this._path.length > 0;
  }

  /* Remaining waypoints, for the debug hook and headless checks. */
  get path() {
    return this._path.map((p) => ({ x: p.x, z: p.z }));
  }

  get position() {
    return this.group.position;
  }

  _arrive() {
    const t = this._target;
    if (t) this._place(t.pos, t.flip, t.at);
  }

  _place(pos, flip, at) {
    this.group.position.copy(pos);
    this.flipped = flip;
    this.at = at;
    this._target = null;
    this._path = [];
    this._delay = 0;
    this._lean = 0;
    this.hop();
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
      // set off at once so he is in the bay as the camera settles
      this.walkTo(pos, { at: "book" });
    };
    window.addEventListener("bc:books", () => {
      this._plan = scene._plan;
      if (scene._plan) this.setHome(scene._plan.desk);
    });
    this._plan = scene._plan;
    window.addEventListener("bc:search", (e) => toBook(e.detail.topId));
    window.addEventListener("bc:fly", (e) => toBook(e.detail.id));
    window.addEventListener("bc:reset-view", () => this.goHome());
    let last = 0;
    return (t) => {
      this.update(Math.min(0.1, t - last), t, scene.camera);
      last = t;
      const g = scene.guide;
      // once he's beside the book, the lantern settles into the book he holds
      if (this.at === "book" && !this.isWalking && this._delay <= 0 &&
          g.mode === "hover" && g.hoverAt && !g.active) {
        this.bookPoint(g.hoverAt);
      }
    };
  }

  update(dt, t, camera = null) {
    if (this._delay > 0) {
      this._delay -= dt;
    } else if (this._path.length) {
      this._advance(dt);
    } else if (camera) {
      // turn (yaw only) to face the visitor, with a little lag like a person
      const g = this.group.position;
      const want = Math.atan2(camera.position.x - g.x, camera.position.z - g.z);
      let d = want - this._yaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      this._yaw += this.reducedMotion ? d : d * Math.min(1, dt * 4);
      this.group.rotation.y = this._yaw;
    }

    // ease in/out of the walk; reduced motion never bobs or leans
    const moving = this._path.length ? 1 : 0;
    this._lean += (moving - this._lean) * Math.min(1, dt * 8);
    const gait = this.reducedMotion ? 0 : this._lean;

    // ease-out-back pop so he lands with a little bounce
    const k = this._pop;
    const c = 1.9;
    const pop = k <= 0 ? 0 : 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2);
    const breathe = this.reducedMotion ? 0 : 0.012 * Math.sin(t * 2.2);
    this._hop = Math.max(0, this._hop - dt * 2.5);
    const step = Math.abs(Math.sin(this._stride)) * BOB * gait;
    this.figure.position.y = Math.sin(this._hop * Math.PI) * 0.12 + step;
    this.figure.rotation.x = LEAN * gait;
    this.figure.rotation.z = Math.sin(this._stride) * ROLL * gait;
    const mirror = this.flipped ? -1 : 1;
    this.figure.scale.set(mirror * pop * (1 - breathe * 0.5), pop * (1 + breathe), pop);
    this.group.visible = pop > 0.01;
  }

  /* Step along the route: turn toward the next waypoint, then move. */
  _advance(dt) {
    const wp = this._path[0];
    const g = this.group.position;
    const dx = wp.x - g.x;
    const dz = wp.z - g.z;
    const dist = Math.hypot(dx, dz);
    if (dist < 0.02) {
      this._path.shift();
      if (!this._path.length) this._arrive();
      return;
    }
    const want = Math.atan2(dx, dz); // the model faces +Z
    let d = want - this._yaw;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    this._yaw += d * Math.min(1, dt * TURN_RATE);
    this.group.rotation.y = this._yaw;
    // a sharp corner costs speed rather than sliding sideways
    const facing = Math.max(0.35, Math.cos(d));
    const step = Math.min(dist, WALK_SPEED * facing * dt);
    g.x += (dx / dist) * step;
    g.z += (dz / dist) * step;
    this._stride += step * 7; // one full bob every ~0.9 m
    if (dist - step < 0.02) {
      this._path.shift();
      if (!this._path.length) this._arrive();
    }
  }
}
