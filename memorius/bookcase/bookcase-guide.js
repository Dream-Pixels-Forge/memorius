/* bookcase-guide.js — the Lantern: the librarian made visible, plus the
 * camera choreography that follows it.
 *
 * The librarian is not a face, it is a light. A small lantern-wisp floats
 * at your shoulder while you walk. Ask it for something and it takes off;
 * the camera follows it in one unbroken crane move — up out of the aisle,
 * over the tops of the stacks (the whole library laid out below, hits
 * glowing), then down into the right aisle and in to the book, where the
 * lantern waits, hovering above it. On load an establishing shot descends
 * from the rafters while the lantern flies in to meet you.
 * prefers-reduced-motion: no crane, no establishing shot (short dolly only).
 */
import * as THREE from "three";
import { glowTexture } from "./bookcase-textures.js";

const TRAIL = 28;
const smooth = (a, b, x) => {
  const t = THREE.MathUtils.clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};
const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

export class Guide {
  constructor(scene, camera, walk, { reducedMotion = false, onCinema = () => {} } = {}) {
    this.camera = camera;
    this.walk = walk;
    this.reducedMotion = reducedMotion;
    this.onCinema = onCinema;
    this.flight = null;
    this.mode = "follow"; // follow | lead | hover
    this.hoverAt = null;

    this.lantern = new THREE.Group();
    const glowMat = new THREE.SpriteMaterial({
      map: glowTexture(), color: 0xffb35c, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    this._halo = new THREE.Sprite(glowMat);
    this._halo.scale.set(0.6, 0.6, 1);
    this._core = new THREE.Sprite(glowMat.clone());
    this._core.material.color.set(0xfff4e0);
    this._core.scale.set(0.12, 0.12, 1);
    this._light = new THREE.PointLight(0xffa850, 2.2, 5, 2);
    this.lantern.add(this._halo, this._core, this._light);
    this.lantern.position.set(0, 1.5, 2);
    scene.add(this.lantern);

    const tpos = new Float32Array(TRAIL * 3);
    const tcol = new Float32Array(TRAIL * 3);
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(tpos, 3));
    trailGeo.setAttribute("color", new THREE.BufferAttribute(tcol, 3));
    this._trail = new THREE.Points(trailGeo, new THREE.PointsMaterial({
      map: glowTexture(), size: 0.07, vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    this._trail.frustumCulled = false;
    scene.add(this._trail);
    this._history = [];
    this._v = new THREE.Vector3();
    this._look = new THREE.Vector3();
  }

  get active() {
    return !!this.flight;
  }

  /* Opening shot: from the rafters down to the spawn point. */
  establishing(spawn, center) {
    if (this.reducedMotion) return;
    const from = new THREE.Vector3(center.x + 2.5, 5.2, spawn.z + 7.5);
    const to = new THREE.Vector3(spawn.x, spawn.y, spawn.z);
    const curve = new THREE.CatmullRomCurve3([
      from, new THREE.Vector3(center.x + 1.2, 4.2, spawn.z + 4), to,
    ]);
    const lookFrom = new THREE.Vector3(center.x, 0.6, center.z);
    const lookTo = new THREE.Vector3(spawn.x, spawn.y, spawn.z - 5);
    this.lantern.position.set(center.x, 2.4, center.z - 4);
    this.mode = "lead";
    this._begin(4.2, (e) => curve.getPoint(e),
      (e) => this._look.lerpVectors(lookFrom, lookTo, smooth(0.25, 0.95, e)),
      (e) => this._v.lerpVectors(new THREE.Vector3(center.x, 2.4, center.z - 4),
        new THREE.Vector3(spawn.x + 0.55, spawn.y - 0.15, spawn.z - 1.4), smooth(0.1, 1, e)),
      () => this.walk.sync(0, 0));
    this.camera.position.copy(from);
  }

  /* The lantern run: crane up, over the stacks, down into the aisle. */
  lanternRun(bookPos, standPos, { overview, caseH }) {
    const from = this.camera.position.clone();
    const dist = from.distanceTo(standPos);
    if (this.reducedMotion || dist < 1.2) {
      this.dolly(standPos, bookPos, 0.6);
      return;
    }
    const craneY = caseH + 2.3;
    const mid = from.clone().lerp(standPos, 0.5);
    const curve = new THREE.CatmullRomCurve3([
      from,
      new THREE.Vector3(from.x, craneY - 0.4, from.z + 0.4),
      new THREE.Vector3(mid.x, craneY, mid.z + 1.2),
      new THREE.Vector3(standPos.x, craneY - 0.7, standPos.z + 0.6),
      standPos.clone(),
    ], false, "centripetal");
    const fwd = new THREE.Vector3();
    this.camera.getWorldDirection(fwd);
    const look0 = from.clone().addScaledVector(fwd, 4);
    const look1 = new THREE.Vector3(overview.x, 0.4, overview.z);
    const hover = bookPos.clone().add(new THREE.Vector3(0.05, 0.3, 0.08));
    this.mode = "lead";
    this._begin(THREE.MathUtils.clamp(2.6 + dist * 0.06, 2.6, 4.4),
      (e) => curve.getPoint(e),
      (e) => this._look.lerpVectors(look0, look1, smooth(0.0, 0.35, e)).lerp(bookPos, smooth(0.45, 0.92, e)),
      (e) => (e > 0.9 ? this._v.copy(hover) : curve.getPoint(Math.min(1, e + 0.12)).add(this._v.set(0, 0.15, -0.4))),
      () => {
        this.mode = "hover";
        this.hoverAt = hover;
      });
  }

  /* Short, direct move (reduced motion, nearby books, reset view). */
  dolly(toPos, lookPoint, dur = 0.9, { hover = true } = {}) {
    const from = this.camera.position.clone();
    const fwd = new THREE.Vector3();
    this.camera.getWorldDirection(fwd);
    const look0 = from.clone().addScaledVector(fwd, 3);
    const target = lookPoint.clone();
    this._begin(dur, (e) => this._v.lerpVectors(from, toPos, e),
      (e) => this._look.lerpVectors(look0, target, e), null, () => {
        if (hover) {
          this.mode = "hover";
          this.hoverAt = target.clone().add(new THREE.Vector3(0.05, 0.3, 0.08));
        } else {
          this.mode = "follow";
        }
      }, false);
  }

  _begin(dur, posAt, lookAt, lanternAt, onDone, cinema = true) {
    this.flight = { t: 0, dur, posAt, lookAt, lanternAt, onDone, cinema };
    this.walk.enabled = false;
    if (cinema) this.onCinema(true);
  }

  cancel() {
    if (!this.flight) return;
    const f = this.flight;
    this.flight = null;
    this.walk.syncFromCamera();
    this.walk.enabled = true;
    if (f.cinema) this.onCinema(false);
    this.mode = "follow";
  }

  release() {
    this.mode = "follow";
    this.hoverAt = null;
  }

  /* Advance one frame. Returns true while the camera is being driven. */
  update(dt, t) {
    const f = this.flight;
    if (f) {
      f.t += dt;
      const k = Math.min(1, f.t / f.dur);
      const e = easeInOut(k);
      this.camera.position.copy(f.posAt(e));
      this.camera.lookAt(f.lookAt(e));
      if (f.lanternAt) this.lantern.position.copy(f.lanternAt(e));
      if (k >= 1) {
        this.flight = null;
        this.walk.syncFromCamera();
        this.walk.enabled = true;
        if (f.cinema) this.onCinema(false);
        if (f.onDone) f.onDone();
      }
    }
    this._float(dt, t, !!(f && f.lanternAt));
    return !!f;
  }

  _float(dt, t, driven) {
    const bob = this.reducedMotion ? 0 : Math.sin(t * 2.1) * 0.035;
    if (!driven) {
      let goal;
      if (this.mode === "hover" && this.hoverAt) {
        goal = this._v.copy(this.hoverAt);
        if (this.camera.position.distanceTo(this.hoverAt) > 5) this.release();
      } else {
        goal = this._v.set(0.55, -0.12, -1.4).applyQuaternion(this.camera.quaternion)
          .add(this.camera.position);
      }
      goal.y += bob;
      this.lantern.position.lerp(goal, 1 - Math.exp(-dt * 3.2));
    }
    const flick = 1 + (this.reducedMotion ? 0 : 0.06 * Math.sin(t * 11) + 0.04 * Math.sin(t * 17.3));
    // waiting over a book the lantern dims to a reading glow (no blow-out)
    const near = this.mode === "hover" && !driven;
    this._dim = (this._dim ?? 1) + ((near ? 0.4 : 1) - (this._dim ?? 1)) * Math.min(1, dt * 3);
    this._halo.scale.setScalar(0.6 * flick * (0.5 + 0.5 * this._dim));
    this._light.intensity = 2.2 * flick * this._dim;
    this._updateTrail();
  }

  _updateTrail() {
    this._history.unshift(this.lantern.position.clone());
    if (this._history.length > TRAIL) this._history.pop();
    const pos = this._trail.geometry.attributes.position;
    const col = this._trail.geometry.attributes.color;
    for (let i = 0; i < TRAIL; i += 1) {
      const p = this._history[Math.min(i, this._history.length - 1)];
      pos.setXYZ(i, p.x, p.y, p.z);
      const fade = Math.pow(1 - i / TRAIL, 2) * 0.8;
      col.setXYZ(i, fade, fade * 0.62, fade * 0.3);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
  }
}
