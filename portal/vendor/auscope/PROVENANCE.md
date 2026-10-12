# AuScope identity assets

The site draws the AuScope brand kit's own files ("2025 AuScope Logos"), which carry Tasmania. The
earlier cuts from the AuScope Style Guide's page did not, and are gone.

## The mark pair

`auscope-mark.svg` and `auscope-mark-white.svg` are derived from the kit's vector icon,
`2025 AuScope Logo Icon.ai`, read with PyMuPDF: the file's four shapes, as cubic and line paths in
their own geometry, translated so the ink box starts at the origin (viewBox `0 0 67.406 69.083`) and
written to three decimals. Nothing is redrawn or simplified.

| File | Fills |
|---|---|
| `auscope-mark.svg` | As the kit file states them: the body in its Royal Blue, `#272472`, and the swoosh in `#A7A2C5`. They are not normalised to the guide's `#282572`. |
| `auscope-mark-white.svg` | The same four shapes in white, `#FFFFFF`, with the swoosh at `fill-opacity="0.302"`: the alpha, 77 of 255, at which the kit's `2025 AuScope Logo Icon - White.png` renders it. |

Rules from the guide: breathing space of at least the logo's height on every side; the white
versions sit on Royal Blue or another dark ground only.

## The lock-up pair

The AuScope and NCRIS lock-up in every header, and in About's body, is the kit's own PNG pair, kept
one level up at the vendor root and never re-encoded, resized or recoloured:
`../auscope-ncris-colour.png` is `2025 AuScope-NCRIS Logo - Colour.png` and
`../auscope-ncris-white.png` is `2025 AuScope-NCRIS Logo - White.png`, both 1919 by 325. The kit's
only vector lock-up is an EPS this repository's tools do not read, so the PNGs are drawn as
published: 40px tall in the header, 320px wide in About. `../README.md` records each file's digest
and size.

## Icons derived from the mark

`portal/tools/gen_auscope_icons.py` renders the site's favicon and app icons from `auscope-mark.svg` and
from nothing else, so a change to the mark is a change to that file and a rerun of the tool.

| File | Derivation |
|---|---|
| `portal/vendor/favicon.svg` | The mark's `<path>` elements verbatim, in a viewBox cropped to the ink (rounded outward to two decimals, so no padding and no crop), with a `<title>` of AuScope. Transparent. |
| `portal/favicon.ico` | 16, 32 and 48 px frames, each the mark fitted edge to edge on its longer side on a transparent ground. |
| `icon-180.png`, `icon-192.png`, `icon-512.png` | The mark centred at 70 percent of the icon's width on an opaque white (#FFFFFF) square, RGB. 180 is the apple-touch-icon; 192 and 512 are kept for a future web manifest. |

Every raster is drawn by Pillow: each path is flattened to a polygon and filled in the source's
order at eight times the icon's size, then resampled down with Lanczos, which keeps the 16 px frame's
edges clean. `python3 tools/gen_auscope_icons.py --check` compares `favicon.svg` byte for byte and
each raster as its decoded picture (mode, size and pixels; for `favicon.ico`, the frame sizes and
each frame's pixels), so a different Pillow encoding the same picture stays in sync. The white
versions of the mark are not used for icons: a browser tab and a home screen give no guarantee of a
dark ground.
