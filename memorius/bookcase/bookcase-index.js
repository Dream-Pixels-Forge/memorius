/* bookcase-index.js — the library index panel and "surprise me".
 *
 * The index is the bookcase's table of contents: one row per bay (the
 * physical shelf alcove in the floor plan) with its book and folder counts,
 * and a click that walks the visitor to the bay's centre, facing into the
 * shelves. "Surprise me" opens a random book from the current vault.
 *
 * Pure DOM: bookcase.js owns the state, the scene and the REST calls and
 * passes them in. Keyboard: I toggles, X surprises, Escape closes;
 * handleKey() is called from the main shortcut handler so typing in a field
 * never triggers them.
 */

const ORD = ["first", "second", "third", "fourth", "fifth", "sixth",
  "seventh", "eighth"];

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/* createdAt is epoch seconds, epoch millis, or ISO — normalise to millis. */
function stamp(book) {
  const v = book.createdAt;
  const t = typeof v === "number" ? v * (v < 1e12 ? 1000 : 1) : Date.parse(v);
  return Number.isFinite(t) ? t : 0;
}

export class LibraryIndex {
  constructor(source = {}) {
    this.src = source;
    this.panel = document.getElementById("bc-index");
    this.list = document.getElementById("bc-index-list");
    this.card = document.getElementById("bc-index-card");
    this.button = document.getElementById("bc-index-btn");
    this.closeBtn = document.getElementById("bc-index-close");
    this.button.addEventListener("click", () => this.toggle());
    this.closeBtn.addEventListener("click", () => this.close());
    document.getElementById("bc-surprise")
      .addEventListener("click", () => this.surprise());
  }

  toggle() {
    if (this.panel.hidden) this.show();
    else this.close();
  }

  show() {
    this.render();
    this.panel.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    this.closeBtn.focus();
  }

  close() {
    this.panel.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  /* Returns true when the key was consumed, so the main handler stops. */
  handleKey(e) {
    const tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false;
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    const key = String(e.key || "").toLowerCase();
    if (key === "i") { e.preventDefault(); this.toggle(); return true; }
    if (key === "x") { e.preventDefault(); this.surprise(); return true; }
    if (key === "escape" && !this.panel.hidden) {
      e.preventDefault();
      this.close();
      return true;
    }
    return false;
  }

  render() {
    const plan = (this.src.plan && this.src.plan()) || { bays: [], cases: [] };
    // books and folders per bay, straight from the floor plan
    const groups = new Map();
    for (const c of plan.cases || []) {
      const g = groups.get(c.bay) || { books: 0, folders: new Set() };
      g.folders.add(c.folder);
      for (const shelf of c.shelves || []) g.books += (shelf.slots || []).length;
      groups.set(c.bay, g);
    }
    this.renderCard();
    this.list.innerHTML = "";
    const bays = plan.bays || [];
    if (!bays.length) {
      this.list.appendChild(el("p", "bc-index-empty",
        "The shelves are still being arranged — choose a vault with books."));
      return;
    }
    for (const bay of bays) {
      const g = groups.get(bay.label) || { books: 0, folders: new Set() };
      const folders = plural(g.folders.size, "folder");
      const where = `${ORD[bay.ordinal - 1] || `#${bay.ordinal}`} on the ${bay.sideName}`;
      const row = el("button", "bc-index-row");
      row.type = "button";
      row.setAttribute("aria-label",
        `${bay.label} bay, ${where}, ${plural(g.books, "book")}, ${folders}`);
      row.append(
        el("span", "bc-index-bay", bay.label),
        el("span", "bc-index-where", `${where} · ${folders}`),
        el("span", "bc-index-count", String(g.books)),
        el("span", "bc-index-unit", g.books === 1 ? "book" : "books")
      );
      row.addEventListener("click", () => this.walkTo(bay));
      this.list.appendChild(row);
    }
  }

  renderCard() {
    const books = (this.src.books && this.src.books()) || [];
    const shelves = new Set(books.map((b) => b.shelf || "default"));
    const folders = new Set(
      books.map((b) => `${b.shelf || "default"}/${b.folder || "default"}`)
    );
    const stat = (n, label) => {
      const box = el("div", "bc-index-stat");
      box.append(el("b", null, String(n)), el("span", null, label));
      return box;
    };
    this.card.innerHTML = "";
    this.card.append(
      stat(books.length, "books"),
      stat(shelves.size, "shelves"),
      stat(folders.size, "folders")
    );
    const line = el("p", "bc-index-when");
    const times = books.map(stamp).filter((t) => t > 0);
    if (!times.length) {
      line.textContent = "no dated books yet — the index fills as you store memories";
    } else {
      const age = this.src.age || ((t) => new Date(t).toLocaleDateString());
      line.textContent = `oldest ${age(Math.min(...times))} · newest ${age(Math.max(...times))}`;
    }
    this.card.appendChild(line);
  }

  /* Walk to the bay's centre, facing into the alcove. side -1 is the left of
   * the nave (negative X); yaw 0 looks down -Z, +PI/2 looks down -X. */
  walkTo(bay) {
    const yaw = bay.side < 0 ? Math.PI / 2 : -Math.PI / 2;
    window.dispatchEvent(new CustomEvent("bc:goto", {
      detail: { x: bay.center.x, z: bay.center.z, yaw },
    }));
    this.close();
    this.announce(
      `Walking you to the ${bay.label} bay, ${ORD[bay.ordinal - 1] || ""} on the ${bay.sideName}.`
    );
  }

  surprise() {
    const books = (this.src.books && this.src.books()) || [];
    if (!books.length) {
      this.announce("There are no books to surprise you with yet.");
      return;
    }
    const pick = books[Math.floor(Math.random() * books.length)];
    const shelf = pick.shelf || "default";
    const folder = pick.folder || "default";
    const note = String(pick.note || "default").replace(/[-_]+/g, " ");
    this.close();
    window.dispatchEvent(new CustomEvent("bc:fly", { detail: { id: pick.id } }));
    if (this.src.open) this.src.open(pick.id);
    this.announce(`Surprise: ${note} — ${shelf} shelf, ${folder} folder.`);
  }

  announce(text) {
    if (this.src.announce) this.src.announce(text);
  }
}
