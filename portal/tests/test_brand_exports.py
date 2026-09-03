"""The committed brand exports are renderings of contract/brand.json, and nothing else.

Ten files: two horizontal logos (dark and light background), two extended lockups that add the tagline
line, the standalone mark, each as an SVG and a PNG. The rules these pins hold, all of them from the
the brief:

  * ONE MARK. The dot markup is byte-identical in all five SVGs. Dark and light differ in the WORDMARK
    ink and in nothing else, which is what "the mark is identical in both" has to mean if it is to be
    checkable. A per-theme geometry is the failure this module exists to prevent.
  * REAL VECTORS. The SVGs are circles and text elements, not a PNG in a wrapper: no <image>, no data
    URI, no base64. A logo that is a raster inside an XML envelope cannot be scaled, restyled or
    printed, and it is the usual way a brand kit rots.
  * TRANSPARENT. No background plate in either format, so a variant sits on whatever it is placed on
    and the two variants stay a choice of INK rather than a choice of card.
  * THE TYPOGRAPHY RULE. The SVG wordmark declares the site's own system UI stack at weight 800 and
    the declared tracking, so it renders in the reader's fonts and matches the portal header. No SVG
    names the bundled raster face, because it has nothing to do with what a browser draws.
  * NO EN OR EM DASH anywhere in generated asset text.
  * The PNGs are rendered from the same declared geometry rather than by rasterising the SVGs, which
    is why they are checked for the geometry's own signature (transparent corners, the declared sizes)
    rather than for pixel equality with a browser's SVG rasteriser.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]          # portal/
REPO = ROOT.parent
BRAND_DIR = ROOT / "vendor" / "brand"
BRAND_JSON = REPO / "contract" / "brand.json"
TOOL = ROOT / "tools" / "gen_brand.py"

SVGS = ("ausmt-logo-dark.svg", "ausmt-logo-light.svg",
        "ausmt-logo-dark-extended.svg", "ausmt-logo-light-extended.svg",
        "ausmt-mark.svg")
PNGS = ("ausmt-logo-dark.png", "ausmt-logo-light.png",
        "ausmt-logo-dark-extended.png", "ausmt-logo-light-extended.png",
        "ausmt-mark.png")
DARK_VARIANTS = ("ausmt-logo-dark.svg", "ausmt-logo-dark-extended.svg")
LIGHT_VARIANTS = ("ausmt-logo-light.svg", "ausmt-logo-light-extended.svg")
EXTENDED = ("ausmt-logo-dark-extended.svg", "ausmt-logo-light-extended.svg")

# Spelt as escapes so this file never trips a dash sweep of its own, the same convention
# tests/test_no_en_dash.py uses.
EN_DASH = "\u2013"
EM_DASH = "\u2014"


def _svg(name):
    return (BRAND_DIR / name).read_text(encoding="utf-8")


def _dot_markup(text):
    """The mark's own markup: every colour group and every circle, wordmark markup excluded."""
    return re.findall(r'<g fill="#[0-9A-F]{6}">.*?</g>', text, re.S)


@pytest.mark.parametrize("name", SVGS + PNGS)
def test_every_declared_export_is_committed(name):
    """FAILS IF a variant is missing. The set is the brief's: two logos, two extended lockups, the
    standalone mark, in both formats."""
    assert (BRAND_DIR / name).is_file(), f"vendor/brand/{name} must be committed"


@pytest.mark.parametrize("name", SVGS)
def test_the_svgs_are_real_vectors_on_a_transparent_ground(name):
    """FAILS IF an SVG embeds a raster, carries a background plate, or loses its circles. A logo that
    is a PNG in an XML envelope cannot be scaled or restyled, and a background plate turns a variant
    into a card that cannot sit on anything else."""
    text = _svg(name)
    assert "<image" not in text and "base64" not in text and "data:" not in text, \
        f"{name}: the SVG must be real vector geometry, not an embedded raster"
    n_dots = len(re.findall(r"<circle ", text))
    want = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["geometry"]["dot_count"]
    assert n_dots == want, f"{name}: expected {want} dot circles from brand.json, found {n_dots}"
    assert "<rect" not in text, f"{name}: no background plate; brand exports are transparent"


def test_the_mark_is_one_geometry_in_every_variant():
    """FAILS IF any variant's dot markup differs by a single character from the standalone mark's.
    Dark and light are a choice of wordmark ink; the mark itself is the same object everywhere."""
    reference = _dot_markup(_svg("ausmt-mark.svg"))
    assert reference, "the standalone mark must carry the dot markup"
    for name in SVGS:
        assert _dot_markup(_svg(name)) == reference, \
            f"{name}: the mark's geometry or colour mapping has drifted from ausmt-mark.svg"


