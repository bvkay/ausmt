# Vendored third-party libraries

Vendored (not loaded from a CDN) so the portal has no runtime dependency on a third-party host at
page-load time — a CDN outage, MITM, or supply-chain compromise of the CDN cannot silently break or
tamper with the portal. Each file below is committed verbatim (byte-identical to the upstream release);
do not hand-edit them. To update a version: download the new release from the same upstream project,
verify its hash (the project's own release page or npm/cdnjs metadata), replace the file here, update
this table, and bump the `<script>`/`<link>` tags in `index.html` / `add-survey.html` if the filename
changes.

| File | Upstream | Version | SHA-256 | Size |
|---|---|---|---|---|
| `leaflet.js` | https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js | 1.9.4 | `db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a` | 147552 B |
| `leaflet.css` | https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css | 1.9.4 | `337bfca5cabd03b39815b2700febe2b3b7edf55921c59cd49f88ecb328212303` | 14145 B |
| `jszip.min.js` | https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js | 3.10.1 | `acc7e41455a80765b5fd9c7ee1b8078a6d160bbbca455aeae854de65c947d59e` | 97630 B |
| `leaflet.markercluster.min.js` | https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js | 1.5.3 | `020a517be9a15b99cf2033cd420b561e0f27b1b6ddd49cbb60a057f335327fb4` | 33995 B |
| `MarkerCluster.min.css` | https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.min.css | 1.5.3 | `5ea4d37ba829f27588ed3c9f85b156b03b23db14f70dadd4b48c5fe9f8370e5a` | 688 B |
| `leaflet.draw.js` | https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js | 1.0.4 | `b22a1f7385308e5adadd85a4c2d84e9fc523ebd70d37868cba0fe2387362460b` | 67484 B |
| `leaflet.draw.css` | https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css | 1.0.4 | `5f30f74696873efee5cd7f6ab7eda7d63e5c5a3e3c3b6e0ab2068662928df31f` | 5267 B |

Notes:
- `MarkerCluster.min.css` is the base plugin stylesheet only — `MarkerCluster.Default.min.css` (the
  default pin/sprite icons) is intentionally NOT vendored; the portal ships its own cluster icon styles
  (`.ausmt-cluster` in `index.html`) that replace it.
- `leaflet.js`/`leaflet.css` and `jszip.min.js` were already vendored before this pass; their hashes above
  were computed from the committed files and cross-checked against cdnjs's own published SRI digests
  (`https://api.cdnjs.com/libraries/<pkg>/<version>?fields=sri`) — `leaflet.js` matches cdnjs's
  `leaflet.js` (unminified) digest; `leaflet.css` is byte-identical to cdnjs's `leaflet.css` modulo
  CRLF-vs-LF line endings (a pre-existing local normalisation, not a content change).
- `leaflet.markercluster.min.js`, `MarkerCluster.min.css`, `leaflet.draw.js` and `leaflet.draw.css` were
  downloaded fresh for this pass and verified byte-for-byte against cdnjs's published SRI (sha-512)
  digests before being committed.

## images/ (Leaflet + Leaflet.draw assets) — added 2026-07-05

Leaflet's CSS references `images/` RELATIVE to the stylesheet URL (layer-control icons, default
markers), and Leaflet.draw's CSS references `images/spritesheet.*` the same way — vendoring only
the .css/.js files left those requests 404ing in the deployed portal (first live-serve finding).
All eight assets fetched from the exact cdnjs versions the css files shipped with:

| file | upstream |
|---|---|
| layers.png, layers-2x.png, marker-icon.png, marker-icon-2x.png, marker-shadow.png | cdnjs leaflet/1.9.4/images/ |
| spritesheet.png, spritesheet-2x.png, spritesheet.svg | cdnjs leaflet.draw/1.0.4/images/ |

## favicon.svg — added 2026-07-05

Local hand-authored SVG favicon (MT sounding curve over a station dot), linked from all three
pages to stop the browser's automatic /favicon.ico 404.
