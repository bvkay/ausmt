#!/usr/bin/env python3
"""Compute the canonical AusMT mark once, and write it to contract/brand.json.

    python3 tools/gen_brand.py            # (re)write the generated brand artefacts
    python3 tools/gen_brand.py --check    # CI drift gate: exit 1 if anything is stale

WHAT THE MARK IS. A coarse dot rasterisation of Australia: the engine's own coastline truth
(engine/extract/_au_outline.py, the COAST rings and EXTENT the survey minimap and the link-preview
cards already draw) laid over a fixed lattice, one dot per cell whose centre falls on land. The pitch
is chosen so the silhouette still reads as Australia at favicon size and so Tasmania survives as its
own cluster rather than rounding away. That is the whole geometry: ONE lattice, ONE colour mapping,
used by every export at every size, on dark and on light alike. The brief forbids per-theme geometries
for a plain reason - a mark that is a different shape on a white page is two marks, not one.

WHY A GENERATOR RATHER THAN CHECKED-IN ART. Hand-drawn exports drift: someone nudges a hex in one SVG,
regenerates one PNG from a newer source, and the family quietly stops matching. Here the lattice, the
palette and the colour mapping are computed here, written to contract/brand.json, and every export is a
rendering of that file. --check regenerates everything and fails on any difference, the same gate
tools/gen_config.py runs over config.js, so a hand-edited asset cannot survive a pull request.

DETERMINISM. No timestamps, no locale-dependent formatting, no randomness, no network. Two runs produce
identical output. contract/brand.json is compared byte for byte.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # portal/
REPO = ROOT.parent                                   # the ausmt monorepo root
BRAND_JSON = REPO / "contract" / "brand.json"
FONT_DIR = ROOT / "tools" / "brand_font"

# The coastline single source. Same sys.path-then-import sibling pattern gen_config.py uses to reach
# the contract package: this is a TOOL running from the checkout, never the engine image, so the module
# is simply there. _au_outline is stdlib-only and imports nothing, so no engine environment is needed.
sys.path.insert(0, str(REPO / "engine" / "extract"))
from _au_outline import COAST, EXTENT  # noqa: E402  (sibling engine module, stdlib-only)

# ==================================================================================================
# THE DECLARED CONSTANTS. Everything below this line is the source of truth; everything after it is
# derivation. A change here is a brand change and must be regenerated and reviewed as one.
# ==================================================================================================

# The lattice. The engine's drawing EXTENT (112E to 154E, 44S to 9S) divided into this many cells.
# 21 x 18 was chosen by rendering the candidates at 16, 24, 32, 48 and 96 px on dark and on light and
# looking at them: a coarser lattice (19 x 16) loses Tasmania to a single sub-pixel dot, and finer ones
# (26 x 22 and up) turn the 16 px favicon into an unreadable smear because no dot is a whole pixel any
# more. At 21 x 18 the silhouette keeps Cape York, the Gulf of Carpentaria notch, the Top End and the
# flat Bight coast at 16 px, and Tasmania survives as two dots.
GRID_COLS = 21
GRID_ROWS = 18

# The palette. FOUR stops, sampled ONCE from the established artwork (portal/vendor/social-card.png,
# the pixelated-Australia hero) and then hardcoded here as the declared truth, so the mark never
# depends on re-reading a PNG at build time. Derivation, recorded so the sampling can be repeated:
# the card's dot centres were recovered from its own lattice (7.3 px pitch), sorted by hue, and the
# cool end, the median and the warm end of that distribution taken as blue, purple and pink; coral is
# the card's own accent literal (#FF6655, the rule under the wordmark and the URL line).
PALETTE_STOPS = (("blue", "#3953DC", 0.00),
                 ("purple", "#9444CE", 0.38),
                 ("pink", "#E44696", 0.76),
                 ("coral", "#FF6655", 1.00))
PALETTE_DERIVATION = (
    "Sampled once from portal/vendor/social-card.png, the established pixelated-Australia artwork. "
    "Its dot centres were recovered on the artwork's own 7.3 px lattice and sorted by hue: blue is the "
    "median of the coolest two per cent (#3953DC), purple the median of the middle (#9444CE), pink the "
    "median of the warmest two per cent (#E44696). Coral is the card's own accent literal (#FF6655), "
    "the colour of the rule under the wordmark and of the URL line. The stops are hardcoded here as "
    "the declared truth; nothing re-reads the artwork at build time."
)
# Where each stop sits on the ramp. Coral is given the narrow far-east band it occupies in the artwork
# rather than a quarter of the mark, which is what an evenly spaced four-stop ramp would hand it.
BACKGROUNDS = {"dark": "#07162F", "light": "#FFFFFF"}
WORDMARK_INK = {"on_dark": "#FFFFFF", "on_light": "#11182D"}

# The colour of a dot is a pure function of its POSITION: t runs 0 at the western-most column to 1 at
# the eastern-most, and the ramp is evaluated at t. Left cool, right warm, per the owner's guidance.
T_PRECISION = 6

# SIZE-ADAPTIVE DOT RADIUS, as a ratio of the lattice pitch. The presentation ratio 0.44 is measured
# from the established artwork (6.5 px dots on a 7.3 px pitch). Small renders get FULLER dots: below
# about 32 px a 0.44 dot is under a pixel across and the silhouette dissolves into a haze, so the dots
# are enlarged until they close into a solid outline. That is the favicon sheet's rule, and it is why
# the 16 px favicon still reads as Australia without a second geometry existing anywhere.
RADIUS_BANDS = ((16, 0.62), (24, 0.54), (32, 0.50), (64, 0.46))
RADIUS_ABOVE = 0.44
# The frame margin around the mark's own bounding box, as a fraction of the square it is fitted into.
MARK_PAD = 0.02
# An SVG cannot know the size it will be drawn at, so each SVG declares the band it is generated FOR.
# The mark's smallest routine use is the 30 px header lockup, so it takes the 64 px band (0.46), which
# still leaves visible gaps between dots at presentation size. The favicon's whole job is the browser
# tab, so it takes the 16 px band and renders as a solid silhouette wherever it is drawn larger.
SVG_NOMINAL_PX = {"mark": 48, "favicon": 16}

# TYPOGRAPHY (owner ruling). The web and SVG wordmark render in the SITE's system UI stack, character
# for character the same stack and weight as the portal header wordmark, so the logo and the header
# agree in the viewer's own fonts. The bundled Inter Bold is a DETERMINISTIC RASTER SUBSTITUTE for the
# PNG pipeline only: it is not the AusMT typeface, is never described as one, is never served, and is
# never loaded as a web font. See tools/brand_font/PROVENANCE.md, which states the same thing beside
# the file itself. A monospaced face never renders the wordmark; monospace belongs to identifiers and
# technical metadata elsewhere in AusMT.
WEB_FONT_STACK = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
WEB_FONT_WEIGHT = 800
# KERNING. The raster wordmark is drawn glyph by glyph with an explicit advance so it comes out
# identical whatever the font engine does with kerning pairs. Two candidates were rendered at 22, 44
# and 160 px and judged by eye: default tracking, and one slight negative. The negative won - default
# tracking leaves the "sM" and "MT" pairs visibly loose at logo size - and it also puts the raster
# wordmark at the same optical density as the header's own CSS wordmark (letter-spacing -0.5px at
# 22px, which is -0.023em). The tested value is the declared one; nothing here is a value that was
# assumed rather than looked at.
LETTER_SPACING_EM = -0.02

# LOCKUP PROPORTIONS, in units of the mark's height M. One geometry for both backgrounds and both
# lockup widths; the extended variants add the tagline line and nothing else.
PROPORTIONS = {
    "mark_height": 1.0,
    "gap_mark_to_wordmark": 0.30,
    "wordmark_font_size": 0.62,
    "tagline_font_size": 0.20,
    "tagline_baseline_gap": 0.34,
    "clear_space": 0.25,
}
TAGLINE = "Australia's Magnetotelluric Data Portal"


# ==================================================================================================
# Derivation
# ==================================================================================================

def _inside(ring, x, y):
    """Even-odd point-in-polygon against a closed ring of (lon, lat) vertices."""
    hit = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < xi + (y - yi) * (xj - xi) / (yj - yi):
            hit = not hit
        j = i
    return hit


def _ramp(t):
    """The declared four-stop ramp, evaluated at t in [0, 1]. Linear in sRGB, which is what the
    artwork's own blend looks like and what an SVG gradient would do."""
    for a, b in zip(PALETTE_STOPS, PALETTE_STOPS[1:]):
        if t <= b[2] or b is PALETTE_STOPS[-1]:
            span = b[2] - a[2]
            u = 0.0 if span == 0 else min(1.0, max(0.0, (t - a[2]) / span))
            ca = [int(a[1][k:k + 2], 16) for k in (1, 3, 5)]
            cb = [int(b[1][k:k + 2], 16) for k in (1, 3, 5)]
            return "#%02X%02X%02X" % tuple(round(x + (y - x) * u) for x, y in zip(ca, cb))
    raise AssertionError("the ramp must cover [0, 1]")


