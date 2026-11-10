/* bookcase-layout.js — pure floor-plan math for the vault library.
 *
 * The vault is a building and its hierarchy is the architecture:
 *   vault  → the hall (one per vault)
 *   shelf  → a named BAY: a U-shaped alcove opening off a straight central
 *            NAVE, bays alternating left / right as you walk in
 *   folder → one bookcase (or a run of neighbouring cases) inside its bay,
 *            never split across bays, labelled on its cornice
 *   note   → one upright book; books read left → right, starting at eye
 *            level and flowing down, the top shelf being overflow
 * Inside a bay, cases run clockwise as you enter: left wall going in, back
 * wall, right wall coming out — one continuous reading order.
 * Positions are STABLE: the plan depends only on names, never on dates, so
 * a book keeps its place and your spatial memory stays valid ("projects
 * bay, second on your left, refs case, eye level"). Recency is shown with
 * light (scene) and on the new-arrivals table by the entrance.
 *
 * Plain numbers only (no THREE) so the plan is inspectable and testable.
 * Every case is described in its own LOCAL frame (centre at origin, books
 * facing local +Z, reading order along local +X) plus a world placement
 * {x, z, rot}; aabb is the world-space footprint used for walk collision.
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
export const FILL_ORDER = [3, 2, 1, 0, 4]; // eye level first, down, top = overflow
export const CASE_W = 1.9; // usable plank length
export const CASE_D = 0.34; // case depth (books + backboard)
export const CASE_STEP = CASE_W + 0.2; // case pitch along a wall (side boards + 10 cm gap)
export const SHELF_USABLE = CASE_W - 0.08;
export const NAVE = 3.2; // width of the central walkway
export const AISLE = NAVE; // (kept for callers: the main walking corridor)
export const BAY_BACK = 2; // cases on a bay's back wall
export const MAX_SIDE = 5; // cases per bay side wall before a "II" bay opens
export const BAY_SECTION_CAP = BAY_BACK + 2 * MAX_SIDE;
export const BAY_GAP = 0.9; // pier between neighbouring bays along the nave
export const HALL = 6.0; // entrance hall depth (desk, new-arrivals table)
export const MIN_SECTIONS = 3;
export const SPAWN_BACK = HALL + 0.4; // spawn z, just inside the doors

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

/* One folder → one or more case units of ≤ SHELVES_PER_CASE shelves. */
function folderUnits(folder, slots) {
  const shelves = packShelves(slots);
  const units = [];
  for (let i = 0; i < shelves.length; i += SHELVES_PER_CASE) {
    units.push(shelves.slice(i, i + SHELVES_PER_CASE));
  }
  return units.map((shelfRows, i) => ({
    label: units.length > 1 ? `${folder} · ${i + 1}` : String(folder),
    folder: String(folder),
    rows: shelfRows,
  }));
}

/* Tiny vaults: guarantee ≥ MIN_SECTIONS cases by splitting the fullest
 * case's rows in two (deterministic), so there is always a room to walk. */
function ensureMinCases(bays) {
  const all = () => bays.flatMap((b) => b.units);
  while (all().length < MIN_SECTIONS) {
    let best = null;
    for (const b of bays) for (const u of b.units) {
      const n = u.rows.flat().length;
      if (n >= 2 && (!best || n > best.n)) best = { b, u, n };
    }
    if (!best) break;
    const flat = best.u.rows.flat();
    const mid = Math.floor(flat.length / 2);
    const i = best.b.units.indexOf(best.u);
    best.b.units.splice(i, 1,
      { ...best.u, label: `${best.u.folder} · a`, rows: packShelves(flat.slice(0, mid)) },
      { ...best.u, label: `${best.u.folder} · b`, rows: packShelves(flat.slice(mid)) });
  }
}

