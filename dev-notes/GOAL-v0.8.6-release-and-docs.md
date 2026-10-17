## Goal: Ship memorius v0.8.6, split the landing page by concern, add user documentation on the site, slim down the README

### Objective
Complete the v0.8.6 release pipeline (tag + GitHub release + PyPI publish), then restructure the monolithic `docs/index.html` landing page into concern-based sections, add full user documentation (getting started + everything needed to work with memorius) as pages within the site, and slim the README down to a quick-start that links out to the on-site documentation.

### Context
- `a29fa6b` (feat: repair + --json) and `5fa4d9e` (chore: bump 0.8.6 + changelog) are committed and pushed to `origin/main`. Issue #21 is closed.
- Nothing has shipped v0.8.6 yet: no git tag, no release, no PyPI publish. Per project memory, v0.8.5 was published via **trusted publishing on GitHub release** — so a tag + GitHub release is the expected publish path.
- `docs/index.html` is 1,188 lines: hero, install, how-it-works, CLI reference, feature narrative all in one file. GitHub Pages deploys `docs/` as a static site on any push touching `docs/**`.
- The README (808 lines) duplicates much of the on-site content; the user wants it simplified into a quick-start that redirects to the site's docs.
- GitHub Pages supports multi-page static sites, so the split pages can live as separate HTML files under `docs/` and be linked from the landing page.

### Deliverables
- [x] v0.8.6 shipped: git tag `v0.8.6` pushed, GitHub release created, PyPI shows 0.8.6 as latest
- [x] `docs/index.html` split into concern-based files (e.g. landing/hero, getting-started, CLI reference, architecture, integration) — no single monolithic file
- [x] On-site documentation covering: what memorius is, install, quick start, CLI reference, MCP server setup, hooks, REST API, vault/shelf hierarchy, graph, consolidation, repair/doctor, agent skill install
- [x] Slimmed README.md: quick-start + links to on-site docs, no long-form feature duplication
- [x] All pages responsive and consistent with the existing orange cinematic design system
- [x] New/changed HTML validated (no broken links, no build errors); pages render in browser

### Definition of Done
- [x] `gh release view v0.8.6` succeeds and PyPI lists 0.8.6
- [x] `git tag` shows `v0.8.6` on the pushed commit
- [x] `docs/index.html` no longer contains all concerns; at least 4 separate concern-based doc pages exist under `docs/`
- [x] Landing page links to the new doc pages; each link target resolves
- [x] README.md line count is significantly reduced and links to the on-site docs
- [x] Every CLI subcommand (incl. `repair`, `--json`) is documented on-site
- [x] Site renders without broken internal links

### Verification Steps
1. `git tag v0.8.6 && git push origin v0.8.6 && gh release create v0.8.6` → release exists
2. Wait for/trigger publish; `curl -s https://pypi.org/pypi/memorius/json | jq .info.version` → `0.8.6`
3. `ls docs/*.html` → multiple concern pages present; `grep -c '<section' docs/index.html` far lower than before
4. `grep -o 'href="[^"]*\.html"' docs/index.html` → every target file exists under docs/
5. `wc -l README.md` → notably fewer lines; `grep -c 'memorius ' README.md` reduced
6. Open pages in a browser (or `python -m http.server` in docs/) → renders, no broken links

### Anti-Drift Rules
- Do not rewrite the design system; extend the existing orange/cinematic look across the split pages.
- Do not delete working content when splitting — move it, don't drop it.
- Do not touch `memorius/` source code in this goal; it is v0.8.6-ready and shipped.
- If PyPI trusted publishing fails, report the blocker — do not fall back to twine/upload without confirmation.
- If a doc page would exceed ~500 lines, split it further by sub-concern.

### Estimated Effort
Large: release (small) + page split + ~6 doc pages + README rewrite. Multiple steps; run as background subagents where pages are independent, coordinate in one session.
