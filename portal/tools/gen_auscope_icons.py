#!/usr/bin/env python3
"""Render the site's favicon and app icons from the AuScope mark.

    python3 tools/gen_auscope_icons.py            # (re)write the icons
    python3 tools/gen_auscope_icons.py --check    # exit 1 if a committed icon differs from a fresh render

The one source is vendor/auscope/auscope-mark.svg, so replacing that file with the official artwork
and rerunning this tool is the whole of a change to the icons. It writes:

  vendor/favicon.svg                 the mark's own paths in a viewBox cropped to the mark, titled AuScope
  favicon.ico                        16, 32 and 48 px frames of the mark on a transparent ground
  vendor/auscope/icon-<size>.png     180, 192 and 512 px: the mark at 70 percent of the icon's width,
                                     centred on an opaque white square

Pillow is the only renderer. Each path is flattened to a polygon, the polygons are filled in source
order at eight times the icon's size, and the result is resampled down with Lanczos, which keeps the
16 px frame's edges clean. --check compares favicon.svg as text bytes and every raster as its decoded
picture (mode, size and pixels; for favicon.ico the frame sizes and each frame's pixels), because a
different Pillow can encode the same picture as different bytes.
"""
import argparse
import io
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # portal/
MARK = ROOT / "vendor" / "auscope" / "auscope-mark.svg"
FAVICON_SVG = ROOT / "vendor" / "favicon.svg"
FAVICON_ICO = ROOT / "favicon.ico"
ICON_DIR = ROOT / "vendor" / "auscope"

TITLE = "AuScope"
# A browser picks the ICO frame it needs: 16 for the tab, 32 for a high-density tab and the bookmark
# bar, 48 for a desktop shortcut. Each frame is drawn at its own size, never resampled from another.
ICO_SIZES = (16, 32, 48)
# 180 is the apple-touch-icon a home-screen shortcut uses; 192 and 512 are the pair a web manifest names.
APP_ICON_SIZES = (180, 192, 512)
# A home screen fills a transparent icon with black and rounds its corners, so the ground is opaque
# white and the mark keeps 15 percent of the width clear on each side.
APP_ICON_MARK_WIDTH = 0.70
APP_ICON_GROUND = (255, 255, 255)
SUPERSAMPLE = 8
# Line pieces per cubic segment when a path is flattened to a polygon.
CUBIC_STEPS = 64
# The viewBox is rounded outward to this many decimals, so rounding can only add space, never crop ink.
VIEWBOX_DECIMALS = 2


def app_icon_path(size):
    return ICON_DIR / f"icon-{size}.png"


# ==================================================================================================
# The mark's geometry
# ==================================================================================================

def mark_paths(svg_text):
    """The mark's <path> elements, character for character as the source writes them."""
    paths = re.findall(r"<path\b[^>]*/>", svg_text)
    if not paths:
        raise SystemExit(f"ERROR: {MARK.relative_to(ROOT)} carries no <path> element to draw")
    return paths


def _segments(d):
    """The cubic segments of one path's data, lines included as degenerate cubics.

    The mark is written in absolute M, L, C and Z only; any other command refuses, because a
    misread command would frame the mark wrongly without failing."""
    tokens = re.findall(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    segs, i, cmd = [], 0, None
    start = cur = None
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                if cur != start:
                    segs.append((cur, cur, start, start))
                cur = start
                continue
        if cmd not in ("M", "L", "C"):
            raise SystemExit(f"ERROR: path command {cmd!r} is not drawn here; use absolute M, L, C, Z")
        n = 6 if cmd == "C" else 2
        nums = [float(t) for t in tokens[i:i + n]]
        if len(nums) != n:
            raise SystemExit("ERROR: a path command is missing its coordinates")
        i += n
        if cmd == "M":
            start = cur = (nums[0], nums[1])
            cmd = "L"
        elif cmd == "L":
            segs.append((cur, cur, (nums[0], nums[1]), (nums[0], nums[1])))
            cur = (nums[0], nums[1])
        else:
            p1, p2, p3 = (nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])
            segs.append((cur, p1, p2, p3))
            cur = p3
    return segs