def test_the_two_backgrounds_differ_only_in_the_wordmark_ink():
    """FAILS IF a dark variant stops carrying the light wordmark, a light variant the dark one, or if
    either grows a second ink. brand.json declares both; nothing here re-decides them."""
    ink = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["palette"]["wordmark_ink"]
    for name in DARK_VARIANTS:
        assert f'fill="{ink["on_dark"]}">AusMT<' in _svg(name), \
            f"{name}: the dark-background variant carries the light wordmark {ink['on_dark']}"
    for name in LIGHT_VARIANTS:
        assert f'fill="{ink["on_light"]}">AusMT<' in _svg(name), \
            f"{name}: the light-background variant carries the dark wordmark {ink['on_light']}"


@pytest.mark.parametrize("name", DARK_VARIANTS + LIGHT_VARIANTS)
def test_the_svg_wordmark_declares_the_sites_own_font_stack(name):
    """The typography rule, on the surface it governs. FAILS IF an SVG wordmark stops declaring the
    portal header's stack and weight, loses the declared tracking, or names the bundled raster face:
    the exports must render in the READER's fonts, and the bundled face is a generator detail."""
    doc = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["typography"]
    text = _svg(name)
    assert f'font-family="{doc["web_font_stack"]}"' in text, \
        f"{name}: the wordmark must declare the site's system UI stack"
    assert f'font-weight="{doc["web_font_weight"]}"' in text, f"{name}: weight must match the header"
    assert f'letter-spacing="{doc["letter_spacing_em"]}em"' in text, \
        f"{name}: the declared tracking must ride the SVG, not the font engine's default"
    assert "inter" not in text.lower(), \
        f"{name}: no export may name the bundled raster substitute; it is not the AusMT typeface"


def test_only_the_extended_lockups_carry_the_tagline():
    """FAILS IF the tagline leaks into the compact logos or goes missing from the extended ones. Two
    widths, one difference."""
    tagline = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["tagline"]
    for name in EXTENDED:
        assert tagline in _svg(name), f"{name}: the extended lockup must carry the tagline"
    for name in ("ausmt-logo-dark.svg", "ausmt-logo-light.svg", "ausmt-mark.svg"):
        assert tagline not in _svg(name), f"{name}: the compact variant carries no tagline"


def test_the_extended_tagline_cannot_outrun_the_canvas_in_a_wide_fallback():
    """The lockup canvas is sized from the DECLARED advances, which are the bundled face's. The SVG
    then draws the text in the reader's system stack, which measures it differently, and an outermost
    <svg> loaded through <img> clips at its own viewBox. Measured in a real browser at the SVG's own
    sizes, the tagline's right edge lands at

      site stack 4131.6   Helvetica 4184.5   Tahoma 4358.1   Georgia 4461.6   Verdana 4707.5

    against a canvas 4473.35 wide: a Verdana or DejaVu-class fallback loses the end of the tagline,
    with a 200 and the right content type, which is the same silent failure the illegal XML comment
    produced. The wordmark cannot do this (its widest measured overrun is 113 units against 200 units
    of clear space); only the tagline sets the canvas edge, so only the tagline is held.

    FAILS IF the tagline stops declaring textLength at its declared advance, or if that advance stops
    ending exactly one clear space short of the canvas edge."""
    doc = json.loads(BRAND_JSON.read_text(encoding="utf-8"))
    m, prop = doc["proportions"]["mark_units"], doc["proportions"]
    advance = prop["tagline_font_size"] * m * doc["typography"]["tagline_advance_em"]
    for name in EXTENDED:
        text = _svg(name)
        tag = re.search(r"<text[^>]*>" + re.escape(doc["tagline"]) + r"</text>", text)
        assert tag, f"{name}: no tagline text element"
        got = re.search(r'textLength="([\d.]+)" lengthAdjust="spacing"', tag.group(0))
        assert got, (
            f"{name}: the tagline must declare textLength and lengthAdjust, or a wide fallback font "
            "draws it past the canvas edge and the reader loses the end of it")
        assert abs(float(got.group(1)) - advance) < 0.05, (
            f"{name}: textLength must be the declared advance {advance:.2f}, got {got.group(1)}")
        width = float(re.search(r'viewBox="0 0 ([\d.]+) ', text).group(1))
        text_x = float(re.search(r'<text x="([\d.]+)"', text).group(1))
        assert abs((text_x + advance + prop["clear_space"] * m) - width) < 0.05, (
            f"{name}: the tagline's declared end must sit exactly one clear space inside the canvas")


@pytest.mark.parametrize("name", SVGS)
def test_no_generated_asset_text_carries_an_en_or_em_dash(name):
    """The standing glyph rule, reaffirmed for this module and applied to generated bytes.
    FAILS IF either dash reaches an export. Both codepoints are spelt as escapes so this file never
    trips a sweep of its own, the same convention tests/test_no_en_dash.py uses."""
    text = _svg(name)
    for glyph, label in ((EN_DASH, "en dash"), (EM_DASH, "em dash")):
        assert glyph not in text, f"{name}: no {label} may reach an export"


