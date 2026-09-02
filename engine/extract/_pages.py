#!/usr/bin/env python3
"""Tier-3 entity landing pages: one static HTML document per survey, station and collection,
served at the path-URL contract's own shapes (/surveys/<slug>, /stations/<ausmt_id>,
/collections/<id>).

Every page is rendered ONLY from the already-served public documents (surveys.json entries,
survey-metadata.json, station.json, the collections rollup, the manifest's bundle rows and the
time-series register), so a page can never disclose anything the gated products do not already
publish; the C42 posture is inherited, and the coord-access whole-tree sweep audits pages/ like
every other emitter. All free text is HTML-escaped (curator-authored YAML is still a public
serving surface), and the JSON-LD block escapes "</" so document text can never close the
script element.

Survey pages carry the full design of record: a "Cite this survey" disclosure (surname-plus-initial
authors, source-led locator), location minimap on the shared schematic outline (_au_outline, the
same geometry the portal's collections view draws), footprint zoom for compact surveys, stat tiles,
per-level download panels with manifest sizes and checksums, grouped contributors, publications,
and the five-column station table (station, lat, lon, T max, time series) whose rows link to the
station pages that carry the deployment and instrument metadata. Time-series panels and cells
render ONLY the levels the served register carries. NO em/en dashes and NO tick glyphs anywhere:
numeric ranges take a spaced hyphen, absent cells are plain hyphens, availability is stated as data
(sizes), per the owner's rulings.

Per-survey AND per-collection link-preview cards (og:image) are rendered when Pillow is importable;
without it every entity page falls back to the portal's root card. Both paths emit the og/twitter
tags, and a page advertises a card only where the emitter has actually written that file.

Structured data is emitted per page kind: the entity node (Dataset) first where a page has one,
then a BreadcrumbList matching the visible crumb. Station pages carry neither, because they are
noindex and a trail on one describes a result that can never be shown.

Stdlib only (Pillow soft-gated), deliberately: this is a leaf like _license_text, importable by
the spawn workers' build_portal without extra weight.
"""
from __future__ import annotations

import colorsys
import html
import json
import math
import re
from pathlib import Path

import _au_outline as au
import _stationcheck as stcheck
from _contract import LICENSES  # sibling-import house pattern; the licence instrument is single-sourced

_LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}

# Keys as the MANIFEST bundle rows spell them ("mth5", not the station-resource id
# "survey-mth5"; the two vocabularies differ and the manifest is what this emitter reads).
_BUNDLE_LABELS = {
    "edi-zip": ("EDI archive (zip)", "application/zip"),
    "xml-zip": ("EMTF XML archive (zip)", "application/zip"),
    "mth5": ("Survey MTH5 bundle", "application/x-hdf5"),
    "survey-mth5": ("Survey MTH5 bundle", "application/x-hdf5"),
}

# The register's level keys, in the order the portal renders them, with the badge and the name the
# portal uses (portal/src/state.js TS_LEVELS): one vocabulary across the SPA, the survey page and
# the station page. Every badge is distinct, so a station cell listing two levels can be read.
_TS_LEVELS = (("raw_packed", "Raw", "Packed raw"),
              ("level0", "L0", "Level 0"),
              ("level1_mth5", "L1 MTH5", "Level 1 MTH5"),
              ("level1_netcdf", "L1 NetCDF", "Level 1 NetCDF"))

# The portal's own data-type palette (portal/src/state.js TYPE_COL), byte for byte, so the page maps
# and the SPA map speak one colour language. BBMT's value is the one the portal MEASURED for LP/BB
# separability and deutan-safety; the page carried a lightened variant of it, which meant the two
# surfaces coloured the same survey differently and the one with the measurement behind it lost.
_TYPE_COL = {"LPMT": "#2E8FA3", "BBMT": "#3730B8", "AMT": "#CDA1EC", "GDS": "#C255A0"}
_TYPE_FALLBACK = "#4FC3D9"

# The portal collections view's member palette (portal/src/drawer.js COLL_PAL), same order. It has
# eight entries and used to CYCLE, so a collection with more members than that gave two surveys the
# same colour and its legend could not disambiguate them (AusLAMP: 14 members, 8 colours, 6 reused).
_COLL_PAL = ("#2E8FA3", "#EF7256", "#8A5FC0", "#5BAE6A", "#3F6FC4", "#C255A0", "#D9A23B", "#A85454")

# The map panel's own ground, one step CLOSER to the card it sits on than the near-black it used to
# carry. The panel was a box on a box: a dark rectangle inside a lighter card, so the eye read the
# rectangle before it read the coastline. Stepping the fill to the card's own token and softening the
# rule leaves the Australia outline as the only object with an edge, which is what the panel is for.
_MAP_PANEL = "#18213D"
_MAP_PANEL_LINE = "#222C4E"

# The coastline's own two colours, declared once because two surfaces draw the same outline in two
# media: the SVG panels below and the raster collection card. A card that previewed a page whose
# coastline was a different colour would read as a different map.
_COAST_FILL = "#1d3140"
_COAST_LINE = "#3a5266"

# The site's own name, as the structured data and every og:site_name state it. Google labelled the
# site by its publisher because nothing on it ever named the site itself.
_SITE_NAME = "AusMT"


_ROLE_LABELS = {"ProjectLeader": "Project Leader", "ProjectMember": "Project Member",
                "DataCollector": "Data Collector", "DataCurator": "Data Curator",
                "ContactPerson": "Contact", "RightsHolder": "Rights Holder",
                "Distributor": "Distributor"}


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _jsonld(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1).replace("</", "<\\/")


def _breadcrumb(base, trail):
    """A BreadcrumbList for `trail`: [(name, path)] from the site root down to this page.

    The names are the VISIBLE crumb's own words, because the markup has to describe the trail the
    reader is actually shown; a hub whose crumb reads "surveys" may not claim "Surveys" here.
    Station pages take no breadcrumb at all: they are noindex, so a trail on one describes a rich
    result that can never be rendered, and this tier's thousands of station documents are the one
    place where a block per page is worth counting."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": name,
                                 "item": f"{base}{path}"}
                                for i, (name, path) in enumerate(trail, start=1)]}


def _initials(authors) -> str:
    """"Kay, Ben; Heinson, Graham" -> "Kay, B.; Heinson, G." An entry without a comma (an
    organisation) passes through verbatim."""
    out = []
    for raw_entry in str(authors or "").split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "," in entry:
            last, _, given = entry.partition(",")
            initials = " ".join(f"{g[0]}." for g in given.split() if g)
            out.append(f"{last.strip()}, {initials}" if initials else last.strip())
        else:
            out.append(entry)
    return "; ".join(out)


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    return f"{n / 1e3:.0f} KB"


def _fmt_period(v) -> str:
    """A period in seconds as a READER sees it. The stored value never changes; this is the one
    display helper the hubs and the entity pages share, so one period prints one way everywhere.

    Under 100: two significant figures, trailing zeros stripped. At or above 100: a
    thousands-separated integer. Never exponent notation, whatever the magnitude: `%g` printed a
    2.6e-05 s period as "2.6e-05", which is a number a processing log can carry and a survey page
    cannot. The unit is always seconds and belongs to the caller's slot, not to this string."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v == 0:
        return "0"
    if abs(v) >= 100:
        return f"{round(v):,}"
    # Two significant figures without ever reaching for an exponent: the decimal place count is
    # derived from the magnitude, so 0.005012 rounds at the fourth place and 9.6e-05 at the sixth.
    decimals = max(0, 1 - math.floor(math.log10(abs(v))))
    out = f"{v:.{decimals}f}"
    return out.rstrip("0").rstrip(".") if "." in out else out


# The range separator, one place. The owner's revised ruling: numeric ranges in UI chrome read as a
# SPACED HYPHEN-MINUS rather than as the word "to", and the glyph ban is untouched (no en dash, no
# em dash, no tick glyphs anywhere in engine chrome). Curator prose is not chrome and is not touched.
def _range(lo, hi) -> str:
    return f"{lo} - {hi}"


# The human form of a Creative Commons identifier, DERIVED from the licence instrument itself so the
# display map cannot fall behind it. The SPDX identifier is the machine's name for a licence and
# stays untouched in every served document and every machine-readable slot; what a reader sees in
# page chrome is the form the licence is published under ("CC BY 4.0", not "CC-BY-4.0").
#
# Derived rather than listed because a hand-kept map covering only the ids today's corpus declares
# goes wrong silently: the instrument recognises fourteen CC ids, so the first third-party release
# under a 3.0, -AU, NC or ND id would have printed "CC-BY-3.0-AU" on one card beside "CC BY 4.0" on
# the next, which is the inconsistency this rule exists to remove. The grammar is the deed's own:
# the prefix, the clause letters (which keep their internal hyphens: BY-NC-SA), the version, and a
# jurisdiction port where one exists.
#
# Non-CC ids (PUBLIC DOMAIN, ODBL-1.0, ODC-BY-1.0, ALL RIGHTS RESERVED, COPYRIGHT) have no such
# published reader's form, and neither does an identifier the instrument does not recognise at all;
# both are printed verbatim, because guessing a human form would be inventing metadata.
_CC_ID = re.compile(r"^(CC0|CC)(?:-([A-Z]+(?:-[A-Z]+)*))?-(\d+\.\d+)(?:-([A-Z]{2,3}))?$")


def _cc_human(identifier):
    m = _CC_ID.match(identifier)
    return " ".join(part for part in m.groups() if part) if m else None


_LICENCE_DISPLAY = {i: _cc_human(i)
                    for i in LICENSES["redistributable"] + LICENSES["recognised_only"]
                    if _cc_human(i)}


def _fmt_licence(lic) -> str:
    v = str(lic or "").strip()
    return _LICENCE_DISPLAY.get(v, v)


def _doi_url(identifier) -> str | None:
    """A related identifier as a resolvable URL. Bare DOIs resolve via doi.org; a value already
    carrying a scheme is used as-is (one corpus row is a full dx.doi.org URL)."""
    v = str(identifier or "").strip()
    if not v:
        return None
    if v.startswith(("http://", "https://")):
        return v
    return f"https://doi.org/{v}"


def _bare_doi(identifier) -> str | None:
    v = str(identifier or "").strip()
    v = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", v, flags=re.IGNORECASE)
    return v or None


# --------------------------------------------------------------------------- SVG map panels

def _proj(extent):
    w, e, s, n = extent["w"], extent["e"], extent["s"], extent["n"]

    def to(width, height, pad):
        def p(lon, lat):
            x = pad + (lon - w) / (e - w) * (width - 2 * pad)
            y = pad + (n - lat) / (n - s) * (height - 2 * pad)
            return round(x, 1), round(y, 1)
        return p
    return to


def _hemisphere(v, neg, pos) -> str:
    """A coordinate as a magnitude plus its hemisphere letter, never both a sign and a letter.

    The footprint caption printed the raw signed latitude and then appended the letter, so a
    Tasmanian survey read "-43.44 degrees S": south stated twice, once as a minus and once as an S,
    which reads as a typo rather than as a coordinate."""
    return f"{abs(float(v)):.2f}&#176;{neg if float(v) < 0 else pos}"


def _extent_deg(points):
    lons = [pt[0] for pt in points]
    lats = [pt[1] for pt in points]
    return max(max(lons) - min(lons), max(lats) - min(lats)) if points else 0.0


def _minimap_height(width) -> int:
    ext = au.EXTENT
    return round(width * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))


def _outline_paths(p) -> str:
    """The schematic coast rings and state borders, projected by `p`."""
    def path(ring, close=True):
        d = "M" + "L".join(f"{x},{y}" for x, y in (p(lo, la) for lo, la in ring))
        return d + ("Z" if close else "")
    coast = "".join(f'<path d="{path(r)}" fill="{_COAST_FILL}" stroke="{_COAST_LINE}" '
                    f'stroke-width="1"/>' for r in au.COAST)
    borders = "".join(f'<path d="{path(r, False)}" fill="none" stroke="{_COAST_LINE}" '
                      f'stroke-width=".8" stroke-dasharray="3 3"/>' for r in au.BORDERS)
    return coast + borders


def au_outline_defs(width):
    """(hidden defs block, symbol id) for the outline at `width`, so a document carrying MANY
    minimaps pays for the geometry ONCE and every card references it. An entity page draws a single
    map and keeps the inline form; an index page draws one per survey, where the repeated path data
    would dominate the document. The symbol's viewBox matches the referencing minimap's exactly, so
    the projected station dots register against it without scaling."""
    height = _minimap_height(width)
    ref = f"au-outline-{width}"
    geom = _outline_paths(_proj(au.EXTENT)(width, height, 8))
    return (f'<svg width="0" height="0" aria-hidden="true" focusable="false" '
            f'style="position:absolute">'
            f'<defs><symbol id="{ref}" viewBox="0 0 {width} {height}">{geom}</symbol></defs>'
            f"</svg>"), ref


def _minimap_svg(points, *, width=230, compact=False, colours=None, labelled=False,
                 label="Survey location in Australia", outline_ref=None, locator=True) -> str:
    """The location minimap: the shared schematic outline with this survey's stations, dots
    coloured by data type in the portal's own palette (or by `colours`, the collection page's
    member-colour map). The projection is the portal collections view's own fixed-extent
    equirectangular fit, so the two surfaces draw one map. Under one degree of extent the dots
    are sub-pixel here, so only the ring renders and the footprint panel owns the dots.
    `outline_ref`: a symbol id from au_outline_defs, referenced instead of inlining the geometry.
    `locator`: whether this map is allowed to mark a single location at all. A footprint that
    gathers many surveys has no one location to mark, so the collection surfaces pass False."""
    extent = au.EXTENT
    height = _minimap_height(width)
    p = _proj(extent)(width, height, 8)
    # Both reference forms: `href` on <use> is SVG2, `xlink:href` is the SVG 1.1 spelling older
    # engines read. They cost a few hundred bytes across a whole hub page, and without the second
    # one an engine that predates SVG2 draws the dots with no coastline behind them.
    outline = (f'<use href="#{_e(outline_ref)}" xlink:href="#{_e(outline_ref)}"/>' if outline_ref
               else _outline_paths(p))
    xlink_ns = ' xmlns:xlink="http://www.w3.org/1999/xlink"' if outline_ref else ""
    # Dot size: on a compact survey the separate footprint panel carries the structure, so the
    # minimap dots are a location hint and stay small regardless of count; a state-wide survey has
    # no zoom panel, so its dots ARE the content and scale by density.
    r = 1.2 if compact else (2 if len(points) <= 60 else (1.4 if len(points) <= 200 else 1.1))
    # Below one degree the whole footprint projects to under a pixel on this continental viewBox,
    # so the dots would be an invisible smudge and the separate footprint panel owns them instead.
    dots_drawn = _extent_deg(points) >= 1
    dots = ""
    if dots_drawn:
        def col(pt):
            if colours is not None:
                return colours.get(pt[2], _TYPE_FALLBACK)
            return _TYPE_COL.get(pt[2], _TYPE_FALLBACK)

        def dot(pt):
            x, y = p(pt[0], pt[1])
            head = f'<circle cx="{x}" cy="{y}" r="{r}"'
            # A dot whose colour encodes WHICH member survey it belongs to must also say so in
            # text: colour alone is not an identifier (design brief 45), and the SPA's own scatter
            # has carried these titles all along. Type-coloured dots need none; the type is a
            # category the legend and the tiles already name.
            if labelled:
                return f"{head}><title>{_e(pt[2])}</title></circle>"
            return f"{head}/>"

        # `fill` and `fill-opacity` repeat identically across every dot of a run, so they ride on a
        # wrapping <g> rather than on each circle: a map carrying a thousand-station footprint pays
        # for its colour once per run instead of once per station, which is what lets a hub card
        # draw every member station inside the page's size budget. Runs rather than one group per
        # colour, because collapsing a colour globally would reorder the paint and these dots are
        # translucent. `r` stays on the circle: geometry properties do not inherit, so an r hoisted
        # onto the group would leave every circle at the default radius of zero and draw nothing.
        runs, group, fill = [], [], None
        for pt in points:
            colour = col(pt)
            if colour != fill:
                if group:
                    runs.append(f'<g fill="{fill}">{"".join(group)}</g>')
                group, fill = [], colour
            group.append(dot(pt))
        if group:
            runs.append(f'<g fill="{fill}">{"".join(group)}</g>')
        dots = f'<g fill-opacity=".9">{"".join(runs)}</g>'
    marker = ""
    # The ring is the exact complement of the dot gate: its whole job is to stand in for dots too
    # small to draw, so it is meaningful when and only when they are suppressed. Keying it off a
    # point COUNT instead put a ring on every map that happened to be short, including one drawn
    # from a sampled footprint, where it marked the centroid of a continent.
    if locator and points and not dots_drawn:
        clon = sum(pt[0] for pt in points) / len(points)
        clat = sum(pt[1] for pt in points) / len(points)
        mx, my = p(clon, clat)
        # Muted, not coral: the ring is a locator hint on a map, and coral is reserved for primary
        # actions and active states (design brief 3). Same ink as the footprint panel's scale bar,
        # so the two map annotations read as one layer over the geography.
        marker = (f'<circle cx="{mx}" cy="{my}" r="9" fill="none" stroke="#8FA3B0" '
                  f'stroke-width="1.4" opacity=".75"/>')
    return (f'<svg viewBox="0 0 {width} {height}"{xlink_ns} role="img" '
            f'aria-label="{_e(label)}" '
            f'style="background:{_MAP_PANEL};border:1px solid {_MAP_PANEL_LINE};border-radius:8px">'
            f'{outline}{dots}{marker}</svg>')


