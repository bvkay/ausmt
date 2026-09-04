#!/usr/bin/env python3
"""Compute the canonical AusMT mark once, and render every brand export from it.

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

SVG VERSUS PNG. The SVGs are real vector circles and text elements: they scale, they print, and their
wordmark renders in the READER's own system UI stack, which is the rule for anything a
browser draws. The PNGs are for slide decks and documents, where a viewer's fonts are not available and
the bytes must be identical everywhere; they are rendered from the SAME lattice with a bundled face,
never by rasterising the SVGs (a converted SVG would bake in whatever fonts the converter happened to
have). Both formats are transparent, so a variant is a choice of INK rather than a choice of card.

DETERMINISM. No timestamps, no locale-dependent formatting, no randomness, no network. Two runs produce
identical output. Text artefacts are compared byte for byte; PNGs are compared as decoded pixels, which
is the invariant that actually matters (a committed export must show exactly what the tool draws) and
which does not go red when a PNG encoder or its zlib is upgraded under CI.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # portal/
REPO = ROOT.parent                                   # the ausmt monorepo root
BRAND_JSON = REPO / "contract" / "brand.json"
BRAND_DIR = ROOT / "vendor" / "brand"
FONT_DIR = ROOT / "tools" / "brand_font"
FONT_FILE = FONT_DIR / "Inter-Bold.ttf"

# The coastline single source. Same sys.path-then-import sibling pattern gen_config.py uses to reach
# the contract package: this is a TOOL running from the checkout, never the engine image, so the module
# is simply there. _au_outline is stdlib-only and imports nothing, so no engine environment is needed.
sys.path.insert(0, str(REPO / "engine" / "extract"))
from _au_outline import COAST, EXTENT  # noqa: E402  (sibling engine module, stdlib-only)

# ==================================================================================================
# THE DECLARED CONSTANTS. Everything above the derivation banner is the source of truth; everything
# below it is derivation. A change here is a brand change and must be regenerated and reviewed as one.
# ==================================================================================================

# The lattice. The engine's drawing EXTENT (112E to 154E, 44S to 9S) divided into this many cells.
# 21 x 18 was chosen by rendering the candidates at 16, 24, 32, 48 and 96 px on dark and on light and
# looking at them: a coarser lattice (19 x 16) loses Tasmania to a single sub-pixel dot, and finer ones
# (26 x 22 and up) turn the 16 px favicon into an unreadable smear because no dot is a whole pixel any
# more. At 21 x 18 the silhouette keeps Cape York, the Gulf of Carpentaria notch, the Top End and the
# Bight coast at 16 px, and Tasmania survives as three dots.
#
# The pitch holds on the derived Natural Earth coastline: the mark carries a dot in the Kimberley, a
# deeper Gulf notch and a third Tasmanian dot. The lattice is the coarser of the two inputs: the
# coastline resolves the Bight concavity and the taper of Cape York, and a 2 degree cell throws both
# away. Changing the pitch is a BRAND decision, not a consequence of this generator.
GRID_COLS = 21
GRID_ROWS = 18

# The palette. FOUR stops, sampled ONCE from the established artwork and then hardcoded here as the
# declared truth, so the mark never depends on re-reading a PNG at build time. The artwork is
# vendor/social-card-source.png: the served root card is now a composite of it (tools/gen_social_card.py
# adds the AuScope mark to its signature row), and the sampling was done on the artwork itself.
# Derivation, recorded so the sampling can be repeated:
# the card's dot centres were recovered from its own lattice (7.3 px pitch), sorted by hue, and the
# cool end, the median and the warm end of that distribution taken as blue, purple and pink; coral is
# the card's own accent literal (#FF6655, the rule under the wordmark and the URL line).
PALETTE_STOPS = (("blue", "#3953DC", 0.00),
                 ("purple", "#9444CE", 0.38),
                 ("pink", "#E44696", 0.76),
                 ("coral", "#FF6655", 1.00))
PALETTE_DERIVATION = (
    "Sampled once from portal/vendor/social-card-source.png, the established pixelated-Australia artwork. "
    "Its dot centres were recovered on the artwork's own 7.3 px lattice and sorted by hue: blue is the "
    "median of the coolest two per cent (#3953DC), purple the median of the middle (#9444CE), pink the "
    "median of the warmest two per cent (#E44696). Coral is the card's own accent literal (#FF6655), "
    "the colour of the rule under the wordmark and of the URL line. The stops are hardcoded here as "
    "the declared truth; nothing re-reads the artwork at build time."
)
# Where each stop sits on the ramp. Coral is given the narrow far-east band it occupies in the artwork
# rather than a quarter of the mark, which is what an evenly spaced four-stop ramp would hand it.
#
# The intended backgrounds for the two variants. Dark is the artwork's own field colour; light is plain
# white. These are what the brand page previews the variants against, NOT a plate baked into any export.
BACKGROUNDS = {"dark": "#07162F", "light": "#FFFFFF"}
# Wordmark ink per variant. On dark it is white. On light it is the portal's own deepest surface colour
# (--ink, #11182D), so the light lockup is drawn in the same navy the site is built from.
WORDMARK_INK = {"on_dark": "#FFFFFF", "on_light": "#11182D"}
# Tagline ink. On dark it is the established artwork's own secondary text colour. On light it is the
# dark wordmark ink at 65 per cent over white, which is the same optical step down.
TAGLINE_INK = {"on_dark": "#C9D4E8", "on_light": "#646979"}

# The colour of a dot is a pure function of its POSITION: t runs 0 at the western-most column to 1 at
# the eastern-most, and the ramp is evaluated at t. Left cool, right warm, per the guidance.
T_PRECISION = 6

# SIZE-ADAPTIVE DOT RADIUS, as a ratio of the lattice pitch. The presentation ratio 0.44 is measured
# from the established artwork (6.5 px dots on a 7.3 px pitch). Small renders get FULLER dots: below
# about 32 px a 0.44 dot is under a pixel across and the silhouette dissolves into a haze, so the dots
# are enlarged until they close into a solid outline. That is the favicon sheet's rule, and it is why
# the 16 px favicon still reads as Australia without a second geometry existing anywhere.
#
# THE 16 PX BAND WAS SET BY LOOKING AT A REAL RASTERISER, NOT A PREVIEW. A supersampled Pillow render
# flattered it: 0.62 looked solid there and washed out in headless Chrome at device-scale-factor 1,
# because at 16 px the lattice pitch is 0.77 px and a 0.62 dot is 0.95 px across, so every dot lands
# under one device pixel and the whole mark renders as translucent haze. Candidates 0.62, 0.70, 0.78
# and 0.86 were rendered at 1x on a white tab, a dark tab and the portal navy: 0.78 is the first that
# closes into a solid silhouette with Cape York, the Top End and Tasmania still legible, and 0.86 is
# already fat enough to fill in the Gulf of Carpentaria and the Bight. Hence 0.78.
RADIUS_BANDS = ((16, 0.78), (24, 0.60), (32, 0.50), (64, 0.46))
RADIUS_ABOVE = 0.44
# The frame margin around the mark's own bounding box, as a fraction of the square it is fitted into.
MARK_PAD = 0.02
# An SVG cannot know the size it will be drawn at, so each SVG declares the band it is generated FOR.
# The mark's smallest routine use is the 30 px header lockup, and the five bands were rendered in a
# real browser at 30 px in the header and again at 120 and 200 px: at 0.46 and 0.44 the 30 px mark is
# noticeably airy, at 0.62 the large render bloats into a solid blob, and 0.50 (the 32 px band) is the
# one that closes the silhouette in the header while still reading as separate dots at presentation
# size. The favicon's whole job is the browser tab, so it takes the 16 px band and simply renders as a
# solid silhouette wherever it is drawn larger, which is what a favicon should do.
SVG_NOMINAL_PX = {"mark": 32, "favicon": 16}

# TYPOGRAPHY. The web and SVG wordmark render in the SITE's system UI stack, character
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
# Layout metrics, measured once from the bundled face and declared so the SVG canvas can be sized
# without a font engine. A viewer whose system stack measures the WORDMARK wider or narrower than
# this sits a little closer to, or further from, the right clear-space edge, and the clear space
# absorbs it: measured in a real browser at the SVG's own sizes, the widest common fallback (Verdana)
# draws the wordmark 113 user units over the declared advance against 200 units of clear space. The
# TAGLINE is not absorbed (Verdana draws it 434 units over), so it declares its advance in the SVG;
# see _svg_text for the measurements and for why the wordmark is deliberately left free.
WORDMARK_ADVANCE_EM = 3.429      # "AusMT" at the declared tracking
TAGLINE_ADVANCE_EM = 18.889      # the tagline at default tracking
CAP_HEIGHT_EM = 0.728            # cap height, for optically centring the text block on the mark
DESCENDER_EM = 0.242

# LOCKUP PROPORTIONS, in units of the mark's height M. One geometry for both backgrounds and both
# lockup widths; the extended variants add the tagline line and nothing else.
MARK_UNITS = 1000                # M, in SVG user units: the whole coordinate system is M-relative
PROPORTIONS = {
    "mark_height": 1.0,
    "gap_mark_to_wordmark": 0.24,
    "wordmark_font_size": 0.62,
    "tagline_font_size": 0.15,
    "tagline_baseline_gap": 0.34,
    "clear_space": 0.20,
}
TAGLINE = "Australia's Magnetotelluric Data Portal"

# Export sizes. Presentation resolution for the logos, a square mark for reuse at any size.
PNG_LOGO_WIDTH = 2400
PNG_MARK_SIZE = 1024
# The small mark the engine's link-preview cards carry in their corner. The cards draw it at
# CARD_MARK_DRAWN_PX, and this export is a whole multiple of that height so the card's resample is a
# clean 4:1 box rather than an arbitrary ratio. It exists because the engine image ships no portal
# tree and so must carry its own copy of whatever it draws with: a copy of the 1024 px mark would
# put a third of a megabyte in that image to be shown at 42 px.
PNG_CARD_MARK_SIZE = 168
CARD_MARK_DRAWN_PX = 42
# Rendering is supersampled and then resampled down, which is what gives the dots and the wordmark
# clean edges at every size. The factor is capped so the working canvas stays a sane size.
SUPERSAMPLE_TARGET = 6000
SUPERSAMPLE_MAX = 8


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


# What each COAST ring is called in brand.json. The first two are addressed by NAME downstream (the
# brand pin checks Tasmania survives the rasterisation as its own cluster); the rest are islands and
# share one label, because the mark is a silhouette and does not need to name them individually.
RING_LABELS = ("mainland", "tasmania")


def _ring_label(k):
    return RING_LABELS[k] if k < len(RING_LABELS) else "island"


def dot_lattice():
    """[(col, row, ring)] for every lattice cell whose centre falls on land, in reading order.

    EVERY ring is tested, not just the first two: the coastline carries islands as well as the
    mainland and Tasmania, and a ring the rasteriser skipped would be land the mark silently left
    out. The first ring to claim a cell wins, which only matters for rings that overlap - none do."""
    w, e, s, n = EXTENT["w"], EXTENT["e"], EXTENT["s"], EXTENT["n"]
    dots = []
    for j in range(GRID_ROWS):
        lat = n - (j + 0.5) * (n - s) / GRID_ROWS
        for i in range(GRID_COLS):
            lon = w + (i + 0.5) * (e - w) / GRID_COLS
            for k, ring in enumerate(COAST):
                if _inside(ring, lon, lat):
                    dots.append((i, j, _ring_label(k)))
                    break
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


GEOM = geometry()


def mark_dots(x0, y0, side, size_px):
    """[(cx, cy, r, hex)] placing the mark inside the square (x0, y0, side), fitted and centred.

    `size_px` is the size the mark will actually be SEEN at, which is what selects the radius band."""
    bb = GEOM["bbox"]
    w = bb["col_max"] - bb["col_min"] + 1
    h = bb["row_max"] - bb["row_min"] + 1
    pitch = side * (1 - 2 * MARK_PAD) / max(w, h)
    ox = x0 + (side - w * pitch) / 2
    oy = y0 + (side - h * pitch) / 2
    r = pitch * radius_ratio(size_px)
    return [(ox + (d["col"] - bb["col_min"] + 0.5) * pitch,
             oy + (d["row"] - bb["row_min"] + 0.5) * pitch, r, d["hex"]) for d in GEOM["dots"]]


def lockup(extended):
    """The horizontal lockup's geometry in M-relative user units: canvas, mark box, text baselines."""
    m = MARK_UNITS
    cs = PROPORTIONS["clear_space"] * m
    gap = PROPORTIONS["gap_mark_to_wordmark"] * m
    ws = PROPORTIONS["wordmark_font_size"] * m
    ts = PROPORTIONS["tagline_font_size"] * m
    tgap = PROPORTIONS["tagline_baseline_gap"] * m
    cap = ws * CAP_HEIGHT_EM
    text_x = cs + m + gap
    wm_w = ws * WORDMARK_ADVANCE_EM
    if extended:
        # Centre the WHOLE text block (wordmark cap top to tagline descender) on the mark, not the
        # wordmark alone: otherwise adding the tagline visibly drags the lockup off balance.
        below = tgap + ts * DESCENDER_EM
        baseline = cs + m / 2 + (cap - below) / 2
        text_w = max(wm_w, ts * TAGLINE_ADVANCE_EM)
    else:
        baseline = cs + m / 2 + cap / 2
        text_w = wm_w
    return {"width": text_x + text_w + cs, "height": m + 2 * cs,
            "mark": (cs, cs, m), "text_x": text_x, "baseline": baseline,
            "wordmark_size": ws, "tagline_size": ts,
            "tagline_baseline": baseline + tgap if extended else None}


