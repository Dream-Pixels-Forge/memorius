/* bookcase-reader.js — the centered reader for one memory.
 *
 * A clicked book used to fill the narrow side panel; reading is now a
 * dialog: fetch the memory, draw it out of the shelf ("bc:open"), and show
 * it at a comfortable measure with Copy / Read aloud / Walk me there. The
 * fetch carries a token so a slow response for book A cannot replace the
 * newer book B. While open, Tab is trapped in the panel, Escape / the
 * close button / the backdrop close it, and focus returns to whatever was
 * focused before (the search box, usually). "#bc-detail" is now only the
 * search-results panel.
 */
import { copyButton } from "./bookcase-copy.js";

const $ = (id) => document.getElementById(id);

export function createReader({
  api,
  librarian,
  setStatus,
  books = () => [],
  announce = null,
}) {
  const root = $("bc-reader");
  const backdrop = $("bc-reader-backdrop");
  const panel = $("bc-reader-panel");
  const crumb = $("bc-reader-crumb");
  const title = $("bc-reader-title");
  const meta = $("bc-reader-meta");
  const tags = $("bc-reader-tags");
  const closeBtn = $("bc-reader-close");
  const actions = $("bc-reader-actions");
  const body = $("bc-reader-body");
  const foot = $("bc-reader-foot");

  let token = 0; // last request wins
  let currentId = null;
  let lastFocus = null;

  function close() {
    if (root.hidden) return;
    root.hidden = true;
    document.body.classList.remove("bc-reader-open");
    currentId = null;
    token += 1; // a fetch still in flight must not reopen it
    window.dispatchEvent(new CustomEvent("bc:open", { detail: { id: null } }));
    if (lastFocus && lastFocus.focus) lastFocus.focus();
    lastFocus = null;
  }

  async function open(id) {
    const mine = ++token;
    try {
      const m = await api(`/memory/${encodeURIComponent(id)}`);
      if (mine !== token) return; // a newer book was asked for
      if (root.hidden) lastFocus = document.activeElement;
      render(m, id);
      root.hidden = false;
      document.body.classList.add("bc-reader-open");
      currentId = id;
      window.dispatchEvent(new CustomEvent("bc:open", { detail: { id } }));
      if (closeBtn.focus) closeBtn.focus();
    } catch (err) {
      if (mine !== token) return;
      setStatus("book not found", true);
      if (announce) announce(`I could not open that book: ${err.message}`);
    }
  }

  function handleKey(e) {
    if (root.hidden) return false;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return true;
    }
    if (e.key !== "Tab") return false;
    const items = [...panel.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), ' +
      'select:not([disabled]), textarea:not([disabled]), ' +
      '[tabindex]:not([tabindex="-1"])'
    )];
    if (!items.length) return false;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !items.includes(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !items.includes(active))) {
      e.preventDefault();
      first.focus();
    }
    return true;
  }

  function button(label, onClick, className = "bc-btn") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = className;
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  function render(m, id) {
    const shelf = m.shelf || "default";
    const folder = m.folder || "default";
    crumb.textContent = `${shelf} › ${folder}`;
    title.textContent = (m.note || "default").replace(/[-_]+/g, " ");
    title.title = `${shelf}/${folder}/${m.note || "default"}`;
    const tagList = m.tags || [];
    const when = relativeDate(m.created_at || m.createdAt);
    meta.textContent = [when, tagList.length ? `tagged ${tagList.join(", ")}` : ""]
      .filter(Boolean)
      .join(" · ");
    tags.innerHTML = "";
    for (const t of tagList) {
      const chip = document.createElement("span");
      chip.className = "bc-tag";
      chip.textContent = t;
      tags.appendChild(chip);
    }

    actions.innerHTML = "";
    const copy = copyButton(() => m.content || "");
    copy.id = "bc-reader-copy";
    const read = button(
      librarian.supported ? "Read aloud" : "Read aloud (n/a)",
      () => librarian.readAloud(title.textContent, m.content || "")
    );
    read.disabled = !librarian.supported;
    const walk = button("Walk me there", () =>
      window.dispatchEvent(new CustomEvent("bc:fly", { detail: { id } })));
    actions.append(copy, read, walk, button("Close", close));

    body.innerHTML = "";
    const text = document.createElement("div");
    text.className = "bc-reader-text";
    text.textContent = m.content || "(this memory is empty)";
    body.appendChild(text);
    const beside = books()
      .filter((b) => b.id !== id && b.shelf === shelf && b.folder === folder)
      .slice(0, 6);
    if (beside.length) {
      const h = document.createElement("h3");
      h.textContent = "Beside it on the shelf";
      body.appendChild(h);
      for (const b of beside) {
        const row = button(
          (b.note || "default").replace(/[-_]+/g, " "),
          () => open(b.id),
          "bc-neighbour"
        );
        body.appendChild(row);
      }
    }
    foot.textContent = `id ${m.id || id}`;
  }

  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", close);

  return {
    open,
    close,
    handleKey,
    get id() {
      return currentId;
    },
  };
}

function relativeDate(value) {
  const t = typeof value === "number" ? value * (value < 1e12 ? 1000 : 1) : Date.parse(value);
  if (!t || Number.isNaN(t)) return String(value || "unknown");
  const days = Math.round((Date.now() - t) / 86400000);
  const when = days <= 0 ? "today" : days === 1 ? "yesterday" : days < 60 ? `${days} days ago`
    : days < 730 ? `${Math.round(days / 30)} months ago` : `${Math.round(days / 365)} years ago`;
  return `${new Date(t).toLocaleDateString()} · ${when}`;
}