def _footprint_svg(points, *, width=230) -> str:
    """The station-grid zoom for a compact survey, aspect-fit to the survey's own bbox, dots in
    the type palette, with a SCALE BAR so 9 km and 900 km never look alike (a bare dot field
    carries no sense of size; the bar is computed from the bbox at the survey's own latitude).

    The bar's label is sized in USER UNITS, so it renders at its value times the panel's own scale
    rather than at a fixed number of pixels: measured on the served build the panel is 364px wide at
    a 1280px viewport and 282px at 320px, against this 230-unit viewBox. At the 9 units it carried
    the label fell to 11.0px on the narrow screen, under the page's stated 12px floor; 10 clears the
    floor there (12.3px) and costs 1.5px where the map is normally read."""
    lons = [pt[0] for pt in points]
    lats = [pt[1] for pt in points]
    lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
    dlo, dla = max(lo1 - lo0, 1e-6), max(la1 - la0, 1e-6)
    height = max(90, min(320, int(width * dla / dlo)))
    pad = 0.12

    def p(lon, lat):
        x = (lon - lo0) / dlo * (1 - 2 * pad) * width + pad * width
        y = (la1 - lat) / dla * (1 - 2 * pad) * height + pad * height
        return round(x, 1), round(y, 1)
    # Coastline where it crosses the panel: the shared outline clipped to the bbox, so a
    # coastal survey's dots sit against land instead of floating in a void. Segments are kept
    # when either endpoint is inside the (slightly padded) bbox; inland panels draw nothing.
    mlo, mla = dlo * 0.2, dla * 0.2

    def _inside(lon, lat):
        return (lo0 - mlo) <= lon <= (lo1 + mlo) and (la0 - mla) <= lat <= (la1 + mla)
    coast_parts = []
    for ring in au.COAST:
        closed = list(ring) + [ring[0]]
        run = []
        for a, b in zip(closed, closed[1:]):
            if _inside(*a) or _inside(*b):
                if not run:
                    run.append(a)
                run.append(b)
            elif run:
                coast_parts.append(run)
                run = []
        if run:
            coast_parts.append(run)
    coast = "".join(
        '<polyline points="' + " ".join(f"{p(lo, la)[0]},{p(lo, la)[1]}" for lo, la in part)
        + '" fill="none" stroke="#3a5266" stroke-width="1.2"/>' for part in coast_parts)
    dots = "".join(f'<circle cx="{p(pt[0], pt[1])[0]}" cy="{p(pt[0], pt[1])[1]}" r="2.1" '
                   f'fill="{_TYPE_COL.get(pt[2], _TYPE_FALLBACK)}"/>' for pt in points)
    # scale bar: a round number close to a third of the panel width, in km at the mid latitude
    km_per_deg = 111.32 * math.cos(math.radians((la0 + la1) / 2))
    panel_km = dlo * (1 - 2 * pad) * km_per_deg
    target = panel_km / 3
    nice = min((1, 2, 5, 10, 20, 50, 100, 200, 500, 1000), key=lambda n: abs(n - target))
    bar_px = nice / (dlo * km_per_deg) * width if dlo * km_per_deg else 0
    y = height - 10
    scale = (f'<g stroke="#8FA3B0" stroke-width="1.2"><line x1="{pad * width:.1f}" y1="{y}" '
             f'x2="{pad * width + bar_px:.1f}" y2="{y}"/></g>'
             f'<text x="{pad * width + bar_px + 5:.1f}" y="{y + 3.5}" fill="#8FA3B0" '
             f'font-size="10" font-family="ui-monospace,Menlo,monospace">{nice} km</text>')
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Station grid detail" '
            f'style="background:{_MAP_PANEL};border:1px solid {_MAP_PANEL_LINE};border-radius:8px">'
            f'{coast}{dots}{scale}</svg>')


# --------------------------------------------------------------------------- page shell

_CSS = """
  body{margin:0;background:#11182D;color:#C9D4E8;font:16px/1.55 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
  main{max-width:840px;margin:0 auto;padding:1.6rem 1.25rem 3rem}
  @media(min-width:1180px){main{max-width:1120px}}
  a{color:#EF7256}
  code{overflow-wrap:anywhere}
  a:focus-visible,summary:focus-visible{outline:2px solid #EF7256;outline-offset:2px;border-radius:2px}
  h1{color:#fff;font-size:1.7rem;margin:.5rem 0 .3rem}
  h2{color:#fff;font-size:1.12rem;margin:1.7rem 0 .5rem}
  h3{color:#fff;font-size:1rem;margin:1.2rem 0 .4rem}
  .crumb{font-size:.85rem;opacity:.8}
  .crumb a{opacity:1}
  .pagenav{display:flex;gap:.6rem;margin:.2rem 0 .6rem}
  .navbtn{background:#18213D;border:1px solid #2B3557;border-radius:6px;color:#C9D4E8;font-size:.85rem;padding:.35rem .9rem;text-decoration:none}
  .navbtn.map{color:#EF7256}
  .cite{background:#18213D;border:1px solid #2B3557;border-radius:6px;padding:.7rem .9rem;font-size:.88rem;margin:1rem 0}
  .cite summary{cursor:pointer;color:#fff;font-weight:600}
  .cite p{margin:.6rem 0 0}
  .cite code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;color:#C9D4E8}
  .citeack{color:#8FA3B0;font-size:.82rem}
  .embargo{background:#3a2a1a;border:1px solid #7a5a2a;border-radius:6px;padding:.6rem .9rem;margin:.8rem 0;color:#e8d5b5;font-size:.9rem}
  .idxchip{font-size:.75rem;text-transform:uppercase;letter-spacing:.07em;background:#1E2B4F;border:1px solid #2B3557;border-radius:3px;padding:.05rem .4rem;color:#8FA3B0}
  .typebadge{display:inline-block;font-size:.75rem;font-weight:600;letter-spacing:.07em;background:#1E2B4F;border:1px solid #2B3557;border-radius:4px;padding:.12rem .5rem;color:#C9D4E8;vertical-align:middle;margin-left:.55rem}
  .lede{font-size:1.05rem;max-width:70ch;margin:.7rem 0 1rem}
  .prose{max-width:70ch}
  /* The collection page reads at the width of its own hero map, not at the 70ch reading measure
     the survey pages keep: its prose runs beside a map and a metric rail, and a column narrower
     than the graphic above it reads as a mistake. One token carries the map width so the two
     cannot drift, and below the hero's own collapse breakpoint the rail is gone and the prose
     takes the full column. .prose is NOT widened: it is shared with the survey pages. */
  main{--collw:820px;--railw:230px;--railgap:1.2rem}
  .collprose{max-width:min(var(--collw), 100% - var(--railgap) - var(--railw))}
  @media(max-width:860px){.collprose{max-width:var(--collw)}}
  .hero{display:grid;grid-template-columns:minmax(0,2fr) minmax(180px,1fr);gap:1.2rem;align-items:start;margin:.8rem 0}
  .hero-maps{display:grid;grid-template-columns:1fr;gap:.6rem;max-width:520px}
  .hero-maps.two{max-width:none;grid-template-columns:1fr 1fr;align-items:start}
  .hero-maps svg{width:100%;height:auto;display:block}
  .hero-maps .mapcap{grid-column:1/-1}
  .herofacts{display:flex;flex-direction:column;gap:.55rem}
  .mapcap{font-size:.75rem;color:#8FA3B0;font-family:ui-monospace,Menlo,monospace}
  @media(max-width:760px){.hero-maps.two{grid-template-columns:1fr}}
  @media(max-width:640px){.hero{grid-template-columns:1fr}}
  .cstats{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0}
  .cstat{background:#18213D;border:1px solid #2B3557;border-radius:8px;padding:.55rem .9rem;min-width:96px}
  .cnum{color:#fff;font-size:1.15rem;font-weight:650;font-variant-numeric:tabular-nums}
  .clab{color:#8FA3B0;font-size:.75rem;text-transform:uppercase;letter-spacing:.07em}
  dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:1rem 0}
  dt{color:#8FA3B0}
  dd{margin:0}
  .lvl{border:1px solid #2B3557;border-radius:8px;padding:.7rem .9rem;margin:.6rem 0}
  .lvlhead{display:flex;align-items:center;gap:.6rem;margin-bottom:.35rem}
  .lvlbadge{font-family:ui-monospace,Menlo,monospace;font-size:.75rem;font-weight:600;background:#1E2B4F;border:1px solid #2B3557;border-radius:4px;padding:.1rem .45rem;color:#4FC3D9}
  .lvlname{color:#fff;font-weight:600;font-size:.95rem}
  .dtbl{border-collapse:collapse;font-size:.88rem;font-variant-numeric:tabular-nums;width:100%}
  .dtbl th{text-align:left;color:#8FA3B0;font-weight:600;padding:.24rem .8rem .24rem 0;border-bottom:1px solid #2B3557}
  .dtbl td{padding:.24rem .8rem .24rem 0;border-bottom:1px solid #1E2B4F}
  .dtbl tr:last-child td{border-bottom:none}
  .dtbl td:nth-child(2){font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;color:#8FA3B0}
  .lvlcover{margin:.2rem 0;font-size:.9rem}
  .lvlhost{margin:.15rem 0;font-size:.82rem;color:#8FA3B0}
  .lvlact{margin:.45rem 0 .1rem;font-size:.9rem}
  .tscroll{overflow-x:auto}
  .integrity{margin:.5rem 0 .1rem;font-size:.82rem}
  .integrity summary{cursor:pointer;color:#8FA3B0}
  .shacell{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#8FA3B0;word-break:break-all}
  .tspath{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#8FA3B0;word-break:break-all}
  .collmap{position:relative;margin:1rem 0 .4rem;max-width:var(--collw)}
  .collmap svg{width:100%;height:auto;display:block}
  .collmark{position:absolute;left:14px;bottom:14px;height:28px;width:auto;opacity:.82;pointer-events:none}
  @media(max-width:640px){.collmark{left:9px;bottom:9px;height:20px}}
  .colllegend{font-size:.78rem;color:#8FA3B0;display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin:.2rem 0 1rem}
  .collhero{display:grid;grid-template-columns:minmax(0,1fr) minmax(190px,230px);gap:1.2rem;align-items:start}
  .collhero .cstats{flex-direction:column;margin:1rem 0 0}
  @media(max-width:860px){.collhero{grid-template-columns:1fr;gap:0}.collhero .cstats{flex-direction:row}}
  .memlist{display:flex;flex-direction:column;gap:.5rem;margin:.6rem 0 1rem}
  .mem{border-bottom:1px solid #1E2B4F;padding-bottom:.5rem}
  .mem:last-child{border-bottom:none}
  .memt{margin:0 0 .1rem;font-size:.98rem;font-weight:650}
  .memfacts{margin:0;font-size:.84rem;color:#8FA3B0;font-variant-numeric:tabular-nums}
  .run{border:1px solid #2B3557;border-radius:8px;padding:.7rem .9rem;margin:.6rem 0}
  .run dl{margin:.3rem 0 .6rem}
  .runid{color:#fff;font-size:.95rem;margin:0}
  .doi{font-size:.8rem;color:#8FA3B0;margin-top:.35rem}
  .doi a{color:#4FC3D9}
  .people{display:flex;flex-direction:column;gap:.35rem;margin:.6rem 0;font-size:.88rem}
  .person{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem}
  .orcid{font-family:ui-monospace,Menlo,monospace;font-size:.75rem;color:#4FC3D9}
  .rolechip{font-size:.75rem;background:#1E2B4F;border:1px solid #2B3557;border-radius:3px;padding:.05rem .4rem;color:#8FA3B0}
  .pub{font-size:.88rem;margin:.4rem 0}
  .pub i{color:#8FA3B0}
  .stbl{border-collapse:collapse;width:100%;font-size:.82rem;font-variant-numeric:tabular-nums}
  .stbl th{text-align:left;color:#8FA3B0;font-weight:600;padding:.3rem .5rem .3rem 0;border-bottom:1px solid #2B3557;position:sticky;top:0;background:#11182D}
  .stbl td{padding:.2rem .5rem .2rem 0;border-bottom:1px solid #1E2B4F}
  .stbl th:first-child,.stbl td:first-child{position:sticky;left:0;background:#11182D;z-index:2;padding-left:.2rem}
  .stbl th:first-child{z-index:3}
  .stbl td:nth-child(2),.stbl td:nth-child(3),.stbl td:nth-child(4),.stbl td:nth-child(5){font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.76rem}
  .pidcell,.pidcell a{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;color:#4FC3D9}
  .ts-y{color:#5BAE6A;font-family:ui-monospace,Menlo,monospace;font-size:.76rem}
  .ts-n{color:#8FA3B0}
  .scroll{max-height:360px;overflow:auto;border:1px solid #2B3557;border-radius:6px;padding:0 .8rem}
  ul{padding-left:1.2rem}
  header.site{display:flex;align-items:center;line-height:normal;gap:12px 16px;padding:8px 18px;border-bottom:1px solid #2B3557;flex-wrap:wrap;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
  header.site,header.site *{box-sizing:border-box}
  .hzone{display:flex;align-items:center;gap:12px;min-width:0;flex-wrap:wrap}
  .hleft{flex:1 1 0;min-width:0}
  .hcenter{flex:0 1 auto;justify-content:center;gap:6px}
  .hright{flex:1 1 0;min-width:0;justify-content:flex-end;gap:0}
  .brandmark{height:30px;width:30px;display:block;flex:none}
  .orgmark{display:flex;align-items:center;flex:none;margin-left:16px}
  .orgmark img{height:30px;width:auto;display:block}
  .wordmark{font-weight:800;font-size:22px;letter-spacing:-.5px;color:#E8EDF1;text-decoration:none}
  .tagline{color:#8FA3B0;font-size:12.5px}
  header.site nav{display:flex;gap:6px;flex-wrap:wrap}
  header.site nav a{flex:1;min-width:112px;min-height:40px;display:flex;align-items:center;justify-content:center;background:#1E2B4F;border:1px solid #2B3557;color:#E8EDF1;font-size:14px;font-weight:600;padding:0 16px;border-radius:5px;text-decoration:none}
  header.site nav a:hover{border-color:#EF7256}
  header.site nav a.active{color:#16110b;background:#EF7256;border-color:#EF7256}
  .about,.contribute{color:#EF7256;font-size:13px;text-decoration:none;border:1px solid #2B3557;padding:6px 11px;border-radius:4px;white-space:nowrap}
  .about:hover,.contribute:hover{border-color:#EF7256}
  .counts{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:#8FA3B0;font-variant-numeric:tabular-nums}
  .counts b{color:#E8EDF1}
  @media(max-width:760px){.hzone{flex:1 1 100%;justify-content:flex-start}}
  footer{margin-top:2.2rem;border-top:1px solid #2B3557;padding-top:.7rem;font-size:.8rem;color:#8FA3B0}
  .frow{display:flex;flex-wrap:wrap;gap:.3rem 1.2rem;justify-content:space-between;margin:.3rem 0}
  .flinks{display:flex;gap:1.1rem}
"""