def test_every_svg_parses_as_well_formed_xml():
    """FAILS IF an export is not well-formed XML. This is not pedantry: a browser decodes an SVG
    served as an image with a strict XML parser and shows a BROKEN IMAGE on any error, silently, with
    a 200 in the network panel and correct content type. The defect that put this pin here was a
    double hyphen inside the generated header comment, which XML forbids inside a comment; every
    export parsed fine to the eye, served fine, and rendered as alt text in the page header."""
    import xml.etree.ElementTree as ET
    for name in SVGS:
        try:
            ET.fromstring(_svg(name))
        except ET.ParseError as exc:
            raise AssertionError(f"{name}: not well-formed XML, so a browser will not render it: {exc}")


def test_the_pngs_are_transparent_and_the_declared_sizes():
    """FAILS IF a PNG loses its alpha channel, gains an opaque background, or drifts off the declared
    export sizes. These are rendered from brand.json's geometry, not by rasterising the SVGs, so the
    presentation resolution is a declared constant rather than whatever a converter chose."""
    from PIL import Image
    for name in PNGS:
        with Image.open(BRAND_DIR / name) as im:
            assert im.mode == "RGBA", f"{name}: brand PNGs are transparent (RGBA), got {im.mode}"
            assert im.getpixel((0, 0))[3] == 0, f"{name}: the top-left corner must be transparent"
            if name == "ausmt-mark.png":
                assert im.size == (1024, 1024), f"{name}: the mark exports square at 1024, got {im.size}"
            else:
                assert im.size[0] == 2400, f"{name}: logo exports are 2400 px wide, got {im.size}"


def test_gen_brand_check_covers_every_export():
    """FAILS IF the drift gate stops seeing the exports. A generated file the gate does not compare is
    a file anyone can hand-edit, which is the whole failure this module is built against."""
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True,
                       text=True, encoding="utf-8", cwd=str(REPO))
    assert r.returncode == 0, f"gen_brand.py --check must be green:\n{r.stdout}\n{r.stderr}"
    n = int(re.search(r"brand: (\d+) generated", r.stdout).group(1))
    assert n >= len(SVGS) + len(PNGS) + 1, \
        f"the gate must cover brand.json and all ten exports, it reports {n} artefacts"


def test_the_cards_corner_mark_is_a_generated_export_the_gate_holds():
    """The link-preview cards draw the AusMT mark small, in their top-left corner, and the engine
    ships its own pinned copy of it (engine/tests/test_og_cards.py). That copy is only as trustworthy
    as the file it is pinned to, so the small mark is a DECLARED export like every other: rendered
    from brand.json's geometry by png_mark, listed in the output index, and compared by --check.

    It exists at all because the 1024 px mark is a third of a megabyte to show at 42 px, and the
    engine image would have to carry that. The export size is a whole multiple of the drawn height,
    so the card's resample is a clean box rather than an arbitrary ratio.

    Teeth: the gate must go red when this one file is perturbed, which is what proves it is compared
    rather than merely listed."""
    # Compiled and run rather than imported, so this reads the tool's CURRENT source. An import is
    # answered from __pycache__ whenever the stamped source mtime matches to the second, so an edit
    # and a test run in the same second can be answered with the previous compile.
    ns = {"__file__": str(TOOL), "__name__": "gen_brand_pin"}
    exec(compile(TOOL.read_text(encoding="utf-8"), str(TOOL), "exec"), ns)
    name = f"ausmt-mark-{ns['PNG_CARD_MARK_SIZE']}.png"
    rel = f"portal/vendor/brand/{name}"
    assert rel in [row[0] for row in ns["_OUTPUT_INDEX"]], \
        f"{rel} must be a declared export, or --check never looks at it"
    assert ns["PNG_CARD_MARK_SIZE"] % ns["CARD_MARK_DRAWN_PX"] == 0, (
        f"the export ({ns['PNG_CARD_MARK_SIZE']}) must be a whole multiple of the drawn height "
        f"({ns['CARD_MARK_DRAWN_PX']}) so the card resamples it as a clean box")
    target = BRAND_DIR / name
    assert target.is_file(), f"{rel} must be committed"
    original = target.read_bytes()
    try:
        from PIL import Image
        with Image.open(target) as im:
            perturbed = im.convert("RGBA")
        perturbed.putpixel((0, 0), (255, 0, 0, 255))
        perturbed.save(target, "PNG")
        r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True,
                           text=True, encoding="utf-8", cwd=str(REPO))
        assert r.returncode == 1, \
            f"--check must fail on a perturbed {name}, it returned {r.returncode}"
        assert name in r.stdout + r.stderr, f"--check must name the file that drifted:\n{r.stdout}"
    finally:
        target.write_bytes(original)
