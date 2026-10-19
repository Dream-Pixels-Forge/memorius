/* bookcase-layout.js — pure floor-plan math for the walkable vault library.
 * Turns grouped book rows (one row per shelf) into a deterministic plan of
 * bookcase units arranged in walkable aisles: rows of cases along X, aisles
 * along Z, each case holding up to SHELVES_PER_CASE shelves of upright,
 * centred books. Plain numbers only (no THREE) so the plan is inspectable
 * and testable; bookcase-scene.js consumes it and builds the meshes.
 */
export const FLOOR_Y = 0;
export const EYE_Y = 1.65; // eye height while walking (metres)
export const BOOK_H = 0.32;
export const BOOK_D = 0.22;
export const MIN_W = 0.035;
export const MAX_W = 0.09;
export const GAP = 0.008;
export const SHELF_T = 0.03; // plank thickness
export const SHELF_Y0 = 0.15; // top of the lowest plank
export const SHELF_SPACING = 0.46;
export const SHELVES_PER_CASE = 5;
export const CASE_W = 1.9; // usable plank length
export const CASE_D = 0.34; // case depth (books + backboard)
export const CASE_GAP = 0.9; // gap between cases in the same row
export const AISLE = 2.2; // walking corridor between case rows
export const CASES_PER_ROW = 6;
export const SHELF_USABLE = CASE_W - 0.08;
export const MIN_SECTIONS = 3;
export const SPAWN_BACK = 3.2; // spawn distance in front of the first row

export function caseHeight() {
  return SHELF_Y0 + (SHELVES_PER_CASE - 1) * SHELF_SPACING + 0.14;
}

/* Greedily pack slots into shelves by width so no shelf overflows. */
export function packShelves(slots) {
  const shelves = [];
  let cur = [];
  let w = 0;
  for (const slot of slots) {
    const next = w + slot.w + (cur.length ? GAP : 0);
    if (cur.length && next > SHELF_USABLE) {
      shelves.push(cur);
      cur = [];
      w = 0;
    }
    cur.push(slot);
    w += slot.w + (cur.length > 1 ? GAP : 0);
  }
  if (cur.length) shelves.push(cur);
  return shelves;
}

/* Split one shelf-row into labelled units of at most SHELVES_PER_CASE
 * shelves so very large shelves become several walkable bookcases. */
function chunkIntoUnits(shelfName, slots) {
  const shelves = packShelves(slots);
  const groups = [];
  for (let i = 0; i < shelves.length; i += SHELVES_PER_CASE) {
    groups.push(shelves.slice(i, i + SHELVES_PER_CASE));
  }
  return groups.map((shelfGroup, i) => ({
    label:
      groups.length > 1 ? `${shelfName} · ${i + 1}` : String(shelfName),
    slots: shelfGroup.flat(),
  }));
}

/* Guarantee ≥ MIN_SECTIONS units when there are enough books, by halving
 * the largest unit until the floor is met (deterministic split point). */
function ensureMinSections(units) {
  while (units.length < MIN_SECTIONS) {
    let big = -1;
    let bigLen = 0;
    units.forEach((u, i) => {
      if (u.slots.length > bigLen) {
        bigLen = u.slots.length;
        big = i;
      }
    });
    if (bigLen < 2) break; // cannot split further
    const u = units[big];
    const mid = Math.floor(u.slots.length / 2);
    units.splice(
      big,
      1,
      { label: u.label, slots: u.slots.slice(0, mid) },
      { label: u.label, slots: u.slots.slice(mid) }
    );
  }
}

/* Build the full floor plan.
 * rows: [{shelf, slots:[{book, w}]}] — one entry per shelf, slots in order.
 * Returns {cases, spawn}: cases have {label, x, z, shelves:[{y, xMin, xMax,
 * slots:[{book, w, dx, dy}]}], aabb:{minX,maxX,minZ,maxZ}}; spawn is the
 * starting camera position for the walk. */
export function planSections(rows) {
  const units = [];
  for (const row of rows) units.push(...chunkIntoUnits(row.shelf, row.slots));
  ensureMinSections(units);

  const cases = [];
  let rowIdx = -1;
  for (let i = 0; i < units.length; i += CASES_PER_ROW) {
    rowIdx += 1;
    const rowUnits = units.slice(i, i + CASES_PER_ROW);
    const z = -rowIdx * (CASE_D + AISLE);
    rowUnits.forEach((u, j) => {
      const x = (j - (rowUnits.length - 1) / 2) * (CASE_W + CASE_GAP);
      const shelves = [];
      u.slots && packShelves(u.slots).forEach((shelfSlots, k) => {
        const y = SHELF_Y0 + k * SHELF_SPACING;
        const width = shelfSlots.reduce(
          (a, s) => a + s.w + GAP,
          -GAP
        );
        let dx = -width / 2;
        const placed = shelfSlots.map((s) => {
          const entry = { book: s.book, w: s.w, dx };
          dx += s.w + GAP;
          return entry;
        });
        shelves.push({
          y,
          xMin: x - width / 2,
          xMax: x + width / 2,
          slots: placed,
        });
      });
      cases.push({
        label: u.label,
        x,
        z,
        shelves,
        aabb: {
          minX: x - CASE_W / 2 - 0.05,
          maxX: x + CASE_W / 2 + 0.05,
          minZ: z - CASE_D / 2 - 0.05,
          maxZ: z + CASE_D / 2 + 0.05,
        },
      });
    });
  }
  const spawn = { x: 0, y: EYE_Y, z: SPAWN_BACK };
  return { cases, spawn };
}
