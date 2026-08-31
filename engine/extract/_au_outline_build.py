#!/usr/bin/env python3
"""Derive _au_outline.py and portal/vendor/au-outline.js from Natural Earth.

    python3 extract/_au_outline_build.py            # rewrite both generated files
    python3 extract/_au_outline_build.py --check    # drift gate: exit 1 if either is stale

WHY THIS EXISTS. The coastline used to be hand-simplified, and a hand-typed outline cannot be
checked: a reader had no way to tell a deliberate generalisation from a typo, and the two surfaces
that claim to draw ONE map had no mechanical guarantee they still agreed. Here the geometry is
DERIVED, so the numbers in both files are reproducible from a named public-domain source rather
than trusted, and the Python and the JavaScript are emitted in the same pass from the same rings.

THE SOURCE. Natural Earth 1:50m admin-0 countries, the `Australia` feature. The 1:50m physical
COASTLINE layer would be the more obvious pick and is deliberately not used: it is a MultiLineString,
so every ring would have to be stitched closed by hand before it could be filled, which is exactly
the hand step this script exists to remove. The admin-0 country polygon is already closed rings, and
for Australia specifically it carries no political boundary at all - the country is an island
continent, so its national outline IS its coastline. Nothing is given up by taking the easier layer.

THE SIMPLIFICATION. Douglas-Peucker on raw (lon, lat) degrees. That is the right error metric here
because the surfaces draw an EQUIRECTANGULAR fit of a fixed extent, which over 112E-154E / 44S-9S
resolves to 5.095 px per degree of longitude against 5.029 px per degree of latitude: isotropic to
1.3 per cent, so one tolerance in degrees is one tolerance in pixels everywhere on the map.

WHAT THE CONSTANTS BUY. See the header of the generated _au_outline.py: TOLERANCE_DEG and
MIN_ISLAND_AREA_DEG2 are the two measured decisions, and both are recorded there for the reader who
never opens this script.
"""
import argparse
import hashlib
import json
import math
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent               # engine/extract/
REPO = HERE.parent.parent                            # the ausmt monorepo root
PY_OUT = HERE / "_au_outline.py"
JS_OUT = REPO / "portal" / "vendor" / "au-outline.js"

# ==================================================================================================
# THE DECLARED CONSTANTS. A change here is a coastline change: regenerate, re-measure the page
# budgets, and regenerate the brand mark (portal/tools/gen_brand.py), which rasterises these rings.
# ==================================================================================================

# Pinned to a COMMIT, not to a branch, so re-running this script years from now reproduces the same
# bytes rather than whatever master has drifted to. The digest is checked on every fetch.
NE_COMMIT = "9380cca83db5f9aef52d5e762765100745f84b27"
NE_LAYER = "ne_50m_admin_0_countries"
NE_VERSION = "5.1.1"
NE_SOURCE = (f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_COMMIT}"
             f"/geojson/{NE_LAYER}.geojson")
NE_SHA256 = "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
NE_LICENCE = "public domain (Natural Earth terms of use; CC0-equivalent, no attribution required)"
NE_DERIVED = "2026-08-31"

# THE TOLERANCE, MEASURED RATHER THAN GUESSED. Candidates from 0.01 to 0.80 degrees were rendered and
# scored on worst-case deviation from the full-resolution ring, per region and overall. 0.08 is the
# coarsest tolerance whose worst error is still about ONE PIXEL at 560 px, the widest the outline is
# ever drawn (the collection page scatter); at the 230 px survey minimap it is 0.41 px and at the
# 190 px link-preview inset 0.34 px, both comfortably sub-pixel against a 1 px stroke. Going finer
# buys nothing a reader can see and costs bytes on 27 survey pages: 0.05 would add 110 points for a
# 0.4 px improvement nobody can resolve. For scale, the hand-drawn outline this replaced was out by
# 1.57 degrees, or 20 px at the same width.
TOLERANCE_DEG = 0.08