# The index pages' own rules, appended to _CSS for those two documents only (the entity pages stay
# byte-identical). One card grammar for both hubs: a small map, a linked title, one facts line.
#
# The hub column is WIDER than the entity pages' reading measure and narrower than their wide-screen
# one: a hub is scanned, not read, so 840px is tight, and a card stretched the full 1120px stops
# being a card. Both the base rule and the wide-screen media query are restated here, because
# _INDEX_CSS is appended AFTER _CSS and a media query only loses to another media query.
#
# The stretched link: the whole card is one destination, so the whole card is the target, but the
# TITLE stays the single real anchor and an inset ::after does the covering. That keeps the
# accessibility tree honest (one link, one accessible name) where a card wrapped in an anchor would
# read its map, its facts line and its licence as part of the link text, and it keeps buttons out of
# rows entirely (the hierarchy is catalogue -> survey -> data, and a row is not an action).
_INDEX_CSS = """
  main{max-width:920px}
  @media(min-width:1180px){main{max-width:920px}}
  .idxlede{max-width:62ch;margin:.2rem 0 .1rem}
  .idxsum{color:#8FA3B0;font-size:.92rem;font-variant-numeric:tabular-nums;margin:.2rem 0 .2rem}
  .idxact{font-size:.9rem;margin:.2rem 0 1.1rem}
  .idxlist{display:flex;flex-direction:column;gap:.7rem;margin:0 0 1rem}
  .idxcard{position:relative;display:grid;grid-template-columns:115px 1fr;gap:.9rem;align-items:start;background:#18213D;border:1px solid #2B3557;border-radius:8px;padding:.7rem .9rem}
  .idxcard svg{width:100%;height:auto;display:block}
  .idxcard:hover,.idxccard:hover{background:#1B2547;border-color:#3E4C7D}
  .idxt{color:#fff;font-size:1rem;font-weight:650;margin:0 0 .15rem}
  .idxt a{text-decoration:none}
  .idxt a::after{content:"";position:absolute;inset:0;border-radius:8px}
  .idxgo{position:absolute;right:.9rem;bottom:.7rem;color:#EF7256;opacity:0}
  .idxcard:hover .idxgo{opacity:1}
  .idxorg{font-size:.82rem;margin:0 0 .3rem}
  .idxorgn{color:#B4C2CC}
  .idxloc{color:#8FA3B0}
  .idxfacts{font-size:.82rem;margin:0;font-variant-numeric:tabular-nums}
  .sep{padding:0 .4em}
  .idxdoi{font-family:ui-monospace,Menlo,monospace;font-size:.75rem;background:#1E2B4F;border:1px solid #2B3557;border-radius:3px;padding:.05rem .4rem;color:#4FC3D9}
  .idxgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem;margin:0 0 1rem}
  .idxccard{position:relative;background:#18213D;border:1px solid #2B3557;border-radius:8px;padding:.9rem 1rem}
  .idxccard svg{width:100%;height:auto;display:block;margin:.5rem 0}
  .idxccard .idxact{margin:.2rem 0 0}
  .idxccard .idxact a{position:relative;z-index:1}
  .idxdesc{font-size:.85rem;margin:.4rem 0 .5rem}
  @media(max-width:640px){.idxcard{grid-template-columns:1fr}}
"""


# The three application tabs, in the order the SPA states them: (element id, label, destination).
# The ids are the SPA's own, so the two headers stay comparable element for element the way the
# portal's static-page chrome already is.
_NAV_TABS = (("navMap", "Map", "/"),
             ("navSurveys", "Surveys", "/surveys"),
             ("navCollections", "Collections", "/collections"))

# The parent-organisation mark, top right on every surface of the site. It is NOT the header's
# identity: the identity is the AusMT mark in the left zone, and this states whose service AusMT is,
# the same relationship the footer already puts in words. It closes the header, so it follows the
# primary nav in the tab order while staying focusable.
#
# Same-origin, and the same vendored file the documentation site's sidebar carries. It is stated
# character-identically in portal/index.html and in every portal document wearing this chrome, and
# pinned pairwise there (portal/tests/test_header_geometry_parity.py) for the reason the zone rules
# are: an edit to one surface must not leave the others on a different mark.
#
# The image is white with an alpha channel, which is the whole reason it can sit on this chrome
# untreated: every surface carrying it is dark, and the site declares no light theme.
#
# One unbroken source literal, like the header markup it joins: the pin reads this file's SOURCE and
# holds it character-identical against the portal documents' own.
_ORG_MARK = '<a class="orgmark" href="https://www.auscope.org.au" target="_blank" rel="noopener noreferrer" title="AuScope"><img src="/vendor/auscope-icon-white.png" alt="AuScope" width="29" height="30"></a>'


def _site_header(active="", status="") -> str:
    """The ONE header, everywhere: the SPA header's three-part division rendered as static links.

    Left is the AusMT identity and links the root. The centre carries the three filled application
    tabs with the CURRENT page's tab in the active state, and beside them the two smaller outlined
    supporting controls: the three tabs are the application, About and Contribute are functions
    around it, and the owner kept that distinction and their wording. The right zone is the status
    slot, which is CONTEXTUAL (see the callers) while the shell around it is identical.

    THE FETCHED ASSETS, WHICH ARE TWO AND NAMED. The identity zone opens with the AusMT mark, the
    same file and the same markup the SPA header carries, so a reader arriving on a survey page from a
    search result meets the site's own identity rather than a wordmark alone. The right zone closes
    with the AuScope mark, which states whose service this is and is not an identity. Both are
    SAME-ORIGIN paths served by the portal image beside these pages: not a build-time read, not an
    external fetch, and not 180 circles inlined into 2,655 documents. Everything else on the page
    stays inline, and the src allow-list in engine/tests/test_index_pages.py names these paths and
    nothing else.

    VERSION SKEW, STATED HONESTLY FOR THE FIRST DEPLOY. /vendor/* is served from the portal image and
    the pages tree from the data volume, so the two can be a deploy apart. Once both carry the mark
    that shows as a one-deploy-old logo, which is the acceptable failure mode for a logo and for
    nothing else in this tier. On the FIRST deploy it is worse than that, because the file is new: a
    pages tree rebuilt from this commit against a portal image that predates it asks for a mark the
    image does not serve, and every page renders the alt text instead. So the portal image and the
    data rebuild go out in the same pass, image first, and both /vendor/brand/ausmt-mark.svg and
    /vendor/auscope-icon-white.png answering 200 with an image type is the check before the pages
    tree is swapped.

    The AusMT mark is a fixed 30x30 box inside the zero-basis .hleft zone and the AuScope mark a
    fixed-height box inside the zero-basis .hright zone, so neither identity block can move the
    centre tab group: a zero-basis side hands its leftover space out evenly whatever it holds
    (tests/test_header_geometry_parity.py)."""
    tabs = "".join(
        f'<a id="{i}" href="{h}"' + (' class="active"' if i == active else "") + f">{lbl}</a>"
        for i, lbl, h in _NAV_TABS)
    return ('<header class="site">\n'
            # One unbroken literal on purpose: portal/tests/test_header_geometry_parity.py holds this
            # markup character-identical against portal/index.html's own, and it reads this file's
            # SOURCE (the pages sheet cannot be imported without the engine's path set up).
            '<div class="hzone hleft">'
            '<img class="brandmark" src="/vendor/brand/ausmt-mark.svg" alt="AusMT" width="30" height="30">'
            '<a class="wordmark" href="/">AusMT</a>'
            '<span class="tagline">Australia\'s Magnetotelluric Data Portal</span></div>\n'
            f'<div class="hzone hcenter"><nav>{tabs}</nav>'
            '<a class="about" href="/about.html">About</a>'
            f'<a class="contribute" href="/add-survey.html">Contribute a survey {_ARROW_FWD}</a>'
            "</div>\n"
            f'<div class="hzone hright">{status}{_ORG_MARK}</div>\n'
            "</header>\n")


def _site_footer(machine=None, build=None) -> str:
    """The contextual footer, two rows, on every page in this tier.

    Row 1 left is the machine-readable document FOR THIS PAGE, so a reader on a station page is
    handed that station's own record rather than the whole catalogue. The collection wording is
    deliberately honest: no per-collection document is served, so the footer says the collection's
    record lives in MTCAT rather than advertising a surface that does not exist. The arrow is the
    leaves-this-page one; these links hand over a JSON document, not another page of the site.

    Row 2 carries the attribution and the licence note. The build identity was removed from it
    (owner ruling 2026-08-31): the commit sha spoke to operators, not to the readers a public
    footer is for, and build_provenance.json still carries it for anyone who needs it. The `build`
    argument is kept so callers do not change and a future /build page has its input."""
    left = ""
    if machine:
        label, href = machine
        left = f'<a href="{_e(href)}">{_e(label)} {_ARROW_OUT}</a>'
    return ("\n<footer>\n"
            f'<div class="frow"><div>{left}</div>'
            '<div class="flinks"><a href="/releases.html">Releases</a>'
            '<a href="/about.html">About</a></div></div>\n'
            '<div class="frow"><span>&#169; 2026 AuScope and AusMT contributors - an AuScope '
            "service</span>"
            "<span>Data licences vary by survey; each download carries its licence.</span>"
            "</div>\n"
            "</footer>\n")


def _shell(*, title, description, canonical, body, jsonld=None, noindex=False,
           og_image=None, base="", extra_css="", nav="", machine=None, build=None,
           status="") -> str:
    # `jsonld` is ONE node or a list of nodes, emitted in order as one script element each. Order is
    # load-bearing: the entity node stays first on every page that carries one, so anything reading
    # "the page's structured data" gets the record the page is about and not its breadcrumb. A
    # @graph wrapper would have collapsed the two into a node no first-block reader can follow.
    nodes = [n for n in (jsonld if isinstance(jsonld, list) else [jsonld]) if n]
    ld = "".join(f'<script type="application/ld+json">{_jsonld(n)}</script>\n' for n in nodes)
    # noindex: the page exists for the URL contract and for humans following published links, but
    # is deliberately kept out of the search index (station pages: thousands of templated
    # documents would read as thin content at scale and dilute the survey/collection pages that
    # carry the ranking).
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    # Link previews: crawlers resolve nothing relative, so og:url/og:image are absolute.
    image = og_image or (f"{base}/vendor/social-card.png" if base else None)
    og = ""
    if image:
        og = (f'<meta property="og:type" content="website">\n'
              # The SITE's name, not the publisher's. Every page states it, station pages included:
              # a preview card that names the wrong site is wrong wherever it is shared, and the
              # station pages are exactly the ones an inbound link is most likely to land on.
              f'<meta property="og:site_name" content="{_SITE_NAME}">\n'
              f'<meta property="og:title" content="{_e(title)}">\n'
              f'<meta property="og:description" content="{_e(description)}">\n'
              f'<meta property="og:url" content="{_e(canonical)}">\n'
              f'<meta property="og:image" content="{_e(image)}">\n'
              f'<meta name="twitter:card" content="summary_large_image">\n')
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"{robots}"
        f"<title>{_e(title)}</title>\n"
        f'<meta name="description" content="{_e(description)}">\n'
        f'<link rel="canonical" href="{_e(canonical)}">\n'
        # ICON LINKS (brand-assets lane E4). This tier shipped none, so every one of the entity pages
        # asked the server for /favicon.ico on every visit and got a 404. Both are same-origin portal
        # paths served beside these pages, and both are absolute because a page served at
        # /surveys/<slug> cannot resolve a relative vendor path. The favicon is transparent, so the one
        # file serves a light and a dark browser chrome.
        '<link rel="icon" href="/vendor/favicon.svg" type="image/svg+xml">\n'
        '<link rel="apple-touch-icon" href="/vendor/brand/ausmt-icon-180.png">\n'
        f"{og}"
        f"{ld}"
        f"<style>{_CSS}{extra_css}</style>\n</head>\n<body>\n"
        f"{_site_header(nav, status)}"
        "<main>\n"
        f"{body}"
        f"{_site_footer(machine, build)}"
        "</main>\n</body>\n</html>\n"
    )


def _survey_years(sm_doc, smeta):
    cov = ((sm_doc or {}).get("dates") or {}).get("coverage") or {}
    y0 = cov.get("year_start") or (smeta or {}).get("year_start")
    y1 = cov.get("year_end") or (smeta or {}).get("year_end")
    if y0 and y1:
        return f"{y0}" if y0 == y1 else _range(y0, y1)
    return str(y0 or y1 or "")


def _station_points(docs):
    """[(lon, lat, type)] for every station whose served document discloses a position."""
    pts = []
    for doc in docs:
        loc = doc.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            pts.append((float(loc["lon"]), float(loc["lat"]),
                        ((doc.get("data") or {}).get("type"))))
    return pts


def _run_summary(docs):
    """(sample rates set, dipole lengths list) across the survey's published runs."""
    rates, dipoles = set(), []
    for doc in docs:
        for run in doc.get("runs") or []:
            if run.get("sample_rate_hz"):
                rates.add(run["sample_rate_hz"])
            for ch in run.get("channels") or []:
                if ch.get("component", "").startswith("e") and ch.get("dipole_length_m"):
                    dipoles.append(float(ch["dipole_length_m"]))
    return rates, dipoles


def _person_rows(contributors):
    """Contributors grouped by (name, orcid), roles in first-seen order, names as initials."""
    order, roles, orcids = [], {}, {}
    for c in contributors or []:
        name = (c or {}).get("name") or ""
        if not name:
            continue
        key = name
        if key not in roles:
            order.append(key)
            roles[key] = []
            orcids[key] = (c or {}).get("orcid")
        role = _ROLE_LABELS.get((c or {}).get("role") or "", (c or {}).get("role"))
        if role and role not in roles[key]:
            roles[key].append(role)
    rows = []
    for name in order:
        chips = "".join(f'<span class="rolechip">{_e(r)}</span>' for r in roles[name])
        orcid = (f'<a class="orcid" href="https://orcid.org/{_e(orcids[name])}">{_e(orcids[name])}</a>'
                 if orcids[name] else "")
        rows.append(f'<div class="person"><span>{_e(_initials(name))}</span>{orcid}{chips}</div>')
    return rows


def _ts_survey_rows(slug, ts_access):
    """{level key: {aid: row}} for one survey, from the served register.

    Membership is the documented ausmt_id prefix test, `au.<slug>.` (the API reference states it as
    the way to filter by slug), not a split on dots with a component count. The count form dropped
    every row of a survey whose slug contains a dot, and dropped the variant ids that carry a fourth
    component, both silently."""
    prefix = f"au.{slug}."
    out: dict = {}
    for aid, levels in (ts_access or {}).items():
        if not str(aid).startswith(prefix):
            continue
        for level, row in (levels or {}).items():
            out.setdefault(level, {})[aid] = row
    return out


def _related_by_identifies(smeta):
    out = {}
    for row in (smeta or {}).get("related_identifiers") or []:
        key = (row or {}).get("identifies")
        if key and key not in out:
            out[key] = row
    return out


# The AusMT access acknowledgement, verbatim from AUSMT-DATA-CITATION-AND-ACKNOWLEDGEMENT-MODEL.md
# section 9. It is a SEPARATE statement from the citation and is never folded into it: providing
# access does not make AusMT the cited object.
_ACKNOWLEDGEMENT = ("Data were accessed through the AusMT national magnetotelluric data portal.")

# The related-identifier scopes that name THIS SURVEY RECORD rather than something near it. Only
# `entire` qualifies. A collection row names the parent, a raw_packed row names the time-series
# archive, a level3 row names a derived model and a level2 row names the published transfer-function
# PRODUCT: each is a resource of the survey, not the survey, and the model requires that distinction
# to survive (AUSMT-DATA-CITATION-AND-ACKNOWLEDGEMENT-MODEL.md section 14, with survey-level and
# resource-level citation separated in section 7). Promoting a product identifier would print it
# under the survey's own authors and publisher, which asserts a citation neither layer states.
_SELF_IDENTIFIES = ("entire",)


def _citation_locator(smeta, access_url):
    """The locator slot of the formatted citation, SOURCE-LED and SCOPE-BOUND.

    A citation should identify the dataset as persistently and specifically as the source allows
    (AUSMT-DATA-CITATION-AND-ACKNOWLEDGEMENT-MODEL.md sections 3 and 4). Where the survey's own
    record carries a persistent identifier FOR ITSELF, that identifier is the locator. The AusMT
    page URL is used only where the record carries none, and then as the access route rather than as
    a claim that the AusMT page is the object being cited.

    Two rows claiming the same self-identifying scope are not a tie to break. Row order in a curated
    YAML file is not a curation decision, so an ambiguous record promotes nothing and keeps the
    access route: section 13 rules that an absent preferred citation means AusMT asserts none, which
    is true and useful, where an arbitrary pick is neither. Naming one target among several is a
    curation act belonging in a curator-declared preferred identifier (section 12)."""
    doi = _doi_url((smeta or {}).get("doi"))
    if doi:
        return doi
    pid = str((smeta or {}).get("pid") or "").strip()
    if pid.startswith(("http://", "https://")):
        return pid
    for key in _SELF_IDENTIFIES:
        rows = [row for row in (smeta or {}).get("related_identifiers") or []
                if (row or {}).get("identifies") == key]
        if not rows:
            continue
        url = _doi_url(rows[0].get("identifier")) if len(rows) == 1 else None
        return url or access_url
    return access_url


