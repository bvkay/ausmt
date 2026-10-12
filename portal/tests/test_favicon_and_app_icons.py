"""The favicon and the app icons are the AuScope mark, and every surface links them.

The browser tab and the home-screen icon carry the parent organisation's mark, Royal Blue with its
lighter swoosh, rendered by portal/tools/gen_auscope_icons.py from vendor/auscope/auscope-mark.svg.
The AusMT mark stays the product mark of the brand page and the link-preview cards, and its
exports are held by tests/test_brand_exports.py. What these pins hold:

  * ONE SOURCE. vendor/favicon.svg carries the mark's own path elements character for character, in
    a viewBox cropped to the ink, with a title and nothing else. A redrawn mark would drift from the
    file AuScope supplies, and replacing that file is meant to be the whole of a change to the icons.
  * THE RASTERS ARE THE MARK. Each favicon.ico frame is transparent at its corners, the mark fills
    it, and its opaque pixels average to the blend of Royal Blue and the swoosh tint that the
    vector's own areas predict. Each app icon is opaque at its declared size, white at the corners,
    with the mark centred at 70 percent of its width and the mark's two solid colours as its two
    commonest inks.
  * EVERY SURFACE LINKS THEM in one three-line block, root-anchored, with no query on any href.
  * THE DRIFT GATE. The committed files are a fresh render: favicon.svg byte for byte, each raster
    as its decoded picture, so a different Pillow encoding the same picture stays green and a
    one-pixel edit goes red. Pillow is the only renderer, so every pin runs wherever the suite does.

NO WEB MANIFEST: 192 and 512 are rendered so that a manifest can be added later, but an installable
PWA is its own decision.
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]          # portal/
REPO = ROOT.parent
MARK = ROOT / "vendor" / "auscope" / "auscope-mark.svg"
FAVICON = ROOT / "vendor" / "favicon.svg"
FAVICON_ICO = ROOT / "favicon.ico"
ICON_DIR = ROOT / "vendor" / "auscope"
TOOL = ROOT / "tools" / "gen_auscope_icons.py"
BRAND_TOOL = ROOT / "tools" / "gen_brand.py"
BRAND_JSON = REPO / "contract" / "brand.json"
PAGES_PY = REPO / "engine" / "extract" / "_pages.py"

ROYAL_BLUE = (0x28, 0x25, 0x72)
SWOOSH_TINT = (0xBF, 0xBD, 0xD4)
WHITE = (255, 255, 255)
ICO_SIZES = (16, 32, 48)
APP_ICONS = {"icon-180.png": 180, "icon-192.png": 192, "icon-512.png": 512}
# The mark's width as a fraction of an app icon's width.
APP_ICON_MARK_WIDTH = 0.70
# Per channel, on 0 to 255: the furthest an ICO frame's mean opaque colour may sit from the blend the
# vector's areas predict. Anti-aliasing moves it by about 6 at 16 px; the AusMT mark's lattice
# averages near (150, 70, 200), and the white mark near (255, 255, 255).
BLEND_TOLERANCE = 12

# The static portal documents that carry the site chrome. 404.html is not a chrome page (it has no
# header), but it is in SHIPPED_PAGES below: it is the document a browser lands on for any unknown
# path, so it links the icons like every other page.
CHROME_PAGES = ("index.html", "about.html", "add-survey.html", "brand.html", "releases.html")
SHIPPED_PAGES = CHROME_PAGES + ("404.html",)


def _tool_namespace(tool=TOOL):
    """A generator's constants and functions, read from its CURRENT source.

    Compiled and run rather than imported: an import is answered from __pycache__ whenever the
    stamped source mtime matches to the second."""
    ns = {"__file__": str(tool), "__name__": "icon_pin"}
    exec(compile(tool.read_text(encoding="utf-8"), str(tool), "exec"), ns)
    return ns


# --------------------------------------------------------------------------------------------------
# The mark's own geometry, restated here so the pins do not lean on the tool they check.
# --------------------------------------------------------------------------------------------------

def _paths(svg):
    return re.findall(r"<path\b[^>]*/>", svg)


def _outline(d, steps=200):
    """One path's outline as a polyline, from absolute M, L, C and Z, the commands the mark uses."""
    pts, cmd, i = [], None, 0
    toks = re.findall(r"[A-Za-z]|-?\d+\.?\d*", d)
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            assert cmd in "MLCZ", f"the mark uses a path command this pin does not read: {cmd}"
            i += 1
            continue
        if cmd == "C":
            p0 = pts[-1]
            c = [float(t) for t in toks[i:i + 6]]
            i += 6
            for k in range(1, steps + 1):
                t = k / steps
                pts.append(tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * q
                                 + t ** 3 * e
                                 for a, b, q, e in zip(p0, c[0:2], c[2:4], c[4:6])))
        else:
            pts.append((float(toks[i]), float(toks[i + 1])))
            i += 2
    return pts