def radius_ratio(size_px):
    """The declared radius, as a ratio of the lattice pitch, for an output of this pixel size."""
    for cap, ratio in RADIUS_BANDS:
        if size_px <= cap:
            return ratio
    return RADIUS_ABOVE


def dot_lattice():
    """[(col, row, ring)] for every lattice cell whose centre falls on land, in reading order."""
    w, e, s, n = EXTENT["w"], EXTENT["e"], EXTENT["s"], EXTENT["n"]
    dots = []
    for j in range(GRID_ROWS):
        lat = n - (j + 0.5) * (n - s) / GRID_ROWS
        for i in range(GRID_COLS):
            lon = w + (i + 0.5) * (e - w) / GRID_COLS
            if _inside(COAST[0], lon, lat):
                dots.append((i, j, "mainland"))
            elif _inside(COAST[1], lon, lat):
                dots.append((i, j, "tasmania"))
    return dots


def geometry():
    """The mark: the lattice, its bounding box, and every dot with its mapped colour."""
    dots = dot_lattice()
    if not dots:
        raise SystemExit("ERROR: the lattice selected no dots; the coastline source is unusable")
    cols = [c for c, _r, _k in dots]
    rows = [r for _c, r, _k in dots]
    c0, c1, r0, r1 = min(cols), max(cols), min(rows), max(rows)
    out = []
    for c, r, kind in dots:
        t = round((c - c0) / (c1 - c0), T_PRECISION)
        out.append({"col": c, "row": r, "ring": kind, "t": t, "hex": _ramp(t)})
    return {
        "extent": {k: EXTENT[k] for k in ("w", "e", "s", "n")},
        "grid": {"cols": GRID_COLS, "rows": GRID_ROWS},
        "bbox": {"col_min": c0, "col_max": c1, "row_min": r0, "row_max": r1},
        "pad_fraction": MARK_PAD,
        "radius_ratio_by_output_size": {
            "note": ("The dot radius as a fraction of the lattice pitch. The first band whose max_px is "
                     "at or above the output size applies; above the last band, 'above' applies. Small "
                     "outputs get fuller dots so the silhouette closes instead of dissolving."),
            "bands": [{"max_px": cap, "ratio": ratio} for cap, ratio in RADIUS_BANDS],
            "above": RADIUS_ABOVE,
        },
        "svg_nominal_size_px": dict(SVG_NOMINAL_PX),
        "dot_count": len(out),
        "dots": out,
    }