# The corpus's own spelling for each recorded channel, in the order a page prints them: electric
# first, then the horizontal magnetic pair, then the vertical coil. The keys are the normalised
# form (lowercase, B-for-H folded) that build_portal's channels_recorded masks read, so a survey
# declaring Hz and a survey declaring Bz are the same declaration to both.
_CHANNEL_LABELS = {"ex": "Ex", "ey": "Ey", "hx": "Bx", "hy": "By", "hz": "Bz"}


def _channel_key(name) -> str:
    """One declared channel name in the normalised form the impedance and tipper masks use."""
    key = str(name).strip().lower()
    return "h" + key[1:] if key.startswith("b") else key


def _channels_declared(declared) -> str:
    """The channels tile from the survey's OWN channels_recorded declaration.

    The declaration is the ratified authority on what a survey measured: it is what masks the
    impedance and the tipper survey-wide, so it is also what the page may state. Known channels
    print in the corpus's spelling and in one fixed order, and a channel outside that vocabulary
    prints as the declaration spells it rather than being dropped, because a tile that silently
    discards a declared channel is the same defect as one that invents an undeclared one."""
    seen = {}
    for raw in declared or []:
        name = str(raw).strip()
        if name:
            seen.setdefault(_channel_key(name), name)
    known = [label for key, label in _CHANNEL_LABELS.items() if key in seen]
    other = sorted(name for key, name in seen.items() if key not in _CHANNEL_LABELS)
    return " ".join(known + other)


def _survey_kind(served_types) -> str:
    """What KIND of survey this is, in lower case, from the same served station types the data-type
    badge prints. A geomagnetic depth sounding survey records no electric field and estimates no
    impedance, so calling it magnetotelluric is wrong in the crumb, the page title, the meta
    description and the structured data alike. A survey serving both kinds names both: neither half
    is a rewrite of the other, and naming only the larger one would suppress a real holding. A
    survey whose stations disclose no type keeps the magnetotelluric reading, which is what the
    corpus is."""
    gds = "GDS" in served_types
    if gds and served_types - {"GDS"}:
        return "magnetotelluric and geomagnetic depth sounding survey"
    return "geomagnetic depth sounding survey" if gds else "magnetotelluric survey"