def _area(pts):
    n = len(pts)
    return abs(sum(pts[k][0] * pts[(k + 1) % n][1] - pts[(k + 1) % n][0] * pts[k][1]
                   for k in range(n))) / 2


def _mark():
    """[(outline, fill)] for every path of the AuScope mark."""
    out = []
    for path in _paths(MARK.read_text(encoding="utf-8")):
        d = re.search(r'\bd="([^"]+)"', path).group(1)
        fill = re.search(r'\bfill="(#[0-9A-Fa-f]{6})"', path).group(1).upper()
        out.append((_outline(d), fill))
    return out


def _ink_bbox():
    pts = [p for outline, _f in _mark() for p in outline]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _expected_blend():
    """The mean colour of the mark's ink: Royal Blue and the swoosh tint, weighted by area."""
    areas = Counter()
    for outline, fill in _mark():
        areas[fill] += _area(outline)
    assert set(areas) == {"#282572", "#BFBDD4"}, \
        f"the mark is Royal Blue with a lighter swoosh, its fills are {sorted(areas)}"
    f = areas["#BFBDD4"] / sum(areas.values())
    return tuple((1 - f) * b + f * s for b, s in zip(ROYAL_BLUE, SWOOSH_TINT)), f


def _pixels(im):
    data = im.tobytes()
    n = len(im.getbands())
    return [tuple(data[k:k + n]) for k in range(0, len(data), n)]


# --------------------------------------------------------------------------------------------------
# favicon.svg
# --------------------------------------------------------------------------------------------------

def test_the_favicon_is_the_auscope_mark_and_nothing_else():
    """FAILS IF favicon.svg stops carrying the mark's own path elements character for character, in
    the same order, or carries anything beyond the viewBox, a title of AuScope and those paths."""
    mark_paths = _paths(MARK.read_text(encoding="utf-8"))
    assert mark_paths, "vendor/auscope/auscope-mark.svg must carry the mark's paths"
    svg = FAVICON.read_text(encoding="utf-8")
    assert _paths(svg) == mark_paths, \
        "favicon.svg must carry the AuScope mark's path elements verbatim and in order"
    vb = re.search(r'viewBox="([^"]+)"', svg)
    assert vb, "favicon.svg must declare a viewBox"
    want = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + vb.group(1) + '">'
            "<title>AuScope</title>" + "".join(mark_paths) + "</svg>\n")
    assert svg == want, "favicon.svg is the viewBox, the title and the mark's paths, and nothing else"
    root = ET.fromstring(svg)
    assert [child.tag.split("}")[-1] for child in root] == ["title"] + ["path"] * len(mark_paths)
    assert root[0].text == "AuScope"


def test_the_favicon_viewbox_frames_the_ink_with_no_padding():
    """FAILS IF the viewBox crops any ink or adds space beyond rounding to two decimals. Padding
    shrinks the mark inside a 16 px tab, and a crop cuts it."""
    x, y, w, h = (float(v) for v in
                  re.search(r'viewBox="([^"]+)"', FAVICON.read_text(encoding="utf-8")).group(1).split())
    x0, y0, x1, y1 = _ink_bbox()
    eps = 1e-6
    for got, ink, label in ((x, x0, "left"), (y, y0, "top")):
        assert got <= ink + eps and ink - got < 0.01, \
            f"the viewBox {label} edge sits at {got}, the ink at {ink:.4f}"
    for got, ink, label in ((x + w, x1, "right"), (y + h, y1, "bottom")):
        assert got >= ink - eps and got - ink < 0.01, \
            f"the viewBox {label} edge sits at {got}, the ink at {ink:.4f}"


