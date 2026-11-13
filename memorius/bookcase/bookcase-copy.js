/* bookcase-copy.js — copy a memory to the clipboard, with a fallback.
 *
 * navigator.clipboard needs a secure context (loopback counts), but the
 * bookcase can be opened over plain http from another host, so fall back
 * to a hidden textarea + execCommand("copy"). copyButton() is the small
 * UI wrapper the detail panel uses: it flashes the result, then resets.
 */

export async function copyText(text) {
  const value = text == null ? "" : String(text);
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* permission denied or insecure origin — try the textarea path */
  }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/* A "Copy" button: copies getText() (string or function), flashes
 * "Copied" / "Copy failed", then resets. resetMs exists for tests. */
export function copyButton(getText, resetMs = 1600) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "bc-btn";
  btn.textContent = "Copy";
  btn.addEventListener("click", async () => {
    const text = typeof getText === "function" ? getText() : getText;
    const ok = await copyText(text);
    btn.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => { btn.textContent = "Copy"; }, resetMs);
  });
  return btn;
}
