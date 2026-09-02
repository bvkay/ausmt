"""vendor/social-card.png: the root link-preview card, and the artwork it is composed from.

The card is hand-made art. Nothing in this repo draws its dot-Australia, so the AuScope mark could
not be added by re-rendering it; tools/gen_social_card.py translates the wordmark block and
composites the mark onto the artwork's own pixels instead, and the untouched artwork ships beside
the card as vendor/social-card-source.png.

That arrangement needs three things held. The source must keep shipping, or the card can never be
regenerated. The composite must still be reproducible from it. And the signature row must read the
way the generated survey and collection cards' rows read, which is a geometric property of the
pixels rather than of the code, so it is measured off the file.

The composite is deliberately NOT part of gen_brand.py --check. That gate compares decoded pixels
exactly, and a resampled paste is the one artefact whose bytes could legitimately move under a
Pillow upgrade with no brand decision behind it. The pins below are tolerance-based for the same
reason, and are the same shape the engine's card pins use (engine/tests/test_og_cards.py).
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]          # portal/
REPO = ROOT.parent
CARD = ROOT / "vendor" / "social-card.png"
SOURCE = ROOT / "vendor" / "social-card-source.png"
TOOL = ROOT / "tools" / "gen_social_card.py"

# The line height the card's own wordmark is signed at. The artwork's typeface is not in the repo,
# so this is a declared constant rather than a measurement, and gen_social_card.py records how it
# was derived from the generated cards' own ink-to-line ratio.
LINE_H = 38
_SIG_REGION = (0, 500, 620, 630)

Image = pytest.importorskip("PIL.Image")


def test_the_untouched_artwork_still_ships():
    """FAILS IF the source artwork is deleted or resized. It is the only copy of the hand-made card
    that exists; without it the composite can never be rebuilt, and the mark could never be moved,
    resized or removed again."""
    assert SOURCE.is_file(), "vendor/social-card-source.png must ship beside the card"
    with Image.open(SOURCE) as im:
        assert im.size == (1200, 630), f"the artwork is a 1200x630 card, got {im.size}"


def test_the_committed_card_is_the_composite_of_the_artwork():
    """The tool is hand-run, so this is what stops the committed card and its generator drifting
    apart in silence."""
    proc = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"


def test_the_card_signs_itself_with_the_mark_beside_the_wordmark():
    """The same row the generated cards carry: the mark entirely left of the wordmark, the two
    vertically centred on each other, and the mark at the wordmark's line height so the pair reads
    as one line rather than as a logo with a caption beside it."""
    with Image.open(CARD) as im:
        img = im.convert("RGB")
        assert img.size == (1200, 630), f"a link-preview card is 1200x630, got {img.size}"
    px = img.load()
    x0, y0, x1, y1 = _SIG_REGION
    white, coral = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y]
            if min(r, g, b) >= 240:
                white.append((x, y))
            elif r >= 190 and g < 150 and b < 140 and r - b >= 60:
                coral.append((x, y))
    assert white, "no mark ink found in the card's signature corner"
    assert coral, "no wordmark ink found in the card's signature corner"

    def box(pts):
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))
    mark, word = box(white), box(coral)
    assert mark[2] < word[0], \
        f"the mark must sit entirely left of the wordmark, mark {mark} wordmark {word}"
    assert abs((mark[1] + mark[3]) / 2 - (word[1] + word[3]) / 2) <= 2, \
        f"the pair must read as one line, mark {mark} wordmark {word}"
    mark_h = mark[3] - mark[1] + 1
    assert abs(mark_h - LINE_H) / LINE_H <= 0.15, \
        f"the mark's height must be the wordmark's line height, got {mark_h} for {LINE_H}"


def test_the_artwork_itself_is_unsigned():
    """The source is the artwork, not a second copy of the card. FAILS IF a regeneration is ever
    committed over the source, which would make the next run composite a mark onto a mark."""
    with Image.open(SOURCE) as im:
        px = im.convert("RGB").load()
    x0, y0, x1, y1 = _SIG_REGION
    near_white = sum(1 for y in range(y0, y1) for x in range(x0, x1)
                     if min(px[x, y]) >= 240)
    assert near_white == 0, \
        f"the source artwork must carry no mark in its signature corner, found {near_white} pixels"