def test_the_favicon_is_transparent_well_formed_and_carries_no_retired_art():
    """FAILS IF the favicon grows a background plate, keeps the AusMT dot lattice or the retired
    placeholder curve, embeds a raster, or stops parsing as XML (a browser shows nothing for an SVG
    icon it cannot parse)."""
    svg = FAVICON.read_text(encoding="utf-8")
    ET.fromstring(svg)
    for stale in ("<rect", "<circle", "<polyline", "<image", "data:", "<!--"):
        assert stale not in svg, f"favicon.svg must not carry {stale!r}"


def test_the_favicon_svg_is_the_generators_output():
    """The text half of the drift gate, in process. FAILS IF the committed favicon.svg is not what
    gen_auscope_icons.py writes from the mark today."""
    ns = _tool_namespace()
    paths = ns["mark_paths"](MARK.read_text(encoding="utf-8"))
    assert FAVICON.read_text(encoding="utf-8") == ns["favicon_svg"](paths), \
        "favicon.svg has drifted from gen_auscope_icons.py; regenerate it"


# --------------------------------------------------------------------------------------------------
# favicon.ico
# --------------------------------------------------------------------------------------------------

def test_the_root_icon_exists_and_carries_three_sizes():
    """FAILS IF the portal ships no /favicon.ico, or if the file stops carrying exactly the three
    entries. A browser that ignores the SVG icon link requests this path by name, and nothing else on
    the site answers it."""
    from PIL import Image
    assert FAVICON_ICO.is_file(), \
        "portal/favicon.ico must be committed; the portal image serves portal/ at the site root"
    with Image.open(FAVICON_ICO) as ico:
        assert ico.format == "ICO", f"the root icon must decode as an ICO, got {ico.format!r}"
        got = sorted(s[0] for s in ico.info["sizes"])
        assert got == list(ICO_SIZES), \
            f"the root icon must carry {list(ICO_SIZES)} px entries, got {got}"


@pytest.mark.parametrize("size", ICO_SIZES)
def test_every_root_icon_frame_is_the_mark_in_royal_blue_on_a_transparent_ground(size):
    """FAILS IF a frame loses its transparent corners, stops filling its square, or stops being the
    AuScope mark's colours: the mean of its fully opaque pixels must sit within BLEND_TOLERANCE of
    Royal Blue blended with the swoosh tint in the proportion of their areas in the vector."""
    from PIL import Image
    with Image.open(FAVICON_ICO) as ico:
        ico.size = (size, size)
        frame = ico.convert("RGBA")
    assert frame.size == (size, size)
    for corner in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
        assert frame.getpixel(corner)[3] == 0, f"{size} px: the corner {corner} must be transparent"
    solid = frame.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
    assert solid and max(solid[2] - solid[0], solid[3] - solid[1]) >= size - 2, (
        f"{size} px: the mark must fill the frame edge to edge on its longer side, it spans {solid}")
    opaque = [p[:3] for p in _pixels(frame) if p[3] == 255]
    assert len(opaque) >= 0.10 * size * size, \
        f"{size} px: only {len(opaque)} fully opaque pixels; the mark has dissolved"
    mean = [sum(p[k] for p in opaque) / len(opaque) for k in range(3)]
    want, _f = _expected_blend()
    assert all(abs(m - w) <= BLEND_TOLERANCE for m, w in zip(mean, want)), (
        f"{size} px: the opaque pixels average {[round(m, 1) for m in mean]}, which is not the "
        f"AuScope mark's {[round(w, 1) for w in want]} within {BLEND_TOLERANCE}")


@pytest.mark.parametrize("size", ICO_SIZES)
def test_every_root_icon_frame_is_the_generators_render_at_its_own_size(size):
    """FAILS IF a frame's decoded pixels differ from the generator's render at that size. Each frame
    is drawn at its own size, so the 16 px frame is not a resampled copy of the 48 px one."""
    from PIL import Image
    ns = _tool_namespace()
    paths = ns["mark_paths"](MARK.read_text(encoding="utf-8"))
    with Image.open(FAVICON_ICO) as ico:
        ico.size = (size, size)
        frame = ico.convert("RGBA")
    assert frame.tobytes() == ns["ico_frame"](paths, size).tobytes(), \
        f"the {size} px frame is not the generator's mark rendered at {size} px"


