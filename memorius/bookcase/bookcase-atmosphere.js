/* bookcase-atmosphere.js — the light and air of the vault library.
 * Night-time reading-room look: warm brass pendant lamps hang down the
 * nave and over every bay, each throwing a faint visible cone of light; cool moonlight rakes
 * in from one side (warm/cool contrast); dust motes drift through the
 * beams; contact shadows ground each case on a parquet floor.
 * Performance: lamps are visual-only meshes; a fixed pool of real point
 * lights is re-assigned every frame to the lamps nearest the camera, so
 * whichever aisle you walk into is lit, at a constant shader cost.
 */
import * as THREE from "three";
import { floorTexture, glowTexture, shadowTexture } from "./bookcase-textures.js";

export const CEILING_Y = 6.2;
const LAMP_Y = 3.05; // bulb height
const LIGHT_POOL = 6;
const DUST = 650;

export class Atmosphere {
  constructor(scene, { reducedMotion = false } = {}) {
    this.scene = scene;
    this.reducedMotion = reducedMotion;
    scene.background = new THREE.Color("#07060a");
    scene.fog = new THREE.FogExp2("#0a0807", 0.045);

    scene.add(new THREE.HemisphereLight(0x3c3448, 0x140c06, 0.9));
    const moon = new THREE.DirectionalLight(0x7d9cc8, 0.55);
    moon.position.set(-14, 9, 6);
    scene.add(moon);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400),
      new THREE.MeshStandardMaterial({ map: floorTexture(), roughness: 0.62, metalness: 0.0 })
    );
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);

    const ceiling = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400),
      new THREE.MeshLambertMaterial({ color: 0x0b0908 })
    );
    ceiling.rotation.x = Math.PI / 2;
    ceiling.position.y = CEILING_Y;
    scene.add(ceiling);

    this.group = new THREE.Group();
    scene.add(this.group);
    this.lamps = [];
    this.pool = [];
    for (let i = 0; i < LIGHT_POOL; i += 1) {
      const l = new THREE.PointLight(0xffc98a, 0, 9, 1.6);
      l.position.set(0, -50, 0);
      scene.add(l);
      this.pool.push(l);
    }
    this._shared = {
      cord: new THREE.CylinderGeometry(0.006, 0.006, 1, 5),
      shade: new THREE.ConeGeometry(0.22, 0.2, 24, 1, true),
      beam: new THREE.ConeGeometry(1.05, LAMP_Y, 32, 1, true),
      brass: new THREE.MeshStandardMaterial({
        color: 0xb08a4a, metalness: 0.85, roughness: 0.35, side: THREE.DoubleSide,
      }),
      cordMat: new THREE.MeshBasicMaterial({ color: 0x0a0806 }),
      bulb: new THREE.SpriteMaterial({
        map: glowTexture(), color: 0xffd9a0, blending: THREE.AdditiveBlending,
        depthWrite: false, transparent: true,
      }),
      beamMat: new THREE.MeshBasicMaterial({
        color: 0xffc070, transparent: true, opacity: 0.035,
        blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
      }),
      shadow: new THREE.MeshBasicMaterial({
        map: shadowTexture(), transparent: true, depthWrite: false,
      }),
    };
    this._dust = null;
    this._near = new THREE.Vector3();
  }

  /* Dress the hall for a fresh floor plan: lamps down the nave and over
   * every bay, contact shadows under every case, dust through the stacks. */
  build(plan, caseH) {
    this.clear();
    const s = this._shared;
    for (const c of plan.cases) {
      const a = c.aabb;
      const blob = new THREE.Mesh(
        new THREE.PlaneGeometry(a.maxX - a.minX + 0.8, a.maxZ - a.minZ + 0.8), s.shadow);
      blob.rotation.x = -Math.PI / 2;
      blob.position.set((a.minX + a.maxX) / 2, 0.003, (a.minZ + a.maxZ) / 2);
      this.group.add(blob);
    }
    for (const l of plan.lamps) this._addLamp(l.x, l.z);
    this._addDust(plan.bounds, caseH);
  }

  _addLamp(x, z) {
    const s = this._shared;
    const lamp = new THREE.Group();
    lamp.position.set(x, 0, z);
    const cordLen = CEILING_Y - LAMP_Y - 0.1;
    const cord = new THREE.Mesh(s.cord, s.cordMat);
    cord.scale.y = cordLen;
    cord.position.y = LAMP_Y + 0.1 + cordLen / 2;
    const shade = new THREE.Mesh(s.shade, s.brass);
    shade.position.y = LAMP_Y + 0.08;
    const bulb = new THREE.Sprite(s.bulb);
    bulb.scale.set(0.5, 0.5, 1);
    bulb.position.y = LAMP_Y;
    const beam = new THREE.Mesh(s.beam, s.beamMat);
    beam.position.y = LAMP_Y / 2;
    lamp.add(cord, shade, bulb, beam);
    this.group.add(lamp);
    this.lamps.push(new THREE.Vector3(x, LAMP_Y - 0.1, z));
  }

  _addDust(b, caseH) {
    const pos = new Float32Array(DUST * 3);
    const seed = new Float32Array(DUST);
    for (let i = 0; i < DUST; i += 1) {
      pos[i * 3] = b.minX + Math.random() * (b.maxX - b.minX);
      pos[i * 3 + 1] = 0.2 + Math.random() * (caseH + 1.4);
      pos[i * 3 + 2] = b.minZ + Math.random() * (b.maxZ - b.minZ);
      seed[i] = Math.random() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      map: glowTexture(), size: 0.035, color: 0xffd8a8, transparent: true,
      opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    this._dust = new THREE.Points(geo, mat);
    this._dust.userData = { seed, base: pos.slice() };
    this.group.add(this._dust);
  }

  /* Per frame: move the light pool to the nearest lamps; drift the dust. */
  update(t, camPos) {
    if (this.lamps.length) {
      const ranked = this.lamps
        .map((p) => [p, p.distanceToSquared(camPos)])
        .sort((a, b) => a[1] - b[1]);
      this.pool.forEach((light, i) => {
        const hit = ranked[i];
        if (!hit) {
          light.intensity = 0;
          return;
        }
        light.position.copy(hit[0]);
        light.intensity = 9 * (0.96 + 0.04 * Math.sin(t * 7 + i * 1.7)); // faint filament flicker
      });
    }
    if (this._dust && !this.reducedMotion) {
      const attr = this._dust.geometry.attributes.position;
      const { seed, base } = this._dust.userData;
      for (let i = 0; i < seed.length; i += 1) {
        const s = seed[i];
        attr.array[i * 3] = base[i * 3] + Math.sin(t * 0.13 + s) * 0.35;
        attr.array[i * 3 + 1] = base[i * 3 + 1] + Math.sin(t * 0.09 + s * 2) * 0.25;
        attr.array[i * 3 + 2] = base[i * 3 + 2] + Math.cos(t * 0.11 + s) * 0.35;
      }
      attr.needsUpdate = true;
    }
  }

  clear() {
    for (const child of [...this.group.children]) {
      child.traverse((o) => {
        if (o.isPoints) {
          o.geometry.dispose();
          o.material.dispose();
        } else if (o.isMesh && o.geometry.type === "PlaneGeometry") {
          o.geometry.dispose();
        }
      });
      this.group.remove(child);
    }
    this.lamps = [];
    this._dust = null;
  }
}
