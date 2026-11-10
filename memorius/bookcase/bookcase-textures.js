/* bookcase-textures.js — procedural canvas textures for the vault library.
 * Everything is painted at runtime (no image assets, no downloads):
 * cloth/leather book spines with gilt bands and cylindrical shading, wood
 * grain for the cases, parquet for the floor, a brass section plaque, a
 * soft radial glow (lantern, dust) and a contact-shadow blob.
 * Colour language: hue = folder (stable hash into a bookbinder palette),
 * brightness/gilt = recency (fresh books are lively, old ones age).
 */
import * as THREE from "three";

/* Bookbinder cloth palette — oxblood, forest, navy, ochre, plum, teal,
 * umber, slate, mustard, brick, moss, ink. */
export const BINDINGS = [
  "#6b1e1e", "#1f3d2b", "#1c2a44", "#8a5a1c", "#43233f", "#1d4a4a",
  "#4a2f1d", "#2f3438", "#9a7b2a", "#8a3b24", "#3f4a22", "#1a1f2e",
];
export const GILT = "#d9b25f";
export const ACCENT = "#f97316";

/* Small stable string hash (FNV-1a) → unsigned int. */
export function hash(str) {
  let h = 2166136261;
  const s = String(str || "");
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/* Deterministic 0..1 value from a key + salt. */
export function rand01(key, salt = 0) {
  return (hash(`${key}|${salt}`) % 10007) / 10007;
}

/* Binding colour: hue family from the folder, aged by recency t (0 old → 1 new). */
export function bindingColor(book, t) {
  const base = new THREE.Color(BINDINGS[hash(`${book.shelf}/${book.folder}`) % BINDINGS.length]);
  const hsl = {};
  base.getHSL(hsl);
  const jitter = (rand01(book.id, 1) - 0.5) * 0.05;
  const light = THREE.MathUtils.clamp(hsl.l * (0.72 + 0.6 * t) + jitter, 0.06, 0.5);
  const sat = THREE.MathUtils.clamp(hsl.s * (0.6 + 0.5 * t), 0, 1);
  return new THREE.Color().setHSL(hsl.h + jitter * 0.3, sat, light);
}

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")];
}

function tex(c, { repeat = null, srgb = true } = {}) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) {
    t.wrapS = THREE.RepeatWrapping;
    t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat[0], repeat[1]);
  }
  t.anisotropy = 4;
  return t;
}

/* Book spine: cylindrical shading, head/tail gilt bands, vertical title,
 * folder label plate. t = recency (gilt brightness). */
export function spineTexture(book, color, t) {
  const [c, ctx] = canvas(64, 256);
  const hex = "#" + color.getHexString();
  ctx.fillStyle = hex;
  ctx.fillRect(0, 0, 64, 256);
  // cloth weave noise
  for (let i = 0; i < 260; i += 1) {
    const x = rand01(book.id, i) * 64;
    const y = rand01(book.id, i + 999) * 256;
    ctx.fillStyle = i % 2 ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.06)";
    ctx.fillRect(x, y, 2, 1);
  }
  // rounded-spine shading: dark edges, soft highlight left of centre
  const g = ctx.createLinearGradient(0, 0, 64, 0);
  g.addColorStop(0, "rgba(0,0,0,0.55)");
  g.addColorStop(0.32, "rgba(255,255,255,0.10)");
  g.addColorStop(0.55, "rgba(0,0,0,0.0)");
  g.addColorStop(1, "rgba(0,0,0,0.6)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 256);
  // gilt bands (head + tail); fresher books shine brighter
  const gilt = new THREE.Color(GILT).multiplyScalar(0.55 + 0.45 * t);
  ctx.fillStyle = "#" + gilt.getHexString();
  for (const y of [14, 22, 230, 238]) ctx.fillRect(4, y, 56, 2);
  // title, set vertically like a real spine
  const title = String(book.note || book.path || book.id || "").replace(/[-_]+/g, " ");
  ctx.save();
  ctx.translate(34, 128);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = "#" + gilt.clone().lerp(new THREE.Color("#f5efe6"), 0.35).getHexString();
  ctx.font = "600 17px Georgia, 'Times New Roman', serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(title.length > 16 ? title.slice(0, 15) + "…" : title, 0, 0);
  ctx.restore();
  // folder label plate near the tail
  ctx.fillStyle = "rgba(0,0,0,0.38)";
  ctx.fillRect(14, 196, 36, 20);
  ctx.fillStyle = "#" + gilt.getHexString();
  ctx.font = "bold 12px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(book.folder || "·").slice(0, 3).toUpperCase(), 32, 207);
  return tex(c);
}

