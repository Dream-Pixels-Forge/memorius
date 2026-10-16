/* Memorius docs site — shared behaviour. Loaded at the end of every docs page. */
(function () {
  "use strict";

  /* ── Card / fade-up entrance animations ── */
  function animateElements(selector) {
    var els = document.querySelectorAll(selector);
    if (!els.length) return;
    if (!("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("visible"); });
      return;
    }
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    els.forEach(function (el) { obs.observe(el); });
  }
  animateElements(".card");
  animateElements(".fade-up");

  /* ── Docs-nav scroll-spy: mark the current page's link active ── */
  var path = (window.location.pathname || "").split("/").pop() || "index.html";
  document.querySelectorAll(".docs-links a").forEach(function (a) {
    var href = a.getAttribute("href");
    if (!href) return;
    if (href === path || (path === "" && href === "index.html") || (href === "index.html" && (path === "" || path === "index"))) {
      a.classList.add("active");
    }
  });
})();
