/* bookcase-nav.js — on-screen walk controls (bottom-left).
 *
 * Hold ▲◀▼▶ to walk: pointerdown presses the key the keyboard uses,
 * pointerup / cancel / leave releases it, so the camera moves continuously
 * and focus/modifiers stay untouched. Home dispatches bc:reset-view.
 * The cluster is hidden during cinematic flights (bc:cinema) so a stray
 * press cannot fight a camera move.
 */

const KEYS = ["bc-nav-forward", "bc-nav-left", "bc-nav-back", "bc-nav-right"];

export function createNav({ walk, onHome = null } = {}) {
  const nav = document.getElementById("bc-nav");
  const buttons = [...document.querySelectorAll("#bc-nav [data-key]")];
  const home = document.getElementById("bc-nav-home");
  if (home) {
    home.addEventListener("click", () => {
      if (onHome) onHome();
    });
  }
  for (const btn of buttons) {
    const code = btn.getAttribute("data-key");
    btn.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      e.preventDefault();
      walk.press(code);
      btn.classList.add("bc-nav-active");
      if (btn.setPointerCapture && e.pointerId != null) {
        try { btn.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
      }
    });
    const up = () => {
      walk.release(code);
      btn.classList.remove("bc-nav-active");
    };
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) =>
      btn.addEventListener(t, up)
    );
  }
  // Enter / Space on a focused button: hold to keep walking (keydown repeats)
  const codeOf = (e) =>
    e.target && e.target.getAttribute && e.target.getAttribute("data-key");
  window.addEventListener("keydown", (e) => {
    const code = codeOf(e);
    if (code && (e.key === " " || e.key === "Enter")) {
      e.preventDefault();
      walk.press(code);
      e.target.classList.add("bc-nav-active");
    }
  });
  window.addEventListener("keyup", (e) => {
    const code = codeOf(e);
    if (code && (e.key === " " || e.key === "Enter")) {
      walk.release(code);
      e.target.classList.remove("bc-nav-active");
    }
  });
  // a lost focus must not leave a key stuck down
  window.addEventListener("blur", () => {
    for (const b of buttons) {
      walk.release(b.getAttribute("data-key"));
      b.classList.remove("bc-nav-active");
    }
  });
  window.addEventListener("bc:cinema", (e) => {
    if (nav) nav.hidden = !!e.detail.on;
  });
  return { buttons, keys: KEYS };
}