def _cubic_extent(a, b, c, e):
    """(min, max) of one coordinate of a cubic Bezier over t in [0, 1], from its end points and the
    roots of its derivative."""
    ts = [0.0, 1.0]
    qa, qb, qc = 3 * (-a + 3 * b - 3 * c + e), 6 * (a - 2 * b + c), 3 * (b - a)
    if abs(qa) < 1e-12:
        if abs(qb) > 1e-12:
            ts.append(-qc / qb)
    else:
        disc = qb * qb - 4 * qa * qc
        if disc >= 0:
            r = math.sqrt(disc)
            ts += [(-qb + r) / (2 * qa), (-qb - r) / (2 * qa)]
    vals = [(1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * e
            for t in ts if 0.0 <= t <= 1.0]
    return min(vals), max(vals)


def mark_bbox(paths):
    """(x0, y0, x1, y1): the exact extent of the mark's ink, curves included."""
    xs, ys = [], []
    for path in paths:
        d = re.search(r'\bd="([^"]*)"', path)
        if not d:
            raise SystemExit("ERROR: a <path> element carries no d attribute")
        for p0, p1, p2, p3 in _segments(d.group(1)):
            xs += _cubic_extent(p0[0], p1[0], p2[0], p3[0])
            ys += _cubic_extent(p0[1], p1[1], p2[1], p3[1])
    return min(xs), min(ys), max(xs), max(ys)


def favicon_viewbox(paths):
    """(x, y, w, h): the mark's extent rounded outward, which frames the mark with no padding."""
    k = 10 ** VIEWBOX_DECIMALS
    x0, y0, x1, y1 = mark_bbox(paths)
    lo = [math.floor(round(v * k, 6)) / k for v in (x0, y0)]
    hi = [math.ceil(round(v * k, 6)) / k for v in (x1, y1)]
    return lo[0], lo[1], hi[0] - lo[0], hi[1] - lo[1]


def _num(v):
    return f"{v:.{VIEWBOX_DECIMALS}f}"


def favicon_svg(paths):
    vb = " ".join(_num(v) for v in favicon_viewbox(paths))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">'
            f"<title>{TITLE}</title>{''.join(paths)}</svg>\n")


# ==================================================================================================
# Rasters
# ==================================================================================================

def _pillow():
    from PIL import Image, ImageDraw
    return Image, ImageDraw


def _polygon(d):
    """One path's outline as a closed polygon, each cubic flattened to CUBIC_STEPS line pieces.

    A path with a second subpath refuses: its polygons would be filled one by one, so a hole would be
    filled in without failing."""
    segs = _segments(d)
    pts = [segs[0][0]] if segs else []
    for p0, p1, p2, p3 in segs:
        if p0 != pts[-1]:
            raise SystemExit("ERROR: a path with more than one subpath is not drawn here")
        if p0 == p1 and p2 == p3:
            pts.append(p3)
            continue
        for k in range(1, CUBIC_STEPS + 1):
            t = k / CUBIC_STEPS
            pts.append(tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c
                             + t ** 3 * e for a, b, c, e in zip(p0, p1, p2, p3)))
    return pts


def _fill(path):
    m = re.search(r'\bfill="#([0-9A-Fa-f]{6})"', path)
    if not m:
        raise SystemExit("ERROR: a <path> element carries no #RRGGBB fill")
    return tuple(int(m.group(1)[k:k + 2], 16) for k in (0, 2, 4)) + (255,)


def _draw(paths, side, px):
    """The mark centred in a square of `side` user units, as RGBA at `px` pixels.

    Drawn at SUPERSAMPLE times the size on a transparent canvas, then resampled with Lanczos; Pillow
    resamples RGBA premultiplied, which keeps a dark fringe off the anti-aliased edge."""
    Image, ImageDraw = _pillow()
    x0, y0, x1, y1 = mark_bbox(paths)
    big = px * SUPERSAMPLE
    scale = big / side
    left, top = (x0 + x1) / 2 - side / 2, (y0 + y1) / 2 - side / 2
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    for path in paths:
        d = re.search(r'\bd="([^"]*)"', path).group(1)
        # Pillow puts a pixel's centre on the integer coordinate, half a pixel from the SVG's.
        draw.polygon([((x - left) * scale - 0.5, (y - top) * scale - 0.5) for x, y in _polygon(d)],
                     fill=_fill(path))
    return im.resize((px, px), Image.LANCZOS)


