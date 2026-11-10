/* bookcase.js — bootstrap + data flow + UI wiring for the vault bookcase.
 * Talks to the Memorius REST API (GET /vaults, GET /vault, GET /memories,
 * POST /search, GET /memory/{id}); API base comes from the ?api= query
 * param (set by `memorius bookcase`), defaulting to http://127.0.0.1:8912.
 * DOM contract: see the comment block at the top of bookcase.html.
 */
import { BookcaseScene } from "./bookcase-scene.js";
import { Librarian } from "./bookcase-librarian.js";
import { Minimap } from "./bookcase-minimap.js";
import { Mascot } from "./bookcase-mascot.js";

const $ = (id) => document.getElementById(id);
const API =
  new URLSearchParams(location.search).get("api") || "http://127.0.0.1:8912";
const MAX_BOOKS = 1000; // perf guard: cap the books we render

const state = {
  vault: "",
  layout: "shelf",
  books: [],
  shelfCount: 0,
  greeting: false,
  results: [],
  resultIdx: 0,
  current: null, // book open in the detail panel
};

const scene = new BookcaseScene($("bc-scene"));
const librarian = new Librarian({ onLog: logGuidance });
const minimap = new Minimap($("bc-map"), {
  plan: () => scene._cases,
  bounds: () => scene._plan && scene._plan.bounds,
  bays: () => (scene._plan ? scene._plan.bays : []),
  cam: () => scene.camera.position,
  yaw: () => scene.walk.yaw,
  hits: () => scene.hits(),
  lantern: () => scene.guide.lantern.position,
});
// the hippo librarian: waits at the entrance, meets you at the found book
const mascot = new Mascot(scene.scene, { reducedMotion: scene.reducedMotion });
const mascotFrame = mascot.attach(scene);
scene.onFrame = (t) => {
  minimap.draw(t);
  mascotFrame(t);
};

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: opts.body
      ? { "Content-Type": "application/json", ...(opts.headers || {}) }
      : opts.headers,
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

function setStatus(text, isError = false) {
  const pill = $("bc-status");
  pill.textContent = text;
  pill.classList.toggle("bc-pill-error", isError);
}

function logGuidance(text) {
  const log = $("bc-guidance");
  const line = document.createElement("div");
  line.className = "bc-line";
  line.textContent = text;
  log.appendChild(line);
  while (log.children.length > 3) log.removeChild(log.firstChild);
  mascot.hop(); // the librarian hops when he speaks
}

async function loadVaults() {
  const data = await api("/vaults");
  const vaults = data.vaults || [];
  const select = $("bc-vault");
  select.innerHTML = "";
  for (const v of vaults) {
    const opt = document.createElement("option");
    opt.value = v.name;
    opt.textContent = `${v.name} (${v.memories})`;
    select.appendChild(opt);
  }
  state.vault = vaults.some((v) => v.name === "main")
    ? "main"
    : (vaults[0] && vaults[0].name) || "";
  select.value = state.vault;
  return vaults;
}

async function selectVault(name) {
  if (!name) {
    setStatus("no vaults yet — store a memory first");
    window.dispatchEvent(new CustomEvent("bc:books", {
      detail: { books: [], layout: state.layout, vaultLabel: "" },
    }));
    return;
  }
  state.vault = name;
  setStatus(`loading ${name}…`);
  try {
    await api(`/vault?vault=${encodeURIComponent(name)}`); // hierarchy (drives labels)
    const books = await collectMemories(name);
    state.books = books;
    state.shelfCount = new Set(books.map((b) => b.shelf)).size;
    window.dispatchEvent(new CustomEvent("bc:books", {
      detail: { books, layout: state.layout, vaultLabel: name },
    }));
    setStatus(
      books.length >= MAX_BOOKS
        ? `${MAX_BOOKS} of ${books.length + 1}+ books`
        : `${books.length} books`
    );
    if (!state.greeting) {
      state.greeting = true;
      librarian.greet(books.length, state.shelfCount);
    } else {
      librarian.announceVault(name, books.length);
    }
  } catch (err) {
    setStatus("API unreachable", true);
    librarian.announceError(
      `Cannot reach the Memorius API at ${API}. Is the REST server running? (${err.message})`
    );
  }
}

