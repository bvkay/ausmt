# AuScope identity assets, placeholders

Six SVG files cut from the vector pages of the AuScope Style Guide
(https://www.auscope.org.au/s/AuScope-Style-Guide.pdf, page 4): the mark alone, the mark with the
wordmark, and the AuScope and NCRIS lock-up, each in Royal Blue (#282572) and in white (the mark's
lighter swoosh at 55 percent). The paths are the guide's own geometry; the blues are normalised to the
guide's stated hex. They stand in until AuScope supplies the official files, which replace them under
the same names. Rules from the guide: breathing space of at least the logo's height on every side; the
white versions sit on Royal Blue or another dark ground only.

## Icons derived from the mark

`portal/tools/gen_auscope_icons.py` renders the site's favicon and app icons from `auscope-mark.svg` and
from nothing else, so replacing that file with the official artwork and rerunning the tool is the
whole of a change to the icons.

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