def survey_page(*, slug, label, sm_doc, smeta, station_docs, bundle_rows, ts_access,
                base, extent=None, discovery=None, build=None, og_image=None) -> str:
    """`og_image` is the absolute URL of the card the EMITTER has already written for this survey,
    or None for the portal's root card. The page used to derive it from "is Pillow importable",
    which is a claim about the environment rather than about the file: a card whose write failed
    still left the page advertising it, and a link preview then fetched a 404."""
    smeta = smeta or {}
    title = ((sm_doc or {}).get("title")) or label
    blurb = smeta.get("blurb") or ""
    org = smeta.get("org") or ""
    lic = smeta.get("lic") or ""
    region = smeta.get("region") or "Australia"
    version = smeta.get("version") or ""
    years = _survey_years(sm_doc, smeta)
    url = f"{base}/surveys/{slug}"
    docs = sorted(station_docs, key=lambda d: str(d.get("station") or d.get("ausmt_id")))
    n_stations = len(docs)

    # ---- aggregates from the served station documents ----
    type_counts: dict = {}
    pmin = pmax = None
    tipper = 0
    for doc in docs:
        data = doc.get("data") or {}
        t = data.get("type")
        if t:
            type_counts[t] = type_counts.get(t, 0) + 1
        for key, cmp_ in (("period_min_s", min), ("period_max_s", max)):
            v = data.get(key)
            if v is not None:
                if key == "period_min_s":
                    pmin = v if pmin is None else min(pmin, v)
                else:
                    pmax = v if pmax is None else max(pmax, v)
        if ((doc.get("diagnostics") or {}).get("tipper_available")):
            tipper += 1
    rates, dipoles = _run_summary(docs)
    points = _station_points(docs)
    # DISCOVERY FALLBACK (embargoed and metadata-only surveys): the withheld station documents
    # deliberately carry no position or science, but the survey IS in the public catalogue with
    # coordinates, types and period rollups (discovery-universal posture). The page shows exactly
    # that discovery layer - locations, types, the period band - and nothing the gate withholds.
    disc_by_station = {}
    if not points and discovery:
        for row in discovery.get("stations") or []:
            # mtcat's station_id IS the ausmt id (the rollup publishes the full form).
            disc_by_station[row.get("station_id")] = row
            if row.get("latitude") is not None and row.get("longitude") is not None:
                points.append((float(row["longitude"]), float(row["latitude"]),
                               row.get("data_type")))
                type_counts[row.get("data_type")] = type_counts.get(row.get("data_type"), 0) + 1
        srow = (discovery or {}).get("survey") or {}
        if pmin is None:
            pmin, pmax = srow.get("period_min_s"), srow.get("period_max_s")
        if not tipper:
            tipper = int(srow.get("n_stations_tipper") or 0)

    # The band classes this survey actually serves, read once and spent on both the survey's kind
    # and the channels tile's fallback, so the two can never disagree about the same stations. Read
    # after the discovery fallback, which is what fills the types for an embargoed survey.
    served_types = {t for t in type_counts if t}
    # The kind is derived once and spent on every surface that names it: the crumb, the page title,
    # the meta-description fallback and the JSON-LD name must tell one story.
    kind = _survey_kind(served_types)
    kind_lead = kind[0].upper() + kind[1:]
    desc = (blurb or f"{kind_lead} data: {title}.").strip()
    desc_meta = _meta_summary(desc)

    # ---- JSON-LD ----
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": f"{title} {kind}",
          "description": desc, "url": url,
          "identifier": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "measurementTechnique": "magnetotellurics",
          "variableMeasured": "magnetotelluric transfer function",
          "keywords": ["magnetotellurics", "MT", "transfer function", "geophysics", "Australia"]}
    if org:
        creator = {"@type": "Organization", "name": org}
        if smeta.get("org_ror"):
            creator["sameAs"] = smeta["org_ror"]
        ld["creator"] = creator
    if lic:
        ld["license"] = _LICENSE_URLS.get(lic, lic)
    if version:
        ld["version"] = str(version)
    if years:
        ld["temporalCoverage"] = years.replace(" - ", "/")
    same_as = [u for u in (_doi_url((row or {}).get("identifier"))
                           for row in (smeta.get("related_identifiers") or [])) if u]
    if same_as:
        ld["sameAs"] = same_as
    pubs = smeta.get("pubs") or []
    if pubs:
        ld["citation"] = [{"@type": "ScholarlyArticle", "name": p.get("t"),
                           **({"sameAs": _doi_url(p["doi"])} if p.get("doi") else {})}
                          for p in pubs if p.get("t")]
    funders = smeta.get("funders") or []
    if funders:
        ld["funder"] = [{"@type": "Organization", "name": f.get("name"),
                         **({"sameAs": f["pid"]} if f.get("pid") else {})}
                        for f in funders if f.get("name")]
    # spatialCoverage: the DECLARED extent tuple (west, east, south, north) from _extent_of when
    # the survey declares one, else the bbox of the served (posture-filtered) station positions.
    box = None
    if extent and len(extent) == 4:
        w, e_, s, n = extent
        box = (s, w, n, e_)
    elif points:
        lons = [pt[0] for pt in points]
        lats = [pt[1] for pt in points]
        box = (min(lats), min(lons), max(lats), max(lons))
    if box:
        ld["spatialCoverage"] = {"@type": "Place", "geo": {
            "@type": "GeoShape", "box": f"{box[0]} {box[1]} {box[2]} {box[3]}"}}

    # ---- downloads: one product card per level, and one for the transfer functions ----
    # Each card states what a reader chooses on (coverage, size, host) and carries exactly one
    # action. Every number comes from the register or the manifest; a level with no register rows
    # renders no card at all, so absence is never dressed as a pending download.
    dist = []
    ts_rows = _ts_survey_rows(slug, ts_access)
    panels = []
    related = _related_by_identifies(smeta)
    archive_doi_placed = False
    for level_key, badge, name in _TS_LEVELS:
        rows = ts_rows.get(level_key)
        if not rows:
            continue
        total = sum((r or {}).get("bytes") or 0 for r in rows.values())
        per = (f", about {_fmt_bytes(total / len(rows))} per station" if total else "")
        doi_bits = []
        # The archive-release DOI names the packed raw archive, so it rides the first raw-family
        # card this survey renders and never repeats on a second one.
        if related.get("raw_packed") and level_key in ("raw_packed", "level0") \
                and not archive_doi_placed:
            u = _doi_url(related["raw_packed"].get("identifier"))
            if u:
                archive_doi_placed = True
                doi_bits.append(f'Archive release: <a href="{_e(u)}">{_e(_bare_doi(related["raw_packed"].get("identifier")) or u)}</a>')
        if related.get("collection"):
            u = _doi_url(related["collection"].get("identifier"))
            if u:
                doi_bits.append(f'part of <a href="{_e(u)}">{_e(_bare_doi(related["collection"].get("identifier")) or u)}</a>')
        doi_line = f'<div class="doi">{" &#183; ".join(doi_bits)}</div>' if doi_bits else ""
        panels.append(
            f'<div class="lvl"><div class="lvlhead"><span class="lvlbadge">{badge}</span>'
            f'<span class="lvlname">{_e(name)}</span></div>'
            f'<p class="lvlcover"><b style="color:#fff">{len(rows)} of {n_stations} stations'
            f"</b>{per}</p>"
            f'<p class="lvlhost">Hosted at NCI</p>'
            f'<p class="lvlact"><a href="/#/survey/{_e(slug)}">Build a download script</a></p>'
            f"{doi_line}</div>")
    bundle_items, integrity_items = [], []
    for row in sorted(bundle_rows or [], key=lambda r: (r or {}).get("format") or ""):
        fmt = (row or {}).get("format")
        lbl, mime = _BUNDLE_LABELS.get(fmt, (fmt, "application/octet-stream"))
        rel = (row or {}).get("url") or ""
        size = _fmt_bytes(row.get("size"))
        sha = str(row.get("sha256") or "")
        nst = row.get("n_stations")
        meta_bits = " &#183; ".join(b for b in
                                    ([f"{int(nst)} stations"] if nst else [])
                                    + ([size] if size else []))
        bundle_items.append(f"<tr><td>{_e(lbl)}</td><td>{meta_bits}</td>"
                            f'<td><a href="/data/{_e(rel)}">Download &#8595;</a></td></tr>')
        # The COMPLETE digest, from the manifest row the page already reads. The page used to carry
        # an 8-character prefix, which is not enough to verify anything; the whole value belongs on
        # the page but not in competition with format and size, so it sits behind a disclosure.
        if sha:
            integrity_items.append(f"<tr><td>{_e(lbl)}</td>"
                                   f'<td class="shacell">sha256 {_e(sha)}</td></tr>')
        dist.append({"@type": "DataDownload", "encodingFormat": mime,
                     "contentUrl": f"{base}/data/{rel}"})
    integrity = ""
    if integrity_items:
        integrity = ('<details class="integrity"><summary>Integrity details</summary>'
                     '<table class="dtbl">' + "".join(integrity_items) + "</table></details>")
    if bundle_items:
        doi_line = ""
        if related.get("level2"):
            u = _doi_url(related["level2"].get("identifier"))
            if u:
                doi_line = (f'<div class="doi">Published release: <a href="{_e(u)}">'
                            f'{_e(_bare_doi(related["level2"].get("identifier")) or u)}</a></div>')
        # Host attribution from the manifest's own tier, and only where every row agrees: a mixed
        # card would have to name a host per row, and the tier is the manifest's word, not ours.
        tiers = {(r or {}).get("tier") for r in (bundle_rows or [])}
        host = {"repo": "Hosted by AusMT", "nci": "Hosted at NCI"}.get(
            next(iter(tiers)) if len(tiers) == 1 else None, "")
        host_line = f'<p class="lvlhost">{host}</p>' if host else ""
        panels.append(
            '<div class="lvl"><div class="lvlhead"><span class="lvlbadge">L2</span>'
            '<span class="lvlname">Transfer functions</span></div>'
            f"{host_line}"
            '<table class="dtbl">' + "".join(bundle_items)
            + f"</table>{integrity}{doi_line}</div>")
    if dist:
        ld["distribution"] = dist

    # ---- head-of-page blocks ----
    # The site crumb the station and collection pages already carry: a survey page is the most
    # likely landing page from search and social, and it had no route back to the root at all.
    crumb = (f'<p class="crumb"><a href="/">AusMT</a> / <a href="/surveys">surveys</a> / '
             f"{_e(title)}</p>")
    nav = ('<div class="pagenav"><a class="navbtn" href="/surveys">&#8592; All surveys</a>'
           f'<a class="navbtn map" href="/#/survey/{_e(slug)}">View all stations on the main map</a></div>')
    # The discovery edge into the collection this survey belongs to. A NAVIGATION link, never a
    # citable-parent claim: collections are a discovery layer and hold no transfer functions of
    # their own. Rendered only where the survey's own record declares membership.
    coll_line = ""
    _coll = smeta.get("collection") or {}
    if _coll.get("id"):
        coll_line = (f'<p class="crumb">Part of the <a href="/collections/{_e(_coll["id"])}">'
                     f'{_e(_coll.get("title") or _coll["id"])}</a> collection</p>')
    cite = ""
    c = smeta.get("cite") or {}
    if c.get("au") or c.get("ti"):
        parts = [f"{_e(_initials(c.get('au')))}" if c.get("au") else _e(org)]
        if c.get("yr"):
            parts.append(f"({_e(c['yr'])}):")
        parts.append(f"<i>{_e(c.get('ti') or title)}.</i>")
        if c.get("ve"):
            parts.append(f"Version {_e(c['ve'])}.")
        if c.get("pb"):
            parts.append(f"{_e(c['pb'])}.")
        cite = ('<details class="cite"><summary>Cite this survey</summary>'
                '<p class="citeline"><span style="color:#8FA3B0">Cite as:</span> '
                + " ".join(parts)
                + f' <code>{_e(_citation_locator(smeta, url))}</code></p>'
                + f'<p class="citeack">{_ACKNOWLEDGEMENT}</p></details>')
    embargo = ""
    if (smeta.get("access") or "").lower() == "embargoed":
        until = smeta.get("embargo_until")
        embargo = (f'<div class="embargo">This survey is under embargo'
                   f'{f" until {_e(until)}" if until else ""}: its transfer functions are not '
                   f"yet distributed. Discovery metadata is published now; the data follows when "
                   f"the embargo lifts.</div>")

    # ---- the type badge and the lede ----
    # The badge states the survey's data type(s) beside the title, from the served station
    # documents' own type counts; a survey whose documents disclose no type shows no badge.
    type_str = " / ".join(f"{t}" if len(type_counts) == 1 else f"{t} {n}"
                          for t, n in sorted(type_counts.items())) if type_counts else ""
    # The leading space is content, not layout: without it the h1's text content, its accessible
    # name and a copy-paste of the title all run the badge onto the last word ("...2019BBMT"). The
    # .typebadge margin stays beside it, because a space before an inline-block can collapse at a
    # line wrap and the visual gap must not be the only separator either.
    type_badge = f' <span class="typebadge">{_e(type_str)}</span>' if type_str else ""
    # The lede is the blurb's OWN first sentence, never a rewrite: an opening line the reader can
    # take in before the map, with the full abstract one section down. A blurb whose first sentence
    # is the whole blurb simply reads twice, which is honest for a one-sentence abstract.
    lede_text = _first_sentences(blurb, limit=1)
    lede = f'<p class="lede">{_e(lede_text)}</p>' if lede_text else ""

    # ---- hero: the map leads, the fixed metric core rides beside it ----
    compact = False
    if points:
        lons = [pt[0] for pt in points]
        lats = [pt[1] for pt in points]
        compact = max(max(lons) - min(lons), max(lats) - min(lats)) < 8 and len(points) > 1
    maps = [_minimap_svg(points, compact=compact)]
    cap = ""
    if compact:
        maps.append(_footprint_svg(points))
        cap = ('<div class="mapcap">'
               + _range(_hemisphere(min(lats), "S", "N"), _hemisphere(max(lats), "S", "N"))
               + " &#183; "
               + _range(_hemisphere(min(lons), "W", "E"), _hemisphere(max(lons), "W", "E"))
               + "</div>")

    def tile(num, lab):
        return f'<div class="cstat"><div class="cnum">{num}</div><div class="clab">{lab}</div></div>'
    # The FIXED core (brief 13): stations, type, acquisition, period. Every survey answers these in
    # the same four slots and the same order, so the rhythm is predictable across the corpus; each
    # is still presence-guarded, because a predictable slot is not a licence to invent a value.
    core = [tile(n_stations, "stations")]
    if type_str:
        core.append(tile(_e(type_str), "data type"))
    if years:
        core.append(tile(_e(years), "acquired"))
    if pmin is not None and pmax is not None:
        core.append(tile(f'{_range(_fmt_period(pmin), _fmt_period(pmax))} s', "period coverage"))
    # Two maps ride SIDE BY SIDE on a wide screen: stacked, the locator and the zoom together stand
    # over a thousand pixels tall in the widened column, which pushes the metric rail's own content
    # off the first screen and makes the hero a scroll rather than a view.
    hero = (f'<div class="hero"><div class="hero-maps{" two" if len(maps) > 1 else ""}">'
            f'{"".join(maps)}{cap}</div>'
            f'<div class="herofacts">{"".join(core)}</div></div>')

    # ---- the optional secondary metrics, after the hero ----
    # Channels recorded: what the survey actually measured, from its own declaration where it makes
    # one and from the served components where it does not. The declaration is the authority the
    # build already acts on (it masks the impedance and the tipper survey-wide), so a page that
    # contradicted it would contradict the data beside it. With no declaration the tile may assert
    # only what the served components corroborate: a survey serving nothing but tipper-only stations
    # recorded no electric field, and Ex Ey on that tile is an invented channel. The tipper tile
    # appears only where a tipper exists (a zero count is the channels tile's job).
    channels = _channels_declared(smeta.get("channels_recorded"))
    if not channels:
        if served_types and not (served_types - {"GDS"}):
            channels = "Bx By Bz"
        else:
            channels = "Ex Ey Bx By" + (" Bz" if tipper == n_stations and n_stations else "")
            if 0 < tipper < n_stations:
                channels = "Ex Ey Bx By (+Bz)"
    tiles = [tile(_e(channels), "channels recorded")] if channels else []
    if tipper:
        tiles.append(tile(f"{tipper} / {n_stations}", "tipper stations"))
    if len(rates) == 1:
        tiles.append(tile(f"{next(iter(rates)):,.0f} Hz", "sample rate"))
    if version:
        tiles.append(tile(_e(version), "version"))
    stats = f'<div class="cstats">{"".join(tiles)}</div>'

    # ---- facts ----
    facts = []
    if org:
        org_html = (f'<a href="{_e(smeta["org_ror"])}">{_e(org)}</a>'
                    if smeta.get("org_ror") else _e(org))
        facts.append(f"<dt>Organisation</dt><dd>{org_html}</dd>")
    if lic:
        facts.append(f"<dt>Licence</dt><dd>{_e(_fmt_licence(lic))}</dd>")
    if len(rates) > 1:
        facts.append(f"<dt>Sample rates</dt><dd>{', '.join(f'{r:,.0f}' for r in sorted(rates))} Hz</dd>")
    # The dipole summary and the survey-level instrument PID are gone by ruling: dipoles live in
    # the station table, and the platform-PID registry is retired (per-station PIDs remain).
    if smeta.get("instrument_model"):
        instruments = "<br>".join(_e(part.strip())
                                  for part in str(smeta["instrument_model"]).split(";") if part.strip())
        facts.append(f"<dt>Instruments</dt><dd>{instruments}</dd>")
    if smeta.get("software"):
        facts.append(f"<dt>Processing</dt><dd>{_e(smeta['software'])}</dd>")
    # Activity-scope related identifiers (e.g. ANSIR project records): a labelled link, one per
    # line. The label is the record id where the URL carries one, else the bare host.
    projects = []
    for row in smeta.get("related_identifiers") or []:
        if (row or {}).get("scope") != "activity":
            continue
        u = str(row.get("identifier") or "")
        if not u:
            continue
        m = re.search(r"[?&]id=([A-Za-z0-9._-]+)", u)
        label = m.group(1) if m else re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        projects.append(f'<a href="{_e(_doi_url(u))}">{_e(label)}</a>')
    if projects:
        facts.append(f"<dt>Project</dt><dd>{'<br>'.join(projects)}</dd>")
    if funders:
        bits = []
        for f in funders:
            name = _e(f.get("name") or "")
            if not name:
                continue
            if f.get("pid"):
                name = f'<a href="{_e(f["pid"])}">{name}</a>'
            grant = f.get("grant_id")
            bits.append(name + (f" (grant {_e(grant)})" if grant else ""))
        facts.append(f"<dt>Funding</dt><dd>{'<br>'.join(bits)}</dd>")
    facts_html = f"<dl>{''.join(facts)}</dl>" if facts else ""

    # ---- contributors / publications ----
    people = _person_rows(smeta.get("contributors"))
    people_html = f'<div class="people">{"".join(people)}</div>' if people else ""
    pub_rows = []
    for p in pubs:
        doi = _doi_url(p.get("doi"))
        link = f' <a href="{_e(doi)}">{_e(_bare_doi(p.get("doi")) or "")}</a>' if doi else ""
        pub_rows.append(f'<p class="pub">{_e(p.get("a") or "")} ({_e(p.get("y") or "")}). '
                        f'{_e(p.get("t") or "")}. <i>{_e(p.get("j") or "")}.</i>{link}</p>')
    pubs_html = (f'<h2 id="publications">Publications</h2>{"".join(pub_rows)}'
                 if pub_rows else "")

    # ---- the station table ----
    # The five default columns of design brief 17. Deployment and instrument metadata used to live
    # here in eight more columns, which is why the station pages had to grow their Runs section
    # FIRST: the survey table is a chooser, and the per-station detail belongs behind the station
    # link this table's first column already carries.
    header = ["Station", "Lat", "Lon", "T max (s)", "Time series"]
    rows_html = []
    for doc in docs:
        aid = doc["ausmt_id"]
        st = doc.get("station") or aid
        loc = doc.get("location") or {}
        data = doc.get("data") or {}
        drow = disc_by_station.get(aid) or {}
        cells = [f'<td><a href="/stations/{_e(aid)}">{_e(st)}</a></td>']
        for v in (loc.get("lat") if loc.get("lat") is not None else drow.get("latitude"),
                  loc.get("lon") if loc.get("lon") is not None else drow.get("longitude")):
            cells.append(f"<td>{v if v is not None else '-'}</td>")
        pm = data.get("period_max_s")
        cells.append(f"<td>{_fmt_period(pm) if pm is not None else '-'}</td>")
        level_bits = []
        for level_key, level_badge, _name in _TS_LEVELS:
            row = (ts_rows.get(level_key) or {}).get(aid)
            if row:
                size = _fmt_bytes((row or {}).get("bytes"))
                level_bits.append(f"{level_badge} {size}" if size else level_badge)
        cells.append(f'<td class="ts-y">{" &#183; ".join(level_bits)}</td>'
                     if level_bits else '<td class="ts-n">-</td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")
    table = ""
    if rows_html:
        table = (f'<h2 id="stations">Stations ({n_stations})</h2>'
                 '<div class="scroll"><table class="stbl"><thead><tr>'
                 + "".join(f"<th>{h}</th>" for h in header)
                 + "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div>")

    # ---- the page, in the brief's sequence ----
    # Hero (geography and the fixed core) first, then the named sections in one fixed order, each
    # with an id anchor so a reader can be sent to a section rather than to a page. About carries
    # the FULL abstract; the hero's lede is its first sentence.
    about = (f'<h2 id="about">About this survey</h2>\n'
             f'<p class="prose">{_e(blurb)}</p>\n') if blurb else ""
    downloads = (f'<h2 id="data">Data and downloads</h2>\n{"".join(panels)}\n'
                 if panels else "")
    provenance = ""
    if people_html or facts_html:
        provenance = "\n".join(
            p for p in ('<h2 id="contributors">Contributors and organisations</h2>',
                        people_html, facts_html) if p)
    # Slots that render nothing leave NOTHING behind: joining the non-empty ones means a survey with
    # no collection, no citation record or no publications does not carry a stray blank line where
    # that block would have been (13 of the 27 served pages carried one).
    body = "\n".join(part.rstrip("\n") for part in (
        crumb,
        nav,
        f"<h1>{_e(title)}{type_badge}</h1>",
        f'<p class="crumb">{_e(kind_lead)} &#183; {_e(region)}'
        + (f" &#183; {_e(org)}" if org else "") + "</p>",
        coll_line, cite, embargo, lede, hero, stats,
        about, downloads, table, provenance, pubs_html,
        '<h2 id="identifiers">Identifiers and provenance</h2>\n'
        f'<p><a href="/data/products/{_e(slug)}/survey-metadata.json">Machine-readable survey record</a>'
        ' &#183; catalogue schema <a href="/data/mtcat.schema.json">mtcat 2.0</a></p>',
    ) if part) + "\n"
    return _shell(title=f"{title} - {kind} data - AusMT",
                  description=desc_meta, canonical=url, body=body,
                  jsonld=[ld, _breadcrumb(base, [(_SITE_NAME, "/"), ("surveys", "/surveys"),
                                                 (title, f"/surveys/{slug}")])],
                  og_image=og_image, base=base, nav="navSurveys", build=build,
                  machine=("Machine-readable survey metadata - JSON",
                           f"/data/products/{slug}/survey-metadata.json"))


def _unit_value(uv) -> str:
    """A unit_value rendered in BOTH the forms the document carries.

    The schema keeps `source_value` as "the source text, never discarded after normalisation" and
    makes `value` optional because "a missing value beats a confidently wrong one". So the page
    shows the normalised value with its unit where the parse was safe, and the source string it was
    read from beside it where the two differ; a row carrying only source text shows only that."""
    uv = uv or {}
    src = str(uv.get("source_value") or "").strip()
    value, unit = uv.get("value"), uv.get("unit")
    if value is None or not unit:
        return _e(src)
    shown = f"{value:,g} {unit}"
    return _e(shown) if shown == src else f"{_e(shown)} ({_e(src)})"


def _instrument_text(inst) -> str:
    """An instrument as the document states it: make and model, the serial where one is asserted,
    and each PID as a resolvable link. Every part is presence-guarded; an instrument object that
    carries nothing renders nothing, so a caller can test the return value for emptiness."""
    inst = inst or {}
    name = " ".join(b for b in (str(inst.get("manufacturer") or "").strip(),
                                str(inst.get("model") or "").strip()) if b)
    out = [_e(name)] if name else []
    serial = str(inst.get("serial_number") or "").strip()
    if serial:
        out.append(f"serial {_e(serial)}")
    for row in inst.get("identifiers") or []:
        ident = (row or {}).get("identifier")
        url = _doi_url(ident)
        if url:
            out.append(f'<a class="pidcell" href="{_e(url)}">{_e(_bare_doi(ident) or ident)}</a>')
    return " &#183; ".join(out)


# The channel columns, in render order: (header, reader). A column is emitted only where at least
# one channel of the run RENDERS it, so a run without electrodes draws no dipole column and a run
# whose source recorded no contact resistance draws no resistance column full of hyphens. Each guard
# asks the same reader the column's cells will ask, because a key can be present and still render
# nothing: a unit_value carrying only library defaults is a truthy dict and an empty string, and a
# guard on the object would head a column of hyphens over a measurement the source never made.
def _channel_cells(run):
    channels = [ch for ch in (run.get("channels") or []) if (ch or {}).get("component")]
    if not channels:
        return "", []
    cols = []
    if any(ch.get("measurement_azimuth_deg") is not None for ch in channels):
        cols.append(("Azimuth", lambda ch: (f"{ch['measurement_azimuth_deg']:g}&#176;"
                                            if ch.get("measurement_azimuth_deg") is not None
                                            else "-")))
    if any(ch.get("dipole_length_m") is not None for ch in channels):
        cols.append(("Dipole", lambda ch: (f"{ch['dipole_length_m']:g} m"
                                           if ch.get("dipole_length_m") is not None else "-")))
    if any(_unit_value(ch.get("contact_resistance")) for ch in channels):
        cols.append(("Contact resistance",
                     lambda ch: _unit_value(ch.get("contact_resistance")) or "-"))
    if any(_instrument_text(ch.get("sensor")) for ch in channels):
        cols.append(("Sensor", lambda ch: _instrument_text(ch.get("sensor")) or "-"))
    head = "<th>Channel</th>" + "".join(f"<th>{h}</th>" for h, _r in cols)
    rows = ["<tr><td>" + _e(str(ch["component"])) + "</td>"
            + "".join(f"<td>{read(ch)}</td>" for _h, read in cols) + "</tr>"
            for ch in channels]
    return head, rows


def _runs_section(doc) -> str:
    """The station's own runs[], rendered verbatim. An absent runs[] means run metadata NOT
    ASSERTED (schema wording), never "no runs occurred", so the section is not written at all."""
    runs = [r for r in (doc.get("runs") or []) if r]
    if not runs:
        return ""
    blocks = []
    for run in runs:
        facts = []
        period = run.get("time_period") or {}
        for key, label in (("start", "Deployed"), ("end", "Recovered")):
            when = str(period.get(key) or "")[:16].replace("T", " ")
            if when:
                facts.append(f"<dt>{label}</dt><dd>{_e(when)}</dd>")
        if run.get("sample_rate_hz"):
            facts.append(f"<dt>Sample rate</dt><dd>{run['sample_rate_hz']:,g} Hz</dd>")
        logger = _instrument_text(run.get("data_logger"))
        if logger:
            facts.append(f"<dt>Logger</dt><dd>{logger}</dd>")
        head, ch_rows = _channel_cells(run)
        # The channel table is the one table on a station page that can outgrow a phone: five
        # columns, one of them an instrument PID. It scrolls inside its own box rather than pushing
        # the document sideways.
        table = (f'<div class="tscroll"><table class="dtbl"><thead><tr>{head}</tr></thead><tbody>'
                 + "".join(ch_rows) + "</tbody></table></div>") if ch_rows else ""
        rid = str(run.get("id") or "").strip()
        blocks.append('<div class="run">'
                      + (f'<h3 class="runid">Run {_e(rid)}</h3>' if rid else "")
                      + (f"<dl>{''.join(facts)}</dl>" if facts else "")
                      + table + "</div>")
    return f'<h2 id="runs">Runs</h2>\n{"".join(blocks)}\n'


def _station_ts_section(ts_levels) -> str:
    """The archive routes this station's register rows opened, from ts_access.json. The path is the
    archive's own string and is shown as TEXT: AusMT hosts none of these bytes, so the page names
    the fileServer root the path is relative to rather than pretending to serve it."""
    rows = []
    for level_key, _badge, name in _TS_LEVELS:
        row = (ts_levels or {}).get(level_key)
        if not row:
            continue
        rows.append(f"<tr><td>{_e(name)}</td><td>{_fmt_bytes(row.get('bytes'))}</td>"
                    f'<td class="tspath">{_e(str(row.get("url_path") or ""))}</td></tr>')
    if not rows:
        return ""
    return ('<h2 id="time-series">Time series</h2>\n'
            '<p class="prose">Held at NCI, not by AusMT. Each path below is relative to the '
            f'THREDDS fileServer root <code>{_e(stcheck.TS_ACCESS_PREFIX)}</code>.</p>\n'
            '<div class="tscroll"><table class="dtbl">'
            "<thead><tr><th>Level</th><th>Size</th><th>Path</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>\n')


def _station_kind(dtype) -> str:
    """What KIND of station this is, in lower case, from the SAME band class the page's own Data
    type row prints. A geomagnetic depth sounding station recorded no electric field and serves no
    impedance, so calling its transfer function magnetotelluric is wrong in the crumb and in the
    description alike. The comparison is exact, against the classifier's own spelling, so the kind
    and the Data type row beside it can never read off different values. A station whose document
    discloses no type keeps the magnetotelluric reading, which is what the corpus is."""
    return "geomagnetic depth sounding" if dtype == "GDS" else "magnetotelluric"


def station_page(*, doc, survey_slug, base, ts_levels=None, build=None) -> str:
    aid = doc["ausmt_id"]
    st = doc.get("station") or aid
    survey = doc.get("survey") or survey_slug
    url = f"{base}/stations/{aid}"
    loc = doc.get("location") or {}
    data = doc.get("data") or {}
    facts = [f"<dt>AusMT id</dt><dd>{_e(aid)}</dd>",
             f"<dt>Survey</dt><dd><a href=\"/surveys/{_e(survey_slug)}\">{_e(survey)}</a></dd>"]
    # The served document's OWN presentation, verbatim: a generalised or withheld station's
    # document already carries the disclosed (or absent) position, so echoing it adds nothing.
    if loc.get("lat") is not None and loc.get("lon") is not None:
        facts.append(f"<dt>Location</dt><dd>{_e(loc['lat'])}, {_e(loc['lon'])}</dd>")
    else:
        facts.append("<dt>Location</dt><dd>withheld or generalised by the data custodian</dd>")
    if data.get("type"):
        facts.append(f"<dt>Data type</dt><dd>{_e(data['type'])}</dd>")
    if data.get("period_min_s") is not None and data.get("period_max_s") is not None:
        # The shared display helper, like every other period slot in the tier: this row printed the
        # stored float verbatim, so a station band read "0.0000625 to 100000.0 s". The full-precision
        # values stay in the station.json this page links to.
        facts.append("<dt>Period range</dt><dd>"
                     + _range(_fmt_period(data["period_min_s"]),
                              _fmt_period(data["period_max_s"])) + " s"
                     f" ({int(data.get('n_periods') or 0)} periods)</dd>")
    # The kind is derived once and spent on every surface that names it: the crumb under the h1 and
    # the description the meta and og:description tags both carry must tell one story, and the same
    # story as the Data type row this page already prints.
    kind = _station_kind(data.get("type"))
    kind_lead = kind[0].upper() + kind[1:]
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / <a href="/surveys/{_e(survey_slug)}">{_e(survey)}</a></p>\n'
        f"<h1>Station {_e(st)}</h1>\n"
        f'<p class="crumb">{_e(kind_lead)} transfer function &#183; {_e(survey)}</p>\n'
        "<dl>\n" + "\n".join(facts) + "\n</dl>\n"
        f'<p><a class="navbtn" href="/#/station/{_e(aid)}">Open in the interactive portal</a></p>\n'
        + _runs_section(doc)
        + _station_ts_section(ts_levels)
        + '<h2 id="identifiers">Identifiers and provenance</h2>\n'
        + f'<p><a href="/data/products/{_e(survey_slug)}/{_e(st)}/station.json">Machine-readable station record</a></p>\n'
    )
    return _shell(title=f"{st} - {survey} - AusMT",
                  description=f"{kind_lead} station {st} from the {survey} survey: "
                              "transfer function data, metadata and downloads on AusMT.",
                  canonical=url, body=body, noindex=True, base=base,
                  nav="navSurveys", build=build,
                  machine=("Machine-readable station metadata - JSON",
                           f"/data/products/{survey_slug}/{st}/station.json"))


def _member_colours(n):
    """`n` distinct colours, deterministic in MEMBER ORDER and with no randomness anywhere.

    The portal's eight-entry palette leads while it can, so the two surfaces agree on the common
    case. Past eight it stops cycling (which gave two surveys one colour and made the legend
    useless) and the whole set becomes an evenly spaced hue ramp instead: hue i/n so the widest
    gap possible for this many members, and lightness alternating between two bands so that two
    neighbouring hues still separate on the dark ground. Same members in the same order, same
    colours, every build."""
    if n <= len(_COLL_PAL):
        return list(_COLL_PAL[:n])
    out = []
    for i in range(n):
        r, g, b = colorsys.hls_to_rgb(i / n, 0.62 if i % 2 == 0 else 0.46, 0.58)
        out.append("#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)))
    return out


def _collection_scatter(member_labels, member_points, title, *, width=560, legend=True,
                        outline_ref=None) -> str:
    """The member-coloured footprint the portal collections view draws (collScatter), as static
    SVG: dots coloured per member survey, with a compact legend. `legend=False` is the hub card's
    form, where the roll-call belongs on the collection page itself.

    BOTH forms draw every member station. A card that sampled its footprint reported a programme
    as smaller and sparser than it is, which is the one thing a coverage map may not do, and it
    reported it worst for the largest collections. The per-dot cost carries the page instead (see
    the dot grouping in _minimap_svg), and the hub's own asserted size budget is what holds the
    line as the corpus grows: it fails loudly rather than quietly dropping stations.

    The per-dot `<title>` rides with the legend. It exists so that colour is not the only
    identifier of a member survey (design brief 45), and the legend is what gives those colours
    names. The card has no legend, and its whole surface is one stretched link, so no pointer can
    reach a dot there to read a title in the first place."""
    if not member_points:
        return ""
    present = [lbl for lbl in member_labels if member_points.get(lbl)]
    palette = _member_colours(len(present))
    colours, pts, legend_rows = {}, [], []
    for i, lbl in enumerate(present):
        colour = palette[i]
        colours[lbl] = colour
        pts += [(lon, lat, lbl) for lon, lat in member_points[lbl]]
        legend_rows.append(f'<span style="white-space:nowrap"><span style="display:inline-block;'
                           f'width:.6em;height:.6em;border-radius:50%;background:{colour}"></span> '
                           f'{_e(lbl)}</span>')
    if not pts:
        return ""
    # No locator ring on a collection footprint: a grouping of surveys has no single location, and
    # the centroid of a continent-spanning programme is a spot no member of it occupies.
    svg = _minimap_svg(pts, width=width, colours=colours, outline_ref=outline_ref,
                       labelled=legend, locator=False,
                       label=f"Member stations of {title} over Australia")
    if not legend:
        return svg
    # The AuScope mark rides the panel as an absolutely positioned sibling of the SVG, never inside
    # it: the map is generated geometry that several pins read and compare, and an <image> in it
    # would put a brand asset inside the thing those pins measure. The bottom-left corner is the one
    # part of this fixed-extent panel that is always open ocean (the nearest coastline in the bottom
    # 120 viewBox units is Tasmania, at x=326 of 560), so the overlay cannot reach the geography at
    # any rendered width. The legend is a sibling of the figure, so it is out of reach by structure.
    # This is the legend=True form alone: the hub card has no panel padding to spare.
    return (f'<figure class="collmap">{svg}'
            # One unbroken literal, held character-identical against the SPA's own
            # (portal/tests/test_collection_map_mark.py).
            '<img class="collmark" src="/vendor/auscope-icon-white.png" alt="AuScope" width="27" height="28">'
            "</figure>"
            f'<p class="colllegend">{"".join(legend_rows)}</p>')


def _prose_block(paragraphs) -> str:
    """Curator paragraphs as escaped <p class="collprose">, with one ratified structural
    convention: a paragraph whose first two characters are '# ' is that section's subheading and
    renders as <h3>. Everything else is a paragraph.

    This is NOT markdown and must not grow into it. There is one sigil, it is recognised only at
    the start of a paragraph, there is no inline syntax, and every character of every paragraph
    (subheadings included) goes through _e(). Author-supplied text can never carry markup onto a
    served page. A non-list value yields nothing rather than one <p> per character.
    """
    if not isinstance(paragraphs, (list, tuple)):
        return ""
    out = []
    for p in paragraphs:
        s = str(p or "").strip()
        if not s:
            continue
        if s.startswith("# "):
            out.append(f'<h3 class="collsub">{_e(s[2:].strip())}</h3>\n')
        else:
            out.append(f'<p class="collprose">{_e(s)}</p>\n')
    return "".join(out)


def _prose_of(coll, key) -> str:
    """The rendered block for one collection prose slot, or "" when the collection declares none.
    Every caller keeps its own fallback, so a collection with no prose renders exactly as before."""
    prose = (coll or {}).get("prose")
    if not isinstance(prose, dict):
        return ""
    return _prose_block(prose.get(key))


def collection_page(*, cid, coll, member_slugs, member_smeta, base, member_points=None,
                    member_facts=None, level_counts=None, formats=None, build=None,
                    og_image=None) -> str:
    """The collection page as an EXPLORATORY layer (design brief 23 to 31), not a catalogue record.

    `member_facts` ({slug: row}), `level_counts` ({level: n stations}) and `formats` are rollups the
    emitter computes from the SAME served documents the member survey pages render from. All three
    are optional: a caller that supplies none gets the hero, the map and the member list, and the
    sections those rollups would have filled are simply not written.

    `og_image` is the absolute URL of the card the emitter has already written for this collection,
    or None for the portal's root card. A collection whose members disclose no position gets no card
    and therefore no URL: an empty coastline would read as a collection with no coverage.
    """
    title = (coll or {}).get("title") or cid
    desc = (coll or {}).get("description") or f"{title}: a collection of magnetotelluric surveys on AusMT."
    url = f"{base}/collections/{cid}"
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": title, "description": desc, "url": url,
          "identifier": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "measurementTechnique": "magnetotellurics",
          "variableMeasured": "magnetotelluric transfer function",
          "hasPart": [{"@type": "Dataset", "url": f"{base}/surveys/{s}"} for _lbl, s in member_slugs],
          "keywords": ["magnetotellurics", "MT", "AusLAMP", "geophysics", "Australia"]}
    # licence / creators / temporal coverage roll up from the member surveys' own served records:
    # a single shared licence is stated; mixed licences state nothing (never overclaim).
    lics = {(_LICENSE_URLS.get((m or {}).get("lic"), (m or {}).get("lic")))
            for m in member_smeta if (m or {}).get("lic")}
    if len(lics) == 1:
        ld["license"] = next(iter(lics))
    orgs = []
    for m in member_smeta:
        name = (m or {}).get("org")
        if name and name not in [o["name"] for o in orgs]:
            orgs.append({"@type": "Organization", "name": name})
    if orgs:
        ld["creator"] = orgs
    y0 = [m.get("year_start") for m in member_smeta if (m or {}).get("year_start")]
    y1 = [m.get("year_end") for m in member_smeta if (m or {}).get("year_end")]
    if y0:
        ld["temporalCoverage"] = f"{min(y0)}/{max(y1)}" if y1 else f"{min(y0)}/.."
    scatter = _collection_scatter([lbl for lbl, _s in member_slugs], member_points, title)

    # ---- hero: what it is, where it is, how large it is ----
    # Chips state the rollup's OWN type and status and nothing else: a discovery layer never
    # asserts a taxonomy its record does not carry.
    chips = "".join(f'<span class="idxchip">{_e(str(v))}</span> '
                    for v in ((coll or {}).get("type"), (coll or {}).get("status")) if v)
    lede_text = _first_sentences(desc, limit=1)
    lede = f'<p class="lede">{_e(lede_text)}</p>' if lede_text else ""

    facts = list((member_facts or {}).values())

    def tile(num, lab):
        return f'<div class="cstat"><div class="cnum">{num}</div><div class="clab">{lab}</div></div>'
    # Headline metrics the brief asks for: how many surveys, how many stations, what band, what
    # years. NOT the angular extent it calls unhelpful, because the map above says it better.
    tiles = [tile(len(member_slugs), "surveys")]
    n_stations = int((coll or {}).get("n_stations") or 0)
    if n_stations:
        tiles.append(tile(f"{n_stations:,}", "stations"))
    pmins = [f["period_min_s"] for f in facts if f.get("period_min_s") is not None]
    pmaxs = [f["period_max_s"] for f in facts if f.get("period_max_s") is not None]
    if pmins and pmaxs:
        tiles.append(tile(f'{_range(_fmt_period(min(pmins)), _fmt_period(max(pmaxs)))} s',
                          "period coverage"))
    ystart = [m.get("year_start") for m in member_smeta if (m or {}).get("year_start")]
    yend = [m.get("year_end") for m in member_smeta if (m or {}).get("year_end")]
    if ystart:
        span = (f"{min(ystart)}" if yend and min(ystart) == max(yend)
                else _range(min(ystart), max(yend)) if yend else f"{min(ystart)}")
        tiles.append(tile(_e(span), "years"))
    stats = f'<div class="cstats">{"".join(tiles)}</div>'

    # ---- data available: rolled up from served facts only ----
    avail = []
    fmt_names = [_BUNDLE_LABELS.get(f, (f, ""))[0] for f in (formats or [])]
    if fmt_names:
        avail.append(f"<dt>Transfer functions</dt><dd>{' &#183; '.join(_e(n) for n in fmt_names)}"
                     "</dd>")
    for level_key, _badge, name in _TS_LEVELS:
        n = (level_counts or {}).get(level_key)
        if n:
            avail.append(f"<dt>{_e(name)}</dt><dd>{n:,} stations</dd>")
    data_section = ""
    if avail:
        # A collection that declares its own prose for this section speaks for itself; the engine
        # sentence is the fallback for one that does not. Either way the section must still say
        # that the data are the members' own, never the collection's as a single download.
        data_intro = _prose_of(coll, "data") or (
            '<p class="collprose">A collection groups surveys for discovery; each member survey '
            "publishes its own data under its own licence, and the rows below say what exists "
            f"across the {len(member_slugs)} members rather than offering the collection as one "
            "download.</p>\n")
        data_section = ('<h2 id="data">Data available</h2>\n'
                        f"{data_intro}"
                        f"<dl>{''.join(avail)}</dl>\n")

    # ---- member surveys, the brief's compact list ----
    rows = []
    for lbl, slug in member_slugs:
        row = (member_facts or {}).get(slug) or {}
        types = row.get("types") or {}
        bits = [_e(str(row.get("org") or "")),
                _plural(int(row["n_stations"]), "station") if row.get("n_stations") else "",
                _e(" / ".join(str(t) for t in sorted(types))) if types else "",
                _e(str(row.get("years") or "")),
                (f'{_range(_fmt_period(row["period_min_s"]), _fmt_period(row["period_max_s"]))} s'
                 if row.get("period_min_s") is not None and row.get("period_max_s") is not None
                 else "")]
        facts_line = _facts_line(bits)
        # The link text is the COLLECTION's own label for this member, not the survey document's
        # title. The two usually agree; where they differ the label is what this collection calls
        # that member and what the map legend and every dot title above already say, so taking the
        # doc title would put two wordings for one survey on one page.
        rows.append(f'<div class="mem"><p class="memt">'
                    f'<a href="/surveys/{_e(slug)}">{_e(lbl or row.get("title") or slug)}</a></p>'
                    + (f'<p class="memfacts">{facts_line}</p>' if facts_line else "")
                    + "</div>")
    # The curator's prose WRAPS the generated roll-call rather than replacing it: what a member
    # survey is goes before the cards, and any explanation of how to read them goes after.
    members_section = (f'<h2 id="surveys">Member surveys</h2>\n'
                       f'{_prose_of(coll, "members_before")}'
                       f'<div class="memlist">{"".join(rows)}</div>\n'
                       f'{_prose_of(coll, "members_after")}') if rows else ""

    # ---- participating organisations: names the members declare, ROR-linked, no logos ----
    org_bits, seen_orgs = [], set()
    for lbl, slug in member_slugs:
        row = (member_facts or {}).get(slug) or {}
        name = str(row.get("org") or "").strip()
        if not name or name in seen_orgs:
            continue
        seen_orgs.add(name)
        ror = str(row.get("org_ror") or "").strip()
        org_bits.append(f'<a href="{_e(ror)}">{_e(name)}</a>' if ror else _e(name))
    # The prose precedes the roll-call and never replaces it: the list is generated from the member
    # records, so a curator paragraph can qualify what the names mean but cannot restate them.
    orgs_section = (f'<h2 id="organisations">Participating organisations</h2>\n'
                    f'{_prose_of(coll, "organisations")}'
                    f'<p class="collprose">{" &#183; ".join(org_bits)}</p>\n') if org_bits else ""

    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / <a href="/collections">collections</a> / '
        f"{_e(title)}</p>\n"
        f"<h1>{_e(title)}</h1>\n"
        + (f"<p>{chips}</p>\n" if chips else "")
        + f"{lede}\n"
        # The map and the headline metrics share one hero container so the numbers ride BESIDE the
        # map on a wide screen. Stacked, an 820px map stands tall enough to push the four figures
        # off the first screen, and a reader had to scroll the whole hero to learn how many surveys
        # and stations the collection holds. The survey page's hero already reads this way; below
        # the breakpoint the rail falls back under the map.
        + f'<div class="collhero"><div>{scatter}</div>{stats}</div>\n'
        + f'<p><a class="navbtn" href="/#/collection/{_e(cid)}">Open in the interactive portal</a></p>\n'
        + '<h2 id="about">About</h2>\n'
        + (_prose_of(coll, "about") or f'<p class="collprose">{_e(desc)}</p>\n')
        + data_section
        + members_section
        + orgs_section
    )
    return _shell(title=f"{title} - magnetotelluric data - AusMT",
                  # The meta/og description is a summary of the rollup description, never the
                  # section prose: the prose is a page-length payload and a link preview is a line.
                  description=_meta_summary(desc),
                  canonical=url, body=body, base=base,
                  jsonld=[ld, _breadcrumb(base, [(_SITE_NAME, "/"),
                                                 ("collections", "/collections"),
                                                 (title, f"/collections/{cid}")])],
                  og_image=og_image, nav="navCollections", build=build,
                  machine=("Collection record in the MTCAT catalogue - JSON",
                           "/data/mtcat.json"))


