#!/usr/bin/env python3
"""Compose portal/vendor/social-card.png from the artwork in portal/vendor/social-card-source.png.

    python3 portal/tools/gen_social_card.py            # write the card
    python3 portal/tools/gen_social_card.py --check    # verify the committed card, write nothing

WHY THIS IS A COMPOSITE AND NOT A RENDER
The root card is hand-made artwork: a dot-Australia on a 7.3 px lattice beside a wordmark. Nothing
in this repo draws it, and redrawing it would not preserve it. What the AuScope mark needs is one
change to the signature row, so this tool makes exactly that change on the artwork's own pixels: the
wordmark block is translated right by the width of the mark plus its gap, and the mark is composited
into the space that opens on the text margin. Every pixel outside that band is the artwork's.

The transform is verified before it is applied. The tool refuses to write if the block it is about
to move carries anything other than wordmark ink on the artwork's ground, or if the destination band
is not empty ground, so a future edit to the artwork cannot silently destroy part of it.

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

# The artwork's own measurements, declared rather than re-derived so that a change to the artwork
# fails the checks below instead of quietly moving the signature to somewhere else.
GROUND = (7, 22, 47, 255)          # the card's flat field colour behind the wordmark
INK = (255, 102, 85, 255)          # the wordmark's coral, the card's accent literal
MARGIN = 56                        # the wordmark's left ink edge, and so the card's text margin
# Left, top, right, bottom of every non-ground pixel of the wordmark, inclusive: the antialiased
# edge counts, because it is the edge that has to survive the move intact.
WORDMARK_INK = (55, 520, 354, 545)
BAND = (50, 495, 476, 575)         # the region this tool is allowed to touch, left/top/right/bottom

# The mark's height. The generated og cards give the mark the wordmark's own LINE height, which
# their face reports; this artwork's face is not in the repo, so the line height is declared from
# the ratio those cards measure (ink height 23 on a 35 px line), applied to this wordmark's 25 px
# ink. The mark then sits on this card exactly as it sits on the others.
LINE_H = 38


def _pillow():
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - the tool is hand-run on a machine that has Pillow
        print("gen_social_card: Pillow is required (pip install pillow)", file=sys.stderr)
        raise SystemExit(2)
    return Image


def compose():
    """The card as an in-memory image. Reads only the SOURCE, so running the tool twice is a
    no-op rather than a second shift."""
    Image = _pillow()
    with Image.open(SOURCE) as src:
        img = src.convert("RGBA")
    x0, y0, x1, y1 = BAND
    px = img.load()

    mark_w = round(LINE_H * _mark_size()[0] / _mark_size()[1])
    gap = mark_w // 2
    shift = MARGIN + mark_w + gap - MARGIN

    # 1. the block about to move carries the wordmark and nothing else
    wl, wt, wr, wb = WORDMARK_INK
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] == GROUND:
                continue
            if not (wl <= x <= wr and wt <= y <= wb):
                raise ValueError(f"the artwork carries content at ({x}, {y}), outside the wordmark "
                                 "block this tool moves; re-measure before regenerating")
    # 2. the space the wordmark is moving into is empty ground
    for y in range(y0, y1):
        for x in range(wr + 1, min(wr + 1 + shift, x1)):
            if px[x, y] != GROUND:
                raise ValueError(f"the artwork carries content at ({x}, {y}), where the shifted "
                                 "wordmark would land; re-measure before regenerating")

    block = img.crop((x0, y0, wr + 1, y1))
    img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), GROUND), (x0, y0))
    img.paste(block, (x0 + shift, y0))

    with Image.open(MARK) as src:
        mark = src.convert("RGBA").resize((mark_w, LINE_H), Image.LANCZOS)
    # Centred on the wordmark's ink, the rule the generated cards follow.
    img.paste(mark, (MARGIN, round((wt + wb) / 2 - LINE_H / 2)), mark)
    return img


def _mark_size():
    Image = _pillow()
    with Image.open(MARK) as m:
        return m.size


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/gen_social_card.py",
                                description="Compose the AusMT root link-preview card.")
    p.add_argument("--check", action="store_true",
                   help="verify the committed card against a fresh compose; writes nothing")
    a = p.parse_args(argv)
    Image = _pillow()
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