def ico_frame(paths, size):
    """The mark fitted to a transparent square of `size` px, its longer side edge to edge."""
    x0, y0, x1, y1 = mark_bbox(paths)
    return _draw(paths, max(x1 - x0, y1 - y0), size)


def ico_bytes(paths):
    frames = [ico_frame(paths, size) for size in ICO_SIZES]
    buf = io.BytesIO()
    frames[-1].save(buf, "ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    return buf.getvalue()


def app_icon(paths, size):
    """The mark at APP_ICON_MARK_WIDTH of the width, centred on the opaque ground, as RGB."""
    Image, _ImageDraw = _pillow()
    x0, _y0, x1, _y1 = mark_bbox(paths)
    mark = _draw(paths, (x1 - x0) / APP_ICON_MARK_WIDTH, size)
    ground = Image.new("RGBA", mark.size, APP_ICON_GROUND + (255,))
    return Image.alpha_composite(ground, mark).convert("RGB")


def app_icon_bytes(paths, size):
    buf = io.BytesIO()
    app_icon(paths, size).save(buf, "PNG")
    return buf.getvalue()


# ==================================================================================================
# The drift gate
# ==================================================================================================

def _png_matches(path, want):
    """Mode, size and decoded pixels. The mode is compared before the conversion to RGBA, so a file
    re-saved in another mode that happens to decode to the same pixels still fails."""
    Image, _ImageDraw = _pillow()
    with Image.open(path) as have, Image.open(io.BytesIO(want)) as fresh:
        return (have.mode == fresh.mode and have.size == fresh.size
                and have.convert("RGBA").tobytes() == fresh.convert("RGBA").tobytes())


def _ico_matches(path, want):
    """The frame sizes and every frame's decoded pixels."""
    Image, _ImageDraw = _pillow()
    with Image.open(path) as have, Image.open(io.BytesIO(want)) as fresh:
        if have.format != "ICO" or have.info["sizes"] != fresh.info["sizes"]:
            return False
        for size in sorted(fresh.info["sizes"]):
            have.size, fresh.size = size, size
            if have.convert("RGBA").tobytes() != fresh.convert("RGBA").tobytes():
                return False
    return True


def _matches(path, kind, want):
    """True when the committed file is what the tool would write today."""
    if not path.is_file():
        return False
    if kind == "bytes":
        return path.read_bytes() == want
    try:
        return (_ico_matches if kind == "ico" else _png_matches)(path, want)
    except OSError:
        return False


# ==================================================================================================
# The artefact set
# ==================================================================================================

def artefacts():
    """[(path, kind, bytes)] for every file this tool owns; kind is how --check compares it."""
    paths = mark_paths(MARK.read_text(encoding="utf-8"))
    items = [(FAVICON_SVG, "bytes", favicon_svg(paths).encode("utf-8")),
             (FAVICON_ICO, "ico", ico_bytes(paths))]
    items += [(app_icon_path(size), "png", app_icon_bytes(paths, size)) for size in APP_ICON_SIZES]
    return items


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/gen_auscope_icons.py",
                                description="Render the favicon and app icons from the AuScope mark.")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if a committed icon differs from a fresh render; writes nothing")
    a = p.parse_args(argv)
    items = artefacts()
    if a.check:
        stale = [path for path, kind, data in items if not _matches(path, kind, data)]
        if stale:
            print("AUSCOPE ICON DRIFT: regenerate with `python3 portal/tools/gen_auscope_icons.py`. "
                  "Stale: " + ", ".join(str(s.relative_to(ROOT.parent)) for s in stale),
                  file=sys.stderr)
            return 1
        print(f"auscope icons: {len(items)} file(s) in sync with tools/gen_auscope_icons.py")
        return 0
    for path, _kind, data in items:
        path.write_bytes(data)
    print(f"wrote {len(items)} file(s) from {MARK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