/* Lay a unit's shelf rows into the local case frame. */
function shelvesFor(rows) {
  return rows.map((shelfSlots, k) => {
    const level = FILL_ORDER[k];
    const width = shelfSlots.reduce((a, s) => a + s.w + GAP, -GAP);
    let dx = -width / 2;
    const slots = shelfSlots.map((s) => {
      const entry = { book: s.book, w: s.w, dx };
      dx += s.w + GAP;
      return entry;
    });
    return { y: SHELF_Y0 + level * SHELF_SPACING, level, xMin: -width / 2, xMax: width / 2, slots };
  });
}

function footprint(x, z, rot) {
  const across = Math.abs(Math.sin(rot)) > 0.5; // case runs along world Z
  const hw = (across ? CASE_D : CASE_W + 0.05) / 2 + 0.05;
  const hd = (across ? CASE_W + 0.05 : CASE_D) / 2 + 0.05;
  return { minX: x - hw, maxX: x + hw, minZ: z - hd, maxZ: z + hd };
}

/* Place one bay. side = -1 (left of the nave) | +1 (right); z0 = the bay's
 * edge nearest the entrance. Returns cases + the bay's own geometry. */
function placeBay(bay, side, z0) {
  const units = bay.units;
  const C = units.length;
  const m = Math.min(C, BAY_BACK);
  const nLeft = Math.ceil(Math.max(0, C - m) / 2);
  const nRight = C - m - nLeft;
  const nSide = Math.max(nLeft, nRight);
  const span = m * CASE_STEP + 2 * CASE_D + 0.2; // along Z
  const depth = nSide * CASE_STEP + CASE_D + 0.25; // along X, out from the nave
  const xIn = side * (NAVE / 2); // bay opening edge
  const xBack = side * (NAVE / 2 + depth - CASE_D / 2);
  const zNear = z0 - CASE_D / 2; // wall nearest the entrance (faces -Z)
  const zFar = z0 - span + CASE_D / 2; // far wall (faces +Z)
  const along = (i) => xIn + side * (0.05 + (i + 0.5) * CASE_STEP);
  // reading order = clockwise as you face into the bay
  const seats = [];
  const leftWall = side > 0 ? { z: zFar, rot: 0 } : { z: zNear, rot: Math.PI };
  const rightWall = side > 0 ? { z: zNear, rot: Math.PI } : { z: zFar, rot: 0 };
  for (let i = 0; i < nLeft; i += 1) seats.push({ x: along(i), z: leftWall.z, rot: leftWall.rot });
  for (let i = 0; i < m; i += 1) {
    const t = (i + 0.5) * CASE_STEP - (m * CASE_STEP) / 2; // offset from bay centre
    const zc = z0 - span / 2 + (side > 0 ? t : -t);
    seats.push({ x: xBack, z: zc, rot: side > 0 ? -Math.PI / 2 : Math.PI / 2 });
  }
  for (let i = nRight - 1; i >= 0; i -= 1) seats.push({ x: along(i), z: rightWall.z, rot: rightWall.rot });

  const cases = units.map((u, i) => {
    const s = seats[i];
    return {
      label: u.label, folder: u.folder, bay: bay.label, x: s.x, z: s.z, rot: s.rot,
      shelves: shelvesFor(u.rows), aabb: footprint(s.x, s.z, s.rot),
    };
  });
  const xOut = xIn + side * depth;
  return {
    cases,
    geo: {
      label: bay.label, side, span, depth,
      minX: Math.min(xIn, xOut), maxX: Math.max(xIn, xOut), minZ: z0 - span, maxZ: z0,
      center: { x: (xIn + xOut) / 2, z: z0 - span / 2 },
      sign: { x: xIn + side * 0.35, z: z0 - span / 2 }, // blade sign at the opening
    },
  };
}

/* Build the full floor plan.
 * rows: [{shelf, folders:[{folder, slots:[{book, w}]}]}], sorted by name.
 * Returns {cases, bays, lamps, spawn, desk, table, props, bounds}. */
