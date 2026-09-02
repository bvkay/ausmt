"""vendor/social-card.png: the root link-preview card, and the artwork it is composed from.

The card is hand-made art. Nothing in this repo draws its dot-Australia, so the signature row could
not be added by re-rendering it; tools/gen_social_card.py clears the one band the address occupies,
sets the address again in the artwork's own face, and composites the mark onto the artwork's own
pixels, and the untouched artwork ships beside the card as vendor/social-card-source.png.

That arrangement needs four things held. The source must keep shipping, or the card can never be
regenerated. The composite must still be reproducible from it. The signature row must read the way
the generated survey and collection cards' rows read, which is a geometric property of the pixels
rather than of the code, so it is measured off the file. And the card must carry NO corner mark:
the generated cards put the AusMT mark in their top-left corner to name the site they belong to,
but this card's artwork IS that mark, and a second copy of it would read as a duplicate.

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

# The line height the card's own address is signed at, and the size that address is set at. Both are
# declared here rather than measured, so that a change to the tool's constants has to be made twice
# and on purpose; gen_social_card.py records how each was derived from the artwork's own pixels.
LINE_H = 42
ADDRESS_SIZE = 30
GROUND = (7, 22, 47)
_SIG_REGION = (0, 500, 620, 630)
# The top-left corner, the slot the GENERATED cards put the AusMT mark in. On this card it is the
# artwork's own empty margin, and it stays empty.
_CORNER_REGION = (40, 0, 300, 100)

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


def test_the_tool_sets_the_row_at_the_sizes_this_file_declares():
    """The pin above is geometric and tolerant, which is what makes it survive a Pillow upgrade and
    also what stops it noticing a size change on its own: a mark drawn at 38 px passes a tolerance
    declared for 42, and so does one at 46. The two numbers are therefore held exactly, here and in
    the tool, so a change to the signature row's scale has to be made in both places.

    The tool's source is compiled and run here rather than imported. An import would write a
    __pycache__ entry beside a hand-run tool and, worse, could READ a stale one: the validity stamp
    is the source's mtime to the second, so an edit and a test in the same second can be answered
    with the previous compile. A pin that can report the constant a file used to hold is not a pin."""
    ns = {"__file__": str(TOOL), "__name__": "gen_social_card_pin"}
    exec(compile(TOOL.read_text(encoding="utf-8"), str(TOOL), "exec"), ns)
    assert ns["LINE_H"] == LINE_H, \
        f"the mark stands on a {LINE_H} px line, the tool uses {ns['LINE_H']}"
    assert ns["ADDRESS_SIZE"] == ADDRESS_SIZE, \
        f"the address is set at {ADDRESS_SIZE} px, the tool uses {ns['ADDRESS_SIZE']}"
    assert ns["FONT_FILE"].is_file(), "the address face must ship with the tool that sets it"
    assert ns["FONT_FILE"].name == "Inter-Bold.ttf", \
        f"the address is set in the artwork's own face, got {ns['FONT_FILE'].name}"


def test_the_root_card_carries_no_corner_mark():
    """The generated survey and collection cards put the AusMT mark in their top-left corner to name
    the site the card belongs to. This card does not need naming: its artwork IS the mark, at the
    size the whole card is built around. FAILS IF a corner mark is ever composited onto it, which
    would put two copies of the same mark on one card."""
    with Image.open(CARD) as im:
        px = im.convert("RGB").load()
    x0, y0, x1, y1 = _CORNER_REGION
    ink = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if px[x, y] != GROUND]
    assert not ink, \
        f"the root card's corner must stay the artwork's own ground, found ink at {ink[:3]}"


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