# --------------------------------------------------------------------------- the two index pages

_INDEX_MAP_WIDTH = 230          # the surveys index card map
_COLL_INDEX_MAP_WIDTH = 380     # the collections index card map

_COLLECTIONS_LEDE = ("Collections group related surveys for discovery and exploration. A collection "
                     "may represent a programme, region, geological province, or thematic dataset.")

# The catalogue document a hub page hands over: MTCAT is the machine-readable form of exactly what
# a hub lists, so it is the honest counterpart to the hub itself.
_MTCAT_LINK = ("Machine-readable catalogue - MTCAT JSON", "/data/mtcat.json")

# The surveys hub's own lede, the owner's wording verbatim. It sits between the summary line (the
# headline numbers) and the list, and it answers the question a hub page has to answer before its
# cards can: what IS this list, and what is it for.
_SURVEYS_LEDE = ("Discover magnetotelluric surveys from across Australia. Browse survey coverage, "
                 "acquisition periods and available data.")

# Two arrows, two meanings, used consistently. The RIGHT arrow marks a forward action that stays on
# the site; the UPWARD-RIGHT arrow marks a link that LEAVES the page (an outbound host, or a
# machine-readable document that is not this page). A reader should be able to tell which kind of
# link they are about to follow without reading the URL.
_ARROW_FWD = "&#8594;"
_ARROW_OUT = "&#8599;"