# --------------------------------------------------------------------------------------------------
# The app icons
# --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,size", sorted(APP_ICONS.items()))
def test_every_app_icon_is_the_mark_on_an_opaque_white_square(name, size):
    """FAILS IF an app icon is missing, is not its declared size, carries an alpha channel (a home
    screen fills transparency with black), loses its white corners, or stops carrying the mark at
    70 percent of its width, centred, in the mark's own two solid colours."""
    from PIL import Image
    path = ICON_DIR / name
    assert path.is_file(), f"vendor/auscope/{name} must be committed"
    with Image.open(path) as im:
        assert im.mode == "RGB", f"{name}: app icons are opaque RGB, got {im.mode}"
        assert im.size == (size, size), f"{name}: must be {size}x{size}, got {im.size}"
        for corner in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
            assert im.getpixel(corner) == WHITE, f"{name}: the corner {corner} must be white"
        # The ink's half-coverage edge: a pixel at least half Royal Blue. The mark's four extremes
        # are all Royal Blue, so this is the mark's extent.
        half = (255 + ROYAL_BLUE[0]) / 2
        bb = im.getchannel("R").point(lambda v: 255 if v < half else 0).getbbox()
        pixels = _pixels(im)
    assert bb, f"{name}: no mark found"
    x0, y0, x1, y1 = _ink_bbox()
    width, height = bb[2] - bb[0], bb[3] - bb[1]
    assert abs(width - APP_ICON_MARK_WIDTH * size) <= 1.5, (
        f"{name}: the mark spans {width} px, not {APP_ICON_MARK_WIDTH:.0%} of {size}")
    assert abs(height - width * (y1 - y0) / (x1 - x0)) <= 2.5, \
        f"{name}: the mark's height {height} px has lost the vector's proportions"
    for lo, hi, axis in ((bb[0], bb[2], "horizontally"), (bb[1], bb[3], "vertically")):
        assert abs((lo + hi) / 2 - size / 2) <= 1.0, f"{name}: the mark is not centred {axis}"
    inks = Counter(p for p in pixels if p != WHITE).most_common(2)
    assert [c for c, _n in inks] == [ROYAL_BLUE, SWOOSH_TINT], (
        f"{name}: the two commonest inks must be Royal Blue and the swoosh tint, got {inks}")
    _want, f = _expected_blend()
    ratio = inks[1][1] / inks[0][1]
    assert abs(ratio - f / (1 - f)) <= 0.05, (
        f"{name}: the swoosh covers {ratio:.3f} of the blue, the vector says {f / (1 - f):.3f}")


def test_the_icon_rules_are_named_constants_of_the_generator():
    """The source, the frame sizes, the proportion, the ground and the supersampling are named in the
    generator so they can be read and pinned. FAILS IF one of them moves without this pin moving."""
    ns = _tool_namespace()
    assert ns["MARK"] == MARK
    assert ns["TITLE"] == "AuScope"
    assert tuple(ns["ICO_SIZES"]) == ICO_SIZES
    assert tuple(ns["APP_ICON_SIZES"]) == tuple(sorted(APP_ICONS.values()))
    assert abs(ns["APP_ICON_MARK_WIDTH"] - APP_ICON_MARK_WIDTH) < 1e-9
    assert tuple(ns["APP_ICON_GROUND"]) == WHITE
    assert ns["SUPERSAMPLE"] == 8
    assert ns["CUBIC_STEPS"] == 64