async function collectMemories(vault) {
  const books = [];
  let cursor = null;
  for (;;) {
    const qs = new URLSearchParams({
      vault,
      limit: "100",
    });
    if (cursor) qs.set("cursor", cursor);
    const page = await api(`/memories?${qs.toString()}`);
    for (const m of page.memories || []) {
      books.push({
        id: m.id,
        shelf: m.shelf || "default",
        folder: m.folder || "default",
        note: m.note || "default",
        path: `${m.shelf || "default"}/${m.folder || "default"}/${m.note || "default"}`,
        contentLen: (m.content || "").length,
        createdAt: m.created_at || m.createdAt || 0,
        tags: m.tags || [],
      });
      if (books.length >= MAX_BOOKS) return books;
    }
    cursor = page.next_cursor;
    if (!cursor || !(page.memories || []).length) break;
  }
  return books;
}
/* ── search ──────────────────────────────────────────────────── */
async function runSearch(query) {
  const q = (query || "").trim();
  if (!q) return;
  setStatus(`searching "${q}"…`);
  try {
    const data = await api("/search", {
      method: "POST",
      body: JSON.stringify({
        query: q,
        limit: 5,
        vault: state.vault || undefined,
      }),
    });
    const results = (data.results || []).map((m) => ({
      id: m.id,
      shelf: m.shelf,
      folder: m.folder,
      note: m.note,
      label: `${m.shelf || "default"}/${m.folder || "default"}/${m.note || "default"}`,
      content: m.content,
      created_at: m.created_at || m.createdAt,
    }));
    // directions are computed from where the visitor stands *before* the flight
    const directions = results.length ? scene.describe(results[0].id) : null;
    state.results = results;
    state.resultIdx = 0;
    window.dispatchEvent(new CustomEvent("bc:search", {
      detail: {
        topId: results.length ? results[0].id : null,
        ids: results.map((r) => r.id),
        query: q,
      },
    }));
    renderResults(q, results, directions);
    librarian.announceSearch(q, results, directions);
    setStatus(results.length ? `${results.length} matches` : "no matches");
  } catch (err) {
    setStatus("search failed", true);
    librarian.announceError(`Search failed: ${err.message}`);
  }
}

/* N / P: walk the visitor from one result to the next. */
function stepResult(delta) {
  const list = state.results;
  if (!list.length) return;
  state.resultIdx = (state.resultIdx + delta + list.length) % list.length;
  const r = list[state.resultIdx];
  const directions = scene.describe(r.id);
  window.dispatchEvent(new CustomEvent("bc:fly", { detail: { id: r.id } }));
  document.querySelectorAll(".bc-result").forEach((el, i) =>
    el.classList.toggle("bc-result-current", i === state.resultIdx));
  librarian.announceStep(state.resultIdx, list.length, r, directions);
}