# The hover affordance on a stretched-link card: decoration only, so it is hidden from assistive
# technology (the card already has exactly one real link, and its title is the accessible name).
_CARD_ARROW = f'<span class="idxgo" aria-hidden="true">{_ARROW_FWD}</span>'


def _first_sentences(text, *, limit=2, budget=220) -> str:
    """The first sentence or two of a rollup description, cut at a SENTENCE boundary and never
    mid-word: an index card is a summary, and the full text is one click away on the entity page.
    A single over-long opening sentence is kept whole rather than chopped."""
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    parts = [p.strip() for p in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", s) if p.strip()]
    out = ""
    for part in parts[:limit]:
        cand = (out + " " + part).strip() if out else part
        if out and len(cand) > budget:
            break
        out = cand
    return out


_META_LIMIT = 160


def _meta_summary(text) -> str:
    """A BOUNDED single-line summary for <meta name="description"> and og:description.

    A slice at a fixed offset cuts mid-word, so a long description shipped a link preview ending on
    a broken word. Whole sentences are taken where they fit; where one opening sentence is already
    longer than the budget the cut still falls on a word boundary, never inside a word. The result
    is never longer than the budget, so the page cannot ship an unbounded preview.
    """
    s = " ".join(str(text or "").split())
    if len(s) <= _META_LIMIT:
        return s
    out = _first_sentences(s, limit=2, budget=_META_LIMIT)
    if out and len(out) <= _META_LIMIT:
        return out
    cut = s[:_META_LIMIT - 3]
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "..."


def _plural(n, word) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _facts_line(bits) -> str:
    return " &#183; ".join(b for b in bits if b)


# The hub CARDS give each interpunct its air as CSS padding on a span (.sep, _INDEX_CSS), never as
# literal whitespace: text copied off a card must keep reading "1 station &#183; LPMT" with single
# spaces. Page-level summary lines and the entity pages keep the bare join above.
_CARD_SEP = ' <span class="sep">&#183;</span> '


def _card_facts_line(bits) -> str:
    return _CARD_SEP.join(b for b in bits if b)


def surveys_index_page(*, rows, base, build=None) -> str:
    """The /surveys hub: every published survey as one linked row with the facts a reader chooses
    on. Rendered from the catalogue rollups alone (mtcat.json / surveys.json), so it states nothing
    the served documents do not already publish and needs no survey-metadata read.

    Rows carry: slug, title, org, region, n_stations, years, types {type: n}, period_min_s,
    period_max_s, lic, doi, points [(lon, lat, type)]. The card is a DISCOVERY SUMMARY, not a
    miniature survey record: no abstract, and exactly one action (the title link)."""
    base = (base or "").rstrip("/")
    url = f"{base}/surveys"
    rows = sorted(rows or [], key=lambda r: (str(r.get("title") or ""), str(r.get("slug") or "")))
    n_stations = sum(int(r.get("n_stations") or 0) for r in rows)
    defs, ref = au_outline_defs(_INDEX_MAP_WIDTH)
    cards = []
    for r in rows:
        slug = str(r.get("slug") or "")
        title = str(r.get("title") or slug)
        types = r.get("types") or {}
        type_bit = " / ".join(str(t) for t in types) if types else ""
        pmin, pmax = r.get("period_min_s"), r.get("period_max_s")
        period = (f'{_range(_fmt_period(pmin), _fmt_period(pmax))} s'
                  if pmin is not None and pmax is not None else "")
        facts = _card_facts_line([
            _e(_plural(int(r.get("n_stations") or 0), "station")),
            _e(type_bit), _e(str(r.get("years") or "")), _e(period), _e(_fmt_licence(r.get("lic"))),
            '<span class="idxdoi">DOI</span>' if r.get("doi") else ""])
        svg = _minimap_svg(r.get("points") or [], width=_INDEX_MAP_WIDTH, outline_ref=ref,
                           label=f"{title} location in Australia")
        # Organisation and location, one unlabelled line: the only thing that can say which is
        # which is ink. Two muted shades, the organisation the brighter of the two, because "who
        # collected this" is the coarser filter a reader applies first.
        org_line = _card_facts_line([
            f'<span class="idxorgn">{_e(str(r.get("org") or ""))}</span>' if r.get("org") else "",
            f'<span class="idxloc">{_e(str(r.get("region") or ""))}</span>' if r.get("region")
            else ""])
        cards.append(
            f'<article class="idxcard"><div>{svg}</div><div>'
            f'<h2 class="idxt"><a href="/surveys/{_e(slug)}">{_e(title)}</a></h2>'
            f'<p class="idxorg">{org_line}</p>'
            f'<p class="idxfacts">{facts}</p></div>'
            f'{_CARD_ARROW}</article>')
    # The page-level counts go through _plural like the card counts do: a corpus of one is a real
    # state (it is where every new deployment starts), and the summary line and the description are
    # the two strings a reader and a search result actually read.
    summary = _facts_line([_plural(len(rows), "survey"), _plural(n_stations, "station")])
    desc = (f"Every magnetotelluric survey published on AusMT: {_plural(len(rows), 'survey')} and "
            f"{_plural(n_stations, 'station')}, with coverage, data types, licences and downloads.")
    # The header's right status slot, in the SPA counter's own grammar (bold figure, muted noun,
    # interpunct). The SPA's counter reports LIVE map state, which a static page has none of; this
    # hub does have a count to state, and it is the catalogue's own.
    counts = (f'<div class="counts"><b>{len(rows):,}</b> '
              f'{"survey" if len(rows) == 1 else "surveys"} &#183; '
              f'<b>{n_stations:,}</b> {"station" if n_stations == 1 else "stations"}</div>')
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / surveys</p>\n'
        "<h1>Surveys</h1>\n"
        f'<p class="idxsum">{summary}</p>\n'
        f'<p class="idxlede">{_SURVEYS_LEDE}</p>\n'
        f"{defs}\n"
        f'<div class="idxlist">{"".join(cards)}</div>\n')
    return _shell(title="Surveys - magnetotelluric survey data - AusMT",
                  description=desc, canonical=url, body=body, base=base,
                  jsonld=_breadcrumb(base, [(_SITE_NAME, "/"), ("surveys", "/surveys")]),
                  extra_css=_INDEX_CSS, nav="navSurveys", build=build, status=counts,
                  machine=_MTCAT_LINK)


def collections_index_page(*, rows, base, build=None) -> str:
    """The /collections hub. Rows carry: cid, title, description, n_surveys, n_stations, type,
    status, member_labels, member_points {label: [(lon, lat)]}. ONLY the fields the collections
    rollup actually carries are rendered: a collection whose record declares no type or status
    shows neither, because a discovery layer never asserts a taxonomy its members did not."""
    base = (base or "").rstrip("/")
    url = f"{base}/collections"
    rows = sorted(rows or [], key=lambda r: (str(r.get("title") or ""), str(r.get("cid") or "")))
    defs, ref = au_outline_defs(_COLL_INDEX_MAP_WIDTH)
    cards = []
    for r in rows:
        cid = str(r.get("cid") or "")
        title = str(r.get("title") or cid)
        chips = "".join(f'<span class="idxchip">{_e(str(v))}</span> '
                        for v in (r.get("type"), r.get("status")) if v)
        scatter = _collection_scatter(r.get("member_labels") or [], r.get("member_points") or {},
                                      title, width=_COLL_INDEX_MAP_WIDTH, legend=False,
                                      outline_ref=ref)
        blurb = _first_sentences(r.get("description"))
        chip_row = f"<p>{chips}</p>" if chips else ""
        desc_row = f'<p class="idxdesc">{_e(blurb)}</p>' if blurb else ""
        counts = _card_facts_line([_e(_plural(int(r.get("n_surveys") or 0), "survey")),
                                   _e(_plural(int(r.get("n_stations") or 0), "station"))])
        cards.append(
            '<article class="idxccard">'
            f'<h2 class="idxt"><a href="/collections/{_e(cid)}">{_e(title)}</a></h2>'
            f"{chip_row}{scatter}{desc_row}"
            f'<p class="idxfacts">{counts}</p>'
            f'<p class="idxact"><a href="/collections/{_e(cid)}">Explore collection '
            f"{_ARROW_FWD}</a></p>"
            "</article>")
    desc = (f"Collections on AusMT: {_plural(len(rows), 'curated grouping')} of related "
            "magnetotelluric surveys, each linking the surveys it gathers.")
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / collections</p>\n'
        "<h1>Collections</h1>\n"
        f'<p class="idxlede">{_COLLECTIONS_LEDE}</p>\n'
        f"{defs}\n"
        f'<div class="idxgrid">{"".join(cards)}</div>\n')
    return _shell(title="Collections - magnetotelluric survey data - AusMT",
                  description=desc, canonical=url, body=body, base=base,
                  jsonld=_breadcrumb(base, [(_SITE_NAME, "/"), ("collections", "/collections")]),
                  extra_css=_INDEX_CSS, nav="navCollections", build=build,
                  machine=_MTCAT_LINK)


# --------------------------------------------------------------------------- og cards (Pillow)

def _og_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


_CARD_SIZE = (1200, 630)
_CARD_MARGIN = 60                 # the text margin every card's left column sits on
_CARD_WORDMARK = "ausmt.auscope.org.au"
_CARD_WORDMARK_Y = 540
_CARD_WORDMARK_SIZE = 28
_CARD_TITLE_SIZES = (64, 52, 44, 36)
# The collection card's title column. It stops well short of the map panel's outset edge, because
# the gutter between a 64 px title and a bordered panel has to read as space rather than as a near
# miss; the ladder above steps the type down inside this width, it does not widen the column.
_CARD_TEXT_WIDTH = 476

# The AuScope mark the card signs itself with. It ships BESIDE this module rather than being read
# from portal/vendor/, because the engine image carries no portal tree: an emitter that reached
# across to the portal would draw an unsigned card in exactly the environment that serves the
# corpus. The two files are pinned byte-identical, so there is still one asset.
_CARD_MARK = Path(__file__).resolve().parent / "_auscope_mark.png"


def _rgb(colour):
    """'#RRGGBB' as the (r, g, b) tuple the raster cards draw with, so a card and the SVG panel it
    previews can share one declared colour instead of each carrying its own literal."""
    h = str(colour).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _card_wordmark_row(img, d, font, ink):
    """The AuScope mark, a half-mark-width gap, then the wordmark: ONE row on the card's text
    margin, on every card family this module draws.

    The mark's height is the wordmark's own line height and it is centred on the wordmark's INK
    rather than on its em box, so the pair reads as a single line of type. Centring on the em box
    would pay out the face's descent, which no glyph in this string uses, and sit the mark high."""
    from PIL import Image
    x0, y0 = _CARD_MARGIN, _CARD_WORDMARK_Y
    box = d.textbbox((x0, y0), _CARD_WORDMARK, font=font)
    try:
        line_h = sum(font.getmetrics())
    except AttributeError:                # Pillow < 10.1: the bitmap face carries no metrics
        line_h = box[3] - box[1]
    with Image.open(_CARD_MARK) as src:
        mark = src.convert("RGBA").resize(
            (round(line_h * src.width / src.height), line_h), Image.LANCZOS)
    # Floor, not round: half of an odd width under banker's rounding is a gap nobody can predict
    # from the numbers on this line.
    gap = mark.width // 2
    img.paste(mark, (x0, round((box[1] + box[3]) / 2 - line_h / 2)), mark)
    d.text((x0 + mark.width + gap, y0), _CARD_WORDMARK, font=font, fill=ink)


def _card_font(size):
    """Pillow's bundled scalable default face (no font files shipped or fetched)."""
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow < 10.1: tiny bitmap face, still legible
        return ImageFont.load_default()


def _card_lines(d, text, font, width, max_lines):
    """(lines, whether the WHOLE string fitted). Word boundaries only.

    A title that is silently cut is a title the card gets wrong, so the caller steps the type down
    while the whole string still fits and truncates only when nothing does."""
    lines, cur = [], ""
    for word in str(text).split():
        trial = f"{cur} {word}".strip()
        if cur and d.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    whole = (len(lines) <= max_lines
             and all(d.textlength(ln, font=font) <= width for ln in lines))
    return lines[:max_lines] or [""], whole


def _og_card(path, *, title, subtitle, region_year, period_line, dims_line, points):
    """One 1200x630 link-preview card in the portal card's design language: footprint dots,
    Australia locator inset, the survey's key numbers."""
    from PIL import Image, ImageDraw
    W, H = _CARD_SIZE
    ink, panel, line = (13, 20, 40), (17, 26, 51), (43, 53, 87)
    text, muted, copper, cyan = (255, 255, 255), (143, 163, 176), (239, 114, 86), (79, 195, 217)
    img = Image.new("RGB", (W, H), ink)
    d = ImageDraw.Draw(img)
    font = _card_font

    # footprint panel, right side
    if points:
        lons = [pt[0] for pt in points]
        lats = [pt[1] for pt in points]
        lo0, lo1 = min(lons), max(lons)
        la0, la1 = min(lats), max(lats)
        dlo, dla = max(lo1 - lo0, 1e-6), max(la1 - la0, 1e-6)
        px0, py0, px1, py1 = 640, 70, 1150, 560
        pw, ph = px1 - px0, py1 - py0
        if pw * (dla / dlo) > ph:
            pw = ph / (dla / dlo)
        else:
            ph = pw * (dla / dlo)
        px1, py1 = px0 + pw, py0 + ph
        d.rounded_rectangle([px0 - 16, py0 - 16, px1 + 16, py1 + 16], radius=12,
                            fill=panel, outline=line, width=2)
        pr = 4 if len(points) <= 60 else (3 if len(points) <= 200 else 2.2)
        for lo, la, _ty in points:
            x = px0 + (lo - lo0) / dlo * pw
            y = py0 + (la1 - la) / dla * ph
            d.ellipse([x - pr, y - pr, x + pr, y + pr], fill=cyan)
        # Australia locator inset, bottom-right over the panel
        ext = au.EXTENT
        iw = 190
        ih = round(iw * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
        ix, iy = W - iw - 36, H - ih - 36
        d.rounded_rectangle([ix - 10, iy - 10, ix + iw + 10, iy + ih + 10], radius=10,
                            fill=ink, outline=line, width=2)

        def ip(lon, lat):
            return (ix + (lon - ext["w"]) / (ext["e"] - ext["w"]) * iw,
                    iy + (ext["n"] - lat) / (ext["n"] - ext["s"]) * ih)
        for ring in au.COAST:
            d.polygon([ip(lo, la) for lo, la in ring], fill=(20, 29, 54), outline=(49, 64, 107))
        cx, cy = ip((lo0 + lo1) / 2, (la0 + la1) / 2)
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=copper)
        d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=copper, width=2)
    d.text((60, 130), title, font=font(64), fill=text)
    d.text((60, 220), subtitle, font=font(29), fill=muted)
    d.text((60, 262), region_year, font=font(29), fill=muted)
    if period_line:
        d.text((60, 330), period_line, font=font(26), fill=(201, 212, 232))
    if dims_line:
        d.text((60, 370), dims_line, font=font(26), fill=(201, 212, 232))
    _card_wordmark_row(img, d, font(_CARD_WORDMARK_SIZE), copper)
    img.save(path, "PNG", optimize=True)


