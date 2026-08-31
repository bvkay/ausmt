# AusMT portal image — Caddy serving the static, build-step-free portal/ tree + a mounted data volume.
#
# Build context is the ausmt repo root (docker build -f deploy/docker/portal.Dockerfile .), so
# COPY portal/ below is relative to that root, matching engine.Dockerfile's convention.
#
# ZERO-CDN CLAIM (verified by grep against the committed tree, not assumed — re-run this grep if
# portal/*.html changes and this comment starts to drift):
#   grep -n "http" portal/index.html portal/about.html portal/add-survey.html portal/brand.html
# results, and why each is fine to serve behind the CSP in deploy/docker/caddy/Caddyfile:
#   - The one `<script src="https://YOUR-PLAUSIBLE-HOST/...">` line (index.html + add-survey.html)
#     sits INSIDE an HTML comment (<!-- ... -->) — analytics is off by default and there is no live
#     external <script> tag actually parsed by the browser. If an operator later uncomments it to
#     self-host Plausible, script-src in the Caddyfile will need a matching addition then.
#   - ROR/RAiD placeholder text in <input placeholder="https://ror.org/…"> etc — not a resource
#     load, just placeholder text.
#   - add-survey.html's real live external calls: `fetch("https://api.ror.org/...")`, the R3
#     publication-DOI harvest `fetch("https://api.crossref.org/...")` / `fetch("https://api.datacite.org/...")`,
#     and two `L.tileLayer("https://{s}.tile.openstreetmap.org/...")` calls — all allow-listed
#     explicitly in the Caddyfile's per-page CSP (connect-src for the fetches / img-src for the tiles
#     on the add-survey page block).
#   - index.html's map (portal/src/map.js) loads tiles from basemaps.cartocdn.com — allow-listed in
#     the default/index CSP img-src.
#   - the header AuScope logo <a href="https://www.auscope.org.au"> survives on ABOUT.HTML ALONE.
#     It is a NAVIGATION link, not a resource load: CSP does not govern <a href> targets; the logo
#     image itself is vendored (portal/vendor/auscope-icon-white.png, img-src 'self'). The
#     brand-assets lane made the AusMT mark (vendor/brand/ausmt-mark.svg, also img-src 'self') the
#     header identity on index.html, releases.html, add-survey.html and brand.html, and the anchor
#     left with the symbol on each. about.html's header is carved out pending an owner ruling.
#     index.html's only remaining auscope.org.au string is the JSON-LD publisher URL, which is
#     metadata and loads nothing; brand.html's and releases.html's only http strings are their own
#     rel=canonical. Nothing in this changes a CSP rule: one fewer outbound anchor, no new load.
# All other assets (leaflet, leaflet.draw, markercluster, jszip) are vendored under portal/vendor/
# and served from 'self' -- portal/tests/test_no_cdn_references.py (part of the surveys/portal
# pytest gate, not this image build) already guards the cdnjs.cloudflare.com supply-chain case and
# the vendor/ paths, but it does NOT enumerate the map-tile/ROR hosts above (those are legitimate
# live external calls, not vendoring concerns). If a future edit adds a NEW bare (uncommented)
# http(s) asset/script reference anywhere in portal/*.html beyond the four cases above, re-run the
# grep in this comment by hand and update the Caddyfile CSP accordingly -- there is no automated
# check inside THIS image build for that (it would require a headless browser).

FROM caddy:2-alpine

# Caddyfile is validated by `caddy validate` as an image-build smoke check (fails the build loudly
# if the config has a syntax error, rather than only failing at container start).
COPY deploy/docker/caddy/Caddyfile /etc/caddy/Caddyfile
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# The static portal itself. node_modules/ and tests/ are dev-only (jsdom interaction tests, see
# portal/package.json) and are NOT part of the shipped site -- excluded via .dockerignore
# (deploy/.dockerignore) rather than copied and unused, to keep the image lean.
COPY portal/ /srv/portal

EXPOSE 8080