function renderResults(query, results, directions = null) {
  const panel = $("bc-detail");
  const body = $("bc-detail-body");
  body.innerHTML = "";
  const h = document.createElement("h2");
  h.textContent = `results for "${query}"`;
  body.appendChild(h);
  if (!results.length) {
    const p = document.createElement("p");
    p.className = "bc-meta";
    p.textContent = "Nothing matched. The librarian has no lead.";
    body.appendChild(p);
  }
  results.forEach((r, i) => {
    const div = document.createElement("div");
    div.className = "bc-result" + (i === 0 ? " bc-result-top" : "");
    div.innerHTML =
      `<div class="bc-result-title">${escapeHtml(r.label)}</div>` +
      `<div class="bc-result-where">shelf ${escapeHtml(r.shelf || "default")}` +
      ` / folder ${escapeHtml(r.folder || "default")}${i === 0 ? " · top hit" : ""}</div>` +
      (i === 0 && directions
        ? `<div class="bc-result-dir">${escapeHtml(directions.where)} · ${escapeHtml(directions.level)}</div>`
        : "");
    div.addEventListener("click", () => openBook(r.id));
    body.appendChild(div);
  });
  if (results.length > 1) {
    const hint = document.createElement("p");
    hint.className = "bc-meta";
    hint.textContent = "N / P to be walked to the next / previous result.";
    body.appendChild(hint);
  }
  panel.hidden = false;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ── book detail: the book drawn from the shelf and opened ──── */
function relativeDate(value) {
  const t = typeof value === "number" ? value * (value < 1e12 ? 1000 : 1) : Date.parse(value);
  if (!t || Number.isNaN(t)) return String(value || "unknown");
  const days = Math.round((Date.now() - t) / 86400000);
  const when = days <= 0 ? "today" : days === 1 ? "yesterday" : days < 60 ? `${days} days ago`
    : days < 730 ? `${Math.round(days / 30)} months ago` : `${Math.round(days / 365)} years ago`;
  return `${new Date(t).toLocaleDateString()} · ${when}`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

async function openBook(id) {
  try {
    const m = await api(`/memory/${encodeURIComponent(id)}`);
    state.current = m;
    window.dispatchEvent(new CustomEvent("bc:open", { detail: { id } }));
    const shelf = m.shelf || "default";
    const folder = m.folder || "default";
    const body = $("bc-detail-body");
    body.innerHTML = "";
    body.appendChild(el("div", "bc-crumb", `${shelf} › ${folder}`));
    const h = el("h2", "bc-title", (m.note || "default").replace(/[-_]+/g, " "));
    h.title = `${shelf}/${folder}/${m.note || "default"}`;
    body.appendChild(h);
    body.appendChild(el("div", "bc-meta", relativeDate(m.created_at || m.createdAt)));
    if (m.tags && m.tags.length) {
      const tags = el("div", "bc-tags");
      for (const t of m.tags) tags.appendChild(el("span", "bc-tag", t));
      body.appendChild(tags);
    }
    const actions = el("div", "bc-actions");
    const walkBtn = el("button", "bc-btn", "Walk me there");
    walkBtn.type = "button";
    walkBtn.addEventListener("click", () =>
      window.dispatchEvent(new CustomEvent("bc:fly", { detail: { id } })));
    const readBtn = el("button", "bc-btn", librarian.supported ? "Read aloud" : "Read aloud (n/a)");
    readBtn.type = "button";
    readBtn.disabled = !librarian.supported;
    readBtn.addEventListener("click", () => librarian.readAloud(h.textContent, m.content));
    actions.append(walkBtn, readBtn);
    body.appendChild(actions);
    body.appendChild(el("div", "bc-content", m.content || ""));
    const neighbours = state.books
      .filter((b) => b.id !== id && b.shelf === shelf && b.folder === folder)
      .slice(0, 6);
    if (neighbours.length) {
      body.appendChild(el("h3", null, "Beside it on the shelf"));
      for (const b of neighbours) {
        const row = el("div", "bc-neighbour", b.note.replace(/[-_]+/g, " "));
        row.tabIndex = 0;
        row.addEventListener("click", () => openBook(b.id));
        row.addEventListener("keydown", (e) => { if (e.key === "Enter") openBook(b.id); });
        body.appendChild(row);
      }
    }
    body.appendChild(el("div", "bc-meta bc-id", `id ${m.id}`));
    $("bc-detail").hidden = false;
  } catch (err) {
    setStatus("book not found", true);
  }
}

function closeDetail() {
  $("bc-detail").hidden = true;
  state.current = null;
  window.dispatchEvent(new CustomEvent("bc:open", { detail: { id: null } }));
}

/* Keyboard: / search · Esc close · N/P results · F fly to top · R reset ·
 * M map · ? help. Ignored while typing in a field. */
function onShortcut(e) {
  const tag = e.target && e.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key;
  if (k === "/") {
    e.preventDefault();
    $("bc-search").focus();
  } else if (k === "Escape") {
    if (!$("bc-usage").hidden) $("bc-usage").hidden = true;
    else if (!$("bc-detail").hidden) closeDetail();
    librarian.hush();
  } else if (k === "n" || k === "N") stepResult(1);
  else if (k === "p" || k === "P") stepResult(-1);
  else if ((k === "f" || k === "F") && state.results.length) {
    window.dispatchEvent(new CustomEvent("bc:fly", { detail: { id: state.results[state.resultIdx].id } }));
  } else if (k === "r" || k === "R") {
    window.dispatchEvent(new CustomEvent("bc:reset-view", { detail: {} }));
  } else if (k === "m" || k === "M") toggleMap();
  else if (k === "?") toggleHelp();
  if (/^(Key[WASD]|Arrow)/.test(e.code)) dismissHint();
}

function toggleMap() {
  const map = $("bc-map");
  map.hidden = !map.hidden;
}

function toggleHelp() {
  $("bc-usage").hidden = !$("bc-usage").hidden;
}

function dismissHint() {
  const hint = $("bc-hint");
  if (hint && !hint.classList.contains("bc-hint-gone")) hint.classList.add("bc-hint-gone");
}

/* ── wire everything ─────────────────────────────────────────── */
function wire() {
  $("bc-search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch($("bc-search").value);
  });

  $("bc-vault").addEventListener("change", (e) => selectVault(e.target.value));

  $("bc-layout").addEventListener("change", (e) => {
    state.layout = e.target.value;
    window.dispatchEvent(new CustomEvent("bc:layout", {
      detail: { layout: state.layout },
    }));
    setStatus(
      state.layout === "recency" ? "newest books lit — nothing moves" : "shelf layout"
    );
  });

  $("bc-view").addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("bc:reset-view", { detail: {} }));
  });

  $("bc-detail-close").addEventListener("click", closeDetail);
  $("bc-help").addEventListener("click", toggleHelp);
  window.addEventListener("keydown", onShortcut);
  setTimeout(dismissHint, 12000);

  // cinematic letterbox during crane moves; crosshair under pointer-lock
  window.addEventListener("bc:cinema", (e) => {
    document.body.classList.toggle("bc-cinema", !!e.detail.on);
  });
  window.addEventListener("bc:locked", (e) => {
    document.body.classList.toggle("bc-locked", !!e.detail.locked);
    if (e.detail.locked) dismissHint();
  });

  window.addEventListener("bc:book-hover", (e) => {
    const tip = $("bc-tooltip");
    const { id, x, y, label } = e.detail;
    if (!id) {
      tip.hidden = true;
      return;
    }
    tip.textContent = label;
    tip.style.left = `${Math.min(x + 14, window.innerWidth - 310)}px`;
    tip.style.top = `${y + 14}px`;
    tip.hidden = false;
  });

  window.addEventListener("bc:book-click", (e) => openBook(e.detail.id));

  // hold-to-talk microphone (Chromium only; degrades gracefully elsewhere)
  const mic = $("bc-mic");
  if (!librarian.talkSupported) {
    mic.disabled = true;
    mic.title = "Voice input needs a Chromium-based browser";
    $("bc-voice").disabled = true;
  } else {
    const stop = () => {
      mic.classList.remove("bc-talking");
      librarian.stopTalk();
    };
    mic.addEventListener("pointerdown", () => {
      mic.classList.add("bc-talking");
      const ok = librarian.startTalk((transcript) => {
        $("bc-search").value = transcript;
        runSearch(transcript);
        stop();
      });
      if (!ok) stop();
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach((ev) =>
      mic.addEventListener(ev, stop)
    );
  }

  // TTS voice picker
  const voiceSelect = $("bc-voice");
  if (librarian.supported) {
    for (const v of librarian.voices) {
      const opt = document.createElement("option");
      opt.value = v.voiceURI;
      opt.textContent = `${v.name} (${v.lang})`;
      voiceSelect.appendChild(opt);
    }
    voiceSelect.value = (librarian.voice && librarian.voice.voiceURI) || "";
    voiceSelect.addEventListener("change", () => {
      if (librarian.setVoiceByUri(voiceSelect.value)) {
        librarian.say(`Voice set to ${librarian.voice.name}.`);
      }
    });
  }

  // librarian on/off — guidance stays visible as text either way
  const toggle = $("bc-librarian");
  toggle.addEventListener("change", () => {
    librarian.enabled = toggle.checked;
    if (librarian.enabled) {
      librarian.greet(state.books.length, state.shelfCount);
    } else {
      logGuidance("Librarian voice off — guidance continues in text only.");
    }
  });
}

async function init() {
  wire();
  try {
    await loadVaults();
    await selectVault(state.vault);
  } catch (err) {
    setStatus("API unreachable", true);
    librarian.announceError(
      `Cannot reach the Memorius API at ${API}. Start it with \`memorius serve-rest\`. (${err.message})`
    );
  }
  window.__bcBooted = true;
}

init();