# WHICH ISLANDS EARN A RING. The outline exists to LOCATE STATIONS, so the test that decides this is
# whether the served corpus puts stations on an island, not whether the island is famous. Of the
# candidates, Kangaroo Island carries 5 stations (Eyre Peninsula & Kangaroo Island 2014) and Flinders
# Island carries 2 (AusLAMP Tasmania); without their rings those 7 dots float on blank sea, which is
# the one defect a locator map must not have. Melville, Groote Eylandt and Fraser Island carry none.
# The cut is set at 0.10 square degrees because that is the band which covers both islands the corpus
# actually needs AND completes the two natural pairs a reader would notice were broken - the Tiwis
# (Melville with Bathurst) and the Bass Strait pair (Flinders with King). Seven islands cost 45
# points and about 520 bytes in total, so drawing the neighbour is cheaper than explaining its
# absence. Below the cut the next island is a sub-pixel speck carrying no data.
MIN_ISLAND_AREA_DEG2 = 0.10

# Coordinate precision in the emitted files. 0.001 degrees is 0.005 px at the survey minimap, well
# under the 0.1 px the projection rounds to, so this is lossless as far as any surface can tell.
PRECISION = 3

# The fixed drawing extent both surfaces project through. Rings outside it are dropped (Macquarie
# Island, at 158.9E / 54.6S, is the only one).
EXTENT = {"w": 112, "e": 154, "s": -44, "n": -9}

# The inter-state borders are NOT derived. They are the legislated meridian and parallel segments -
# geographic facts, not a simplification of anything - so they are carried through verbatim and a
# change to Natural Earth must never move them.
BORDERS = (
    [(129, -14.8), (129, -31.9)],
    [(129, -26), (141, -26)],
    [(138, -26), (138, -17.7)],
    [(141, -29), (141, -38)],
    [(141, -29), (148.9, -29), (151, -28.9), (152.5, -28.2)],
    [(141, -34.1), (143.5, -35.3), (144.5, -35.9), (146, -36.1), (147, -36.1), (148.1, -36.8),
     (149.9, -37.8)],
)
BORDER_NOTES = (
    "WA border (129E meridian)",
    "SA northern border (26S parallel)",
    "NT / QLD (138E meridian)",
    "SA eastern border (141E meridian)",
    "QLD / NSW (29S + rivers)",
    "NSW / VIC (River Murray, approximated)",
)

# ------------------------------------------------------------------------------ derivation


def fetch(source: str | None) -> bytes:
    """The pinned GeoJSON bytes, from a local path when given one, else the pinned URL. The digest
    is verified either way: a source that is not the pinned bytes is refused rather than silently
    producing a different coastline."""
    if source:
        raw = Path(source).read_bytes()
    else:
        with urllib.request.urlopen(NE_SOURCE, timeout=120) as r:   # noqa: S310 (pinned https URL)
            raw = r.read()
    got = hashlib.sha256(raw).hexdigest()
    if got != NE_SHA256:
        raise SystemExit(f"ERROR: source digest {got} is not the pinned {NE_SHA256}")
    return raw