# ==================================================================================================
# SVG emission
# ==================================================================================================

def _n(v):
    """A number with no trailing zeros and no locale, so the emitted bytes are stable."""
    return f"{round(v, 2):g}"


def _svg_mark_group(x0, y0, size_px):
    """The mark as ONE reusable block: always drawn in its own 0..MARK_UNITS box and placed by a
    translate, so the dot markup is character-identical in every export and a variant cannot acquire a
    geometry of its own. The standalone mark carries the same wrapper with a zero translate rather than
    a special-cased shorter form, for exactly that reason.

    One group per lattice column. Grouping by colour keeps the emitted file small and makes the
    one-colour-per-column mapping visible in the markup itself."""
    cols = {}
    for cx, cy, r, hexc in mark_dots(0, 0, MARK_UNITS, size_px):
        cols.setdefault(hexc, []).append((cx, cy, r))
    body = "\n".join(
        '    <g fill="%s">%s</g>' % (hexc, "".join(
            f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"/>' for cx, cy, r in cols[hexc]))
        for hexc in sorted(cols, key=lambda h: min(c[0] for c in cols[h])))
    return f'  <g transform="translate({_n(x0)},{_n(y0)})">\n{body}\n  </g>\n'


def _svg_open(width, height, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(width)} {_n(height)}" '
            f'width="{_n(width)}" height="{_n(height)}" role="img" aria-label="{label}">\n')


def _svg_text(x, y, size, ink, spacing, body, advance=None):
    """One <text>. `advance`, when given, is the declared width the line must occupy.

    WHY THE TAGLINE DECLARES ONE AND THE WORDMARK DOES NOT. The canvas is sized from the declared
    advances, which were measured from the bundled face; the SVG then renders in the READER's system
    stack, which measures the same string differently, and an outermost <svg> loaded through <img>
    clips at its own viewBox. Measured in a real browser at the SVG's own sizes, the tagline's right
    edge lands at 4131.6 user units in the site stack, 4358.1 in Tahoma, 4461.6 in Georgia and 4707.5
    in Verdana, against a canvas 4473.35 wide: a Verdana or DejaVu-class fallback loses the end of the
    line, served with a 200 and the right content type. The tagline is the line that sets the canvas
    edge on the extended lockups, so it declares its advance and any stack renders it at the declared
    width. lengthAdjust="spacing" adjusts the gaps only, never the glyph shapes, and in the common
    case the correction is imperceptible (the site stack is 141.7 units short over 39 gaps).

    The WORDMARK is deliberately left free. Its widest measured overrun is 113 units against 200
    units of clear space, so it cannot clip, and forcing its advance would override the tracking the
    was chosen by eye with whatever a viewer's font happens to need."""
    sp = f' letter-spacing="{spacing}em"' if spacing is not None else ""
    adv = f' textLength="{_n(advance)}" lengthAdjust="spacing"' if advance is not None else ""
    return (f'  <text x="{_n(x)}" y="{_n(y)}" font-family="{WEB_FONT_STACK}" '
            f'font-weight="{WEB_FONT_WEIGHT}" font-size="{_n(size)}"{sp}{adv} '
            f'fill="{ink}">{body}</text>\n')


# NO DOUBLE HYPHEN IN THIS COMMENT. XML forbids "--" inside a comment, and a browser decodes an SVG
# served as an image with a strict XML parser: one illegal token and the mark renders as alt text on
# every page of the site, with a 200 and the right content type in the network panel. The obvious
# phrasing here ("gen_brand.py --check") is exactly the trap, so the flag is named without its dashes.
_SVG_NOTE = ("<!-- GENERATED by portal/tools/gen_brand.py from contract/brand.json. Do not edit by "
             "hand: the gen_brand.py check mode fails on drift. The wordmark deliberately declares "
             "the site's own system UI stack, so it renders in the reader's fonts and matches the "
             "portal header. Transparent ground: dark and light differ in ink, not in card. -->\n")


def svg_mark():
    side = MARK_UNITS
    return (_svg_open(side, side, "AusMT") + _SVG_NOTE
            + _svg_mark_group(0, 0, SVG_NOMINAL_PX["mark"]) + "</svg>\n")


def svg_favicon():
    """The browser-tab mark. Same lattice, same colour mapping, the 16 px radius band.

    It keeps the filename vendor/favicon.svg the placeholder had, so no link tag on any page had to
    move. Transparent, so one file serves a light and a dark browser chrome; the concept sheet's tile
    variants are context previews of that same file, not separate assets."""
    side = MARK_UNITS
    return (_svg_open(side, side, "AusMT") + _SVG_NOTE
            + _svg_mark_group(0, 0, SVG_NOMINAL_PX["favicon"]) + "</svg>\n")


def svg_logo(dark, extended):
    lay = lockup(extended)
    mx, my, _ms = lay["mark"]
    ink = WORDMARK_INK["on_dark" if dark else "on_light"]
    body = (_svg_open(lay["width"], lay["height"], "AusMT") + _SVG_NOTE
            + _svg_mark_group(mx, my, SVG_NOMINAL_PX["mark"])
            + _svg_text(lay["text_x"], lay["baseline"], lay["wordmark_size"], ink,
                        LETTER_SPACING_EM, "AusMT"))
    if extended:
        body += _svg_text(lay["text_x"], lay["tagline_baseline"], lay["tagline_size"],
                          TAGLINE_INK["on_dark" if dark else "on_light"], None, TAGLINE,
                          advance=lay["tagline_size"] * TAGLINE_ADVANCE_EM)
    return body + "</svg>\n"


# ==================================================================================================
# PNG emission (the bundled face renders the wordmark; never a rasterised SVG)
# ==================================================================================================

def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError:
        sys.exit("ERROR: gen_brand.py requires Pillow to render the PNG exports (pip install Pillow). "
                 "It is a declared engine dependency and is installed in CI.")
    return Image, ImageDraw, ImageFont


def _supersample(longest):
    return max(1, min(SUPERSAMPLE_MAX, SUPERSAMPLE_TARGET // max(1, longest)))


def _draw_tracked(draw, x, y, text, font, fill, tracking_px):
    """The wordmark, glyph by glyph with an explicit advance. Pillow would otherwise hand the whole
    string to the font engine, whose kerning-pair handling is a property of the build rather than of
    this repository; drawing the advances ourselves makes the spacing a declared constant."""
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill, anchor="ls")
        if i + 1 < len(text):
            adv = draw.textlength(text[i:i + 2], font=font) - draw.textlength(text[i + 1], font=font)
        else:
            adv = draw.textlength(ch, font=font)
        x += adv + tracking_px


def png_mark(size):
    """The standalone mark, square and transparent, at `size` pixels."""
    Image, ImageDraw, _ = _pillow()
    ss = _supersample(size)
    side = size * ss
    im = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for cx, cy, r, hexc in mark_dots(0, 0, side, size):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=hexc)
    return im.resize((size, size), Image.LANCZOS) if ss > 1 else im


def png_logo(dark, extended, width=PNG_LOGO_WIDTH):
    Image, ImageDraw, ImageFont = _pillow()
    lay = lockup(extended)
    height = round(width * lay["height"] / lay["width"])
    ss = _supersample(width)
    scale = width * ss / lay["width"]
    im = Image.new("RGBA", (width * ss, height * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    mx, my, ms = lay["mark"]
    # The radius band follows the size the MARK is actually seen at in this export, not the canvas.
    for cx, cy, r, hexc in mark_dots(mx * scale, my * scale, ms * scale, round(ms * width / lay["width"])):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=hexc)
    ws = lay["wordmark_size"] * scale
    # BASIC layout is pinned, not defaulted: Pillow picks Raqm when its wheel bundles libraqm and
    # Basic when it does not, and the two shape text differently, so the same call produced
    # different bytes on a developer's macOS wheel and on CI's manylinux one. Every Pillow build
    # has Basic, so pinning it is what makes the committed exports reproducible and the drift
    # gate meaningful.
    font = ImageFont.truetype(str(FONT_FILE), round(ws), layout_engine=ImageFont.Layout.BASIC)
    _draw_tracked(d, lay["text_x"] * scale, lay["baseline"] * scale, "AusMT", font,
                  WORDMARK_INK["on_dark" if dark else "on_light"], LETTER_SPACING_EM * ws)
    if extended:
        ts = lay["tagline_size"] * scale
        tfont = ImageFont.truetype(str(FONT_FILE), round(ts),
                                   layout_engine=ImageFont.Layout.BASIC)
        _draw_tracked(d, lay["text_x"] * scale, lay["tagline_baseline"] * scale, TAGLINE, tfont,
                      TAGLINE_INK["on_dark" if dark else "on_light"], 0.0)
    return im.resize((width, height), Image.LANCZOS) if ss > 1 else im


# ==================================================================================================
# The artefact set
# ==================================================================================================

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
            "tagline_ink": dict(TAGLINE_INK),
        },
        "geometry": GEOM,
        "proportions": dict(PROPORTIONS, mark_units=MARK_UNITS),
        "typography": {
            "note": ("The web and SVG wordmark renders in the site's own system UI stack, so the logo "
                     "and the portal header agree in the viewer's fonts. The raster exports cannot "
                     "depend on the viewer's fonts, so they are drawn with a bundled face that serves "
                     "only as a deterministic rendering substitute."),
            "web_font_stack": WEB_FONT_STACK,
            "web_font_weight": WEB_FONT_WEIGHT,
            "letter_spacing_em": LETTER_SPACING_EM,
            "wordmark_advance_em": WORDMARK_ADVANCE_EM,
            "tagline_advance_em": TAGLINE_ADVANCE_EM,
            "cap_height_em": CAP_HEIGHT_EM,
            "descender_em": DESCENDER_EM,
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
        "outputs": [{"path": p, "kind": k, "variant": v} for p, k, v in _OUTPUT_INDEX],
    }


_OUTPUT_INDEX = (
    ("contract/brand.json", "json", "source of truth"),
    ("portal/vendor/brand/ausmt-logo-dark.svg", "svg", "logo, dark background"),
    ("portal/vendor/brand/ausmt-logo-dark.png", "png", "logo, dark background"),
    ("portal/vendor/brand/ausmt-logo-light.svg", "svg", "logo, light background"),
    ("portal/vendor/brand/ausmt-logo-light.png", "png", "logo, light background"),
    ("portal/vendor/brand/ausmt-logo-dark-extended.svg", "svg", "logo with tagline, dark background"),
    ("portal/vendor/brand/ausmt-logo-dark-extended.png", "png", "logo with tagline, dark background"),
    ("portal/vendor/brand/ausmt-logo-light-extended.svg", "svg", "logo with tagline, light background"),
    ("portal/vendor/brand/ausmt-logo-light-extended.png", "png", "logo with tagline, light background"),
    ("portal/vendor/brand/ausmt-mark.svg", "svg", "standalone mark"),
    ("portal/vendor/brand/ausmt-mark.png", "png", "standalone mark"),
    ("portal/vendor/brand/ausmt-mark-168.png", "png", "standalone mark, link-preview card corner"),
    ("portal/vendor/favicon.svg", "svg", "browser tab icon"),
    ("portal/vendor/brand/ausmt-icon-180.png", "png", "apple-touch-icon"),
    ("portal/vendor/brand/ausmt-icon-192.png", "png", "app icon"),
    ("portal/vendor/brand/ausmt-icon-512.png", "png", "app icon"),
)

# The app-icon sizes. 180 is the apple-touch-icon a home-screen shortcut uses; 192 and 512 are the
# conventional pair a web manifest would name. No manifest ships here (architect default): an
# installable PWA is its own decision, and these two exist so that decision costs no regeneration.
APP_ICON_SIZES = (180, 192, 512)


def artefacts():
    """[(path, kind, payload)] for everything this tool owns.

    kind "bytes" compares byte for byte; kind "image" compares decoded pixels, size and mode, which is
    the invariant that matters for a raster and which survives a PNG encoder upgrade under CI."""
    items = [(BRAND_JSON, "bytes", (json.dumps(document(), indent=2, ensure_ascii=False) + "\n")
              .encode("utf-8"))]
    for dark in (True, False):
        for extended in (False, True):
            stem = f"ausmt-logo-{'dark' if dark else 'light'}{'-extended' if extended else ''}"
            items.append((BRAND_DIR / f"{stem}.svg", "bytes", svg_logo(dark, extended).encode("utf-8")))
            items.append((BRAND_DIR / f"{stem}.png", "image", png_logo(dark, extended)))
    items.append((BRAND_DIR / "ausmt-mark.svg", "bytes", svg_mark().encode("utf-8")))
    items.append((BRAND_DIR / "ausmt-mark.png", "image", png_mark(PNG_MARK_SIZE)))
    items.append((BRAND_DIR / f"ausmt-mark-{PNG_CARD_MARK_SIZE}.png", "image",
                  png_mark(PNG_CARD_MARK_SIZE)))
    items.append((ROOT / "vendor" / "favicon.svg", "bytes", svg_favicon().encode("utf-8")))
    for size in APP_ICON_SIZES:
        items.append((BRAND_DIR / f"ausmt-icon-{size}.png", "image", png_mark(size)))
    return items


def _image_matches(path, want):
    """Size, mode and decoded pixels, in that order.

    MODE IS COMPARED BEFORE THE CONVERSION, not after it: normalising both sides to RGBA and then
    comparing would discard the mode entirely, and a committed export re-saved as a palette image
    whose palette happens to decode to identical RGBA pixels would pass a gate that claims to hold
    the mode. What the browser is served is the file's own mode, so that is what is held."""
    Image, _, _ = _pillow()
    if not path.is_file():
        return False
    with Image.open(path) as committed:
        mode, size = committed.mode, committed.size
        have = committed.convert("RGBA")
    return (size == want.size and mode == want.mode
            and have.tobytes() == want.convert("RGBA").tobytes())


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/gen_brand.py",
                                description="Generate the AusMT brand artefacts from one declared truth.")
    p.add_argument("--check", action="store_true",
                   help="CI drift gate: exit 1 if any generated artefact is stale; writes nothing")
    a = p.parse_args(argv)
    items = artefacts()
    if a.check:
        stale = []
        for path, kind, want in items:
            fresh = (path.read_bytes() if path.is_file() else None) == want if kind == "bytes" \
                else _image_matches(path, want)
            if not fresh:
                stale.append(path)
        if stale:
            print("BRAND DRIFT: regenerate with `python3 portal/tools/gen_brand.py`. Stale: "
                  + ", ".join(str(s.relative_to(REPO)) for s in stale), file=sys.stderr)
            return 1
        print(f"brand: {len(items)} generated artefact(s) in sync with tools/gen_brand.py")
        return 0
    for path, kind, data in items:
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "bytes":
            path.write_bytes(data)
        else:
            data.save(path, "PNG")
    print(f"wrote {len(items)} artefact(s); {GEOM['dot_count']} dots on a {GRID_COLS}x{GRID_ROWS} lattice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