def document():
    """contract/brand.json: the whole declared truth, in one file, for every consumer."""
    return {
        "_comment": ("GENERATED by portal/tools/gen_brand.py from the engine coastline truth and the "
                     "declared constants in that file. Do not edit by hand: tools/gen_brand.py --check "
                     "fails the build on any drift. This is the single source of truth for the AusMT "
                     "mark's geometry, palette, proportions and typography; every brand export and any "
                     "downstream consumer renders from here."),
        "brand": "AusMT",
        "tagline": TAGLINE,
        "palette": {
            "stops": [{"name": n, "hex": h, "position": p} for n, h, p in PALETTE_STOPS],
            "derivation": PALETTE_DERIVATION,
            "backgrounds": dict(BACKGROUNDS),
            "wordmark_ink": dict(WORDMARK_INK),
        },
        "geometry": geometry(),
        "proportions": dict(PROPORTIONS),
        "typography": {
            "note": ("The web and SVG wordmark renders in the site's own system UI stack, so the logo "
                     "and the portal header agree in the viewer's fonts. The raster exports cannot "
                     "depend on the viewer's fonts, so they are drawn with a bundled face that serves "
                     "only as a deterministic rendering substitute."),
            "web_font_stack": WEB_FONT_STACK,
            "web_font_weight": WEB_FONT_WEIGHT,
            "letter_spacing_em": LETTER_SPACING_EM,
            "raster_substitute": {
                "family": "Inter",
                "style": "Bold",
                "is_the_ausmt_typeface": False,
                "note": ("A deterministic rendering substitute for the PNG pipeline only. AusMT has no "
                         "proprietary typeface and this face must never be presented as one. It is "
                         "bundled under portal/tools/brand_font/ with its SIL OFL text and provenance, "
                         "is never served, and is never loaded as a web font."),
            },
        },
    }


# ==================================================================================================
# Emission
# ==================================================================================================

def render_json(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def artefacts():
    """[(path, bytes)] for everything this tool owns. --check compares, the write mode writes."""
    return [(BRAND_JSON, render_json(document()).encode("utf-8"))]


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/gen_brand.py",
                                description="Generate the AusMT brand artefacts from one declared truth.")
    p.add_argument("--check", action="store_true",
                   help="CI drift gate: exit 1 if any generated artefact is stale; writes nothing")
    a = p.parse_args(argv)
    items = artefacts()
    if a.check:
        stale = [path for path, want in items
                 if (path.read_bytes() if path.is_file() else None) != want]
        if stale:
            print("BRAND DRIFT: regenerate with `python3 portal/tools/gen_brand.py`. Stale: "
                  + ", ".join(str(s.relative_to(REPO)) for s in stale), file=sys.stderr)
            return 1
        print(f"brand: {len(items)} generated artefact(s) in sync with tools/gen_brand.py")
        return 0
    for path, data in items:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(items)} artefact(s); {document()['geometry']['dot_count']} dots "
          f"on a {GRID_COLS}x{GRID_ROWS} lattice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