def _ring_area(ring) -> float:
    """Shoelace area in square degrees. Used only to RANK rings, so a planar area is the right
    measure: it is comparing like with like over one small latitude band."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _within_extent(ring) -> bool:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (min(lons) >= EXTENT["w"] and max(lons) <= EXTENT["e"]
            and min(lats) >= EXTENT["s"] and max(lats) <= EXTENT["n"])


def douglas_peucker(pts, tol):
    """Iterative Douglas-Peucker over an open polyline. Iterative rather than recursive because a
    1,154-point ring at a fine tolerance can nest deeper than the interpreter's stack allows."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        den = math.hypot(dx, dy)
        worst, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = (math.hypot(x0 - x1, y0 - y1) if den == 0
                 else abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / den)
            if d > worst:
                worst, idx = d, i
        if worst > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def simplify_ring(ring, tol):
    """Douglas-Peucker on a CLOSED ring. The ring is first rotated to its western-most vertex so the
    seam sits at a fixed, data-determined point: Douglas-Peucker pins the two endpoints it is handed,
    so an arbitrary seam would pin an arbitrary vertex and make the output depend on where the source
    file happened to start the ring."""
    body = ring[:-1] if ring[0] == ring[-1] else list(ring)
    k = min(range(len(body)), key=lambda i: body[i])
    body = body[k:] + body[:k]
    out = douglas_peucker(body + [body[0]], tol)
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def derive(raw: bytes):
    """The rings for the mainland, Tasmania and every island above the cut, largest first.

    The order is load-bearing: COAST[0] is the mainland and COAST[1] is Tasmania, and both
    portal/tools/gen_brand.py and the brand pin name them by that position."""
    doc = json.loads(raw)
    feats = [f for f in doc["features"] if f["properties"].get("ADMIN") == "Australia"]
    if len(feats) != 1:
        raise SystemExit(f"ERROR: expected exactly one Australia feature, found {len(feats)}")
    rings = [[(c[0], c[1]) for c in poly[0]] for poly in feats[0]["geometry"]["coordinates"]]
    rings = [r for r in rings if _within_extent(r)]
    ranked = sorted(((r, _ring_area(r)) for r in rings), key=lambda t: t[1], reverse=True)
    kept = [t for i, t in enumerate(ranked) if i < 2 or t[1] >= MIN_ISLAND_AREA_DEG2]
    out = []
    for ring, a in kept:
        simp = [(round(x, PRECISION), round(y, PRECISION))
                for x, y in simplify_ring(ring, TOLERANCE_DEG)]
        # Rounding can collide adjacent vertices; drop the duplicates but keep the closing repeat.
        dedup = [simp[0]]
        for p in simp[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        if dedup[-1] != dedup[0]:
            dedup.append(dedup[0])
        out.append(dedup)
    # Ranked by SOURCE area above (selection is a fact about the island, not about how coarsely we
    # drew it), then re-ranked by the area actually emitted so "largest first" is true of the
    # committed file itself and can be checked there. Simplification moves the small rings by a few
    # per cent, which is enough to swap neighbours like Fraser and Flinders.
    return sorted(out, key=_ring_area, reverse=True)


# ------------------------------------------------------------------------------ emission


def _num(v) -> str:
    """A coordinate as the shortest exact decimal: 129.0 prints as 129, not 129.0."""
    r = round(float(v), PRECISION)
    return str(int(r)) if r == int(r) else f"{r:g}"


def _provenance_lines():
    return (f"Natural Earth {NE_VERSION}, layer {NE_LAYER} (the ADMIN=Australia feature), "
            f"commit {NE_COMMIT[:12]};",
            f"{NE_LICENCE};",
            f"Douglas-Peucker tolerance {TOLERANCE_DEG} degrees; islands above "
            f"{MIN_ISLAND_AREA_DEG2} square degrees; derived {NE_DERIVED}.")


def render_py(rings) -> str:
    prov = _provenance_lines()
    isl = len(rings) - 2
    body = ['#!/usr/bin/env python3',
            '"""True Australia coastline for the survey-page location minimap.',
            '',
            'SAME GEOMETRY as portal/vendor/au-outline.js (the collections footprint minimap), so the',
            'two surfaces draw one map; both files are emitted in one pass by _au_outline_build.py and a',
            'test compares them coordinate for coordinate. GENERATED - edit the build script, not this',
            'file. The inter-state borders are NOT derived: they are the legislated meridian and parallel',
            'segments, which are plain geographic facts rather than a simplification of anything.',
            '',
            'PROVENANCE',
            f'  {prov[0]}',
            f'  {prov[1]}',
            f'  {prov[2]}',
            '',
            'A LOCATOR BACKDROP for placing a survey, never a survey-grade or legal boundary.',
            'Coordinates are (longitude, latitude), WGS84. COAST is closed rings, largest first:',
            f'the mainland, Tasmania, then {isl} islands large enough to matter at this scale',
            '(the corpus puts stations on Kangaroo and Flinders). BORDERS are open polylines.',
            '"""',
            '',
            'COAST = (']
    for ring in rings:
        body.append("    [" + ", ".join(f"({_num(x)}, {_num(y)})" for x, y in ring) + "],")
    body += [')', '', 'BORDERS = (']
    for seg, note in zip(BORDERS, BORDER_NOTES):
        body.append("    [" + ", ".join(f"({_num(x)}, {_num(y)})" for x, y in seg)
                    + f"],  # {note}")
    body += [')', '',
             "# The fixed drawing extent the portal's collScatter uses: the outline and any dots "
             "projected",
             '# through the same equirectangular fit stay registered automatically.',
             'EXTENT = {'
             + ", ".join(f'"{k}": {EXTENT[k]}' for k in ("w", "e", "s", "n")) + '}',
             '']
    return "\n".join(body)


def render_js(rings) -> str:
    prov = _provenance_lines()
    labels = ["Mainland.", "Tasmania."] + ["Island." for _ in rings[2:]]
    body = ['// au-outline.js - Australia coastline + state/territory boundaries for the AusMT',
            '// collection footprint mini-map (drawer.js collScatter). Loaded as a classic <script>',
            '// that assigns one global, so collScatter can draw it synchronously with NO fetch (the',
            "// portal's CSP is script-src 'self', and a JS global avoids the async fetch dance).",
            '//',
            '// GENERATED by engine/extract/_au_outline_build.py - edit the build script, not this file.',
            '// SAME GEOMETRY as engine/extract/_au_outline.py, emitted in the same pass, compared',
            '// coordinate for coordinate by a test so the two surfaces cannot drift apart.',
            '//',
            '// SOURCE / LICENCE ------------------------------------------------------------------',
            f'//   {prov[0]}',
            f'//   {prov[1]}',
            f'//   {prov[2]}',
            '//   Inter-state boundaries are the legislated meridian/parallel segments, which are plain',
            '//   geographic facts. No rights are claimed over this file - reuse freely. It is a LOCATOR',
            '//   BACKDROP for context, NOT a survey-grade or legal boundary.',
            '//',
            '// FORMAT: coordinates are [longitude, latitude] in WGS84. `coast` is an array of closed',
            '// rings, largest first; `borders` is an array of open polylines. collScatter projects both',
            '// through the SAME fixed-Australia transform it uses for the station dots, so the outline',
            '// stays registered to the dots automatically.',
            'window.AU_OUTLINE = {',
            '  coast: [']
    for n, (ring, label) in enumerate(zip(rings, labels)):
        body.append(f"    // {label}")
        body.append("    [")
        for i in range(0, len(ring), 5):
            chunk = ", ".join(f"[{_num(x)}, {_num(y)}]" for x, y in ring[i:i + 5])
            body.append("      " + chunk + ("," if i + 5 < len(ring) else ""))
        body.append("    ]," if n < len(rings) - 1 else "    ]")
    body += ['  ],', '  borders: [']
    for i, (seg, note) in enumerate(zip(BORDERS, BORDER_NOTES)):
        pts = ", ".join(f"[{_num(x)}, {_num(y)}]" for x, y in seg)
        comma = "," if i < len(BORDERS) - 1 else ""
        body.append(f"    [{pts}]{comma}   // {note}")
    body += ['  ]', '};', '']
    return "\n".join(body)


# ------------------------------------------------------------------------------ cli


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if either generated file differs from what this script produces")
    ap.add_argument("--source", help="local copy of the pinned GeoJSON (skips the network)")
    a = ap.parse_args(argv)

    rings = derive(fetch(a.source))
    want = {PY_OUT: render_py(rings), JS_OUT: render_js(rings)}
    counts = ", ".join(str(len(r)) for r in rings)

    if a.check:
        stale = [p for p, text in want.items()
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print(f"STALE: {p.relative_to(REPO)}")
        if stale:
            print(f"re-run: python3 {Path(__file__).relative_to(REPO)}")
            return 1
        print(f"up to date; {len(rings)} rings, {sum(map(len, rings))} points ({counts})")
        return 0

    for p, text in want.items():
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(REPO)}")
    print(f"{len(rings)} rings, {sum(map(len, rings))} points ({counts}) "
          f"at tolerance {TOLERANCE_DEG} deg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
