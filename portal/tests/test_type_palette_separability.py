"""Data-type palette: the four hues must stay separable at SITE-DOT size, in normal and dichromatic vision.

Reported on the deployed badge map: "Long Period and Broadband icon colours are too similar".
At 4px the two read as one cool blob, because the old pair separated mostly by HUE (teal 221 deg vs
indigo 299 deg) while differing by only 9 L* - and small-mark discrimination is value-driven, not hue
driven. BBMT moved #5E5ED6 -> #3730B8: a deeper, more saturated blue-indigo that puts a 24.6 L* gap and a
55.7 C* gap between it and the LP teal, which is deliberately unchanged (teal is the established
fabric colour across the portal and its atlases).

THE PALETTE HAS TWO AUTHORITIES, and that is the first thing this file pins. There is no gen_config /
portal.config.yaml colour flow - that file carries branding, deployment, analytics and feature flags only.
The hexes live in:
    portal/src/state.js  TYPE_COL          -> map dots, drawer type chips, card mixbar, mini-scatter
    portal/index.html    --lpmt/--bbmt/... -> the map legend and the rail's data-type checkboxes
Both are consumed through their own path (the legend reads the CSS token via var(), never a literal), so
neither can be deleted in favour of the other without a redesign nobody asked for. What CAN be guaranteed
is that they never disagree, which is what test_the_two_palette_authorities_agree does. That is the
"single source" property restated as an enforceable invariant rather than a location.

FAILS IF:
  * the JS palette and the CSS tokens drift apart (a change applied to one surface only);
  * any data-type pair falls under PAIR_FLOOR dE00 (the palette-wide separability invariant);
  * the LP/BB pair specifically falls under LP_BB_FLOOR (the pair this module was opened to fix);
  * the LP/BB pair falls under LP_BB_DEUTAN_FLOOR once deuteranopia is SIMULATED - the guard that stops a
    future edit raising normal-vision distance while quietly re-converging them for red-green deficient
    readers, which a plain dE00 floor cannot see;
  * LP stops being teal-family (a rewrite that "fixed" separability by moving the wrong one).

The colour maths is stdlib-only on purpose (no new dependency for a four-colour check): sRGB -> linear ->
XYZ(D65) -> CIELAB, CIEDE2000, and the Vienot 1999 LMS-projection dichromat simulation.
"""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
STATE_JS = ROOT / "src" / "state.js"
INDEX = ROOT / "index.html"
# The third consumer, and the reason this file rather than the engine's suite carries the parity
# pin: portal-ci runs on portal/** and on the engine files portal tests read, so a change to either
# palette fires it. The engine workflow triggers on engine/** alone and would not see a state.js edit.
PAGES_PY = ROOT.parent / "engine" / "extract" / "_pages.py"

TYPES = ("LPMT", "BBMT", "AMT", "GDS")
TOKEN_OF = {"LPMT": "--lpmt", "BBMT": "--bbmt", "AMT": "--amt", "GDS": "--gds"}

# Stated floors. PAIR_FLOOR is the established palette-wide invariant this module preserves (the
# binding pair is AMT/GDS at 21.1, untouched here). LP_BB_FLOOR is this module's own promise: the
# reported pair must stay far clear of the general floor, not merely legal. LP_BB_DEUTAN_FLOOR is the
# same promise under simulated deuteranopia, where the old pair collapsed to 15.3.
PAIR_FLOOR = 21.0
LP_BB_FLOOR = 30.0
LP_BB_DEUTAN_FLOOR = 22.0


# ---------------------------------------------------------------- colour maths (stdlib only)

def _srgb(hx):
    hx = hx.lstrip("#")
    return [int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def lab(hx):
    """CIELAB (D65, 2 deg) for an sRGB hex."""
    r, g, b = (_lin(c) for c in _srgb(hx))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lch(hx):
    ll, aa, bb = lab(hx)
    return ll, math.hypot(aa, bb), math.degrees(math.atan2(bb, aa)) % 360


def de00(hx1, hx2):
    """CIEDE2000 between two sRGB hexes (kL=kC=kH=1)."""
    l1, a1, b1 = lab(hx1)
    l2, a2, b2 = lab(hx2)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cb = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7))) if cb > 0 else 0.5
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0
    dlp, dcp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dhp2 = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)
    lbp, cbp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    sl = 1 + (0.015 * (lbp - 50) ** 2) / math.sqrt(20 + (lbp - 50) ** 2)
    sc = 1 + 0.045 * cbp
    sh = 1 + 0.015 * cbp * t
    rc = 2 * math.sqrt(cbp ** 7 / (cbp ** 7 + 25 ** 7)) if cbp > 0 else 0.0
    rt = -math.sin(math.radians(2 * (30 * math.exp(-(((hbp - 275) / 25) ** 2))))) * rc
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp2 / sh) ** 2 + rt * (dcp / sc) * (dhp2 / sh))


