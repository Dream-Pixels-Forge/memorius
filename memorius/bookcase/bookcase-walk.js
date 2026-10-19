/* bookcase-walk.js — first-person walk controls for the vault library.
 * WASD/arrow walking at eye height with mouse look (pointer-lock preferred,
 * drag-look fallback) and axis-separated AABB collision so the camera can
 * never pass through shelves or fall below the floor. Consumed by
 * bookcase-scene.js; colliders are case AABBs from bookcase-layout.js.
 */
import * as THREE from "three";

export class WalkControls {
  /* opts: { eyeY, speed, pad, colliders } — colliders: [{minX,maxX,minZ,maxZ}] */
  constructor(camera, dom, opts = {}) {
    this.camera = camera;
    this.dom = dom;
    this.eyeY = opts.eyeY ?? 1.65;
    this.speed = opts.speed ?? 2.2; // m/s walking pace
    this.pad = opts.pad ?? 0.35; // body radius vs case AABBs
    this.colliders = opts.colliders ?? [];
    this.enabled = true;
    this.yaw = 0;
    this.pitch = 0;

    this._keys = new Set();
    this._drag = false;
    this._lastX = 0;
    this._lastY = 0;
    this._euler = new THREE.Euler(0, 0, 0, "YXZ");

    this._onKeyDown = (e) => {
      const t = e.target;
      const tag = t && t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (t && t.isContentEditable) return;
      this._keys.add(e.code);
    };
    this._onKeyUp = (e) => this._keys.delete(e.code);
    this._onPointerDown = (e) => {
      this._drag = true;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
    };
    this._onPointerUp = () => {
      this._drag = false;
    };
    this._onMouseMove = (e) => {
      if (!this.enabled) return;
      let dx = 0;
      let dy = 0;
      if (document.pointerLockElement === this.dom) {
        dx = e.movementX || 0;
        dy = e.movementY || 0;
      } else if (this._drag && e.buttons & 1) {
        dx = e.clientX - this._lastX;
        dy = e.clientY - this._lastY;
        this._lastX = e.clientX;
        this._lastY = e.clientY;
      } else {
        return;
      }
      this.look(dx, dy);
    };
    this._onBlur = () => this._keys.clear();

    window.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("keyup", this._onKeyUp);
    window.addEventListener("blur", this._onBlur);
    this.dom.addEventListener("pointerdown", this._onPointerDown);
    window.addEventListener("pointerup", this._onPointerUp);
    document.addEventListener("mousemove", this._onMouseMove);
  }

  /* Mouse-look: dx/dy in pixels → yaw/pitch radians. */
  look(dx, dy) {
    this.yaw -= dx * 0.0022;
    this.pitch -= dy * 0.0022;
    this.pitch = this.clamp(this.pitch, -1.45, 1.45);
    this._apply();
  }

  clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
  }

  requestLock() {
    if (document.pointerLockElement !== this.dom && this.dom.requestPointerLock) {
      try {
        this.dom.requestPointerLock();
      } catch {
        /* drag-look fallback stays available */
      }
    }
  }

  setColliders(list) {
    this.colliders = list;
  }

  /* Would the body (a pad-radius disc) overlap any collider at (x, z)? */
  collides(x, z) {
    for (const c of this.colliders) {
      if (
        x > c.minX - this.pad &&
        x < c.maxX + this.pad &&
        z > c.minZ - this.pad &&
        z < c.maxZ + this.pad
      ) {
        return true;
      }
    }
    return false;
  }

  /* Advance one frame: keyboard walk + axis-separated collision response. */
  update(dt) {
    if (!this.enabled) return false;
    let f = 0;
    let s = 0;
    if (this._keys.has("KeyW") || this._keys.has("ArrowUp")) f += 1;
    if (this._keys.has("KeyS") || this._keys.has("ArrowDown")) f -= 1;
    if (this._keys.has("KeyA") || this._keys.has("ArrowLeft")) s -= 1;
    if (this._keys.has("KeyD") || this._keys.has("ArrowRight")) s += 1;
    if (f === 0 && s === 0) return false;

    const len = Math.hypot(f, s);
    f /= len;
    s /= len;
    const sinY = Math.sin(this.yaw);
    const cosY = Math.cos(this.yaw);
    const dx = (-sinY * f + cosY * s) * this.speed * dt;
    const dz = (-cosY * f - sinY * s) * this.speed * dt;

    const p = this.camera.position;
    const nx = p.x + dx;
    const nz = p.z + dz;
    if (!this.collides(nx, p.z)) p.x = nx; // slide along Z when blocked on X
    if (!this.collides(p.x, nz)) p.z = nz; // slide along X when blocked on Z
    p.y = this.eyeY; // never below (or above) walking eye height
    return true;
  }

  _apply() {
    this._euler.set(this.pitch, this.yaw, 0);
    this.camera.quaternion.setFromEuler(this._euler);
  }

  /* Adopt an explicit orientation (after camera flights / teleports). */
  sync(yaw, pitch) {
    this.yaw = yaw;
    this.pitch = this.clamp(pitch, -1.45, 1.45);
    this._apply();
  }

  /* Re-derive yaw/pitch from wherever the camera currently looks. */
  syncFromCamera() {
    this._euler.setFromQuaternion(this.camera.quaternion, "YXZ");
    this.yaw = this._euler.y;
    this.pitch = this._euler.x;
  }

  dispose() {
    window.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("keyup", this._onKeyUp);
    window.removeEventListener("blur", this._onBlur);
    this.dom.removeEventListener("pointerdown", this._onPointerDown);
    window.removeEventListener("pointerup", this._onPointerUp);
    document.removeEventListener("mousemove", this._onMouseMove);
  }
}
