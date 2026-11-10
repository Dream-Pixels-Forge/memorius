/* bookcase-cases.js — builds the furniture of the vault library from the
 * floor plan (bookcase-layout.js): walnut bookcases placed and rotated
 * into their bays, cloth-bound books on the planks, folder plaques on each
 * cornice, a double-sided blade sign hanging at every bay opening (so you
 * read the shelf names as you walk down the nave), and the new-arrivals
 * table by the entrance. Each case is a THREE.Group in the case's local
 * frame (books face local +Z, reading order along local +X).
 */
import * as THREE from "three";
import {
  caseHeight, BOOK_H, BOOK_D, SHELF_T, CASE_W, CASE_D,
} from "./bookcase-layout.js";
import {
  bindingColor, spineTexture, pagesTexture, woodTexture, plaqueTexture, rand01,
} from "./bookcase-textures.js";

export class CaseBuilder {
  constructor() {
    this.bookGeo = new THREE.BoxGeometry(1, BOOK_H, BOOK_D);
    this.pagesMat = new THREE.MeshStandardMaterial({ map: pagesTexture(), roughness: 0.95 });
    this.woodMat = new THREE.MeshStandardMaterial({ map: woodTexture(), roughness: 0.68 });
    this.recencyT = () => 0.5;
  }

  /* Shared resources are never disposed with a rebuild. */
  isShared(obj) {
    return obj === this.bookGeo || obj === this.pagesMat || obj === this.woodMat ||
      obj === this.woodMat.map || obj === this.pagesMat.map;
  }

  bookMesh(book, w) {
    const t = this.recencyT(book);
    const color = bindingColor(book, t);
    const cover = new THREE.MeshStandardMaterial({ color, roughness: 0.82 });
    const spine = new THREE.MeshStandardMaterial({ map: spineTexture(book, color, t), roughness: 0.7 });
    const p = this.pagesMat;
    // box faces: +x, -x (covers) · +y, -y (page block) · +z spine · -z fore-edge
    const mesh = new THREE.Mesh(this.bookGeo, [cover, cover, p, p, spine, p]);
    mesh.scale.x = w;
    // deterministic height variety (octavo → quarto) so rows look real
    mesh.scale.y = 0.84 + 0.22 * rand01(book.id, 7);
    return mesh;
  }

  _plaque(text, w, h, emissive = 0.4) {
    const map = plaqueTexture(text);
    return new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({
      map, emissiveMap: map, emissive: 0xffffff, emissiveIntensity: emissive, roughness: 0.5,
    }));
  }

  /* One walnut bookcase: plinth, sides, cornice, backboard, planks, books,
   * folder plaque. Returns {group, books:[{mesh, book, shelf, homeZ}]}. */
  buildCase(c) {
    const group = new THREE.Group();
    group.position.set(c.x, 0, c.z);
    group.rotation.y = c.rot || 0;
    const caseH = caseHeight();
    const add = (w, h, d, x, y, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.woodMat);
      m.position.set(x, y, z);
      group.add(m);
    };
    add(CASE_W + 0.1, 0.15, CASE_D, 0, 0.075, 0); // plinth
    add(0.05, caseH, CASE_D, -(CASE_W / 2 + 0.025), caseH / 2, 0);
    add(0.05, caseH, CASE_D, CASE_W / 2 + 0.025, caseH / 2, 0);
    add(CASE_W + 0.1, 0.05, CASE_D, 0, caseH + 0.025, 0);
    add(CASE_W + 0.2, 0.07, CASE_D + 0.06, 0, caseH + 0.085, 0); // cornice
    add(CASE_W + 0.1, caseH, 0.02, 0, caseH / 2, -CASE_D / 2 + 0.01);

    const books = [];
    const homeZ = CASE_D / 2 - BOOK_D / 2 - 0.02;
    for (const shelf of c.shelves) {
      add(CASE_W, SHELF_T, CASE_D - 0.04, 0, shelf.y - SHELF_T / 2, 0);
      for (const slot of shelf.slots) {
        const mesh = this.bookMesh(slot.book, slot.w);
        mesh.position.set(slot.dx + slot.w / 2, shelf.y + (BOOK_H * mesh.scale.y) / 2, homeZ);
        group.add(mesh);
        books.push({ mesh, book: slot.book, shelf, homeZ });
      }
    }
    // the empty planks of the case still exist (a real case has 5 shelves)
    const used = new Set(c.shelves.map((s) => s.level));
    for (let lvl = 0; lvl < 5; lvl += 1) {
      if (!used.has(lvl)) add(CASE_W, SHELF_T, CASE_D - 0.04, 0, 0.15 + lvl * 0.46 - SHELF_T / 2, 0);
    }
    const plaque = this._plaque(c.label, 1.1, 0.27);
    plaque.position.set(0, caseH + 0.27, CASE_D / 2 - 0.02);
    group.add(plaque);
    return { group, books };
  }

  /* Double-sided blade sign hanging over a bay opening, perpendicular to
   * the nave, readable from the entrance and from the far end. */
  baySign(geo) {
    const group = new THREE.Group();
    group.position.set(geo.sign.x, 2.75, geo.sign.z + geo.span / 2 - 0.2);
    const front = this._plaque(geo.label, 1.4, 0.35, 0.55);
    const back = this._plaque(geo.label, 1.4, 0.35, 0.55);
    back.rotation.y = Math.PI;
    back.position.z = -0.012;
    const rod = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 3.5), this.woodMat);
    rod.position.y = 1.92;
    group.add(front, back, rod);
    return group;
  }

  /* The new-arrivals table: the newest books stand on it, spines out. */
  arrivals(table, books) {
    const group = new THREE.Group();
    group.position.set(table.x, 0, table.z);
    const top = new THREE.Mesh(new THREE.BoxGeometry(table.w, 0.05, table.d), this.woodMat);
    top.position.y = 0.76;
    group.add(top);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.74, 0.06), this.woodMat);
      leg.position.set(sx * (table.w / 2 - 0.08), 0.37, sz * (table.d / 2 - 0.08));
      group.add(leg);
    }
    const sign = this._plaque("new arrivals", 0.9, 0.22, 0.5);
    sign.position.set(0, 1.25, -table.d / 2 + 0.05);
    group.add(sign);
    const meshes = [];
    let x = -table.w / 2 + 0.1;
    for (const book of books) {
      const w = 0.05;
      if (x + w > table.w / 2 - 0.1) break;
      const mesh = this.bookMesh(book, w);
      mesh.position.set(x + w / 2, 0.785 + (BOOK_H * mesh.scale.y) / 2, 0.05);
      x += w + 0.035;
      group.add(mesh);
      meshes.push(mesh);
    }
    return { group, meshes };
  }
}