# Vienot, Brettel & Mollon (1999): project onto the dichromat's reduced colour plane in LMS.
_M_LMS = ((0.31399022, 0.63951294, 0.04649755),
          (0.15537241, 0.75789446, 0.08670142),
          (0.01775239, 0.10944209, 0.87256922))
_M_LMS_INV = ((5.47221206, -4.6419601, 0.16963708),
              (-1.1252419, 2.29317094, -0.1678952),
              (0.02980165, -0.19318073, 1.16364789))
_PROJ = {"deutan": ((1.0, 0.0, 0.0), (0.9513092, 0.0, 0.04302666), (0.0, 0.0, 1.0)),
         "protan": ((0.0, 1.05118294, -0.05116099), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}


def _mul(m, v):
    return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


def simulate(hx, kind):
    """The hex a dichromat of `kind` sees in place of `hx`."""
    lms = _mul(_M_LMS, [_lin(c) for c in _srgb(hx)])
    rgb = _mul(_M_LMS_INV, _mul(_PROJ[kind], lms))
    return "#" + "".join(f"{round(255 * _unlin(c)):02X}" for c in rgb)


# ---------------------------------------------------------------- the two authorities

def js_palette():
    """TYPE_COL from src/state.js, the palette the map markers and drawer chips read."""
    m = re.search(r"const\s+TYPE_COL\s*=\s*\{([^}]*)\}", STATE_JS.read_text(encoding="utf-8"))
    assert m, "src/state.js must define `const TYPE_COL = {...}` (the data-type marker palette)"
    return {k: v.upper() for k, v in re.findall(r"(\w+)\s*:\s*\"(#[0-9A-Fa-f]{6})\"", m.group(1))}


def css_palette():
    """The --lpmt/--bbmt/--amt/--gds tokens from index.html, which the legend and rail swatches read."""
    css = INDEX.read_text(encoding="utf-8")
    out = {}
    for ty, tok in TOKEN_OF.items():
        m = re.search(re.escape(tok) + r"\s*:\s*(#[0-9A-Fa-f]{6})", css)
        assert m, f"index.html must define the {tok} token"
        out[ty] = m.group(1).upper()
    return out


def pages_palette():
    """_TYPE_COL from the engine's static-page emitter, which draws the same four types on every
    survey page's locator map, station-grid zoom and open-graph card."""
    m = re.search(r"_TYPE_COL\s*=\s*\{([^}]*)\}", PAGES_PY.read_text(encoding="utf-8"))
    assert m, "engine/extract/_pages.py must define `_TYPE_COL = {...}` (the page map palette)"
    return {k: v.upper() for k, v in re.findall(r"\"(\w+)\"\s*:\s*\"(#[0-9A-Fa-f]{6})\"", m.group(1))}


def test_the_two_palette_authorities_agree():
    """The JS marker palette and the CSS tokens must carry identical hexes, so a map dot and its legend
    swatch can never be different colours. FAILS IF a palette edit lands on one surface only - the exact
    accident this module could have caused (two files, one change)."""
    js, css = js_palette(), css_palette()
    for ty in TYPES:
        assert ty in js, f"TYPE_COL is missing {ty}"
        assert js[ty] == css[ty], (
            f"{ty}: src/state.js says {js[ty]} but index.html's {TOKEN_OF[ty]} says {css[ty]}. "
            f"The map dot and its legend swatch would render different colours.")


def test_the_static_pages_draw_the_same_palette_as_the_portal():
    """The THIRD consumer, added once the static entity pages started drawing type-coloured maps.

    This is the pin the BBMT drift proved was missing. The engine's _TYPE_COL kept the superseded
    #5B54D6 after this file's palette moved BBMT to #3730B8, so a
    reader who opens a survey page and then the same survey in the portal sees two different blues
    for one data type; and while an ENGINE test asserts the stale hex as a literal, applying the
    measured value there fails CI. A palette drift that CI defends is the precise failure a parity
    pin catches.

    The engine side is still asserted as a literal in the engine's own suite, which is right: that
    pin says "this hex, deliberately". This one says the two files agree, which is the property no
    literal on either side can state. Every type the engine draws must carry the portal's value; the
    portal's `other` fallback has no page equivalent and is not required here.

    FAILS IF either palette is edited without the other."""
    js, pages = js_palette(), pages_palette()
    assert pages, "the engine palette must parse (a rename here is a silently vacuous pin)"
    for ty, hexv in sorted(pages.items()):
        assert ty in js, (
            f"engine/extract/_pages.py draws data type {ty!r} that portal/src/state.js has no "
            f"colour for; one surface would fall back and the two would disagree")
        assert hexv == js[ty], (
            f"{ty}: engine/extract/_pages.py says {hexv} but portal/src/state.js says {js[ty]}. "
            f"A survey page's map and the portal's map would render one data type in two colours.")


def test_every_data_type_pair_clears_the_palette_floor():
    """Palette-wide separability (the invariant, preserved by this module). FAILS IF any pair of the four
    data-type hues falls under PAIR_FLOOR dE00. Non-vacuous: the binding pair (AMT/GDS) sits at ~21.1, just
    above the floor, so this is a live constraint rather than slack."""
    pal = js_palette()
    for i, t1 in enumerate(TYPES):
        for t2 in TYPES[i + 1:]:
            d = de00(pal[t1], pal[t2])
            assert d >= PAIR_FLOOR, (
                f"{t1} {pal[t1]} vs {t2} {pal[t2]}: dE00 {d:.2f} is under the {PAIR_FLOOR} floor - "
                f"two data types would be confusable at site-dot size.")


def test_lp_bb_pair_is_separated_by_luminance_not_hue_alone():
    """The pair the review reported. FAILS IF LP/BB falls under LP_BB_FLOOR, or if the separation is once
    again carried by hue with the lightnesses nearly equal - the old pair was 26.1 dE00 yet unreadable at
    4px because only 9 L* separated them, and lightness is what small marks are discriminated by."""
    pal = js_palette()
    lp, bb = pal["LPMT"], pal["BBMT"]
    d = de00(lp, bb)
    assert d >= LP_BB_FLOOR, (
        f"LP {lp} vs BB {bb}: dE00 {d:.2f} is under the stated {LP_BB_FLOOR} floor "
        f"(the pair this floor was set against measured 26.08 and read as one colour).")
    l_lp, c_lp, h_lp = lch(lp)
    l_bb, c_bb, _ = lch(bb)
    assert abs(l_lp - l_bb) >= 18.0, (
        f"LP L*={l_lp:.1f} vs BB L*={l_bb:.1f}: only {abs(l_lp - l_bb):.1f} L* apart. Small-dot "
        f"discrimination is value-driven; a hue-only separation is what failed before (old gap: 9.0).")
    assert abs(c_lp - c_bb) >= 30.0, (
        f"LP C*={c_lp:.1f} vs BB C*={c_bb:.1f}: the pair must also differ in saturation, not hue alone.")
    # LP stays teal-family: a future edit must not "fix" separability by moving the established fabric
    # colour instead of the one the review asked to move.
    assert 180.0 <= h_lp <= 240.0, f"LPMT must stay teal-family (hue 180-240 deg), got {h_lp:.1f} deg"


def test_lp_bb_pair_survives_simulated_red_green_deficiency():
    """DEUTAN SAFETY, computed not asserted. A pair distinguished mainly along the red-green axis collapses
    for deuteranopes; this pair is separated by LIGHTNESS and by the blue-yellow axis, so it must survive
    the simulation. FAILS IF the simulated LP/BB distance drops under LP_BB_DEUTAN_FLOOR - the guard a
    plain dE00 floor cannot provide, since normal-vision distance can rise while deutan distance falls."""
    pal = js_palette()
    lp, bb = pal["LPMT"], pal["BBMT"]
    for kind in ("deutan", "protan"):
        d = de00(simulate(lp, kind), simulate(bb, kind))
        assert d >= LP_BB_DEUTAN_FLOOR, (
            f"under simulated {kind}opia LP {lp}->{simulate(lp, kind)} and BB {bb}->{simulate(bb, kind)} "
            f"are only dE00 {d:.2f} apart, under the {LP_BB_DEUTAN_FLOOR} floor. "
            f"(The pair this floor was set against measured 15.26 deutan / 19.23 protan.)")


def test_no_data_type_collides_with_the_action_accent():
    """A data-type dot must never read as the portal's action/selection accent (--copper) or disappear into
    the marker stroke (#11182D). FAILS IF a palette edit walks a type into either - the rule,
    re-pinned here because this module moved a hex toward the dark end."""
    pal = js_palette()
    for ty in TYPES:
        assert de00(pal[ty], "#EF7256") >= PAIR_FLOOR, f"{ty} {pal[ty]} is confusable with the --copper accent"
        assert de00(pal[ty], "#11182D") >= PAIR_FLOOR, (
            f"{ty} {pal[ty]} is confusable with the marker stroke #11182D - the dot would lose its outline")