def test_each_icon_file_has_one_author():
    """FAILS IF gen_brand.py still declares the favicon or the root icon, or gen_auscope_icons.py
    stops declaring any of the five files. Two generators writing one path means the second run wins
    and the drift gates disagree about which file is right."""
    ns = _tool_namespace()
    ours = {ns["FAVICON_SVG"], ns["FAVICON_ICO"]} | {ns["app_icon_path"](s) for s in APP_ICONS.values()}
    assert ours == {FAVICON, FAVICON_ICO} | {ICON_DIR / n for n in APP_ICONS}
    brand = _tool_namespace(BRAND_TOOL)
    declared = {row[0] for row in brand["_OUTPUT_INDEX"]}
    outputs = {o["path"] for o in json.loads(BRAND_JSON.read_text(encoding="utf-8"))["outputs"]}
    for path in ours:
        rel = str(path.relative_to(REPO))
        assert rel not in declared, f"gen_brand.py must not declare {rel}; gen_auscope_icons.py writes it"
        assert rel not in outputs, f"contract/brand.json must not list {rel} as an AusMT export"


# --------------------------------------------------------------------------------------------------
# The drift gate
# --------------------------------------------------------------------------------------------------

def _run_tool(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True,
                          text=True, encoding="utf-8", cwd=str(REPO))


def test_the_drift_gate_is_green_on_the_committed_icons():
    """FAILS IF favicon.svg differs by a byte, or any raster by a pixel, its mode or its frame sizes,
    from a fresh render of the mark."""
    r = _run_tool("--check")
    assert r.returncode == 0, f"gen_auscope_icons.py --check must be green:\n{r.stdout}\n{r.stderr}"
    assert "5 file(s) in sync" in r.stdout, r.stdout


def test_the_drift_gate_compares_the_root_icon():
    """FAILS IF the gate lists the root icon without comparing it: a generated file the gate does not
    compare is a file anyone can hand-edit. The perturbation is what tells the two apart."""
    from PIL import Image
    original = FAVICON_ICO.read_bytes()
    try:
        frames = []
        with Image.open(FAVICON_ICO) as ico:
            for size in ICO_SIZES:
                ico.size = (size, size)
                frames.append(ico.convert("RGBA"))
        frames[0].putpixel((0, 0), (255, 0, 0, 255))
        frames[-1].save(FAVICON_ICO, "ICO", sizes=[(s, s) for s in ICO_SIZES],
                        append_images=frames[:-1])
        r = _run_tool("--check")
        assert r.returncode == 1, f"the gate must fail on a perturbed favicon.ico, got {r.returncode}"
        assert "favicon.ico" in r.stdout + r.stderr, \
            f"the gate must name the file that drifted:\n{r.stdout}\n{r.stderr}"
    finally:
        FAVICON_ICO.write_bytes(original)


def test_the_drift_gate_compares_app_icon_pictures_not_encodings():
    """FAILS IF the gate compares encoded bytes, which turns red when another Pillow writes the same
    picture, or stops comparing pixels or the mode. A re-encode at another compression level must stay
    green; a one-pixel edit and the same pixels saved as RGBA must each go red and name the file."""
    from PIL import Image
    path = ICON_DIR / "icon-180.png"
    original = path.read_bytes()
    try:
        with Image.open(path) as im:
            picture = im.copy()
        picture.save(path, "PNG", compress_level=1)
        assert path.read_bytes() != original, "the re-encode must change the bytes for this pin to bite"
        r = _run_tool("--check")
        assert r.returncode == 0, f"a re-encode of the same picture must pass:\n{r.stdout}\n{r.stderr}"
        edited = picture.copy()
        edited.putpixel((0, 0), (255, 0, 0))
        for name, im in (("a one-pixel edit", edited), ("an RGBA copy", picture.convert("RGBA"))):
            im.save(path, "PNG")
            r = _run_tool("--check")
            assert r.returncode == 1, f"the gate must fail on {name} of icon-180.png, got {r.returncode}"
            assert "icon-180.png" in r.stderr, f"the gate must name the file that drifted:\n{r.stderr}"
    finally:
        path.write_bytes(original)


def test_two_renders_write_the_same_bytes():
    """FAILS IF a render carries a timestamp or any other per-run difference. An icon that differs
    on identical inputs makes every regeneration a spurious diff."""
    ns = _tool_namespace()
    paths = ns["mark_paths"](MARK.read_text(encoding="utf-8"))
    assert ns["ico_bytes"](paths) == ns["ico_bytes"](paths)
    for size in APP_ICONS.values():
        assert ns["app_icon_bytes"](paths, size) == ns["app_icon_bytes"](paths, size)


