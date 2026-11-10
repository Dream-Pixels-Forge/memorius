/* bookcase-minimap.js — the librarian's floor plan (HUD, bottom-right).
 * Draws every case as a walnut block, the visitor as an orange arrow
 * pointing where you look, search hits as glowing dots (top hit pulses),
 * and the lantern as a small spark. Click anywhere on the plan to be
 * walked there (emits "bc:goto" {x, z}). Pure 2D canvas, redrawn ~15fps.
 */
export class Minimap {
  constructor(canvas, source) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.source = source; // {plan(), cam(), yaw(), hits(), lantern()}
    this._last = 0;
    this._view = null;
    canvas.addEventListener("click", (e) => this._click(e));
  }

  _fit(cases) {
    const b = this.source.bounds && this.source.bounds();
    if (b) return this._fitBox(b.minX, b.maxX, b.minZ, b.maxZ);
    let minX = Infinity;
    let maxX = -Infinity;
    let minZ = Infinity;
    let maxZ = -Infinity;
    for (const c of cases) {
      minX = Math.min(minX, c.aabb.minX);
      maxX = Math.max(maxX, c.aabb.maxX);
      minZ = Math.min(minZ, c.aabb.minZ);
      maxZ = Math.max(maxZ, c.aabb.maxZ);
    }
    if (!cases.length) {
      minX = -4; maxX = 4; minZ = -4; maxZ = 4;
    }
    maxZ += 4; // include the entrance / spawn
    return this._fitBox(minX, maxX, minZ, maxZ);
  }

  _fitBox(minX, maxX, minZ, maxZ) {
    const W = this.canvas.width;
    const H = this.canvas.height;
    const pad = 12;
    const s = Math.min((W - pad * 2) / (maxX - minX || 1), (H - pad * 2) / (maxZ - minZ || 1));
    const ox = (W - (maxX - minX) * s) / 2 - minX * s;
    const oz = (H - (maxZ - minZ) * s) / 2 - minZ * s;
    this._view = { s, ox, oz };
  }

  _px(x, z) {
    const v = this._view;
    return [v.ox + x * v.s, v.oz + z * v.s];
  }

  draw(t) {
    if (this.canvas.hidden) return;
    if (t - this._last < 0.066) return;
    this._last = t;
    const { ctx, canvas } = this;
    const cases = this.source.plan();
    this._fit(cases);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const c of cases) {
      const [x0, z0] = this._px(c.aabb.minX, c.aabb.minZ);
      const [x1, z1] = this._px(c.aabb.maxX, c.aabb.maxZ);
      ctx.fillStyle = "rgba(122, 82, 44, 0.85)";
      ctx.fillRect(x0, z0, Math.max(2, x1 - x0), Math.max(2, z1 - z0));
    }
    // bay names, faint, so the plan reads like a library map
    ctx.fillStyle = "rgba(241, 215, 150, 0.55)";
    ctx.font = "9px Georgia, serif";
    ctx.textAlign = "center";
    for (const bay of (this.source.bays && this.source.bays()) || []) {
      const [bx, bz] = this._px(bay.center.x, bay.center.z);
      ctx.fillText(String(bay.label).slice(0, 10), bx, bz + 3);
    }
    const hits = this.source.hits();
    hits.forEach((h, i) => {
      const [x, z] = this._px(h.x, h.z);
      const r = i === 0 ? 3.5 + 1.5 * Math.abs(Math.sin(t * 3)) : 2.5;
      ctx.fillStyle = i === 0 ? "#f97316" : "rgba(249,115,22,0.6)";
      ctx.beginPath();
      ctx.arc(x, z, r, 0, Math.PI * 2);
      ctx.fill();
    });
    const l = this.source.lantern();
    if (l) {
      const [lx, lz] = this._px(l.x, l.z);
      ctx.fillStyle = "#ffe2b0";
      ctx.beginPath();
      ctx.arc(lx, lz, 1.8, 0, Math.PI * 2);
      ctx.fill();
    }
    const cam = this.source.cam();
    const yaw = this.source.yaw();
    const [cx, cz] = this._px(cam.x, cam.z);
    ctx.save();
    ctx.translate(cx, cz);
    ctx.rotate(-yaw);
    ctx.fillStyle = "#f5efe6";
    ctx.strokeStyle = "#f97316";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, -7);
    ctx.lineTo(4.5, 5);
    ctx.lineTo(0, 2.5);
    ctx.lineTo(-4.5, 5);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  _click(e) {
    if (!this._view) return;
    const rect = this.canvas.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * this.canvas.width;
    const pz = ((e.clientY - rect.top) / rect.height) * this.canvas.height;
    const v = this._view;
    window.dispatchEvent(new CustomEvent("bc:goto", {
      detail: { x: (px - v.ox) / v.s, z: (pz - v.oz) / v.s },
    }));
  }
}
