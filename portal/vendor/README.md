# Vendored third-party libraries

Vendored (not loaded from a CDN) so the portal has no runtime dependency on a third-party host at
page-load time: a CDN outage, MITM, or supply-chain compromise of the CDN cannot silently break or
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
| `protomaps-leaflet.js` | https://registry.npmjs.org/protomaps-leaflet/-/protomaps-leaflet-5.1.0.tgz (dist/protomaps-leaflet.js) | 5.1.0 | `26af014f7b1af308ec120b791cff76657bb9c3383633b52033e6edf9e5e4cdb5` | 128171 B |

Notes:
- `MarkerCluster.min.css` is the base plugin stylesheet only. `MarkerCluster.Default.min.css` (the
  default pin/sprite icons) is intentionally NOT vendored; the portal ships its own cluster icon styles
  (`.ausmt-cluster` in `index.html`) that replace it.
- `leaflet.js`/`leaflet.css` and `jszip.min.js` were already vendored before this pass; their hashes above
  were computed from the committed files and cross-checked against cdnjs's own published SRI digests
  (`https://api.cdnjs.com/libraries/<pkg>/<version>?fields=sri`): `leaflet.js` matches cdnjs's
  `leaflet.js` (unminified) digest; `leaflet.css` is byte-identical to cdnjs's `leaflet.css` modulo
  CRLF-vs-LF line endings (a pre-existing local normalisation, not a content change).
- `leaflet.markercluster.min.js`, `MarkerCluster.min.css`, `leaflet.draw.js` and `leaflet.draw.css` were
  downloaded fresh for this pass and verified byte-for-byte against cdnjs's published SRI (sha-512)
  digests before being committed.
- `protomaps-leaflet.js` (BSD-3-Clause) renders the self-hosted PMTiles basemap inside Leaflet.
  Upstream keeps it in maintenance mode for Leaflet-based projects (their new-project path is
  MapLibre); that suits this portal, which is deliberately Leaflet-based and vendors its stack.

## images/ (Leaflet + Leaflet.draw assets), added 2026-07-05

Leaflet's CSS references `images/` RELATIVE to the stylesheet URL (layer-control icons, default
markers), and Leaflet.draw's CSS references `images/spritesheet.*` the same way, and vendoring only
the .css/.js files left those requests 404ing in the deployed portal (first live-serve finding).
All eight assets fetched from the exact cdnjs versions the css files shipped with:

| file | upstream |
|---|---|
| layers.png, layers-2x.png, marker-icon.png, marker-icon-2x.png, marker-shadow.png | cdnjs leaflet/1.9.4/images/ |
| spritesheet.png, spritesheet-2x.png, spritesheet.svg | cdnjs leaflet.draw/1.0.4/images/ |

## favicon.svg

The browser-tab icon: the AuScope mark's own paths in a viewBox cropped to the ink, titled AuScope.
Generated, not hand-edited: `tools/gen_auscope_icons.py` writes it from
`auscope/auscope-mark.svg`, together with the root `favicon.ico` and the app icons under
`auscope/`. See `auscope/PROVENANCE.md` for the derivation.

## auscope/

The AuScope identity, as the site chrome draws it. Placeholders cut from the AuScope Style Guide
until AuScope supplies the official files, which replace them under the same names;
`auscope/PROVENANCE.md` records where each came from and the guide's rules for using them.

| File | What it is |
|---|---|
| `auscope-mark.svg` | The mark in Royal Blue (#282572) with its lighter swoosh. The source of every icon below. |
| `auscope-mark-white.svg` | The mark in white, for dark grounds only. |
| `auscope-logo.svg`, `auscope-logo-white.svg` | The mark with the AuScope wordmark, Royal Blue and white. |
| `auscope-ncris-lockup.svg`, `auscope-ncris-lockup-white.svg` | The AuScope and NCRIS lock-up, Royal Blue and white. |
| `icon-180.png` | The apple-touch-icon: the mark at 70 percent of the width on opaque white. Generated. |
| `icon-192.png`, `icon-512.png` | The same at the sizes a web manifest names; no manifest ships. Generated. |
| `PROVENANCE.md` | Source, normalisation and the icon derivation. |

The three PNG icons, `../favicon.svg` and `../../favicon.ico` are written by
`tools/gen_auscope_icons.py`, which rasterises with Pillow; `--check` compares `favicon.svg` byte for
byte and each raster pixel for pixel (with its mode and size, and for the ICO its frame sizes) against
a fresh render. Regenerate them after replacing `auscope-mark.svg`; never edit them by hand.

`auscope-icon-colour.png`, `auscope-icon-white.png` and `auscope-ncris-white.png`, one level up,
are the AuScope brand kit's own files: they are kept, verbatim, and no longer drawn by the site
chrome. The social card tool, the engine's link-preview cards and the documentation sidebar still
derive their AuScope marks from them, as their own notes below and in the docs state.

## auscope-ncris-white.png

The AuScope-NCRIS white lockup from the AuScope brand kit. The site chrome no longer draws it (the
header carries `auscope/auscope-ncris-lockup.svg` and its white twin); the engine's link-preview
cards draw a crop of it, pinned against this file. Committed VERBATIM from the AuScope brand kit
("2025 AuScope Logos", file `2025 AuScope-NCRIS Logo - White.png`); it is a third-party trademark
asset, so it is never resized, re-encoded or recoloured here, which is why the committed file keeps
its full 1919x325 resolution.

| File | Source | Dimensions | SHA-256 | Size |
|---|---|---|---|---|
| `auscope-ncris-white.png` | AuScope brand kit, `2025 AuScope-NCRIS Logo - White.png` | 1919x325 RGBA | `595a564ece1151d94347331c1521381df987da437aa3080cff47a5280cf818f6` | 35628 B |

## auscope-icon-colour.png

The AuScope icon in its brand colours, from the AuScope brand kit. The site chrome no longer draws
it: the map's corner mark is `auscope/auscope-mark.svg` and its white twin. Committed VERBATIM from
the AuScope brand kit ("2025 AuScope Logos", file `2025 AuScope Logo Icon - Colour.png`); it is a
third-party trademark asset, so it is never resized, re-encoded, recoloured or faded, which is why
the committed file keeps its full 281x288 resolution.

| File | Source | Dimensions | SHA-256 | Size |
|---|---|---|---|---|
| `auscope-icon-colour.png` | AuScope brand kit, `2025 AuScope Logo Icon - Colour.png` | 281x288 RGBA | `edfe057070656636011977270e4d4ba60461937add2f36048626e161c81aa132` | 7392 B |