def _og_collection_card(path, *, title, facts_line, taxonomy_line, member_labels,
                        member_points) -> bool:
    """One 1200x630 link-preview card per collection: the member-coloured footprint the collections
    hub card draws, at raster scale. Returns whether a card was written.

    The palette and the member ORDER are the hub card's, byte for byte (_member_colours over the
    members that declare a position), so one survey carries the same colour on the hub, on the
    collection page's own map and here. Two things deliberately differ from the SVG:

      - the dot radius is the SURVEY card's raster rule, not the hub's. A link preview is resampled
        to roughly a third of this width by the clients that show it, and the hub's rule scaled to
        this panel gives a radius under 1.5 px at AusLAMP density: those dots disappear.
      - the dots are opaque. Translucency on the hub buys a readable overlap for a map that can be
        hovered and has a legend; this card has neither, so it buys nothing and costs contrast.

    NO locator inset: a grouping of surveys has no single location to point at, and the centroid of
    a continent-spanning programme is a place no member of it occupies. A collection whose members
    disclose no position at all gets NO CARD rather than a bare coastline, which would read as a
    collection with no coverage."""
    from PIL import Image, ImageDraw
    present = [lbl for lbl in member_labels if (member_points or {}).get(lbl)]
    palette = _member_colours(len(present))
    pts = []
    for i, lbl in enumerate(present):
        colour = _rgb(palette[i])
        pts += [(lon, lat, colour) for lon, lat in member_points[lbl]]
    if not pts:
        return False

    W, H = _CARD_SIZE
    ink = (13, 20, 40)
    text, muted, copper = (255, 255, 255), (143, 163, 176), (239, 114, 86)
    img = Image.new("RGB", (W, H), ink)
    d = ImageDraw.Draw(img)

    # ---- the member footprint, in the survey card's panel slot and vertically centred in it ----
    ext = au.EXTENT
    pw = 510
    ph = round(pw * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
    px0, py0 = 640, 70 + ((560 - 70) - ph) // 2
    d.rounded_rectangle([px0 - 16, py0 - 16, px0 + pw + 16, py0 + ph + 16], radius=12,
                        fill=_rgb(_MAP_PANEL), outline=_rgb(_MAP_PANEL_LINE), width=2)
    # The hub card's own projection, with its 8 unit pad scaled by the width ratio so the coastline
    # sits in the panel exactly as it does at the hub's width.
    p = _proj(ext)(pw, ph, 8 * pw / _COLL_INDEX_MAP_WIDTH)
    for ring in au.COAST:
        d.polygon([(px0 + x, py0 + y) for x, y in (p(lo, la) for lo, la in ring)],
                  fill=_rgb(_COAST_FILL), outline=_rgb(_COAST_LINE))
    r = 4 if len(pts) <= 60 else (3 if len(pts) <= 200 else 2.2)
    for lon, lat, colour in pts:
        x, y = p(lon, lat)
        d.ellipse([px0 + x - r, py0 + y - r, px0 + x + r, py0 + y + r], fill=colour)

    # ---- the text column, stepped down until the WHOLE title fits ----
    tsize, lines = _CARD_TITLE_SIZES[-1], [str(title)]
    for tsize in _CARD_TITLE_SIZES:
        lines, whole = _card_lines(d, title, _card_font(tsize), _CARD_TEXT_WIDTH, 3)
        if whole:
            break
    else:
        # Nothing in the ladder fits the whole title, so the last line says so rather than ending
        # mid-thought on a word the reader cannot tell was the last one.
        lines[-1] = f"{lines[-1]} ..."
    y = 130
    for ln in lines:
        d.text((_CARD_MARGIN, y), ln, font=_card_font(tsize), fill=text)
        y += round(tsize * 1.18)
    # The survey card's subtitle and region slots, at its scale: a single-line title lands on the
    # same two baselines there, so the two families read as one card design.
    y = max(y + 8, 220)
    d.text((_CARD_MARGIN, y), facts_line, font=_card_font(29), fill=muted)
    if taxonomy_line:
        d.text((_CARD_MARGIN, y + 42), taxonomy_line, font=_card_font(29), fill=muted)
    _card_wordmark_row(img, d, _card_font(_CARD_WORDMARK_SIZE), copper)
    img.save(path, "PNG", optimize=True)
    return True


# --------------------------------------------------------------------------- the emitter

def emit_pages(out, base, *, surveys_meta, survey_docs, station_docs, collections,
               bundle_formats, survey_extent, survey_coll,
               bundle_rows=None, ts_access=None, mtcat=None, build=None) -> int:
    """Write every entity page under <out>/pages/ (and, when Pillow is importable, the per-survey
    link-preview cards under <out>/pages/og/ and the per-collection cards under
    <out>/pages/og/collections/). Inputs are the served documents and rollups the build already
    produced; the return value is the page count the caller reconciles against the sitemap (the two
    must always agree, pinned in tests).

    Each card is written BEFORE the page that names it and the page is given the URL only once the
    file is on disk, so a page can never advertise a card a failed write left missing."""
    base = base.rstrip("/")
    n = 0
    # The hub pages occupy pages/<kind>/index.html, so an entity id of "index" would silently
    # replace one of them (and /surveys/index would then serve the wrong document). Refuse loudly.
    _clash = sorted(lbl for lbl, m in (surveys_meta or {}).items()
                    if ((m or {}).get("slug") or lbl) == "index")
    if _clash:
        raise ValueError(f"survey slug 'index' collides with the surveys index page: {_clash}")
    if "index" in (collections or {}):
        raise ValueError("collection id 'index' collides with the collections index page")
    slug_by_label = {}
    index_rows = []
    docs_by_survey: dict = {}
    for doc in station_docs.values():
        docs_by_survey.setdefault(doc.get("survey_id"), []).append(doc)
    bundles_by_slug: dict = {}
    for row in bundle_rows or []:
        bundles_by_slug.setdefault((row or {}).get("slug"), []).append(row)
    # The public discovery layer per survey (the mtcat rollup): the embargoed-survey fallback.
    disc_stations: dict = {}
    disc_survey: dict = {}
    for row in (mtcat or {}).get("stations") or []:
        disc_stations.setdefault(row.get("survey_id"), []).append(row)
    for row in (mtcat or {}).get("surveys") or []:
        disc_survey[row.get("survey_id")] = row

    sdir = out / "pages" / "surveys"
    sdir.mkdir(parents=True, exist_ok=True)
    ogdir = out / "pages" / "og"
    draw_cards = _og_available()
    if draw_cards:
        ogdir.mkdir(parents=True, exist_ok=True)
    for label in sorted(surveys_meta):
        smeta = surveys_meta.get(label) or {}
        slug = smeta.get("slug") or label
        slug_by_label[label] = slug
        docs = docs_by_survey.get(slug, [])
        rows = bundles_by_slug.get(slug)
        if rows is None and (bundle_formats or {}).get(slug):
            # Compatibility path for callers that pass only the format->path map: rows carry the
            # url alone and the size/sha cells stay absent.
            rows = [{"slug": slug, "format": f, "url": rel}
                    for f, rel in sorted(bundle_formats[slug].items())]
        # The card is drawn BEFORE the page that advertises it, and the page is handed the URL only
        # once the file is on disk: a page may never point a link-preview fetcher at a 404.
        og_image = None
        if draw_cards:
            points = _station_points(docs)
            pmin = pmax = None
            types: dict = {}
            for doc in docs:
                data = doc.get("data") or {}
                if data.get("period_min_s") is not None:
                    pmin = data["period_min_s"] if pmin is None else min(pmin, data["period_min_s"])
                if data.get("period_max_s") is not None:
                    pmax = data["period_max_s"] if pmax is None else max(pmax, data["period_max_s"])
                if data.get("type"):
                    types[data["type"]] = types.get(data["type"], 0) + 1
            tdesc = " + ".join(sorted(types)) if types else "magnetotelluric"
            years = _survey_years(survey_docs.get(slug), smeta)
            period_line = (f'{_range(_fmt_period(pmin), _fmt_period(pmax))} s'
                           if pmin is not None and pmax is not None else "")
            dims = ""
            if points and len(points) > 1:
                lons = [pt[0] for pt in points]
                lats = [pt[1] for pt in points]
                dkm_x = (max(lons) - min(lons)) * 111 * 0.83
                dkm_y = (max(lats) - min(lats)) * 111
                dims = f"about {dkm_x:.0f} x {dkm_y:.0f} km"
            cardpath = ogdir / f"{slug}.png"
            _og_card(cardpath,
                     title=((survey_docs.get(slug) or {}).get("title")) or label,
                     subtitle=f"{len(docs)}-station {tdesc} survey",
                     region_year=" · ".join(x for x in (smeta.get("region"), years) if x),
                     period_line=period_line, dims_line=dims, points=points)
            if not cardpath.is_file():
                raise ValueError(f"survey card {cardpath} was not written; the page must not "
                                 "advertise a card that does not exist")
            # The card lives in the DATA volume, which is served under /data/*; the pages/ tree has
            # no bare route of its own (the entity rewrite matches the two-segment shapes only), so
            # this is the one URL at which the rendered card is reachable.
            og_image = f"{base}/data/pages/og/{slug}.png"
        htmlpage = survey_page(slug=slug, label=label, sm_doc=survey_docs.get(slug),
                               smeta=smeta, station_docs=docs,
                               bundle_rows=rows or [], ts_access=ts_access,
                               base=base, extent=(survey_extent or {}).get(label),
                               build=build, og_image=og_image,
                               discovery={"stations": disc_stations.get(slug),
                                          "survey": disc_survey.get(slug)})
        (sdir / f"{slug}.html").write_text(htmlpage, encoding="utf-8")
        n += 1
        # The hub row for this survey, from the SAME rollups the catalogue publishes (the mtcat
        # survey row, with surveys.json filling the region the rollup does not carry). Positions
        # follow the survey page's own rule: the served station documents, falling back to the
        # public discovery rows for a survey whose documents withhold them.
        _drow = disc_survey.get(slug) or {}
        _pts = _station_points(docs)
        if not _pts:
            for _r in disc_stations.get(slug) or []:
                if _r.get("latitude") is not None and _r.get("longitude") is not None:
                    _pts.append((float(_r["longitude"]), float(_r["latitude"]),
                                 _r.get("data_type")))
        index_rows.append({
            "slug": slug,
            "title": ((survey_docs.get(slug) or {}).get("title")) or label,
            "org": _drow.get("organisation") or smeta.get("org"),
            "org_ror": smeta.get("org_ror"),
            "region": smeta.get("region") or "Australia",
            "n_stations": _drow.get("n_stations") if _drow.get("n_stations") is not None
            else len(docs),
            "years": _survey_years(survey_docs.get(slug), smeta),
            "types": _drow.get("data_types"),
            "period_min_s": _drow.get("period_min_s"),
            "period_max_s": _drow.get("period_max_s"),
            "lic": _drow.get("license") or smeta.get("lic"),
            "doi": _drow.get("doi") or smeta.get("doi"),
            "points": _pts})

    stdir = out / "pages" / "stations"
    stdir.mkdir(parents=True, exist_ok=True)
    for doc in station_docs.values():
        (stdir / f"{doc['ausmt_id']}.html").write_text(
            station_page(doc=doc, survey_slug=doc.get("survey_id"), base=base, build=build,
                         ts_levels=(ts_access or {}).get(doc["ausmt_id"])), encoding="utf-8")
        n += 1

    cdir = out / "pages" / "collections"
    cdir.mkdir(parents=True, exist_ok=True)
    # The collection cards take a SUBDIRECTORY of their own, not the flat og/ tree the survey cards
    # sit in: a collection id equal to a survey slug would otherwise overwrite that survey's card,
    # silently and only for the pair that collided.
    cogdir = ogdir / "collections"
    if draw_cards:
        cogdir.mkdir(parents=True, exist_ok=True)
    coll_index_rows = []
    # The collection page's rollups come from the SAME rows the surveys hub was built from, so a
    # fact can never differ between a collection page and the survey page it names.
    facts_by_slug = {r["slug"]: r for r in index_rows}
    for cid in sorted(collections or {}):
        members = [(lbl, slug_by_label.get(lbl, lbl))
                   for lbl in sorted(surveys_meta) if (survey_coll or {}).get(lbl) == cid]
        member_smeta = [surveys_meta.get(lbl) or {} for lbl, _s in members]
        member_points = {lbl: [(pt[0], pt[1]) for pt in
                                _station_points(docs_by_survey.get(s, []))]
                         for lbl, s in members}
        # What the members between them publish, counted over the served register and the served
        # manifest rows. Nothing here is a claim about the collection: it is a count of member data.
        level_counts: dict = {}
        member_formats = set()
        for _lbl, s in members:
            for row in bundles_by_slug.get(s) or []:
                if (row or {}).get("format"):
                    member_formats.add(row["format"])
            for doc in docs_by_survey.get(s, []):
                for level in (ts_access or {}).get(doc.get("ausmt_id")) or {}:
                    level_counts[level] = level_counts.get(level, 0) + 1
        coll = collections[cid] or {}
        # The card first, on the same rule the survey cards follow. A collection whose members
        # disclose no position writes none, and the page then carries the portal's root card.
        coll_og = None
        if draw_cards:
            cardpath = cogdir / f"{cid}.png"
            n_st = int(coll.get("n_stations") or 0)
            if _og_collection_card(
                    cardpath,
                    title=coll.get("title") or cid,
                    # A raster card carries the interpunct as the CHARACTER, never as the entity
                    # the HTML slots use: nothing here goes through a markup parser.
                    facts_line=" · ".join(x for x in (_plural(len(members), "survey"),
                                                      _plural(n_st, "station") if n_st else "")
                                          if x),
                    taxonomy_line=" · ".join(str(x) for x in (coll.get("type"),
                                                              coll.get("status")) if x),
                    member_labels=[lbl for lbl, _s in members],
                    member_points=member_points):
                if not cardpath.is_file():
                    raise ValueError(f"collection card {cardpath} was not written; the page must "
                                     "not advertise a card that does not exist")
                coll_og = f"{base}/data/pages/og/collections/{cid}.png"
        (cdir / f"{cid}.html").write_text(
            collection_page(cid=cid, coll=collections[cid], member_slugs=members,
                            member_smeta=member_smeta, base=base,
                            member_points=member_points,
                            member_facts={s: facts_by_slug[s] for _lbl, s in members
                                          if s in facts_by_slug},
                            level_counts=level_counts, og_image=coll_og,
                            formats=sorted(member_formats), build=build),
            encoding="utf-8")
        n += 1
        coll_index_rows.append({
            "cid": cid, "title": coll.get("title") or cid,
            "description": coll.get("description"),
            "n_surveys": coll.get("n_surveys") if coll.get("n_surveys") is not None else len(members),
            "n_stations": coll.get("n_stations") or 0,
            "type": coll.get("type"), "status": coll.get("status"),
            "member_labels": [lbl for lbl, _s in members], "member_points": member_points})

    # The two HUB pages, last: they are views over the rows the loops above just built, so they
    # can never advertise a survey or collection this build did not write a page for.
    (sdir / "index.html").write_text(
        surveys_index_page(rows=index_rows, base=base, build=build), encoding="utf-8")
    n += 1
    (cdir / "index.html").write_text(
        collections_index_page(rows=coll_index_rows, base=base, build=build), encoding="utf-8")
    n += 1
    return n
