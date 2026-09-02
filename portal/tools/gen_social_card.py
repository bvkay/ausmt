#!/usr/bin/env python3
"""Compose portal/vendor/social-card.png from the artwork in portal/vendor/social-card-source.png.

    python3 portal/tools/gen_social_card.py            # write the card
    python3 portal/tools/gen_social_card.py --check    # verify the committed card, write nothing

WHY THIS IS A COMPOSITE AND NOT A RENDER
The root card is hand-made artwork: a dot-Australia on a 7.3 px lattice beside an address. Nothing
in this repo draws it, and redrawing it would not preserve it. What the signature row needs is a
mark before the address and both of them a tenth larger, and this tool makes exactly those changes
on the artwork's own pixels: the one band the address occupies is cleared to the artwork's ground,
the address is set again in the face the artwork uses, and the mark is composited onto the text
margin beside it. Every pixel outside that band is the artwork's.

The transform is verified before it is applied. The tool refuses to write if the band it is about to
clear carries anything other than address ink on the artwork's ground, or if the row it is about to
draw would not fit inside that band, so a future edit to the artwork cannot silently destroy part of
it and a face or size change cannot silently overrun the art beside it.

The address is set in Inter Bold from portal/tools/brand_font/, the face the artwork itself uses and
the face the generated cards set their own address in; ADDRESS_SIZE below is the artwork's own size
measured back off its pixels, at the tenth the design adds.

Deliberately NOT wired into gen_brand.py --check: that gate compares decoded pixels exactly, and a
resampled paste is the one artefact whose bytes can legitimately move under a Pillow upgrade with no
brand change behind it. The card's geometry is held by a tolerance-based pin instead
(portal/tests/test_social_card.py), the same shape the generated og cards answer to.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "social-card-source.png"
CARD = ROOT / "vendor" / "social-card.png"
MARK = ROOT / "vendor" / "auscope-icon-white.png"
FONT_FILE = ROOT / "tools" / "brand_font" / "Inter-Bold.ttf"

# The artwork's own measurements, declared rather than re-derived so that a change to the artwork
# fails the checks below instead of quietly moving the signature to somewhere else.
GROUND = (7, 22, 47, 255)          # the card's flat field colour behind the address
INK = (255, 102, 85, 255)          # the address's coral, the card's accent literal
MARGIN = 56                        # the address's left ink edge, and so the card's text margin
WORDMARK = "ausmt.auscope.org.au"  # the address the artwork carries, re-set by this tool
# Left, top, right, bottom of every non-ground pixel of the wordmark, inclusive: the antialiased
# edge counts, because it is the edge that has to survive the move intact.
WORDMARK_INK = (55, 520, 354, 545)
BAND = (50, 495, 476, 575)         # the region this tool is allowed to touch, left/top/right/bottom

# The signature row's two sizes, each the artwork's own value with the design's tenth added. The
# address was set at 27 px (matched back against the artwork's pixels, 301 ink px against its 300),
# and the mark stands on a 38 px signature line, the height the generated cards' ink-to-line ratio
# gives this address. Both grow together, so the row keeps its proportions.
ADDRESS_SIZE = 30
LINE_H = 42


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover - the tool is hand-run on a machine that has Pillow
        print("gen_social_card: Pillow is required (pip install pillow)", file=sys.stderr)
        raise SystemExit(2)
    return Image, ImageDraw, ImageFont


def compose():
    """The card as an in-memory image. Reads only the SOURCE, so running the tool twice is a
    no-op rather than a second shift."""
    Image, ImageDraw, ImageFont = _pillow()
    with Image.open(SOURCE) as src:
        img = src.convert("RGBA")
    x0, y0, x1, y1 = BAND
    px = img.load()

    # 1. the band about to be cleared carries the address and nothing else
    wl, wt, wr, wb = WORDMARK_INK
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] == GROUND:
                continue
            if not (wl <= x <= wr and wt <= y <= wb):
                raise ValueError(f"the artwork carries content at ({x}, {y}), outside the address "
                                 "band this tool clears; re-measure before regenerating")

    mark = _mark(MARK, LINE_H)
    gap = mark.width // 2
    font = ImageFont.truetype(str(FONT_FILE), ADDRESS_SIZE,
                              layout_engine=ImageFont.Layout.BASIC)
    d = ImageDraw.Draw(img)
    # The address's INK box, so the row is placed by what is seen rather than by an em box whose
    # descent this string never uses.
    bx0, by0, bx1, by1 = d.textbbox((0, 0), WORDMARK, font=font)
    tx, top = MARGIN + mark.width + gap, round((wt + wb) / 2 - (by1 - by0) / 2)

    # 2. the row about to be drawn fits inside the band this tool is allowed to touch
    if tx + (bx1 - bx0) > x1 or top < y0 or top + (by1 - by0) > y1:
        raise ValueError(f"the signature row would run to ({tx + bx1 - bx0}, {top + by1 - by0}), "
                         f"outside the band {BAND} this tool may touch; the row cannot be set at "
                         f"{ADDRESS_SIZE} px without re-measuring the artwork")

    img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), GROUND), (x0, y0))
    d.text((tx - bx0, top - by0), WORDMARK, font=font, fill=INK)
    # Centred on the address's ink, the rule the generated cards follow.
    img.paste(mark, (MARGIN, round((wt + wb) / 2 - LINE_H / 2)), mark)
    return img


def _mark(path, height):
    """One mark image at `height` pixels, at its own aspect."""
    Image, _, _ = _pillow()
    with Image.open(path) as src:
        m = src.convert("RGBA")
        return m.resize((round(height * m.width / m.height), height), Image.LANCZOS)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/gen_social_card.py",
                                description="Compose the AusMT root link-preview card.")
    p.add_argument("--check", action="store_true",
                   help="verify the committed card against a fresh compose; writes nothing")
    a = p.parse_args(argv)
    Image, _, _ = _pillow()
    want = compose()
    if a.check:
        if not CARD.is_file():
            print("SOCIAL CARD DRIFT: vendor/social-card.png is missing", file=sys.stderr)
            return 1
        with Image.open(CARD) as have:
            same = (have.size == want.size and have.mode == want.mode
                    and have.convert("RGBA").tobytes() == want.tobytes())
        if not same:
            print("SOCIAL CARD DRIFT: regenerate with `python3 portal/tools/gen_social_card.py`",
                  file=sys.stderr)
            return 1
        print(f"social card: {CARD.name} matches the composite of {SOURCE.name}")
        return 0
    want.save(CARD, "PNG")
    print(f"wrote {CARD.relative_to(ROOT.parent)} ({want.size[0]}x{want.size[1]}, {want.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