export function planSections(rows) {
  const bays = [];
  for (const row of rows) {
    const units = row.folders.flatMap((f) => folderUnits(f.folder, f.slots));
    for (let i = 0, part = 0; i < units.length; i += BAY_SECTION_CAP, part += 1) {
      const roman = ["", " II", " III", " IV", " V", " VI"][part] ?? ` ${part + 1}`;
      bays.push({ label: `${row.shelf}${roman}`, units: units.slice(i, i + BAY_SECTION_CAP) });
    }
  }
  ensureMinCases(bays);

  const cases = [];
  const bayGeo = [];
  let z = -0.4; // first pair of bays starts just past the entrance hall
  for (let i = 0; i < bays.length; i += 2) {
    const pair = [placeBay(bays[i], -1, z)];
    if (bays[i + 1]) pair.push(placeBay(bays[i + 1], +1, z));
    pair.forEach((p, j) => {
      p.geo.ordinal = i / 2 + 1; // nth bay on its side, counted from the doors
      p.geo.sideName = j === 0 ? "left" : "right";
      cases.push(...p.cases.map((c) => ({ ...c, bayOrdinal: p.geo.ordinal, baySide: p.geo.sideName })));
      bayGeo.push(p.geo);
    });
    z -= Math.max(...pair.map((p) => p.geo.span)) + BAY_GAP;
  }
  const endZ = z + BAY_GAP;

  const lamps = [];
  for (let lz = HALL - 1.5; lz > endZ; lz -= 3.6) lamps.push({ x: 0, z: lz });
  for (const b of bayGeo) lamps.push({ x: b.center.x, z: b.center.z });

  const desk = { x: -1.3, z: SPAWN_BACK - 3.4 }; // the librarian's spot
  const table = { x: 1.35, z: SPAWN_BACK - 3.6, w: 1.6, d: 0.7 }; // new arrivals
  const props = [{
    minX: table.x - table.w / 2 - 0.05, maxX: table.x + table.w / 2 + 0.05,
    minZ: table.z - table.d / 2 - 0.05, maxZ: table.z + table.d / 2 + 0.05,
  }];
  const xs = bayGeo.flatMap((b) => [b.minX, b.maxX]).concat([-NAVE, NAVE]);
  const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: endZ - 1, maxZ: HALL + 1 };
  const spawn = { x: 0, y: EYE_Y, z: SPAWN_BACK };
  return { cases, bays: bayGeo, lamps, spawn, desk, table, props, bounds };
}

const ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"];

/* Turn a book's offset from the visitor (dx, dz in metres, yaw of the
 * view) into words a librarian would say: "in the projects bay, second on
 * your left from the doors — refs case, eye level — about 6 metres ahead". */
export function describePlace(dx, dz, yaw, level, caseLabel, bay = null) {
  const ahead = dx * -Math.sin(yaw) + dz * -Math.cos(yaw);
  const side = dx * Math.cos(yaw) + dz * -Math.sin(yaw);
  const metres = Math.max(1, Math.round(Math.hypot(dx, dz)));
  const lr = side > 0 ? "right" : "left";
  let where;
  if (metres <= 1) where = "right in front of you";
  else if (ahead > Math.abs(side) * 1.5) {
    where = `about ${metres} metres ahead${Math.abs(side) > 1.5 ? `, bearing ${lr}` : ""}`;
  } else if (ahead < -Math.abs(side)) where = `about ${metres} metres behind you`;
  else where = `about ${metres} metres to your ${lr}`;
  const levels = ["bottom shelf", "shelf below the middle", "middle shelf, at chest height",
    "eye-level shelf", "top shelf"];
  const lvl = levels[level] || "middle shelf";
  const bayText = bay
    ? `the ${bay.label} bay, ${ORD[bay.ordinal - 1] || `#${bay.ordinal}`} on the ${bay.side} from the doors — `
    : "";
  return {
    case: caseLabel, level: lvl, where, bay: bay && bay.label,
    text: `in ${bayText}${caseLabel} case, ${lvl} — ${where}`,
  };
}
