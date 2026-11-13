/* bookcase-boot.js — report a failed boot instead of leaving a blank page.
 *
 * bookcase.js sets window.__bcBooted once the scene, the vendored Three.js
 * graph and the first book load have succeeded. If that never happens (a
 * missing vendored module, a CSP violation, a dead API) this classic script
 * — deliberately not a module, so it runs even when the module graph cannot
 * be parsed — surfaces the failure in the status pill.
 *
 * Inline script is blocked by the page's Content-Security-Policy; this file
 * is same-origin, so `script-src 'self'` allows it.
 */
(function () {
  "use strict";

  function report(message) {
    var pill = document.getElementById("bc-status");
    if (!pill) return;
    pill.textContent = message;
    pill.classList.add("bc-pill-error");
  }

  window.addEventListener("error", function (event) {
    // Module resolution / CSP failures surface here without a useful message.
    if (window.__bcBooted) return;
    var detail = event && event.message ? event.message : "script failed";
    report("3D engine failed to load — " + detail);
  });

  window.addEventListener("load", function () {
    window.setTimeout(function () {
      if (!window.__bcBooted) {
        report("3D engine failed to load (check the console)");
      }
    }, 4000);
  });
})();
