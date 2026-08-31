# Bundled face: Inter Bold (generator only)

This face exists so that `portal/tools/gen_brand.py` renders the AusMT wordmark to PNG the same way on
every machine. It is **not** the AusMT typeface and must never be presented as one. The web and SVG
wordmark render in the site's own system UI stack (`system-ui,-apple-system,'Segoe UI',Roboto,sans-serif`
at weight 800, the same stack and weight the portal header uses), which is what a reader actually sees.
A raster export cannot depend on the viewer's fonts, so the exports are rendered from this bundled file
instead: a deterministic substitute for the raster pipeline, nothing more. Nothing in `contract/brand.json`,
`portal/brand.html` or any served page names it, links it or fetches it, and no page loads it as a web font.

## Provenance

| item | value |
| --- | --- |
| Project | Inter, https://github.com/rsms/inter |
| Release | v4.1, published 2024-11-16 (the latest stable release at the time of bundling) |
| Archive URL | https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip |
| Archive size | 33,707,794 bytes |
| Archive sha256 | `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e` |
| Bundled file | `Inter-Bold.ttf`, extracted from `extras/ttf/Inter-Bold.ttf` inside that archive |
| Bundled size | 420,428 bytes |
| Bundled sha256 | `288316099b1e0a47a4716d159098005eef7c0066921f34e3200393dbdb01947f` |
| Licence file | `OFL.txt`, the archive's own `LICENSE.txt`, sha256 `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |

Downloaded from the official upstream release only. No mirror, no package index, no system font: a macOS
or Windows system face is not ours to redistribute, and a mirrored copy has no verifiable provenance.

## Licence

Inter is licensed under the SIL Open Font License 1.1. The full text ships beside this note in `OFL.txt`.
The OFL permits bundling and redistribution with the licence text included, which is what this directory
does; the reserved-font-name clause is not engaged because the file is unmodified and keeps its own name.

## Replacing it

Re-download from the upstream release, record the new version, URL and both sha256 values in the table
above, then run `python3 portal/tools/gen_brand.py` and commit the regenerated exports. The drift gate
(`gen_brand.py --check`) fails until the committed PNGs match what the new face produces, so a swapped
face can never land silently.
