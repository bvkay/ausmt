# AusMT portal image — Caddy serving the static, build-step-free portal/ tree + a mounted data volume.
#
# Build context is the ausmt repo root (docker build -f deploy/docker/portal.Dockerfile .), so
# COPY portal/ below is relative to that root, matching engine.Dockerfile's convention.
#
# ZERO-CDN CLAIM (verified by grep against the committed tree, not assumed — re-run this grep if
# portal/*.html changes and this comment starts to drift):
#   grep -n "http" portal/index.html portal/about.html portal/add-survey.html portal/brand.html \
#                  portal/releases.html portal/404.html
# results, and why each is fine to serve behind the CSP in deploy/docker/caddy/Caddyfile:
#   - No page carries an external analytics <script> tag: analytics is off and the shim in
#     src/analytics-shim.js is a no-op. If an operator adds one to
#     self-host Plausible, script-src in the Caddyfile will need a matching addition then.
#   - ROR/RAiD placeholder text in <input placeholder="https://ror.org/…"> etc — not a resource
#     load, just placeholder text.
#   - add-survey.html's real live external calls: `fetch("https://api.ror.org/...")`, the
#     publication-DOI harvest `fetch("https://api.crossref.org/...")` / `fetch("https://api.datacite.org/...")`,
#     and two `L.tileLayer("https://{s}.tile.openstreetmap.org/...")` calls — all allow-listed
#     explicitly in the Caddyfile's per-page CSP (connect-src for the fetches / img-src for the tiles
#     on the add-survey page block).
#   - index.html's map (portal/src/map.js) loads tiles from basemaps.cartocdn.com — allow-listed in
#     the default/index CSP img-src.
#   - the auscope.org.au ANCHORS, which are now the FOOTER's alone. The header's AuScope symbol was
#     the third one on each of the five pages above; it is withdrawn from every header on the site,
#     so what is left is two on every one of the six pages: the acknowledgement's URL text and the
#     AuScope-NCRIS lockup, both in the footer. about.html carries a THIRD, the "Learn more about
#     AuScope" link in its Who enables AusMT section. 404.html is not an exception: it has no
#     header, and no page's header has an anchor. All of them are
#     NAVIGATION links, not resource loads: CSP does not govern <a href> targets. The images those
#     pages fetch are vendored and served from 'self' under img-src: the AusMT identity mark
#     (vendor/brand/ausmt-mark.svg), on the five chrome pages and not on 404.html, and the
#     AuScope-NCRIS lockup (vendor/auscope-ncris-white.png), which about.html names twice, once in
#     its body and once in its footer, and every other page including 404.html once.
#     vendor/auscope-icon-white.png is fetched by no page here. The file still ships: the
#     generated collection pages draw it on their member-footprint panels, the docs site's sidebar
#     copy is made from it and tools/gen_social_card.py composites it.
#   - the auscope.org.au METADATA, which loads nothing: the JSON-LD publisher URL and the WebSite
#     node's own url on index.html, every page's rel=canonical, and og:url plus og:image on
#     index.html, about.html, releases.html and add-survey.html (brand.html is noindex and
#     carries canonical alone). An og:image URL is fetched by a link-preview crawler out of band,
#     never by the browser rendering the page, so no CSP directive governs it. Nothing here
#     changes a CSP rule: outbound anchors only, and no new host is fetched from.
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