/* Page-block texture (tops and fore-edges of books). */
let _pages = null;
export function pagesTexture() {
  if (_pages) return _pages;
  const [c, ctx] = canvas(64, 64);
  ctx.fillStyle = "#d9cdb4";
  ctx.fillRect(0, 0, 64, 64);
  for (let y = 0; y < 64; y += 2) {
    ctx.fillStyle = y % 4 ? "rgba(120,100,70,0.10)" : "rgba(255,255,255,0.10)";
    ctx.fillRect(0, y, 64, 1);
  }
  _pages = tex(c);
  return _pages;
}

/* Walnut wood grain for the bookcases. */
let _wood = null;
export function woodTexture() {
  if (_wood) return _wood;
  const [c, ctx] = canvas(256, 256);
  ctx.fillStyle = "#3b2715";
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 90; i += 1) {
    const y = rand01("wood", i) * 256;
    const amp = 2 + rand01("wood", i + 300) * 6;
    ctx.strokeStyle = i % 3 ? "rgba(20,10,4,0.28)" : "rgba(120,80,40,0.18)";
    ctx.lineWidth = 0.6 + rand01("wood", i + 600) * 1.6;
    ctx.beginPath();
    for (let x = 0; x <= 256; x += 8) {
      const yy = y + Math.sin((x / 256) * Math.PI * 2 + i) * amp;
      if (x === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();
  }
  _wood = tex(c, { repeat: [1, 1] });
  return _wood;
}

/* Parquet planks for the floor (tiled across the whole hall). */
export function floorTexture() {
  const [c, ctx] = canvas(512, 512);
  const plankW = 64;
  const plankL = 256;
  for (let col = 0; col < 512 / plankW; col += 1) {
    const offset = (col % 2) * (plankL / 2);
    for (let row = -1; row < 512 / plankL + 1; row += 1) {
      const y = row * plankL + offset;
      const tone = 0.75 + rand01("floor", col * 31 + row) * 0.35;
      const base = new THREE.Color("#2a1b0f").multiplyScalar(tone);
      ctx.fillStyle = "#" + base.getHexString();
      ctx.fillRect(col * plankW, y, plankW, plankL);
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fillRect(col * plankW, y, 2, plankL);
      ctx.fillRect(col * plankW, y, plankW, 2);
      for (let k = 0; k < 7; k += 1) {
        ctx.fillStyle = "rgba(0,0,0,0.08)";
        const gx = col * plankW + 6 + rand01("grain", col + row * 7 + k) * (plankW - 12);
        ctx.fillRect(gx, y + 4, 1, plankL - 8);
      }
    }
  }
  return tex(c, { repeat: [60, 60] });
}

/* Brass-framed walnut plaque carrying the section name. */
export function plaqueTexture(text) {
  const [c, ctx] = canvas(512, 128);
  const g = ctx.createLinearGradient(0, 0, 0, 128);
  g.addColorStop(0, "#2a1a0d");
  g.addColorStop(1, "#160d06");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 128);
  ctx.strokeStyle = GILT;
  ctx.lineWidth = 5;
  ctx.strokeRect(6, 6, 500, 116);
  ctx.lineWidth = 1.5;
  ctx.strokeRect(15, 15, 482, 98);
  ctx.fillStyle = "#f1d796";
  ctx.font = "600 50px Georgia, 'Times New Roman', serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const label = String(text);
  ctx.fillText(label.length > 20 ? label.slice(0, 19) + "…" : label, 256, 68);
  return tex(c);
}

/* Soft radial glow used for the lantern, dust motes and lamp bulbs. */
let _glow = null;
export function glowTexture() {
  if (_glow) return _glow;
  const [c, ctx] = canvas(128, 128);
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.18, "rgba(255,230,180,0.85)");
  g.addColorStop(0.45, "rgba(255,170,80,0.25)");
  g.addColorStop(1, "rgba(255,140,40,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  _glow = tex(c);
  return _glow;
}

/* Contact-shadow blob that grounds each case on the floor. */
let _shadow = null;
export function shadowTexture() {
  if (_shadow) return _shadow;
  const [c, ctx] = canvas(128, 64);
  const g = ctx.createRadialGradient(64, 32, 4, 64, 32, 64);
  g.addColorStop(0, "rgba(0,0,0,0.75)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 64);
  _shadow = tex(c);
  return _shadow;
}