# --------------------------------------------------------------------------------------------------
# Every surface links the icons
# --------------------------------------------------------------------------------------------------

# One block, root-anchored so a document served at /surveys/<slug> resolves it, and no href carries a
# query: a search engine keeps the icon URL it found on the home page, so the URLs stay stable and the
# bytes revalidate.
ICON_FILES = {
    "/favicon.ico": FAVICON_ICO,
    "/vendor/favicon.svg": FAVICON,
    "/vendor/auscope/icon-180.png": ICON_DIR / "icon-180.png",
}


def _icon_block(sep="\n"):
    """The three icon links, in the declared order and form."""
    return sep.join((
        '<link rel="icon" href="/favicon.ico" sizes="any">',
        '<link rel="icon" href="/vendor/favicon.svg" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/vendor/auscope/icon-180.png">',
    ))


def test_every_href_in_the_icon_block_is_a_committed_file():
    """FAILS IF the block names a file the portal does not ship, so every page would ask for it and
    get a 404."""
    hrefs = re.findall(r'href="([^"]+)"', _icon_block())
    assert hrefs == list(ICON_FILES), hrefs
    for href, path in ICON_FILES.items():
        assert path.is_file(), f"{href} must be committed at {path.relative_to(REPO)}"


@pytest.mark.parametrize("name", SHIPPED_PAGES)
def test_every_shipped_page_carries_the_icon_block(name):
    """FAILS IF a page loses an icon link, writes the three in a different order or a relative form,
    or still points the apple-touch-icon at the AusMT export. 404.html is in scope with the rest: a
    relative href there would resolve against whatever unknown path was requested."""
    text = (ROOT / name).read_text(encoding="utf-8")
    assert _icon_block() in text, f"{name}: the head must carry the three icon links:\n" + _icon_block()


@pytest.mark.parametrize("name", SHIPPED_PAGES + ("_pages.py",))
def test_no_surface_links_a_mask_icon(name):
    """FAILS IF a pinned-tab mask icon appears anywhere. Safari fills a mask with one flat colour, so
    the swoosh, which is the lighter half of the mark, would vanish into the blue."""
    text = (PAGES_PY if name == "_pages.py" else ROOT / name).read_text(encoding="utf-8")
    assert "mask-icon" not in text, f"{name}: no surface may link a pinned-tab mask icon"


def test_the_generated_pages_link_the_same_block_same_origin():
    """FAILS IF the pages' shell stops emitting the block, emits it anywhere but the portal's own
    origin, or drifts from the static pages' copy."""
    src = PAGES_PY.read_text(encoding="utf-8")
    for tag in _icon_block().split("\n"):
        assert tag in src, f"engine/extract/_pages.py must emit {tag}"
    hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', src)
    assert hrefs, "the pages' shell must emit icon links"
    for href in hrefs:
        assert href.startswith("/") and not href.startswith("//"), (
            f"the pages' icon links must be same-origin portal paths, got {href}")
        assert "://" not in href and not href.startswith("data:"), (
            f"an icon href is same-origin only; {href} is not")


def test_no_web_manifest_was_smuggled_in():
    """192 and 512 exist for a future manifest; shipping one would make the portal installable to a
    home screen, which is a product decision of its own. FAILS IF a manifest link appears on any
    chrome page."""
    for name in CHROME_PAGES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert 'rel="manifest"' not in text, (
            f"{name}: an installable-PWA manifest is its own decision, not a side effect of the "
            "icon work")


@pytest.mark.parametrize("name", SHIPPED_PAGES + ("_pages.py",))
def test_no_icon_href_carries_a_version_query(name):
    """A search engine crawls a favicon only when it crawls the home page and keeps the URL it found,
    so the icon URLs stay stable and the edge revalidates their bytes (deploy/docker/caddy/Caddyfile,
    @iconAssets). FAILS IF a query string comes back on any icon href on any surface."""
    text = (PAGES_PY if name == "_pages.py" else ROOT / name).read_text(encoding="utf-8")
    for href in re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', text):
        assert "?" not in href, f"{name}: {href} carries a query; icon URLs are stable by rule"

